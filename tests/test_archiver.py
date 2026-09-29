"""需求 3 的单元测试：归档、报告与撤销。"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hwarchiver import cli
from hwarchiver.archiver import (
    apply_archive,
    build_archive_plan,
    classify,
    detect_category,
    detect_semester,
    parse_category_map,
)
from hwarchiver.journal import Journal
from hwarchiver.report import build_report
from hwarchiver.scanner import FileEntry, scan
from hwarchiver.undo import undo_last


class ClassifyTestCase(unittest.TestCase):
    def _entry(self, name):
        return FileEntry(path=Path("/tmp") / name, name=name, size=1, mtime=0.0, ext=Path(name).suffix.lower())

    def test_detect_semester(self):
        self.assertEqual(detect_semester("2024春_机器学习期末.pdf"), "2024春")
        self.assertEqual(detect_semester("2024-秋_数据库.docx"), "2024秋")
        self.assertEqual(detect_semester("2024_秋季_作业.pdf"), "2024秋")
        self.assertEqual(detect_semester("2024-2025-1_编译原理.pdf"), "2024-2025-1")
        self.assertEqual(detect_semester("2024-2_算法.pdf"), "2024-2")
        self.assertIsNone(detect_semester("机器学习期末.pdf"))

    def test_detect_category(self):
        self.assertEqual(detect_category("2023001_张三_实验一.pdf"), "实验报告")
        self.assertEqual(detect_category("2023001_张三_期末论文.pdf"), "课程论文")
        self.assertEqual(detect_category("2023001_张三_课程设计.docx"), "课程设计")
        self.assertEqual(detect_category("2023001_张三_期末.pdf"), "考试答卷")
        self.assertEqual(detect_category("2023001_张三_作业3.pdf"), "平时作业")
        self.assertEqual(detect_category("随便一个文件.pdf"), "未分类")

    def test_custom_map_is_appended(self):
        mapping = parse_category_map(["实验=实验报告", "读书笔记=读书笔记"])
        self.assertIn("读书笔记", mapping)
        self.assertEqual(detect_category("读书笔记.pdf", mapping), "读书笔记")

    def test_classify_by_ext(self):
        self.assertEqual(classify(self._entry("a.PDF"), "ext"), "pdf")
        self.assertEqual(classify(self._entry("b"), "ext"), "无扩展名")

    def test_classify_unknown_mode(self):
        with self.assertRaises(ValueError):
            classify(self._entry("a.pdf"), "whatever")


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _touch(self, name, size=10):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
        return p

    def test_preview_does_not_move(self):
        self._touch("2024春_机器学习.pdf")
        plan = build_archive_plan(self.root, by="semester")
        self.assertEqual(len(plan.to_move), 1)
        self.assertFalse((self.root / "2024春").exists())

    def test_apply_moves_into_semester_folder(self):
        self._touch("2024春_机器学习.pdf")
        self._touch("2024秋_数据库.pdf")
        plan = build_archive_plan(self.root, by="semester")
        apply_archive(plan)
        self.assertTrue((self.root / "2024春" / "2024春_机器学习.pdf").exists())
        self.assertTrue((self.root / "2024秋" / "2024秋_数据库.pdf").exists())

    def test_unknown_semester_goes_to_unknown_folder(self):
        self._touch("机器学习.pdf")
        plan = build_archive_plan(self.root, by="semester")
        apply_archive(plan)
        self.assertTrue((self.root / "未识别学期" / "机器学习.pdf").exists())

    def test_already_in_target_folder_is_skipped(self):
        self._touch("2024春/2024春_机器学习.pdf")
        plan = build_archive_plan(self.root, by="semester", recursive=True)
        self.assertEqual(len(plan.skipped), 1)
        self.assertIn("已在目标位置", plan.skipped[0].reason)

    def test_conflict_never_overwrites(self):
        victim = self._touch("未识别学期/作业.pdf", size=999)
        source = self._touch("作业.pdf", size=1)
        plan = build_archive_plan(self.root, by="semester")
        apply_archive(plan)
        self.assertTrue(victim.exists())
        self.assertEqual(victim.stat().st_size, 999)
        self.assertFalse(source.exists())
        self.assertTrue((self.root / "未识别学期" / "作业_1.pdf").exists())

    def test_same_target_folder_conflict_gets_numbered(self):
        # 两个不同目录下的同名文件被归到同一个学期文件夹
        self._touch("a/2024春_作业.pdf", size=11)
        self._touch("b/2024春_作业.pdf", size=22)
        plan = build_archive_plan(self.root, by="semester", recursive=True)
        apply_archive(plan)
        folder = self.root / "2024春"
        names = sorted(p.name for p in folder.iterdir())
        self.assertEqual(names, ["2024春_作业.pdf", "2024春_作业_1.pdf"])

    def test_on_conflict_skip(self):
        self._touch("未识别学期/作业.pdf")
        self._touch("作业.pdf")
        plan = build_archive_plan(self.root, by="semester", on_conflict="skip")
        self.assertEqual(len(plan.skipped), 1)

    def test_archive_by_category(self):
        self._touch("2023001_张三_实验一.pdf")
        self._touch("2023001_张三_期末.pdf")
        plan = build_archive_plan(self.root, by="category")
        apply_archive(plan)
        self.assertTrue((self.root / "实验报告" / "2023001_张三_实验一.pdf").exists())
        self.assertTrue((self.root / "考试答卷" / "2023001_张三_期末.pdf").exists())

    def test_archive_by_ext(self):
        self._touch("a.pdf")
        self._touch("b.docx")
        plan = build_archive_plan(self.root, by="ext")
        apply_archive(plan)
        self.assertTrue((self.root / "pdf" / "a.pdf").exists())
        self.assertTrue((self.root / "docx" / "b.docx").exists())


class UndoTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _touch(self, name, size=10):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
        return p

    def test_undo_archive_restores_original_layout(self):
        self._touch("2024春_机器学习.pdf")
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["archive", str(self.root), "--by", "semester", "--apply", "--yes"])
        self.assertTrue((self.root / "2024春" / "2024春_机器学习.pdf").exists())

        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["undo", str(self.root), "--yes"])
        self.assertFalse((self.root / "2024春").exists() or (self.root / "2024春" / "2024春_机器学习.pdf").exists())
        self.assertTrue((self.root / "2024春_机器学习.pdf").exists())
        self.assertIn("撤销完成", buf.getvalue())
        self.assertIsNone(Journal(self.root).last_operation())

    def test_undo_rename_restores_original_name(self):
        self._touch("2023001_张三_实验一.pdf")
        with redirect_stdout(io.StringIO()):
            cli.main(["rename", str(self.root), "--apply", "--yes"])
        self.assertTrue((self.root / "实验一_2023001.pdf").exists())
        with redirect_stdout(io.StringIO()):
            cli.main(["undo", str(self.root), "--yes"])
        self.assertTrue((self.root / "2023001_张三_实验一.pdf").exists())

    def test_undo_without_confirmation_cancels(self):
        self._touch("2023001_张三_实验一.pdf")
        with redirect_stdout(io.StringIO()):
            cli.main(["rename", str(self.root), "--apply", "--yes"])
        buf = io.StringIO()
        with redirect_stdout(buf), patch.object(cli, "request_confirmation", return_value=False):
            code = cli.main(["undo", str(self.root)])
        self.assertEqual(code, 1)
        self.assertTrue((self.root / "实验一_2023001.pdf").exists())

    def test_undo_without_any_operation(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["undo", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("没有可撤销", buf.getvalue())

    def test_undo_does_not_overwrite(self):
        # 归档后，原位被别人占了，撤销时不能覆盖
        self._touch("2024春_机器学习.pdf")
        with redirect_stdout(io.StringIO()):
            cli.main(["archive", str(self.root), "--by", "semester", "--apply", "--yes"])
        blocker = self._touch("2024春_机器学习.pdf", size=777)

        result = undo_last(self.root)
        self.assertIsNotNone(result)
        _, items = result
        self.assertFalse(items[0].applied)
        self.assertIn("原位置已有同名文件", items[0].reason)
        self.assertEqual(blocker.stat().st_size, 777)

    def test_undo_keeps_record_when_partially_failed(self):
        self._touch("2024春_机器学习.pdf")
        self._touch("2024秋_数据库.pdf")
        with redirect_stdout(io.StringIO()):
            cli.main(["archive", str(self.root), "--by", "semester", "--apply", "--yes"])
        self._touch("2024春_机器学习.pdf", size=777)  # 占住其中一个的原位

        undo_last(self.root)
        journal = Journal(self.root)
        self.assertIsNotNone(journal.last_operation(), "部分失败时应保留记录以便重试")
        # 未被占用的那个应当已还原
        self.assertTrue((self.root / "2024秋_数据库.pdf").exists())


class ReportTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _touch(self, name, size=10):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
        return p

    def test_report_counts_processed_and_skipped(self):
        self._touch("2024春_机器学习.pdf")
        self._touch("2024春/2024春_已在位的.pdf")  # 已经在目标文件夹里，应跳过
        self._touch("其它文件.pdf")
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["archive", str(self.root), "--by", "semester", "--recursive", "--apply", "--yes"])
        out = buf.getvalue()
        self.assertIn("整理报告", out)

        journal = Journal(self.root)
        reports = sorted(journal.reports_dir.glob("report-*.json"))
        self.assertEqual(len(reports), 1)
        data = json.loads(reports[0].read_text(encoding="utf-8"))
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["processed"], 2)
        self.assertEqual(data["skipped"], 1)
        self.assertTrue(any("已在目标位置" in r for r in data["skip_reasons"]))

    def test_report_command_prints_markdown(self):
        self._touch("2023001_张三_实验一.pdf")
        with redirect_stdout(io.StringIO()):
            cli.main(["rename", str(self.root), "--apply", "--yes"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["report", str(self.root)])
        self.assertIn("# 整理报告", buf.getvalue())

    def test_no_report_yet(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["report", str(self.root)])
        self.assertIn("还没有任何整理报告", buf.getvalue())

    def test_build_report_markdown_has_reason_table(self):
        self._touch("2023001_张三_实验一.pdf")
        self._touch("未识别学期/单段.pdf")  # 已在目标位置，会被跳过
        plan = build_archive_plan(self.root, by="semester", recursive=True)
        apply_archive(plan)
        report = build_report("archive", self.root, plan.items)
        md = report.to_markdown()
        self.assertIn("## 为什么跳过", md)
        self.assertIn("| 原因 | 数量 |", md)


if __name__ == "__main__":
    unittest.main()

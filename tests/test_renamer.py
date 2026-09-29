"""需求 2 的单元测试：预览优先、确认后才改、冲突绝不覆盖。"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hwarchiver import cli
from hwarchiver.renamer import apply_plan, build_new_name, build_plan, parse_fields, resolve_conflict, sanitize


class ParseTestCase(unittest.TestCase):
    def test_parse_three_segments(self):
        self.assertEqual(
            parse_fields("2023001_张三_数据结构实验一"),
            {"sid": "2023001", "name": "张三", "hw": "数据结构实验一"},
        )

    def test_parse_more_than_three_joins_tail(self):
        self.assertEqual(
            parse_fields("2023001_张三_实验报告_线性代数")["hw"],
            "实验报告_线性代数",
        )

    def test_parse_two_segments_keeps_name_empty(self):
        self.assertEqual(
            parse_fields("2023001_作业一"),
            {"sid": "2023001", "name": "", "hw": "作业一"},
        )

    def test_parse_too_few_returns_none(self):
        self.assertIsNone(parse_fields("作业一"))

    def test_custom_fields(self):
        self.assertEqual(parse_fields("张三_作业一", fields=("name", "hw")), {"name": "张三", "hw": "作业一"})


class BuildNameTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.entry_path = self.root / "2023001_张三_数据结构实验一.pdf"
        self.entry_path.write_bytes(b"x" * 10)
        from hwarchiver.scanner import scan

        self.entry = scan(self.root).entries[0]

    def test_default_template_hw_then_sid(self):
        new_stem, _ = build_new_name(self.entry)
        self.assertEqual(new_stem, "数据结构实验一_2023001")

    def test_custom_template(self):
        new_stem, _ = build_new_name(self.entry, template="{sid}-{name}-{hw}")
        self.assertEqual(new_stem, "2023001-张三-数据结构实验一")

    def test_unknown_field_is_skipped_with_reason(self):
        new_stem, reason = build_new_name(self.entry, template="{学号}_{hw}")
        self.assertIsNone(new_stem)
        self.assertIn("不存在", reason)

    def test_invalid_chars_are_replaced(self):
        # 文件名里带操作系统不允许的字符（这里不落盘，只验证改名逻辑）
        from hwarchiver.scanner import FileEntry

        entry = FileEntry(
            path=self.root / "2023001_张三_数据结构*实验.pdf",
            name="2023001_张三_数据结构*实验.pdf",
            size=10,
            mtime=0.0,
            ext=".pdf",
        )
        new_stem, reason = build_new_name(entry)
        self.assertNotIn("*", new_stem)
        self.assertIn("非法字符", reason)

    def test_sanitize(self):
        self.assertEqual(sanitize('a/b*c?'), ("a_b_c_", True))
        self.assertEqual(sanitize("ok"), ("ok", False))


class PlanTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _touch(self, name, size=10):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
        return p

    def test_preview_does_not_touch_disk(self):
        self._touch("2023001_张三_实验一.pdf")
        plan = build_plan(self.root)
        self.assertEqual(len(plan.to_rename), 1)
        self.assertTrue((self.root / "2023001_张三_实验一.pdf").exists())
        self.assertFalse((self.root / "实验一_2023001.pdf").exists())

    def test_apply_renames_files(self):
        self._touch("2023001_张三_实验一.pdf")
        plan = build_plan(self.root)
        apply_plan(plan)
        self.assertFalse((self.root / "2023001_张三_实验一.pdf").exists())
        self.assertTrue((self.root / "实验一_2023001.pdf").exists())

    def test_unparsable_file_is_skipped_with_reason(self):
        self._touch("实验一.pdf")
        plan = build_plan(self.root)
        self.assertEqual(len(plan.to_rename), 0)
        self.assertEqual(len(plan.skipped), 1)
        self.assertIn("无法", plan.skipped[0].reason)

    def test_same_name_is_skipped(self):
        # 文件名已经是目标格式时无需改动
        self._touch("实验一_2023001.pdf")
        plan = build_plan(self.root, template="{sid}_{hw}")
        self.assertEqual(len(plan.skipped), 1)
        self.assertIn("相同", plan.skipped[0].reason)

    def test_conflict_never_overwrites_existing_file(self):
        # 目标名已被占用：受害者文件用 '-' 分隔、无法解析，因此不参与改名，必须原封不动
        victim = self._touch("实验一_2023001.pdf", size=999)
        source = self._touch("2023001-张三-实验一.pdf", size=1)
        plan = build_plan(self.root, sep="-")
        apply_plan(plan)
        self.assertTrue(victim.exists())
        self.assertEqual(victim.stat().st_size, 999)
        self.assertFalse(source.exists())
        self.assertTrue((self.root / "实验一_2023001_1.pdf").exists())

    def test_different_sids_do_not_collide(self):
        self._touch("2023001_张三_实验一.pdf")
        self._touch("2023002_李四_实验一.pdf")
        plan = build_plan(self.root)
        apply_plan(plan)
        names = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(names, ["实验一_2023001.pdf", "实验一_2023002.pdf"])

    def test_two_sources_same_target_are_numbered(self):
        # 只用作业名做模板时，两人必然撞名，第二个必须自动加序号而不是覆盖
        self._touch("2023001_张三_实验一.pdf", size=11)
        self._touch("2023002_李四_实验一.pdf", size=22)
        plan = build_plan(self.root, template="{hw}")
        self.assertEqual(len(plan.to_rename), 2)
        self.assertEqual(sum(1 for i in plan.items if i.status == "conflict"), 1)
        apply_plan(plan)
        names = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(names, ["实验一.pdf", "实验一_1.pdf"])
        self.assertEqual((self.root / "实验一.pdf").stat().st_size, 11)
        self.assertEqual((self.root / "实验一_1.pdf").stat().st_size, 22)

    def test_on_conflict_skip(self):
        self._touch("实验一_2023001.pdf")
        self._touch("2023001_张三_实验一.pdf")
        plan = build_plan(self.root, on_conflict="skip")
        self.assertEqual(len(plan.skipped), 1)
        self.assertIn("目标已存在", plan.skipped[0].reason)

    def test_ext_filter(self):
        self._touch("2023001_张三_实验一.pdf")
        self._touch("2023002_李四_实验一.docx")
        plan = build_plan(self.root, exts=[".pdf"])
        self.assertEqual(len(plan.to_rename), 1)

    def test_resolve_conflict_finds_free_name(self):
        (self.root / "a.pdf").write_bytes(b"x")
        (self.root / "a_1.pdf").write_bytes(b"x")
        self.assertEqual(resolve_conflict(self.root / "a.pdf", set()).name, "a_2.pdf")


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "2023001_张三_实验一.pdf").write_bytes(b"x" * 10)

    def test_cli_default_is_preview_only(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["rename", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("没有改动任何文件", buf.getvalue())
        self.assertTrue((self.root / "2023001_张三_实验一.pdf").exists())

    def test_cli_apply_without_confirmation_cancels(self):
        buf = io.StringIO()
        with redirect_stdout(buf), patch.object(cli, "request_confirmation", return_value=False):
            code = cli.main(["rename", str(self.root), "--apply"])
        self.assertEqual(code, 1)
        self.assertIn("已取消", buf.getvalue())
        self.assertTrue((self.root / "2023001_张三_实验一.pdf").exists())

    def test_cli_apply_with_yes_renames(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["rename", str(self.root), "--apply", "--yes"])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "实验一_2023001.pdf").exists())

    def test_cli_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["rename", str(self.root), "--json"])
        self.assertIn('"template": "{hw}_{sid}"', buf.getvalue())


if __name__ == "__main__":
    unittest.main()

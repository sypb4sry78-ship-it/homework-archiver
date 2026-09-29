"""需求 1 的单元测试：python -m unittest discover -s tests"""

import tempfile
import time
import unittest
from pathlib import Path

from hwarchiver.scanner import (
    display_width,
    format_size,
    normalize_exts,
    render_table,
    scan,
)


class ScanTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "sub").mkdir()
        self.files = {
            "2023001_张三_实验一.pdf": self.root / "2023001_张三_实验一.pdf",
            "2023002_李四_报告.docx": self.root / "2023002_李四_报告.docx",
            "notes.txt": self.root / "sub" / "notes.txt",
        }
        for path in self.files.values():
            path.write_bytes(b"x" * 100)
        self.addCleanup(self._tmp.cleanup)

    def test_scan_finds_all_files_recursively(self):
        result = scan(self.root)
        self.assertEqual(len(result.entries), 3)
        self.assertEqual(result.total_size, 300)

    def test_scan_non_recursive_only_top_level(self):
        result = scan(self.root, recursive=False)
        self.assertEqual(len(result.entries), 2)

    def test_ext_filter_is_case_insensitive(self):
        result = scan(self.root, exts=[".PDF"])
        self.assertEqual([e.name for e in result.entries], ["2023001_张三_实验一.pdf"])

    def test_ext_filter_accepts_multiple(self):
        result = scan(self.root, exts=["pdf", "docx"])
        self.assertEqual(len(result.entries), 2)

    def test_sort_by_size_descending(self):
        (self.root / "big.pdf").write_bytes(b"x" * 5000)
        result = scan(self.root, sort_by="size", descending=True)
        self.assertEqual(result.entries[0].name, "big.pdf")

    def test_limit(self):
        result = scan(self.root, limit=1)
        self.assertEqual(len(result.entries), 1)

    def test_skips_metadata_dirs(self):
        meta = self.root / ".hwarchiver"
        meta.mkdir()
        (meta / "journal.json").write_text("{}")
        result = scan(self.root)
        self.assertFalse(any(".hwarchiver" in e.path.parts for e in result.entries))

    def test_missing_directory_raises(self):
        with self.assertRaises(FileNotFoundError):
            scan(self.root / "not-exist")

    def test_render_table_contains_size_and_time(self):
        table = render_table(scan(self.root))
        self.assertIn("文件名", table)
        self.assertIn("2023001_张三_实验一.pdf", table)
        self.assertIn("100 B", table)
        self.assertIn(time.strftime("%Y-%m-%d"), table)

    def test_to_dict_has_required_fields(self):
        data = scan(self.root).to_dict()
        self.assertIn("files", data)
        self.assertEqual(data["count"], 3)
        for item in data["files"]:
            self.assertEqual(
                {"name", "path", "relpath", "size", "size_human", "mtime", "ext"}, set(item)
            )


class HelperTestCase(unittest.TestCase):
    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(1024 * 1024 * 3), "3.0 MB")

    def test_normalize_exts(self):
        self.assertEqual(normalize_exts(["PDF", ".docx"]), {".pdf", ".docx"})
        self.assertIsNone(normalize_exts(None))
        self.assertIsNone(normalize_exts([]))

    def test_display_width_counts_wide_chars(self):
        self.assertEqual(display_width("ab"), 2)
        self.assertEqual(display_width("张三"), 4)


if __name__ == "__main__":
    unittest.main()

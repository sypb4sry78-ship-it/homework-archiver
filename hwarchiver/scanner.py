"""扫描目录并列出文件（需求 1）。

只依赖标准库：递归遍历、读取大小与修改时间、按扩展名过滤、排序与格式化输出。
"""

from __future__ import annotations

import os
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

# 默认跳过的目录：工具自身的元数据目录、版本控制与依赖目录
DEFAULT_SKIP_DIRS: Set[str] = {
    ".hwarchiver",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
}

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class FileEntry:
    """一个被扫描到的文件。"""

    path: Path
    name: str
    size: int
    mtime: float
    ext: str

    @property
    def mtime_str(self) -> str:
        return time.strftime(TIME_FORMAT, time.localtime(self.mtime))

    def rel_to(self, root: Path) -> str:
        try:
            return str(self.path.relative_to(root))
        except ValueError:
            return str(self.path)

    def to_dict(self, root: Optional[Path] = None) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "relpath": self.rel_to(root) if root else str(self.path),
            "size": self.size,
            "size_human": format_size(self.size),
            "mtime": self.mtime_str,
            "ext": self.ext,
        }


@dataclass
class ScanResult:
    """扫描结果：命中的文件 + 扫描过程中被跳过/失败的路径及原因。"""

    root: Path
    entries: List[FileEntry] = field(default_factory=list)
    skipped: List[dict] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries)

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "count": len(self.entries),
            "total_size": self.total_size,
            "total_size_human": format_size(self.total_size),
            "files": [e.to_dict(self.root) for e in self.entries],
            "skipped": self.skipped,
        }


def normalize_ext(ext: str) -> str:
    """把 'pdf' / '.PDF' 统一成 '.pdf'。"""
    ext = ext.strip()
    if not ext:
        return ""
    if not ext.startswith("."):
        ext = "." + ext
    return ext.lower()


def normalize_exts(exts: Optional[Iterable[str]]) -> Optional[Set[str]]:
    """把 --ext .pdf,docx 解析成 {'.pdf', '.docx'}；为 None 表示不过滤。"""
    if exts is None:
        return None
    normalized = {normalize_ext(e) for e in exts if normalize_ext(e)}
    return normalized or None


def format_size(num_bytes: float) -> str:
    """字节数转人类可读字符串，如 12.3 KB。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def scan(
    root: os.PathLike | str,
    exts: Optional[Iterable[str]] = None,
    recursive: bool = True,
    skip_dirs: Optional[Iterable[str]] = None,
    sort_by: str = "name",
    descending: bool = False,
    limit: Optional[int] = None,
) -> ScanResult:
    """扫描 root 下的文件。

    :param exts: 扩展名白名单，None 表示全部
    :param recursive: 是否递归子目录
    :param skip_dirs: 需要跳过的目录名集合
    :param sort_by: name | size | mtime | ext
    :param descending: 是否降序
    :param limit: 只保留前 N 个
    """
    root_path = Path(root).expanduser().resolve()
    wanted = normalize_exts(exts)
    blocked = set(DEFAULT_SKIP_DIRS if skip_dirs is None else skip_dirs)

    result = ScanResult(root=root_path)
    if not root_path.exists():
        raise FileNotFoundError(f"目录不存在: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"不是目录: {root_path}")

    if recursive:
        walker = os.walk(root_path, onerror=lambda e: None)
    else:
        walker = [(root_path, [], [p.name for p in root_path.iterdir() if p.is_file()])]

    for current_dir, subdirs, filenames in walker:
        current = Path(current_dir)
        # 原地修改 subdirs 可让 os.walk 不再进入这些目录
        subdirs[:] = [d for d in subdirs if d not in blocked and not d.startswith(".")]
        for filename in filenames:
            file_path = current / filename
            try:
                stat = file_path.stat()
            except OSError as exc:
                result.skipped.append(
                    {"path": str(file_path), "reason": f"无法读取文件信息: {exc.strerror or exc}"}
                )
                continue
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if wanted is not None and ext not in wanted:
                continue
            result.entries.append(
                FileEntry(
                    path=file_path,
                    name=filename,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    ext=ext,
                )
            )

    sort_entries(result.entries, sort_by=sort_by, descending=descending)
    if limit is not None and limit >= 0:
        result.entries = result.entries[:limit]
    return result


SORT_KEYS = {
    "name": lambda e: str(e.path).lower(),
    "size": lambda e: e.size,
    "mtime": lambda e: e.mtime,
    "ext": lambda e: (e.ext, str(e.path).lower()),
}


def sort_entries(entries: List[FileEntry], sort_by: str = "name", descending: bool = False) -> None:
    """原地排序；未知字段时回退为按名称排序。"""
    key_func = SORT_KEYS.get(sort_by, SORT_KEYS["name"])
    entries.sort(key=key_func, reverse=descending)


def display_width(text: str) -> int:
    """计算字符串的终端显示宽度（中日韩全角字符算 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - display_width(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def render_table(result: ScanResult, show_relpath: bool = True) -> str:
    """把扫描结果渲染成对齐的纯文本表格。"""
    if not result.entries:
        return "（没有匹配的文件）"

    headers = ["文件名", "大小", "修改时间"]
    if show_relpath:
        headers.append("相对路径")

    rows = []
    for entry in result.entries:
        row = [entry.name, format_size(entry.size), entry.mtime_str]
        if show_relpath:
            row.append(entry.rel_to(result.root))
        rows.append(row)

    widths = [
        max(display_width(headers[i]), *(display_width(r[i]) for r in rows))
        for i in range(len(headers))
    ]

    def line(cells: Sequence[str]) -> str:
        parts = [
            pad(cells[0], widths[0]),
            pad(cells[1], widths[1], align="right"),
            pad(cells[2], widths[2]),
        ]
        if show_relpath:
            parts.append(pad(cells[3], widths[3]))
        return "  ".join(parts).rstrip()

    out = [line(headers), "  ".join("-" * w for w in widths)]
    out.extend(line(r) for r in rows)
    out.append("")
    out.append(
        f"共 {len(result.entries)} 个文件，合计 {format_size(result.total_size)}"
        f"（目录：{result.root}）"
    )
    if result.skipped:
        out.append(f"跳过 {len(result.skipped)} 个（无法读取），详见 --json 输出")
    return "\n".join(out)

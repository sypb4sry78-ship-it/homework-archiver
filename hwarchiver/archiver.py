"""按学期/类别归档到子文件夹（需求 3）。

与改名一样：默认只预览，--apply 且确认后才真正移动；绝不覆盖已有文件。
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .scanner import FileEntry, display_width, pad, scan

STATUS_MOVE = "moved"
STATUS_SKIP = "skip"
STATUS_CONFLICT = "conflict"

UNKNOWN_SEMESTER = "未识别学期"
UNKNOWN_CATEGORY = "未分类"

# 学期识别：2024春 / 2024-春 / 2024_秋 / 2024-2025-1 / 2024-1
SEMESTER_PATTERNS: List[Tuple[re.Pattern, callable]] = [
    (re.compile(r"(20\d{2})\s*[-_年]?\s*(春季|秋季|春|秋)"), lambda m: f"{m.group(1)}{m.group(2)[0]}"),
    (re.compile(r"(20\d{2})\s*[-_]\s*(20\d{2})\s*[-_]\s*([12])"), lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
    (re.compile(r"(20\d{2})\s*[-_]\s*([12])"), lambda m: f"{m.group(1)}-{m.group(2)}"),
]

DEFAULT_CATEGORIES: Dict[str, Tuple[str, ...]] = {
    "实验报告": ("实验", "experiment", "lab"),
    "课程论文": ("论文", "paper", "thesis"),
    "课程设计": ("设计", "design"),
    "考试答卷": ("期末", "期中", "考试", "exam", "quiz"),
    "平时作业": ("作业", "homework", "hw", "习题"),
}


@dataclass
class MoveItem:
    src: Path
    dst: Path
    status: str = STATUS_MOVE
    reason: str = ""
    applied: bool = False

    @property
    def is_skip(self) -> bool:
        return self.status == STATUS_SKIP

    def to_dict(self, root: Optional[Path] = None) -> dict:
        def rel(p: Path) -> str:
            if root is None:
                return str(p)
            try:
                return str(p.relative_to(root))
            except ValueError:
                return str(p)

        return {
            "from": rel(self.src),
            "to": rel(self.dst),
            "status": self.status,
            "reason": self.reason,
            "applied": self.applied,
        }


@dataclass
class ArchivePlan:
    root: Path
    by: str
    items: List[MoveItem] = field(default_factory=list)

    @property
    def to_move(self) -> List[MoveItem]:
        return [i for i in self.items if not i.is_skip]

    @property
    def skipped(self) -> List[MoveItem]:
        return [i for i in self.items if i.is_skip]

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "by": self.by,
            "total": len(self.items),
            "to_move": len(self.to_move),
            "skipped": len(self.skipped),
            "items": [i.to_dict(self.root) for i in self.items],
        }


def parse_category_map(pairs: Optional[Iterable[str]]) -> Dict[str, List[str]]:
    """把 --map '实验=实验报告' 解析成 {类别: [关键词]}，并在默认表上追加。"""
    mapping: Dict[str, List[str]] = {k: list(v) for k, v in DEFAULT_CATEGORIES.items()}
    for pair in pairs or []:
        if "=" not in pair:
            continue
        keyword, category = (part.strip() for part in pair.split("=", 1))
        if not keyword or not category:
            continue
        mapping.setdefault(category, [])
        if keyword not in mapping[category]:
            mapping[category].append(keyword)
    return mapping


def detect_semester(name: str) -> Optional[str]:
    for pattern, formatter in SEMESTER_PATTERNS:
        match = pattern.search(name)
        if match:
            return formatter(match)
    return None


def detect_category(name: str, mapping: Optional[Dict[str, List[str]]] = None) -> str:
    mapping = mapping or parse_category_map(None)
    lowered = name.lower()
    for category, keywords in mapping.items():
        for keyword in keywords:
            if keyword.lower() in lowered:
                return category
    return UNKNOWN_CATEGORY


def classify(entry: FileEntry, by: str, mapping: Optional[Dict[str, List[str]]] = None) -> str:
    """决定文件该进哪个子文件夹。"""
    if by == "ext":
        return entry.ext.lstrip(".").lower() or "无扩展名"
    if by == "semester":
        return detect_semester(entry.name) or UNKNOWN_SEMESTER
    if by == "category":
        return detect_category(entry.name, mapping)
    raise ValueError(f"未知的归档方式：{by}（可选 ext / semester / category）")


def _key(path: Path) -> str:
    return str(path).lower()


def _resolve_conflict(dst: Path, taken: Set[str]) -> Optional[Path]:
    if _key(dst) not in taken and not dst.exists():
        return dst
    stem, suffix, n = dst.stem, dst.suffix, 1
    while n < 1000:
        candidate = dst.with_name(f"{stem}_{n}{suffix}")
        if _key(candidate) not in taken and not candidate.exists():
            return candidate
        n += 1
    return None


def build_archive_plan(
    root: os.PathLike | str,
    by: str = "semester",
    exts: Optional[Iterable[str]] = None,
    recursive: bool = False,
    category_map: Optional[Dict[str, List[str]]] = None,
    on_conflict: str = "suffix",
) -> ArchivePlan:
    """生成归档计划（只读，不移动任何文件）。"""
    result = scan(root, exts=exts, recursive=recursive)
    plan = ArchivePlan(root=result.root, by=by)
    taken: Set[str] = {_key(e.path) for e in result.entries}

    for entry in result.entries:
        folder = classify(entry, by, category_map)
        target_dir = plan.root / folder
        dst = target_dir / entry.name

        if entry.path.parent == target_dir:
            plan.items.append(
                MoveItem(src=entry.path, dst=dst, status=STATUS_SKIP, reason=f"已在目标位置：{folder}/")
            )
            continue

        if _key(dst) in taken or dst.exists():
            if on_conflict == "skip":
                plan.items.append(
                    MoveItem(
                        src=entry.path,
                        dst=dst,
                        status=STATUS_SKIP,
                        reason=f"目标已存在，按 --on-conflict=skip 跳过：{folder}/{dst.name}",
                    )
                )
                continue
            resolved = _resolve_conflict(dst, taken)
            if resolved is None:
                plan.items.append(
                    MoveItem(src=entry.path, dst=dst, status=STATUS_SKIP, reason="找不到可用的替代文件名")
                )
                continue
            dst = resolved
            status = STATUS_CONFLICT
            reason = f"目标已存在，自动改用 {dst.name}（未覆盖任何文件）"
        else:
            status = STATUS_MOVE
            reason = ""

        taken.add(_key(dst))
        plan.items.append(MoveItem(src=entry.path, dst=dst, status=status, reason=reason))

    return plan


def apply_archive(plan: ArchivePlan) -> ArchivePlan:
    """执行归档移动。"""
    for item in plan.items:
        if item.is_skip:
            continue
        if not item.src.exists():
            item.status = STATUS_SKIP
            item.reason = "源文件已不存在"
            continue
        try:
            item.dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item.src), str(item.dst))
            item.applied = True
        except (OSError, shutil.Error) as exc:
            item.status = STATUS_SKIP
            item.reason = f"移动失败：{exc}"
    return plan


def journal_items(plan: ArchivePlan) -> List[Dict[str, str]]:
    """把已完成的移动转成日志条目（相对路径，便于撤销）。"""
    items = []
    for item in plan.items:
        if not item.applied:
            continue
        items.append(
            {
                "type": "move",
                "from": str(item.src.relative_to(plan.root)),
                "to": str(item.dst.relative_to(plan.root)),
            }
        )
    return items


def render_archive_plan(plan: ArchivePlan, title: str = "归档预览") -> str:
    status_text = {STATUS_MOVE: "移动", STATUS_CONFLICT: "移动(避让)", STATUS_SKIP: "跳过"}
    if not plan.items:
        return "（没有需要归档的文件）"

    headers = ["原文件", "→", "归档到", "状态", "说明"]
    rows = []
    for item in plan.items:
        try:
            target = str(item.dst.relative_to(plan.root))
        except ValueError:
            target = str(item.dst)
        rows.append(
            [
                str(item.src.relative_to(plan.root)),
                "→",
                target if not item.is_skip else "-",
                status_text.get(item.status, item.status),
                item.reason,
            ]
        )

    widths = [
        max(display_width(headers[i]), *(display_width(r[i]) for r in rows)) for i in range(len(headers))
    ]
    lines = ["  ".join(pad(headers[i], widths[i]) for i in range(len(headers)))]
    lines.append("  ".join("-" * w for w in widths))
    lines.extend("  ".join(pad(r[i], widths[i]) for i in range(len(headers))) for r in rows)
    lines.append("")
    lines.append(
        f"{title}（按{plan.by}归类）：共 {len(plan.items)} 个文件，"
        f"待移动 {len(plan.to_move)} 个，跳过 {len(plan.skipped)} 个"
    )
    return "\n".join(lines)

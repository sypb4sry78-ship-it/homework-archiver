"""按规则批量改名（需求 2）。

核心约定：**默认只预览，绝不直接改**。必须先看到"将要改成的名字"，
显式确认后才真正执行；遇到重名冲突一律避让，绝不覆盖已有文件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .scanner import FileEntry, display_width, pad, scan

DEFAULT_TEMPLATE = "{hw}_{sid}"
DEFAULT_FIELDS = ("sid", "name", "hw")
INVALID_CHARS = '/\\:*?"<>|\n\r\t'

STATUS_RENAME = "rename"
STATUS_SKIP = "skip"
STATUS_CONFLICT = "conflict"


@dataclass
class RenameItem:
    """一条改名计划/结果。"""

    src: Path
    dst: Path
    status: str = STATUS_RENAME
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
class RenamePlan:
    """一次改名的完整计划。"""

    root: Path
    template: str
    items: List[RenameItem] = field(default_factory=list)

    @property
    def to_rename(self) -> List[RenameItem]:
        return [i for i in self.items if not i.is_skip]

    @property
    def skipped(self) -> List[RenameItem]:
        return [i for i in self.items if i.is_skip]

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "template": self.template,
            "total": len(self.items),
            "to_rename": len(self.to_rename),
            "skipped": len(self.skipped),
            "items": [i.to_dict(self.root) for i in self.items],
        }


def parse_fields(stem: str, sep: str = "_", fields: Sequence[str] = DEFAULT_FIELDS) -> Optional[Dict[str, str]]:
    """把 `学号_姓名_作业名` 解析成字段字典；段数不足时返回 None。

    - 段数 >= 字段数：前面的段按序赋值，剩余全部并入最后一个字段
    - 段数 == 字段数 - 1：认为缺"姓名"这一段，中间字段留空
    """
    parts = [p for p in stem.split(sep) if p != ""]
    n = len(fields)
    if len(parts) >= n:
        values = list(parts[: n - 1]) + [sep.join(parts[n - 1 :])]
    elif len(parts) == n - 1 and n >= 2:
        values = list(parts[:1]) + [""] + list(parts[1:])
    else:
        return None
    return dict(zip(fields, values))


def sanitize(name: str) -> tuple[str, bool]:
    """去掉文件名中的非法字符，返回 (新名字, 是否被改写)。"""
    cleaned = "".join("_" if ch in INVALID_CHARS else ch for ch in name).strip(" .")
    return cleaned, cleaned != name


def build_new_name(
    entry: FileEntry,
    template: str = DEFAULT_TEMPLATE,
    sep: str = "_",
    fields: Sequence[str] = DEFAULT_FIELDS,
) -> tuple[Optional[str], str]:
    """根据模板生成新文件名主体；返回 (新主体, 跳过原因)。"""
    parsed = parse_fields(entry.path.stem, sep=sep, fields=fields)
    if parsed is None:
        return None, f"文件名无法按 '{sep}' 拆出 {len(fields)} 段（{entry.name}）"
    try:
        new_stem = template.format(**parsed)
    except KeyError as exc:
        return None, f"模板里的字段 {exc} 不存在，可用字段：{', '.join(parsed)}"
    except (IndexError, ValueError) as exc:
        return None, f"模板解析失败：{exc}"
    new_stem, changed = sanitize(new_stem)
    if not new_stem:
        return None, "生成的新文件名为空"
    if new_stem == entry.path.stem:
        return None, "新名字与原名字相同，无需改动"
    return new_stem, ("文件名含非法字符，已替换为 _" if changed else "")


def _key(path: Path) -> str:
    """Windows 文件系统大小写不敏感，比较时统一小写。"""
    return str(path).lower()


def resolve_conflict(dst: Path, taken: Set[str]) -> Optional[Path]:
    """目标已存在时追加 _1/_2/...，返回一个绝不覆盖已有文件的路径。"""
    if _key(dst) not in taken and not dst.exists():
        return dst
    stem, suffix, n = dst.stem, dst.suffix, 1
    while n < 1000:
        candidate = dst.with_name(f"{stem}_{n}{suffix}")
        if _key(candidate) not in taken and not candidate.exists():
            return candidate
        n += 1
    return None


def build_plan(
    root: os.PathLike | str,
    template: str = DEFAULT_TEMPLATE,
    sep: str = "_",
    fields: Sequence[str] = DEFAULT_FIELDS,
    exts: Optional[Iterable[str]] = None,
    recursive: bool = False,
    on_conflict: str = "suffix",
) -> RenamePlan:
    """生成改名计划（只读，不碰磁盘上的文件）。

    :param on_conflict: suffix=自动加序号避让（默认）；skip=直接跳过
    """
    result = scan(root, exts=exts, recursive=recursive)
    plan = RenamePlan(root=result.root, template=template)
    taken: Set[str] = {_key(e.path) for e in result.entries}

    for entry in result.entries:
        new_stem, note = build_new_name(entry, template=template, sep=sep, fields=fields)
        if new_stem is None:
            plan.items.append(RenameItem(src=entry.path, dst=entry.path, status=STATUS_SKIP, reason=note))
            continue

        dst = entry.path.with_name(new_stem + entry.path.suffix)
        conflicted = _key(dst) in taken or dst.exists()
        if conflicted:
            if on_conflict == "skip":
                plan.items.append(
                    RenameItem(
                        src=entry.path,
                        dst=dst,
                        status=STATUS_SKIP,
                        reason=f"目标已存在，按 --on-conflict=skip 跳过：{dst.name}",
                    )
                )
                continue
            resolved = resolve_conflict(dst, taken)
            if resolved is None:
                plan.items.append(
                    RenameItem(src=entry.path, dst=dst, status=STATUS_SKIP, reason="找不到可用的替代文件名")
                )
                continue
            note = (note + "；" if note else "") + f"目标已存在，自动改用 {resolved.name}（未覆盖任何文件）"
            dst = resolved
            status = STATUS_CONFLICT
        else:
            status = STATUS_RENAME

        taken.add(_key(dst))
        plan.items.append(RenameItem(src=entry.path, dst=dst, status=status, reason=note))

    return plan


def apply_plan(plan: RenamePlan) -> RenamePlan:
    """执行计划中的改名；跳过项不动，失败项记录原因。"""
    for item in plan.items:
        if item.is_skip:
            continue
        if not item.src.exists():
            item.status = STATUS_SKIP
            item.reason = "源文件已不存在"
            continue
        try:
            item.dst.parent.mkdir(parents=True, exist_ok=True)
            item.src.rename(item.dst)
            item.applied = True
        except OSError as exc:
            item.status = STATUS_SKIP
            item.reason = f"改名失败：{exc.strerror or exc}"
    return plan


def journal_items(plan: RenamePlan) -> List[Dict[str, str]]:
    """把已完成的改名转成日志条目（相对路径，便于撤销）。"""
    items = []
    for item in plan.items:
        if not item.applied:
            continue
        items.append(
            {
                "type": "rename",
                "from": str(item.src.relative_to(plan.root)),
                "to": str(item.dst.relative_to(plan.root)),
            }
        )
    return items


def render_plan(plan: RenamePlan, title: str = "改名预览") -> str:
    """把计划渲染成 旧名 -> 新名 的表格。"""
    if not plan.items:
        return "（没有需要处理的文件）"

    status_text = {STATUS_RENAME: "改名", STATUS_CONFLICT: "改名(避让)", STATUS_SKIP: "跳过"}
    headers = ["原文件名", "→", "新文件名", "状态", "说明"]
    rows = []
    for item in plan.items:
        rows.append(
            [
                item.src.name,
                "→",
                item.dst.name if not item.is_skip else "-",
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
    lines.append(f"{title}：共 {len(plan.items)} 个文件，待改名 {len(plan.to_rename)} 个，跳过 {len(plan.skipped)} 个")
    return "\n".join(lines)

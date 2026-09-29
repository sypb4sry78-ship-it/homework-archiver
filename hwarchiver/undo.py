"""撤销上次操作（需求 3）。

改名和归档本质上都是"从 A 到 B 的移动"，所以撤销就是把 B 搬回 A。
搬不回去的（文件被手动改过、原位置又被占用）会如实报告，绝不覆盖。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .journal import Journal, Operation


@dataclass
class UndoItem:
    src: Path  # 现在的位置（操作后的路径）
    dst: Path  # 要恢复到的位置（操作前的路径）
    entry: Optional[Dict[str, str]] = None  # 对应的原始日志条目
    status: str = "undo"
    reason: str = ""
    applied: bool = False

    @property
    def is_skip(self) -> bool:
        return self.status == "skip"

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


def build_undo_plan(journal: Journal, op: Operation) -> List[UndoItem]:
    """为一次操作生成反向计划（倒序：后做的先撤销）。"""
    root = Path(op.root)
    items = []
    for entry in reversed(op.items):
        src = root / entry["to"]
        dst = root / entry["from"]
        items.append(UndoItem(src=src, dst=dst, entry=entry))
    return items


def apply_undo(journal: Journal, op: Operation, items: List[UndoItem]) -> List[UndoItem]:
    """执行撤销，并维护日志：全部撤销则归档到 undone/，部分失败则保留剩余条目。"""
    remaining: List[Dict[str, str]] = []
    for item in items:
        if not item.src.exists():
            item.status = "skip"
            item.reason = "文件不在操作后的位置上，可能已被手动改动"
            continue
        if item.dst.exists():
            item.status = "skip"
            item.reason = "原位置已有同名文件，未覆盖"
            continue
        try:
            item.dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item.src), str(item.dst))
            item.applied = True
            # 归档时被搬空的文件夹，撤销后顺手清掉（非空或没权限就算了）
            try:
                if item.src.parent != Path(op.root):
                    item.src.parent.rmdir()
            except OSError:
                pass
        except (OSError, shutil.Error) as exc:
            item.status = "skip"
            item.reason = f"撤销失败：{exc}"

    # 撤销成功的条目从日志里移除；还有没撤掉的就保留，下次可以再试
    remaining = [item.entry for item in items if not item.applied and item.entry]
    if remaining:
        op.items = remaining
        journal.save(op)
    else:
        journal.mark_undone(op)
    return items


def render_undo(op: Operation, items: List[UndoItem]) -> str:
    lines = [
        f"撤销操作：{op.kind}（{op.created_at}），共 {len(items)} 个文件",
        "",
    ]
    for item in items:
        flag = "已还原" if item.applied else f"未还原（{item.reason}）"
        lines.append(f"  {item.src.name}  <-  {item.dst.parent.name}/   {flag}")
    ok = sum(1 for i in items if i.applied)
    lines.append("")
    lines.append(f"撤销完成：成功 {ok} 个，未还原 {len(items) - ok} 个")
    return "\n".join(lines)


def undo_last(root: str | Path) -> Optional[tuple[Operation, List[UndoItem]]]:
    """撤销指定目录下最近一次操作；没有可撤销的操作时返回 None。"""
    journal = Journal(root)
    op = journal.last_operation()
    if op is None:
        return None
    items = build_undo_plan(journal, op)
    apply_undo(journal, op, items)
    return op, items

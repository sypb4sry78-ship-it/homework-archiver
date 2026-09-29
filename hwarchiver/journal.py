"""操作日志：记录每次改名/归档，支撑「撤销上次操作」（需求 3）。

每次操作在 <根目录>/.hwarchiver/ops/ 下写一份 JSON；撤销成功后移入 undone/。
只记录已完成的操作，绝不记录预览。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

META_DIRNAME = ".hwarchiver"


@dataclass
class Operation:
    """一次已执行的操作。"""

    id: str
    kind: str  # rename | archive
    created_at: str
    root: str
    items: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "created_at": self.created_at,
            "root": self.root,
            "items": self.items,
        }


class Journal:
    """简单的文件系统版操作日志。"""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.base = self.root / META_DIRNAME
        self.ops_dir = self.base / "ops"
        self.undone_dir = self.base / "undone"
        self.reports_dir = self.base / "reports"

    def _ensure(self) -> None:
        self.ops_dir.mkdir(parents=True, exist_ok=True)
        self.undone_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, items: List[Dict[str, str]]) -> Optional[Operation]:
        """记录一次操作；没有实际改动就不记录，返回 None。"""
        if not items:
            return None
        self._ensure()
        now = time.time()
        op_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{kind}"
        op = Operation(
            id=op_id,
            kind=kind,
            created_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            root=str(self.root),
            items=items,
        )
        # 同一秒内重复操作时避免互相覆盖
        target = self.ops_dir / f"{op_id}.json"
        n = 1
        while target.exists():
            target = self.ops_dir / f"{op_id}-{n}.json"
            n += 1
        target.write_text(json.dumps(op.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return op

    def _load(self, path: Path) -> Operation:
        data = json.loads(path.read_text(encoding="utf-8"))
        op = Operation(
            id=data.get("id", path.stem),
            kind=data.get("kind", "unknown"),
            created_at=data.get("created_at", ""),
            root=data.get("root", str(self.root)),
            items=data.get("items", []),
        )
        op.id = path.stem
        return op

    def operations(self) -> List[Operation]:
        """未撤销的操作，按时间从新到旧。"""
        if not self.ops_dir.exists():
            return []
        ops = [self._load(p) for p in self.ops_dir.glob("*.json")]
        return sorted(ops, key=lambda o: o.id, reverse=True)

    def last_operation(self) -> Optional[Operation]:
        ops = self.operations()
        return ops[0] if ops else None

    def save(self, op: Operation) -> None:
        (self.ops_dir / f"{op.id}.json").write_text(
            json.dumps(op.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def mark_undone(self, op: Operation) -> None:
        self.undone_dir.mkdir(parents=True, exist_ok=True)
        src = self.ops_dir / f"{op.id}.json"
        if src.exists():
            src.replace(self.undone_dir / src.name)

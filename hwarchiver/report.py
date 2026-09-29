"""整理报告：处理了多少个、跳过多少个、为什么跳过（需求 3）。"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

STATUS_LABELS = {
    "rename": "已改名",
    "moved": "已移动",
    "conflict": "已改名（避让重名）",
    "skip": "已跳过",
}

# 把具体的跳过原因归一成几类，便于在报告里汇总
REASON_RULES = [
    ("目标已存在", "目标位置已被占用"),
    ("已在目标", "文件已在目标位置"),
    ("无法按", "文件名不符合规则，拆不出字段"),
    ("不存在", "源文件已不存在"),
    ("失败", "执行失败"),
    ("相同", "新旧名字相同，无需处理"),
    ("模板", "模板字段不存在"),
    ("为空", "生成的新名字为空"),
    ("未识别", "无法识别学期/类别"),
]


def classify_reason(reason: str) -> str:
    for key, label in REASON_RULES:
        if key in reason:
            return label
    return reason.strip() or "其他"


@dataclass
class Report:
    kind: str
    created_at: str
    root: Path
    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    skip_reasons: Dict[str, int] = field(default_factory=dict)
    items: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "created_at": self.created_at,
            "root": str(self.root),
            "total": self.total,
            "processed": self.processed,
            "skipped": self.skipped,
            "failed": self.failed,
            "skip_reasons": self.skip_reasons,
            "items": self.items,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# 整理报告：{self.kind}",
            "",
            f"- 时间：{self.created_at}",
            f"- 目录：{self.root}",
            f"- 共处理 {self.total} 个文件：成功 {self.processed} 个，跳过 {self.skipped} 个，失败 {self.failed} 个",
            "",
        ]
        if self.skip_reasons:
            lines.append("## 为什么跳过")
            lines.append("")
            lines.append("| 原因 | 数量 |")
            lines.append("| --- | --- |")
            for reason, count in sorted(self.skip_reasons.items(), key=lambda kv: -kv[1]):
                lines.append(f"| {reason} | {count} |")
            lines.append("")
        if self.items:
            lines.append("## 明细")
            lines.append("")
            lines.append("| 原路径 | 新路径 | 状态 | 说明 |")
            lines.append("| --- | --- | --- | --- |")
            for item in self.items:
                lines.append(
                    f"| {item['from']} | {item['to']} | {STATUS_LABELS.get(item['status'], item['status'])} "
                    f"| {item['reason']} |"
                )
            lines.append("")
        return "\n".join(lines)

    def save(self, directory: Path) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        md_path = directory / f"report-{stamp}.md"
        json_path = directory / f"report-{stamp}.json"
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        json_path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return md_path, json_path


def build_report(kind: str, root: Path, items: Sequence) -> Report:
    """根据一批操作结果生成报告。

    items 里的对象需要有 is_skip / applied / status / reason / to_dict(root) 这些属性。
    """
    now = time.time()
    report = Report(
        kind=kind,
        created_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        root=Path(root),
        total=len(items),
    )
    reason_counter: Counter = Counter()
    for item in items:
        report.items.append(item.to_dict(Path(root)))
        if getattr(item, "is_skip", False):
            report.skipped += 1
            reason_counter[classify_reason(getattr(item, "reason", ""))] += 1
        elif getattr(item, "applied", False):
            report.processed += 1
        else:
            report.failed += 1
            reason_counter[classify_reason(getattr(item, "reason", "") or "执行失败")] += 1
    report.skip_reasons = dict(reason_counter)
    return report


def latest_report(reports_dir: Path) -> Optional[Path]:
    files = sorted(reports_dir.glob("report-*.md")) if reports_dir.exists() else []
    return files[-1] if files else None

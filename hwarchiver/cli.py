"""命令行入口：python -m hwarchiver <子命令> [参数]。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .archiver import (
    apply_archive,
    build_archive_plan,
    journal_items as archive_journal_items,
    parse_category_map,
    render_archive_plan,
)
from .journal import Journal
from .renamer import apply_plan, build_plan, journal_items as rename_journal_items, render_plan
from .report import build_report, latest_report
from .scanner import render_table, scan
from .undo import apply_undo, build_undo_plan, render_undo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hwarchiver",
        description="作业文件批量归档工具（扫描 / 改名 / 归档 / 撤销）",
    )
    parser.add_argument("--version", action="version", version=f"hwarchiver {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- 需求 1：扫描与列出 ----
    p_scan = sub.add_parser("scan", help="扫描目录并列出文件")
    p_scan.add_argument("directory", help="要扫描的文件夹")
    p_scan.add_argument(
        "--ext",
        help="按扩展名过滤，逗号分隔，如 .pdf,.docx（不填则列出全部）",
    )
    p_scan.add_argument(
        "--sort",
        choices=["name", "size", "mtime", "ext"],
        default="name",
        help="排序字段（默认 name）",
    )
    p_scan.add_argument("--desc", action="store_true", help="降序排列")
    p_scan.add_argument("--no-recursive", action="store_true", help="只扫描当前层，不进子目录")
    p_scan.add_argument("--limit", type=int, help="只显示前 N 个")
    p_scan.add_argument("--json", action="store_true", help="以 JSON 输出，便于管道处理")
    p_scan.set_defaults(func=cmd_scan)

    # ---- 需求 2：批量改名 ----
    p_rename = sub.add_parser("rename", help="按规则批量改名（默认只预览）")
    p_rename.add_argument("directory", help="要处理的文件夹")
    p_rename.add_argument(
        "--template",
        default="{hw}_{sid}",
        help="新文件名模板，可用 {sid} 学号 / {name} 姓名 / {hw} 作业名（默认 '{hw}_{sid}'）",
    )
    p_rename.add_argument("--sep", default="_", help="文件名分段分隔符（默认 _）")
    p_rename.add_argument(
        "--fields",
        default="sid,name,hw",
        help="各段含义，逗号分隔（默认 sid,name,hw）",
    )
    p_rename.add_argument("--ext", help="只处理指定扩展名，逗号分隔")
    p_rename.add_argument("--recursive", action="store_true", help="同时处理子目录（默认只处理当前层）")
    p_rename.add_argument(
        "--on-conflict",
        choices=["suffix", "skip"],
        default="suffix",
        help="重名冲突时：suffix=自动加 _1/_2 避让（默认，绝不覆盖）；skip=跳过不处理",
    )
    p_rename.add_argument("--apply", action="store_true", help="真正执行改名（不加则只预览）")
    p_rename.add_argument("--yes", action="store_true", help="配合 --apply，跳过交互确认")
    p_rename.add_argument("--json", action="store_true", help="以 JSON 输出计划/结果")
    p_rename.set_defaults(func=cmd_rename)

    # ---- 需求 3：归档 ----
    p_archive = sub.add_parser("archive", help="按学期/类别归档到子文件夹（默认只预览）")
    p_archive.add_argument("directory", help="要整理的文件夹")
    p_archive.add_argument(
        "--by",
        choices=["semester", "category", "ext"],
        default="semester",
        help="归档方式：semester 按学期 / category 按类别 / ext 按扩展名（默认 semester）",
    )
    p_archive.add_argument("--ext", help="只处理指定扩展名，逗号分隔")
    p_archive.add_argument("--recursive", action="store_true", help="同时处理子目录（默认只处理当前层）")
    p_archive.add_argument(
        "--map",
        nargs="*",
        metavar="关键词=类别",
        help="自定义类别规则，如 --map 实验=实验报告 期末=考试答卷（在默认规则上追加）",
    )
    p_archive.add_argument(
        "--on-conflict",
        choices=["suffix", "skip"],
        default="suffix",
        help="目标已存在时：suffix=自动加 _1/_2 避让（默认）；skip=跳过",
    )
    p_archive.add_argument("--apply", action="store_true", help="真正执行移动（不加则只预览）")
    p_archive.add_argument("--yes", action="store_true", help="配合 --apply，跳过交互确认")
    p_archive.add_argument("--json", action="store_true", help="以 JSON 输出计划/结果")
    p_archive.set_defaults(func=cmd_archive)

    # ---- 需求 3：撤销 ----
    p_undo = sub.add_parser("undo", help="撤销上一次改名/归档")
    p_undo.add_argument("directory", help="操作所在的文件夹")
    p_undo.add_argument("--yes", action="store_true", help="跳过交互确认")
    p_undo.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_undo.set_defaults(func=cmd_undo)

    # ---- 需求 3：报告 ----
    p_report = sub.add_parser("report", help="查看最近一次整理报告")
    p_report.add_argument("directory", help="操作所在的文件夹")
    p_report.add_argument("--json", action="store_true", help="输出 JSON 版本的报告")
    p_report.set_defaults(func=cmd_report)

    return parser


def _split_ext(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def request_confirmation(prompt: str = "确认执行？[y/N] ") -> bool:
    """交互确认；非交互环境（管道/重定向）一律视为取消。"""
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("（未获得确认输入，按取消处理）")
        return False
    return answer in ("y", "yes")


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        result = scan(
            args.directory,
            exts=_split_ext(args.ext),
            recursive=not args.no_recursive,
            sort_by=args.sort,
            descending=args.desc,
            limit=args.limit,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_table(result))
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
    try:
        plan = build_plan(
            args.directory,
            template=args.template,
            sep=args.sep,
            fields=fields,
            exts=_split_ext(args.ext),
            recursive=args.recursive,
            on_conflict=args.on_conflict,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    # 第一步永远是"打印将要改成的名字"
    print(render_plan(plan, title="改名预览"))

    if args.json:
        print()
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))

    if not args.apply:
        print("\n以上仅为预览，没有改动任何文件。核对无误后加 --apply 才会真正改名。")
        return 0

    if not args.yes and not request_confirmation("\n按以上预览执行改名？[y/N] "):
        print("已取消，未做任何改动。")
        return 1

    apply_plan(plan)
    print("\n执行结果：")
    print(render_plan(plan, title="改名结果"))
    _finish(args.directory, "rename", plan.items, rename_journal_items(plan))
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    try:
        plan = build_archive_plan(
            args.directory,
            by=args.by,
            exts=_split_ext(args.ext),
            recursive=args.recursive,
            category_map=parse_category_map(args.map),
            on_conflict=args.on_conflict,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    print(render_archive_plan(plan, title="归档预览"))

    if args.json:
        print()
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))

    if not args.apply:
        print("\n以上仅为预览，没有移动任何文件。核对无误后加 --apply 才会真正归档。")
        return 0

    if not args.yes and not request_confirmation("\n按以上预览执行归档？[y/N] "):
        print("已取消，未做任何改动。")
        return 1

    apply_archive(plan)
    print("\n执行结果：")
    print(render_archive_plan(plan, title="归档结果"))
    _finish(args.directory, f"archive:{plan.by}", plan.items, archive_journal_items(plan))
    return 0


def _finish(directory: str, kind: str, items, journal_entries) -> None:
    """执行收尾：写操作日志（供撤销）+ 生成整理报告。"""
    if not journal_entries:
        print("\n本次没有任何文件被改动，未生成报告。")
        return
    journal = Journal(directory)
    journal.record(kind.split(":")[0], journal_entries)
    report = build_report(kind, journal.root, items)
    md_path, json_path = report.save(journal.reports_dir)
    print(f"\n整理报告：{md_path}")
    print(f"         {json_path}")
    print(f"撤销本次操作：python -m hwarchiver undo {directory}")


def cmd_undo(args: argparse.Namespace) -> int:
    journal = Journal(args.directory)
    op = journal.last_operation()
    if op is None:
        print("没有可撤销的操作（.hwarchiver/ops/ 里没有记录）。")
        return 0

    print(f"将要撤销：{op.kind} 操作（{op.created_at}），共 {len(op.items)} 个文件")
    for entry in op.items:
        print(f"  {entry['to']}  ->  {entry['from']}")

    if args.json:
        print(json.dumps(op.to_dict(), ensure_ascii=False, indent=2))

    if not args.yes and not request_confirmation("\n确认撤销？[y/N] "):
        print("已取消，未做任何改动。")
        return 1

    items = build_undo_plan(journal, op)
    apply_undo(journal, op, items)
    print()
    print(render_undo(op, items))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    journal = Journal(args.directory)
    md_path = latest_report(journal.reports_dir)
    if md_path is None:
        print("还没有任何整理报告。")
        return 0
    if args.json:
        print((md_path.with_suffix(".json")).read_text(encoding="utf-8"))
    else:
        print(md_path.read_text(encoding="utf-8"))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

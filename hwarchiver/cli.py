"""命令行入口：python -m hwarchiver <子命令> [参数]。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .renamer import apply_plan, build_plan, render_plan
from .scanner import scan, render_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hwarchiver",
        description="作业文件批量归档工具（扫描 / 改名 / 归档）",
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
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

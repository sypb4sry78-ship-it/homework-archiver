"""命令行入口：python -m hwarchiver <子命令> [参数]。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
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

    return parser


def _split_ext(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


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


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

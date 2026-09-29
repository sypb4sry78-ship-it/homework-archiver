"""生成一批演示用作业文件，方便试用本工具。

用法：
    python tools/make_samples.py [目标目录]
"""

import sys
from pathlib import Path

SAMPLES = [
    ("2023001_张三_数据结构实验一.pdf", 120_000),
    ("2023002_李四_数据结构实验一.pdf", 98_000),
    ("2023003_王五_数据结构实验二.pdf", 134_000),
    ("2023001_张三_操作系统报告.docx", 45_000),
    ("2023002_李四_编译原理作业3.pdf", 76_000),
    ("2023004_赵六_2024春_机器学习期末.pdf", 210_000),
    ("2023003_王五_2024秋_数据库课程设计.docx", 88_000),
    ("2023005_钱七_实验报告_线性代数.pdf", 65_000),
    ("README.txt", 512),
    ("2023001_张三_数据结构实验一.pdf", 120_000),  # 故意重名（放子目录）
]

SUBDIR_FILES = [
    ("补交/2023006_孙八_数据结构实验一.pdf", 101_000),
    ("补交/2023002_李四_实验报告_补交.docx", 33_000),
]


def make_samples(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for rel, size in SAMPLES[:9]:
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)
        written += 1
    for rel, size in SUBDIR_FILES:
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)
        written += 1
    # 再在子目录放一个与根目录同名的文件，用于演示重名冲突
    dup = target / "补交" / "2023001_张三_操作系统报告.docx"
    dup.write_bytes(b"\0" * 45_000)
    written += 1
    return written


def main(argv):
    target = Path(argv[1]) if len(argv) > 1 else Path("sample_homework")
    count = make_samples(target)
    print(f"已生成 {count} 个示例文件到 {target.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

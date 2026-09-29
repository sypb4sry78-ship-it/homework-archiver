# homework-archiver

作业文件批量归档小工具。零第三方依赖，Python 3.8+ 直接运行。

三个需求各一次提交、各一个 PR：

| PR | 需求 | 状态 |
| --- | --- | --- |
| #1 | 扫描与列出 | 已完成 |
| #2 | 批量改名（预览 + 确认 + 冲突避让） | 待开始 |
| #3 | 归档、报告与撤销 | 待开始 |

## 安装

无需安装，克隆后直接使用：

```bash
git clone <仓库地址>
cd homework-archiver
python -m hwarchiver --help
```

想先造一批演示文件：

```bash
python tools/make_samples.py sample_homework
```

## 需求 1：扫描与列出

```bash
# 列出全部文件（含子目录），显示大小与修改时间
python -m hwarchiver scan ./sample_homework

# 只看 pdf 和 docx
python -m hwarchiver scan ./sample_homework --ext .pdf,.docx

# 按体积从大到小，只看前 5 个
python -m hwarchiver scan ./sample_homework --sort size --desc --limit 5

# 不进子目录 / 输出 JSON 给别的程序用
python -m hwarchiver scan ./sample_homework --no-recursive --json
```

输出示例：

```
文件名                                    大小  修改时间             相对路径
------------------------------------  --------  -------------------  ------------------------------------
2023004_赵六_2024春_机器学习期末.pdf  205.1 KB  2026-09-29 23:40:51  2023004_赵六_2024春_机器学习期末.pdf
2023003_王五_数据结构实验二.pdf       130.9 KB  2026-09-29 23:40:51  2023003_王五_数据结构实验二.pdf

共 7 个文件，合计 785.2 KB（目录：.../sample_homework）
```

要点：

- `--ext` 大小写不敏感，`.pdf` 和 `pdf` 都认；不传则列出全部
- 自动跳过 `.hwarchiver`、`.git`、`__pycache__`、`.venv`、`node_modules` 等目录
- 表格按中日韩全角字符计算显示宽度，中文文件名也能对齐
- 扫描不到的文件（权限问题等）计入 `skipped`，可在 `--json` 里看到原因

## 测试

```bash
python -m unittest discover -s tests
```

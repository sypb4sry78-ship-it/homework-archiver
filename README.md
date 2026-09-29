# homework-archiver

作业文件批量归档小工具。零第三方依赖，Python 3.8+ 直接运行。

三个需求各一次提交、各一个 PR：

| PR | 需求 | 状态 |
| --- | --- | --- |
| #1 | 扫描与列出 | 已完成 |
| #2 | 批量改名（预览 + 确认 + 冲突避让） | 已完成 |
| #3 | 归档、报告与撤销 | 已完成 |

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

## 需求 2：批量改名

默认规则：把 `学号_姓名_作业名.pdf` 改成 `作业名_学号.pdf`。

```bash
# 第一步永远是"预览"，不会动任何文件
python -m hwarchiver rename ./sample_homework --ext .pdf

# 确认预览没问题后，才真正执行（会再要一次 y/N 确认）
python -m hwarchiver rename ./sample_homework --ext .pdf --apply

# 脚本里用：跳过交互确认
python -m hwarchiver rename ./sample_homework --ext .pdf --apply --yes
```

预览输出：

```
原文件名                              →  新文件名                         状态  说明
------------------------------------  -  -------------------------------  ----  ----
2023001_张三_数据结构实验一.pdf       →  数据结构实验一_2023001.pdf       改名
2023002_李四_数据结构实验一.pdf       →  数据结构实验一_2023002.pdf       改名
2023005_钱七_实验报告_线性代数.pdf    →  实验报告_线性代数_2023005.pdf    改名

改名预览：共 6 个文件，待改名 6 个，跳过 0 个

以上仅为预览，没有改动任何文件。核对无误后加 --apply 才会真正改名。
```

### 三条硬规则

1. **不允许直接改**：不带 `--apply` 时只打印预览；带 `--apply` 时也会先把新名字打出来，再要求输入 `y` 确认（非交互环境一律按取消处理）。
2. **不覆盖已有文件**：目标名已存在时自动追加 `_1`、`_2`… 并在"说明"列标注；也可以 `--on-conflict skip` 直接跳过。源码里 `resolve_conflict()` 保证只会返回不存在的路径。
3. **跳过必给原因**：文件名拆不出字段、模板引用了不存在的字段、新名与原名相同、目标被占用（skip 模式）等，都会在"说明"列写清楚。

### 改名规则可定制

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--template` | `{hw}_{sid}` | 新文件名模板，可用 `{sid}` 学号、`{name}` 姓名、`{hw}` 作业名 |
| `--sep` | `_` | 文件名分段分隔符 |
| `--fields` | `sid,name,hw` | 各段含义；段数不足时自动把"姓名"留空 |
| `--on-conflict` | `suffix` | `suffix` 自动加序号避让 / `skip` 跳过 |
| `--recursive` | 关 | 默认只处理当前层，避免误伤子目录 |

示例：改成 `学号-作业名.pdf`

```bash
python -m hwarchiver rename ./sample_homework --template "{sid}-{hw}" --apply
```

## 需求 3：归档、报告与撤销

### 归档到子文件夹

```bash
# 按学期归档：先看预览
python -m hwarchiver archive ./sample_homework --by semester

# 确认后执行
python -m hwarchiver archive ./sample_homework --by semester --apply
```

| `--by` | 归类依据 | 示例文件名 → 子文件夹 |
| --- | --- | --- |
| `semester`（默认） | 从文件名里识别学期 | `2024春_机器学习期末.pdf` → `2024春/`；识别不出 → `未识别学期/` |
| `category` | 按关键词分类别 | 含"实验"→`实验报告/`，含"期末/期中"→`考试答卷/`，含"作业"→`平时作业/` |
| `ext` | 按扩展名 | `a.pdf` → `pdf/` |

学期识别支持 `2024春`、`2024-秋`、`2024_秋季`、`2024-2025-1`、`2024-2` 等写法。
类别规则可用 `--map 关键词=类别` 追加，例如 `--map 读书笔记=读书笔记`。

归档同样遵守"预览优先 + 确认后执行 + 不覆盖"：目标位置已有同名文件时自动加 `_1`，`--on-conflict skip` 则跳过。

### 整理报告

每次执行后自动生成报告到 `<目录>/.hwarchiver/reports/`：

```bash
python -m hwarchiver report ./sample_homework          # 查看最近一次
python -m hwarchiver report ./sample_homework --json   # 机器可读版本
```

```
# 整理报告：archive:semester

- 时间：2026-09-29 23:55:26
- 目录：.../sample_homework
- 共处理 9 个文件：成功 9 个，跳过 0 个，失败 0 个

## 为什么跳过

| 原因 | 数量 |
| --- | --- |
| 文件已在目标位置 | 1 |
| 无法识别学期 | 2 |
```

报告同时给出 Markdown 和 JSON 两份，含逐条明细（原路径 / 新路径 / 状态 / 原因）。

### 撤销上次操作

```bash
python -m hwarchiver undo ./sample_homework
```

会先列出"将要撤回到哪里"，确认后把文件一个个搬回原位：

```
将要撤销：archive 操作（2026-09-29 23:55:26），共 9 个文件
  2024春\2024春_机器学习期末_2023004.pdf  ->  2024春_机器学习期末_2023004.pdf
  ...

撤销完成：成功 9 个，未还原 0 个
```

撤销机制说明：

- 每次改名/归档完成后才写日志到 `<目录>/.hwarchiver/ops/`，预览不写
- `undo` 撤销最近一次操作，成功后日志移入 `undone/`
- 撤销时若原位置已被别的同名文件占用，**不会覆盖**，会如实报告"未还原"，并保留这条记录方便你处理后重试
- 归档时被搬空的文件夹，撤销后会顺手删掉

## 安全设计（三条需求共通）

| 担心的事 | 做法 |
| --- | --- |
| 手滑误改 | 所有改动类命令默认只预览，`--apply` 才动手，且还要一次确认 |
| 覆盖别人的文件 | 冲突时自动加 `_1`/`_2` 避让，`resolve_conflict()` 只返回不存在的路径 |
| 改完后悔 | 每次操作留日志，`undo` 一键还原 |
| 不知道发生了什么 | 每次执行生成报告，处理/跳过数量与跳过原因一目了然 |
| 误伤子目录 | 改名/归档默认只处理当前层，要递归需显式 `--recursive` |

## 项目结构

```
hwarchiver/
  scanner.py    需求 1：扫描、过滤、排序、表格渲染
  renamer.py    需求 2：改名规则、冲突避让
  archiver.py   需求 3：按学期/类别归类与移动
  journal.py    需求 3：操作日志
  undo.py       需求 3：撤销
  report.py     需求 3：整理报告
  cli.py        命令行入口
tests/          61 个单元测试（标准库 unittest，无需安装 pytest）
tools/          示例作业文件生成
```

## 测试

```bash
python -m unittest discover -s tests
```

## 完整演示

```bash
python tools/make_samples.py sample_homework
python -m hwarchiver scan sample_homework                                  # 需求 1
python -m hwarchiver rename sample_homework --ext .pdf,.docx --apply       # 需求 2
python -m hwarchiver archive sample_homework --by semester --apply         # 需求 3
python -m hwarchiver report sample_homework                                # 看报告
python -m hwarchiver undo sample_homework                                  # 撤销归档
python -m hwarchiver undo sample_homework                                  # 撤销改名
```

# 词表数据（data/wordlists/）

英语学习项目的词汇数据，全部为开源/免费授权。

## 文件

| 文件 | 说明 |
| --- | --- |
| `wordlist.csv` | **项目主词表**（已过滤、分带），供评测/分级/生词标注使用 |
| `surface_lemma.json` | 词形 → 词族头映射（约 19.8 万条，提交入库），供分级阅读做词形还原 |
| `sensitive_blacklist.json` | 少儿不宜敏感词黑名单（评测抽题时过滤） |
| `transliteration_blacklist.json` | 低频纯音译词黑名单（人名/地名/乐器/药名等，评测抽题时过滤） |
| `download_raw.py` | 一键下载并解压下方所有 `raw/` 数据（幂等 + SHA256 校验），全新 clone 第一步 |
| `process_ecdict.py` | 从 raw 生成 `wordlist.csv` 的处理脚本 |
| `build_surface_lemma.py` | 从 raw 词族表 + 词形还原表生成 `surface_lemma.json` 的脚本 |
| `raw/ecdict.csv` | ECDICT 全量原始数据（约 76 万词条，63MB，MIT） |
| `raw/lemma.en.txt` | 词形还原映射（词 → 原型），供阅读标注做词形还原（**不再用于词表生成**） |
| `raw/ecdict-sqlite-28.zip` | ECDICT SQLite 压缩包（MIT，解压出 `stardict.db`） |
| `raw/stardict.db` | ECDICT SQLite（约 811MB），后台「多词表达式/术语识别」运行时依赖（不入库，由 `download_raw.py` 拉取） |
| `raw/basewrd1.txt`~`basewrd25.txt` | Paul Nation BNC/COCA 25000 基础词族表（每文件 1000 词族，CC BY-SA 4.0） |
| `raw/basewrd31~34.txt` | Nation 附加表：专有名词 / 边缘词 / 透明复合词 / 缩写（**不参与排名**） |
| `raw/BNC_COCA_25000.zip` | 上述 Nation 数据的官方压缩包（已校验 SHA256） |

## wordlist.csv 字段

| 字段 | 说明 |
| --- | --- |
| `lemma` | 词条（词族代表词形 = 词族头原型） |
| `phonetic` | 音标 |
| `pos` | 词性 |
| `translation` | 中文释义（多义项用「；」分隔） |
| `collins` | 柯林斯星级 1–5（越高越常用） |
| `oxford` | 是否牛津 3000 核心词（1 = 是） |
| `tag` | 考试标签（空格分隔）：`zk`中考 / `gk`高考 / `cet4` / `cet6` / `ky`考研 / `toefl` / `ielts` / `gre` |
| `bnc` | BNC（英国国家语料库）词频排名，越小越常见（词形级，参考用） |
| `frq` | 当代语料库词频排名，越小越常见（词形级，参考用） |
| `rank` | **Nation BNC/COCA 词族排名**，1~25000，越小越常见（**评测与分带以此为准**） |
| `freq_band` | 词频分带：`1k/2k/3k/5k/10k/15k/20k/25k` |

## 频率分带规则

按 `rank`（Nation 词族排名，1~25000）分带：

- `1k`：≤1000；`2k`：≤2000；`3k`：≤3000；`5k`：≤5000；`10k`：≤10000；`15k`：≤15000；`20k`：≤20000；其余 `25k`

## 为什么用「Nation 词族 rank」而不是 `frq`？

词汇量测试（qsbdc、欧路等）用的是**词族**（word family）口径——认识一个词族就算认识一族。
`frq` 是**词形级**排名，一个词族的每个屈折变形各占一个排名，会被重复计分。

本项目采用 Paul Nation 的 **BNC/COCA 25000 基础词族表**（25×1000 词族）作为标准标度，
与主流词汇量测试口径完全一致。它的关键特点是：

- **词族覆盖派生**：able / ability / unable / inability 归为 **ABLE** 一族（而不是 4 族）；
  environmentalism 归入 environment 一族。
- **透明复合词不算**：wildfire、bloodline 等在「透明复合词」附加表（basewrd33），不占基础排名；
  认识它们靠词根，不反映独立词汇量。
- **英美拼写合一**：colour / color 归为 **COLOUR** 一族。

早期版本用 `lemma.en.txt`（ECDICT 自带词形还原表）还原词族，但它把每个派生词（environmentalism）
与透明复合词（wildfire）都当成独立词族，共 62072 族，比 Nation 密约 2.5 倍，导致高词汇量用户被
系统性高估（实测同一用户 23280 vs 真实 12000）。故改用 Nation 25000 基础词族作 `rank`。

当前规模：约 2.36 万词族（25000 中约 1389 族因 ECDICT 无词条/释义被过滤而跳过）。

## 数据来源与授权

- **ECDICT** — https://github.com/skywind3000/ECDICT （开源英汉双解词典，**MIT 授权**）：中文释义、音标、柯林斯/牛津分级、考试标签、BNC/当代词频。
- **Paul Nation BNC/COCA 25000** — https://www.wgtn.ac.nz/lals/resources/paul-nations-resources/vocabulary-analysis-programs/range/BNC_COCA_25000.zip （**CC BY-SA 4.0**，使用时请署名 Paul Nation）：词族标度。
- **lemma.en.txt** — ECDICT 附带，扫描 BNC 一亿词生成的词形还原表（供阅读标注做词形还原）。

## 下载原始数据（全新 clone 第一步）

`raw/` 目录（约 875MB）不入库。已提交的 `wordlist.csv` / `surface_lemma.json` 能让主流程
（评测/分级阅读标注）直接运行，但后台「自动定级 → 多词表达式/术语识别」运行时还需要
`raw/stardict.db`（约 811MB）。全新 clone 后先拉取：

```bash
uv run data/wordlists/download_raw.py
```

脚本幂等（已下载/已解压则跳过），下载后按内置 SHA256 校验；若上游更新导致校验失败，
先人工确认新版本无碍，再更新脚本内对应 `sha256`。

## 重新生成（raw → 产物）

```bash
uv run data/wordlists/download_raw.py        # 1. 拉取 raw（已有则跳过）
uv run data/wordlists/process_ecdict.py      # 2. raw → wordlist.csv
uv run data/wordlists/build_surface_lemma.py # 3. raw → surface_lemma.json
```

`surface_lemma.json` 是 `build_surface_lemma.py` 从 `raw/basewrd*.txt`（派生）+ `raw/lemma.en.txt`
（屈折/不规则）生成，运行时加载产物、不解析 raw。

- **派生**（`basewrd*.txt` 缩进成员）只保留词族头在 `wordlist.csv` 中的条目（约 23611 族）——
  映射到无 rank 的头无法判定已知/生词。
- **屈折**（`lemma.en.txt`）**全部收录**，含词表外 base（rover/orbiter），使词表外单词的
  复数/第三人称等也能还原去重（rovers→rover、orbiters→orbiter），否则每个复数都单独成生词。
- 词族头强制自映射，且 lemma.en 不覆盖 basewrd 的派生映射（environmentalism 仍还原到 environment）。

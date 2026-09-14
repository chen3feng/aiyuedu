# ECDICT SQLite（340 万增强版）——数据源评估与集成

> 目的：评估「简明英汉增强版（欧陆）」340 万词条 SQLite，作为**导入文章时查词**的数据源，
> 覆盖短语与术语的自动提取。决策（短语→全局 mwe、术语→文章级注释）见 `docs/multiword.md`。

## 获取

- 下载：`https://github.com/skywind3000/ECDICT/releases/download/1.0.28/ecdict-sqlite-28.zip`（206.7MB）
- 解压：`stardict.db`（**851MB**），放 `data/wordlists/raw/`（已被 `.gitignore` 排除，**不入库**）
- 授权：增强版由开源 MIT ECDICT 与欧陆/有道等专有词条合并，**仅本地读取、不随项目分发**，
  正式集成前需再确认授权边界（见下「授权」）。

## Schema（与 `raw/ecdict.csv` 一致）

`word / sw / phonetic / definition / translation / pos / collins / oxford / tag / bnc / frq / exchange / detail / audio`

## 规模

| 项 | 数量 |
|---|---|
| 总词条 | 3,402,564 |
| 多词（含空格） | 2,044,859（60.1%） |
| 单词语条 | 1,357,705（39.9%） |
| 多词中有中文释义 | 2,039,308 |

多词按词数：2 词 128 万、3 词 51 万、4 词 17 万、5 词 5.5 万……

## 多词条质量（关键限制）

**结构化字段几乎全空**：

- `pos`（词性）：多词条 **0 条有值**
- `bnc` / `frq`（词频）：多词条 **全为 0**
- `phonetic`（音标）：仅 6.5 万条（3.2%）
- `collins > 0`：仅 777 条

**域标签高度集中在「术语 + 地名」，不是通用学习短语**：

```
[网络]27.3万  [医]9.0万  [计]5.9万  [地名]5.5万  [化]5.4万
[经]3.4万  [法]2.4万  [电]2.1万  [机]2.0万  [数]0.7万  [建]0.6万 ...
```

## 具体词查询

| 词/短语 | 是否有 | 释义 |
|---|---|---|
| `rover` | ✅ | n. 漂泊者, 流浪者, 海盗（**无「火星车」义**） |
| `Age of Discovery` | ❌ | — |
| `conservation of momentum` | ✅ | [化] 动量守恒（标签应是 [物]，小瑕疵） |
| `throw up` | ✅ | 呕吐, 猛地举起, 放弃… |
| `take over` | ✅ | 接收, 接管 |
| `break a leg` | ✅ | 祝好运；大获成功 |
| `terracotta warriors` | ✅ | n. 兵马俑 |
| `greenhouse effect` | ✅ | n. 温室效应（collins=1） |

## 结论

1. **可作「导入时查词」的数据源，覆盖面好**：通用短语（throw up / take over / break a leg）、
   术语（conservation of momentum / greenhouse effect / 兵马俑）都在，且带中文释义。
2. **给不了短语频率**：多词条 `bnc/frq` 全 0、无 `pos`。短语进 mwe.json 后**没有 rank**，
   只能「命中即短语 + 释义」；频率排序仍需另补 PHaVE/PHRASE（见 `multiword.md` P2c）。
3. **提取要按域标签过滤噪声**：[地名]5.5 万是专名、[网络]27 万是俚语/口语，不宜进短语或术语库。
4. **词库缺失不因换大词典解决**：`rover`「火星车」义、`Age of Discovery` 340 万版也补不上，
   必须保留「导入时人工补 gloss / 全局术语覆盖表」的口子（`multiword.md` 已留）。

## 短语 vs 术语判别

多词条无 `pos`，但**首词的单词条有 pos**。用「首词是否为动词」判别：

| 短语 | 首词 pos | 判别 |
|---|---|---|
| throw up | throw `v:94` | 短语 ✓ |
| take over | take `v:99` | 短语 ✓ |
| break a leg | break `v:66` | 短语 ✓ |
| greenhouse effect | greenhouse `n:100` | 术语 ✓ |
| conservation of momentum | conservation `n:100` | 术语 ✓ |
| terracotta warriors | terracotta（空） | 术语（默认） ✓ |

即：首词 pos 含 `v`（动词）→ 短语（→ 排重入全局 `mwe.json`）；否则 → 术语（→ 文章级注释）。
空 pos / 边缘词默认术语。自动化判别只是默认值，后台可手工翻转为短语↔术语。

## 授权（待确认）

增强版合并了欧陆/有道等专有词条，MIT 不必然覆盖全部。**本项目只在其本地、导入时读，
不随项目分发该 db**，风险可控；若后续要对外发布生成物，需先核清 340 万条的来源构成。
原始 `raw/ecdict.csv`（77 万，MIT）无此顾虑，纯短语提取可继续用它兜底。

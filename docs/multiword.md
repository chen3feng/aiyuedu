# 多词表达式（短语 / 成语 / 术语）设计

词汇量评测与生词判定都建立在 Nation BNC/COCA **词族（word family）** 之上，只能覆盖单词。
但很多含义无法从核心词看出——短语（throw up / take over）、成语（break a leg / Achilles' heel）、
术语（兵马俑 / UNICEF / 动量守恒）。本文固化这些内容在阅读系统中的处理方式与数据模型。

## 决策

| 类型 | 处理 | 需词频？ | 需单独测试/复习？ |
|---|---|---|---|
| **短语/成语**（动词短语等） | 全局词典 + 阅读标注 + 未来 FSRS 卡片 | 要（后续并入） | 要（P2c） |
| **术语**（专名/文化/领域/固定搭配） | 仅阅读语境注释，帮助理解全文 | 否 | 否 |

理由：短语搭配不同介词容易混，值得单独测试/复习；术语本身独特、频率低，阅读时
给个注释能懂就行，真常用的见多了自然记住。因此**术语层退化成「多词 span 的语境注释」**，
不需要全局库、不需要词频、不进入复习系统；只有短语层需要完整词典 + 匹配 + 复习。

## 数据模型

`data/mwe/mwe.json`（全局短语词典，`data/mwe/build_mwe.py` 生成）：

```json
{
  "items": [
    { "text": "throw up",   "gloss": "呕吐，放弃，举起…", "type": "phrasal_verb", "separable": false },
    { "text": "take apart", "gloss": "拆开",              "type": "phrasal_verb", "separable": true }
  ]
}
```

- 连续短语：`text` 即匹配词面；`separable: false`。
- 可分离短语（宾语夹中间，take it apart）：`separable: true`，`text` 为两词
  `verb particle`，匹配时在 `verb` 与 `particle` 之间允许 ≤ `SEPARABLE_MAX_GAP`（4）个词。

## 匹配算法（`services/mwe.py`）

1. 加载 `mwe.json` 建两套结构：连续短语 **trie**；可分离短语 `verb -> [(particle, entry)]`。
2. `match_spans(words)` 对单词序列从左到右贪心：
   - 先试**连续最长匹配**（"take over" 优先于 "take"）；
   - 无则试**可分离**（verb 在起点，向后找最近的 particle，间隔 ≤ 4）。
3. 返回互不重叠的 `(start, end, entry)`（end 开区间）。

## 与阅读标注的集成（`services/reading.py`）

`_units(sentence, level)` 把一句切成「单元」，**多词匹配先于单词分类**：

- 命中的短语整段合成一个单元，`w` 取原文表面（含内部空格），`lemma` 取短语 canonical
  文本，只注一次 `<ruby>整段<rt>释义</rt></ruby>`；
- 短语内部的单词不再逐个 `_classify`（避免 throw / up 各注无关义）；
- 短语一律按「生词」对待（暂无词频，见下文 P2c）。

`_count`（生词率统计）与 `annotate` 共用 `_units`，口径一致：**短语按 1 个词汇单元计**，
既进分母也进生词数。术语不走此全局词典，无影响。

## 种子来源

- **维基教科书两页**（主力，自带中文释义、贴合国内课纲）：
  - `英语/高中英语动词短语汇编`（~700 条）
  - `英语/英语介词短语动词短语汇编`（~110 条）
- **手工补充** ~30 条维基缺失的高频动词短语（find out / point out / take apart / trade in…）。
- 合计 ~735 条（可分离 30，连续 705）。`build_mwe.py` 负责抓取、清洗（词性标签、`~~` 占位、
  `sb./sth/one's` 歧义模式跳过）、去重、写盘。

**频度标定**（后续）：并入 [PHaVE List](https://www.norbertschmitt.co.uk/vocabulary-resources)（150
动词短语 + 义项频率）与 [PHRASE List](https://academic.oup.com/applij/article-abstract/33/3/299/220807)
（505 非透明多词，BNC 频），给短语排难度/频率，从而让 `rank <= level` 的短语判「已知」。

## 待办（本次未做）

- **P2b 术语层**：后台 analyze 用 LLM 抽多词专名/文化词/领域术语 → 文章级多词注释（复用
  `glosses` 机制的 span 版），不进全局词典/词频/FSRS。
- **P2b 短语手工改**：后台对短语 gloss 做语境化覆盖（行内短义 vs 完整义）。
- **P2c FSRS**：短语/成语作为独立卡片类型进生词本与复习队列；并给短语加词频，
  让高频短语按 level 判「已知」而非一律「生词」。
- **成语库**：PHaVE/PHRASE 覆盖不了的习语（break a leg / Achilles' heel）单独补一份清单。

## 验证

`uv run --directory apps/api pytest -q`：`test_mwe.py`（连续/可分离/间隔上限/最长匹配）
+ `test_reading.py` 新增短语标注与统计口径断言，全量通过。

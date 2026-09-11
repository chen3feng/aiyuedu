# 分级阅读算法

> 实现：[`apps/api/app/services/reading.py`](../apps/api/app/services/reading.py)
> 路由：[`apps/api/app/routers/reading.py`](../apps/api/app/routers/reading.py)
> 测试：[`apps/api/tests/test_reading.py`](../apps/api/tests/test_reading.py)
> 素材：[`data/readings/readings.json`](../data/readings/readings.json)
> 词形还原产物：[`data/wordlists/surface_lemma.json`](../data/wordlists/surface_lemma.json)

## 一句话

按 Krashen「i+1」原则给孩子推送文章：给定读者词汇量 `level`，某词族 `rank ≤ level` 判「已知」，`rank > level` 或不在词表判「生词」，逐行给出仅含生词的中文注释。生词率 = 生词 token 数 / 词 token 总数（数字与标点不计入）。

## 口径

与词汇量评测**完全一致**，都用 Nation BNC/COCA 词族 `rank`（1–25000）作标度（见 [vocab-assessment.md](vocab-assessment.md)）。区别只在一个是「测词汇量」，一个是「用词汇量挑文章」。

- 读者词汇量 `level` 默认 `3600`（design §2.1 初一男生估算），可用 `?level=` 覆盖；未来评测结果存入本地后，前端自动以 `vocab_size` 作为 `level`。
- 生词率目标 **2%–8%**：低于 2% 太简单（无学习量），高于 8% 太吃力（偏离 i+1）。

## 词形还原（surface → 词族头）

阅读中出现的都是词的屈折/派生变形，必须还原到词族头才能查 `rank`。产物 `surface_lemma.json`（约 7.5 万条，提交入库）由 [`data/wordlists/build_surface_lemma.py`](../data/wordlists/build_surface_lemma.py) 从两处 raw 数据生成：

- `raw/lemma.en.txt`：屈折 + 不规则（went→go、children→child、can't→can）。
- `raw/basewrd1..25.txt`：派生（beautiful→beauty、environmentalism→environment）。

只保留「词族头在 `wordlist.csv` 中」的条目，运行时仅加载产物、不解析 raw。

## 生词判定规则（P1 二值近似）

对每个词 token 依次判定，优先级从高到低：

| 优先级 | 规则 | 结果 |
| --- | --- | --- |
| 1 | 数字（含小数，如 `9.58`） | 已知，不计入统计 |
| 2 | 功能词停用表（a/an/the/代词/助动词/介词/连词） | 已知（修复词表生成时被过滤的虚词） |
| 3 | 词族头在词表，`rank ≤ level` | 已知 |
| 4 | 词族头在词表，`rank > level` | **生词**，附 `lemma/rank/gloss/full_gloss/phonetic` |
| 5 | 大写且不在词表 | 专有名词（人名/地名），已知、不注释义 |
| 6 | 小写且不在词表 | 生词，无释义（空 `gloss`） |

补充表 `_EXTRA_COMMON` 兜底「词表生成时被过滤、但阅读高频」的词（run/ran/runs/running/past）。Nation 把 better/best/good 当作**独立词族**，故不强行归并。

这是设计 §7.1「已知词概率模型」的 P1 二值简化；概率模型 + 动态更新（据阅读记录离线分析）留到后续。

## 逐行对照与生词标注

后端按句切分（句末标点 + 空白），每句返回两种产物：`lines[].html`（行内 `<ruby>` 标注）与 `lines[].words`（词级 token，标点含空格作为独立 token 保留原排版）。另有去重后的 `vocabulary` 生词表。

- **行内 ruby（只标本文最贴切义）**：每个生词包成 `<ruby>word<rt>语境义</rt></ruby>`，只标**本文最贴切的那一个意思**。语境义来自素材 `readings.json` 里逐篇手标的 `glosses`（词族头 → 语境义），如 r005 的 `propeller`（词族头 `propel`）标「螺旋桨」而非词典的「推进」。
- **文末生词表（完整意思）**：`vocabulary` 按首次出现顺序列出所有生词，每项含 `word`（词面）、`lemma`（词族头）、`phonetic`（音标）、`gloss`（语境义）、`full_gloss`（**完整义**）。
- **`full_gloss` vs `gloss`**：`vocab.gloss()` 只取前 2 组 × 前 3 义项、限 32 字（用于行内/选项）；`full_gloss()` 保留全部义项与词性、仅剥领域标签 `[医][计]`。派生词「词面义 ≠ 词族头义」时（propeller→propel、sprinter→sprint），用素材里逐篇可选的 `full_glosses` 覆盖完整义。
- **全文 TTS**：前端 `speakLong()` 按句切分逐句入队（规避浏览器单条 utterance 过长被截断），支持开始/停止；词级发音复用 `speak()`。

前端默认「生词标注」模式（H5 用 `v-html` 渲染 ruby；小程序需换 `rich-text`），可切「原文」模式（逐词可点弹窗：音标/完整义/发音/加入生词本）。文末生词表每项可点开弹窗或直接发音。生词本写 `uni.setStorageSync("notebook")`。

## API 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/readings?level=&topic=` | 列表 `[{id,title,topic,topic_label,target_level,word_count,new_word_rate}]`；`topic` 可选过滤 |
| GET | `/readings/{id}?level=` | 详情：`{id,title,topic,topic_label,target_level,body,word_count,new_word_count,new_word_rate,lines:[{words:[…],html}],vocabulary:[{word,lemma,phonetic,gloss,full_gloss}]}` |
| POST | `/readings/{id}/record` | 上报 `{level,completed_ratio,seconds,new_word_clicks}`，落 JSONL（供离线分析，失败不影响接口） |

主题映射（design §11.2 四大兴趣）：science→科普/科技、sports→体育/游戏/汽车、history→历史/名人、adventure→冒险/科幻/悬疑。

## 参数一览

| 参数 | 值 | 含义 |
| --- | --- | --- |
| `DEFAULT_LEVEL` | 3600 | 默认读者词汇量（词族） |
| 生词率目标 | 2%–8% | i+1 舒适区 |
| 素材篇数 | 8 | 手写种子（四大主题 × 2） |

## 素材校准

8 篇手写短文在 `level=3600` 下的实测生词率（目标 2%–8%）：

| 篇 | 主题 | 生词率 |
| --- | --- | --- |
| r001 Why Is the Sky Blue? | science | 2.8% |
| r002 A Visit to the Moon | science | 2.2% |
| r003 The First Football Match | sports | 1.7% |
| r004 The Fastest Man on Earth | sports | 1.7% |
| r005 The Wright Brothers and the First Flight | history | 2.7% |
| r006 How Paper Was Invented | history | 2.1% |
| r007 The Secret of the Old Map | adventure | 2.8% |
| r008 Robot in the Attic | adventure | 5.8% |

r003/r004 是「入门档」略低于 2%，r008 是「挑战档」，整体从易到难。素材为种子内容，后续可据 `reading_records.jsonl` 的点击数据重新校准难度与增补篇目；内容遵守「少儿 + 非政治敏感」约束。

## 测试

```bash
uv run --directory apps/api pytest -q
```

**回归锚点**：`test_head_of` 锚定词形还原（jumped→jump、went→go、beautiful→beauty、better→better）；`test_capitalized_name_treated_as_proper_noun` 锚定「句首/句中大写专名不占生词」；`test_stats_counts_words_excluding_numbers_and_punct` 锚定「数字与标点不计入生词率分母」；`test_annotate_vocabulary_has_complete_meaning` 锚定「ruby 语境义 + 文末生词表完整义」。

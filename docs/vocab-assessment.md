# 词汇量评测：三种算法

> 实现：[`vocab.py`](../apps/api/app/services/vocab.py)（classic）、
> [`vocab_adaptive.py`](../apps/api/app/services/vocab_adaptive.py)（adaptive）、
> [`vocab_cat.py`](../apps/api/app/services/vocab_cat.py)（cat）
> 测试：[`test_vocab.py`](../apps/api/tests/test_vocab.py)、
> [`test_vocab_adaptive.py`](../apps/api/tests/test_vocab_adaptive.py)、
> [`test_vocab_cat.py`](../apps/api/tests/test_vocab_cat.py)
> 诊断：[`diagnose_vocab_bands.py`](../apps/api/scripts/diagnose_vocab_bands.py)
> 欧路原版逆向与推导细节：[eudic-vocab-algorithm.md](eudic-vocab-algorithm.md)

## 1. 三种算法一览

| | **classic 经典分层** | **adaptive 自适应** | **cat 词频 CAT** |
| --- | --- | --- | --- |
| `algo` | `classic` | `adaptive` | `cat` |
| 题量 | 固定 50 | 20 题起结果可用，最多 80 | 同 adaptive |
| 选题 | 10 段各 5 题，由易到难 | 当前档位 ±1；连对 4 题探顶 | 精确 rank ±80 内按 Fisher 信息量 |
| 估分 | 段认识率 × 段宽累加 | 网格贝叶斯 EAP 后验均值 | 同 adaptive，难度用精确 rank |
| 区间 | 无 | 95% 估计区间 | 同 adaptive |
| 单题影响 | 有界（≤ 段宽 / 该段题数） | 似然更新，随题量收敛 | 同 adaptive |
| 顺序无关 | 是（按段统计） | 是（似然乘积） | 是 |
| 定位 | 基线 / 对照 | 默认 | 实验，等题库标定 |

**怎么选**：

1. 前端「词汇量评测」介绍页的「算法」开关，选择记在 `localStorage`，开始测试时下发；
2. 接口参数 `POST /vocab/test/start` body `{"algo": "cat"}`；
3. 服务端默认值环境变量 `VOCAB_ALGO`（默认 `classic`），对未显式下发的客户端生效。

未知 `algo` 返回 400（旧值 `eudic` 会自动归一化为 `adaptive`）。三套算法的会话各自维护，
`/test/answer` 与 `/test/finish` 按 `session_id` 自动分发。

**历史**：classic 是最初实现，2026-09 为稳定性选定；2026-11 加入 adaptive（把
Elo 增量更新换成 EAP）和 cat。classic 保留作基线，但它的「面积口径」与另外两套
的「阈值口径」不是同一个量，见 §6。

## 2. 公共基础

### 2.1 词表

Paul Nation BNC/COCA 25,000 词族（rank 1–25000），过滤后 **23,499** 个可作题目的词
（去掉无释义、非纯字母、敏感词黑名单，并按 lemma 去重）。

- classic：按 rank 切成 10 段；
- adaptive：每 1,000 词一档，共 25 档（0–24）；
- cat：直接用精确 rank 作为难度先验。

### 2.2 题型

三种算法题面一致（classic 于 2026-11 对齐）：

- 每题 **3 个中文释义 +「以上都不对」**，共 4 个选项；「以上都不对」固定为第 4 项（D）；
- 正确释义按 `CORRECT_PRESENT_RATE = 0.75` 的概率出现在前 3 个选项中，否则正确答案
  就是「以上都不对」；
- 另有独立的「不认识」按钮（前端第 5 个操作），不等同于选错；
- 干扰项：classic 从相邻频段 `[rank/2, rank×1.5]` 抽；adaptive/cat 优先同档、同词性，
  并避免释义互相包含。

答后反馈统一为：

```json
{"response": "correct|wrong|unknown", "word": "...",
 "correct_gloss": "选项文字（可能是「以上都不对」）", "word_gloss": "词的真实含义"}
```

当正确选项是「以上都不对」时，前端用 `word_gloss` 展示词义（用
`word_gloss !== correct_gloss` 判断，不硬编码中文）。

### 2.3 记录

历史（`data/vocab_tests/vocab_tests.json`）每条：

```json
{"ts": 1794545430, "algo": "classic", "score": 16500, "vocab_size": 16500,
 "total": 50, "correct": 37, "wrong": 3, "unknown": 10}
```

逐题日志（`data/logs/vocab_sessions.jsonl`，每答一题一行，已 gitignore）公共字段：

```text
ts, session, algo, n, rank, word, response
```

各算法追加：classic `band / n_samples / estimate`；adaptive `level / score`；
cat 再加 `b / a / se`（供后续题库标定）。

## 3. classic：固定分层抽样

### 3.1 抽样

```text
BANDS = (0, 2000, 4000, 6000, 8000, 10000, 12000, 15000, 18000, 21000, 25000)
```

10 段，宽度 2000×6 + 3000×3 + 4000×1 = 25,000。半开区间，末段含 25,000。

下一题始终取自「词频最低、且未抽满 5 题」的段：先把第 0 段抽满，再进第 1 段……
整卷 50 题排成一条由易到难的单坡道。段内随机，并避开最近出现过的词。

> 出题顺序不影响最终成绩：估值只按「每段认识率」计算，各段固定 5 个样本。
> 代价是实时分在坡道早期偏低，随测试爬升；高词汇用户接近尾声才追平。

### 3.2 估值

```text
词汇量 = Σ (段宽 × 该段认识率)
```

「认识率」不是简单的 `答对数 / 作答数`，而是经过三步修正：

1. **单调非增平滑（PAV）**：真实认识率应随词频升高而下降；低段低、高段反而高的
   「尖峰」违反规律，按样本数加权合并成单调曲线。
2. **显著性（Wilson 下界）**：每段只有 5 题，表面认识率噪声很大。对原始 `k/n`
   计算二项比例的 **95% Wilson 下界**，若 `≤ GUESS_RATE`（0.12），说明该段没有
   高于蒙对的知识信号，计 0。例：2/5 = 40%，下界 0.118 ≤ 0.12 → 计 0。
3. **猜测校正**：保留下来的段按 `(r - 0.12) / 0.88` 扣掉蒙对贡献（`r` 为 PAV 平滑后的
   认识率），再乘段宽。

`GUESS_RATE = 0.12` 是「不会时仍蒙对」的有效概率：四选一 25% × 不会时仍会猜的
比例（观测约 45%–50%）。与 adaptive 共用同一套题面，取值一致。

> 2026-11 之前只有「点估计 ≤ 25% 计 0」一道判断，且不扣蒙对：真实一次 50 题里，
> 15k 以上 4/15 与纯猜区分不开，却被按 2/5=40% 计入两个高段，给出 16,500；
> 同一批答案在 EAP 下是 12,973。修正后为 13,977。

### 3.3 显示与结束

- 前 `MIN_SAMPLES = 3` 题不显示分数（返回 `null`）；
- 显示分朝估值逼近，但单次变动不超过 `SCORE_MAX_STEP = 800`，避免「错一个立刻崩」；
- 答满 `MAX_QUESTIONS = 50` 自动结束并写入历史；也可随时 `/test/finish`。

### 3.4 参数

| 参数 | 值 | 含义 |
| --- | --- | --- |
| `BANDS` | 10 段 | 词频分段边界 |
| `MAX_VOCAB` | 25000 | 词族上限 |
| `ROUNDS` / `MAX_QUESTIONS` | 5 / 50 | 每段题数 / 总题量 |
| `MIN_SAMPLES` | 3 | 少于该题数不显示分 |
| `SCORE_MAX_STEP` | 800 | 显示分单次最大变动 |
| `GUESS_RATE` | 0.12 | 有效蒙对率：显著性检验的下界、猜测校正的 `c` |
| `CORRECT_PRESENT_RATE` | 0.75 | 正确释义出现在选项中的概率 |

### 3.5 口径与局限

- 报的是**面积**：「认识多少个词」（25,000 里的占比 × 段宽累加），不是「50% 正确率
  对应的词频位置」。对同一个人，面积通常高于阈值点。
- 每段只有 5 题，段边界附近会在「计入 / 清零」之间跳动；单次波动约 ±1,500–2,000 词。
- 结果页不返回区间（`score_interval` 只有 adaptive/cat 有）。
- 适合看趋势和量级，不适合与另外两套算法逐分比较（见 §6）。

## 4. adaptive：贝叶斯 EAP

选题与估计方式参考 dict.eudic.net 的词汇量测试（逆向分析见
[eudic-vocab-algorithm.md](eudic-vocab-algorithm.md)），但把原版的 Elo 增量更新
换成**网格贝叶斯 EAP**。算法本身不绑定欧路，cat 也复用了同一套估计。

### 4.1 模型

在 0–25,000 分上取 501 个网格点（步长 50）：

```text
p(θ) = sigmoid((θ - (1000 × level + 100)) / 2500)
posterior(θ) ∝ prior(θ) × Π likelihood(θ | 每题结果)
```

似然（3PL + 软惩罚）：

| 作答 | 似然 |
| --- | --- |
| 答对 | `c + (1 - c) · p`，`c = 0.12` |
| 答错 | `(1 - c) · (1 - p)` |
| 不认识 | `(1 - p) ** 0.625` |

先验 `N(1000, 3000)`，截断到 `[0, 25000]`：均值低让前几题从高频词爬升，方差大保证
数据能主导估计。得分取后验均值，`se` 取后验标准差。

**顺序无关**：后验是各题似然的乘积，给定题目与结果，交换答题顺序不改变最终得分。

### 4.2 选题

- 第一题：档位 1–2（高频词热身）；
- 常规：当前档位 `round(score / 1000)` 偏移 −1 / 0 / +1，权重 0.25 / 0.60 / 0.15；
- 探顶：连续答对 4 题后跳到当前档位上方 3–4 档，最多连续 6 题；答对继续每答一题
  抬升 1–2 档，答错或「不认识」立即结束；最多 3 次探顶，两次之间至少间隔 8 题；
- 最近 20 个词不重复（内部保留 40 条历史用于轮换）。

### 4.3 题量与区间

- `MIN_QUESTIONS = 20`：结果接口返回 `ready = true`（前端当前不强制，随时可结束）；- 50 题后 `converged = true`，提示可结束或继续；
- `MAX_QUESTIONS = 80`，答满自动结束；
- 95% 区间：

```text
half = 1.96 × sqrt(se² + FORM_SD²)      FORM_SD = 1200
score_interval = [score - half, score + half]
```

`FORM_SD` 补上「换一套题」的抽样方差：后验只回答「给这些题时能力在哪」，实测
重测波动（约 1,000–1,300）大于后验标准误（约 700–900）。

### 4.4 参数

| 参数 | 值 |
| --- | --- |
| `LEVEL_WIDTH` / `LEVEL_OFFSET` | 1000 / 100 |
| `SCALE` | 2500 |
| `GUESS_RATE` | 0.12 |
| `UNKNOWN_LIKELIHOOD_POWER` | 0.625 |
| `PRIOR_MEAN` / `PRIOR_SD` | 1000 / 3000 |
| `GRID_STEP` / 点数 | 50 / 501 |
| `FORM_SD` | 1200 |
| `MIN_QUESTIONS` / `MAX_QUESTIONS` | 20 / 80 |
| `PROBE_QUESTIONS` / `MAX_PROBES` / `PROBE_COOLDOWN` | 6 / 3 / 8 |

## 5. cat：词频题库 CAT

与 adaptive 共用题型和 EAP 估计，只替换选题与难度参数。

### 5.1 题库

- 每个词：`b = 词频 rank`（精确难度），`a = 1/2500`（统一区分度）；
- 可选覆盖文件 `data/calibration/vocab_cat_items.json`：

```json
{"version": 1, "items": {"abandon": {"b": 5230, "a": 0.00052}}}
```

`b` 是分数尺度上的难度（0–25,000），`a` 是分数尺度上的区分度（2PL 标定后按
`a_logit / 2500` 换算）。文件缺失或格式错误时退化为词频先验。

### 5.2 选题

- 当前能力 θ（首题 1,500）；在 rank 落在 `θ ± 80` 的窗口内取候选；
- 按 3PL Fisher 信息量排序，取信息量最高的 12 题，按信息量加权随机（增加曝光多样性）；
- 最近 40 题不重复；
- 信息量：

```text
p = sigmoid(a(θ - b)),  P = c + (1 - c)p
I(θ) = [a(1 - c)p(1 - p)]² / [P(1 - P)]
```

### 5.3 标定现状

日志里的历史 session 绝大多数是脚本模拟（同一天上千个、准确率为 5 的倍数、
时间戳成组重复），无法做逐词标定。cat 目前用词频先验；等真实作答积累到每词
≥30–50 次后，再拟合 1PL/2PL 并写入覆盖文件。完整流程见 issue #40。

### 5.4 参数

| 参数 | 值 |
| --- | --- |
| `MIN_QUESTIONS` / `MAX_QUESTIONS` | 20 / 80 |
| `CANDIDATE_WINDOW` | ±80 rank |
| `TOP_K` | 12 |
| `RECENT_LIMIT` | 40 |
| `DEFAULT_START` | 1500 |
| 默认 `a` | 1/2500 |

## 6. 怎么读这个分数

### 6.1 三种算法的「分」不是同一个量

| | classic | adaptive / cat |
| --- | --- | --- |
| 定义 | 认识多少个词（面积） | 正确率 56% 对应的词频位置（阈值） |
| 对同一批答案 | 通常更高 | 更低 |

实测（2026-11-13，同一批 50 题答案）：classic 15,773 / 17,227，EAP 11,451 / 13,114。
2026-11 题面对齐后 classic 已和另外两套同题面，但估计量仍不同，**不要逐分比较**；
历史记录不重算。

### 6.2 不确定度

- 单次 80 题：后验 `se ≈ 700`，`FORM_SD = 1200` → 95% 区间约 **±2,700**；
- 实测 13 次 EAP 系测试（猜测校正上线后）：

  | 指标 | 值 |
  | --- | --- |
  | 中位数 | 11,859 |
  | 均值 | 11,715 |
  | 单次标准差 | 1,770 |
  | 均值标准误 | 约 490 |

  多次取中位数可以把标准误压到 ±800 以内。

### 6.3 与母语者的参照（词族口径）

| 参照 | 词族量 |
| --- | --- |
| 母语儿童 ~6 岁 | 5,000–6,000 |
| 母语儿童 ~11–12 岁 | 10,000–12,000 |
| 大学受教育母语成人 | 17,000–20,000（Goulden / Nation） |
| CEFR C2 常用门槛 | 8,000–9,000（Milton） |

约 11,000–12,000 词族 ≈ 母语 11–12 岁孩子的接受性词汇量，约为受教育成人的
60%–65%；已越过 Nation 所说的 8,000–9,000 词族（小说/报纸约 98% 覆盖）。

> 这是「认得出中文释义」的接受性词汇，不等于能主动使用；产出性词汇通常是它的
> 50%–70%。跨测试（中文释义 vs 英语释义）比较只能看量级。

## 7. API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/vocab/test/start` | body `{"algo"?: "classic"\|"adaptive"\|"cat"}`；返回 `session_id`、`algo`、`rules`、第一题、实时进度 |
| POST | `/vocab/test/answer` | body `{session_id, choice, unknown}`；返回反馈、进度、下一题；答满返回 `finished` + `result` |
| POST | `/vocab/test/finish` | body `{session_id}`；提前结束，幂等 |
| GET | `/vocab/tests` | 当前用户的历史记录（含 `algo`） |

进度字段：`score`（classic 前 3 题为 `null`）、`total`、`correct`、`unknown`、
`wrong`、`converged`；adaptive/cat 另有 `level`、`score_interval`，结果另有 `ready`。

## 8. 测试与诊断

```bash
# 全量测试
uv run --directory apps/api pytest -q

# classic 的稳定性 / 校准模拟（尖峰 & 平滑两种模型）
uv run --directory apps/api python scripts/diagnose_vocab_bands.py

# 四种极端作答的快速自检
uv run --directory apps/api python scripts/smoke_vocab.py
```

**回归锚点**（改算法时必须继续通过）：

- classic：`test_estimate_flattens_spike`（PAV 压尖峰）、
  `test_estimate_zeroes_band_indistinguishable_from_guess`（Wilson 下界）、
  `test_estimate_real_session_guess_corrected`（真实会话 16,500 → 13,977）、
  `test_score_never_jumps_more_than_max_step`（单步 ≤ 800）、
  `test_stability_on_spiky_profile`（相对标准差 < 20%）；
- 公共：`test_question_format_matches_eudic` / `test_question_has_three_glosses_plus_none_of_above`
  （3 释义 +「以上都不对」固定第 4 项）；
- adaptive：`test_posterior_score_is_order_invariant`（顺序无关）、
  `test_interval_has_between_form_floor`（区间下限）、探顶三条规则；
- cat：`test_bank_is_sorted_and_covers_all_levels`、`test_selection_follows_ability`、
  `test_posterior_score_is_order_invariant`、`test_cat_result_records_algo`。

## 9. 数据与标定

- 逐题日志用于离线分析（`data/logs/vocab_sessions.jsonl`），测试通过
  `conftest.py` 重定向到临时目录，不会污染真实日志；
- 历史日志里有大量脚本模拟 session（同一天上千个、准确率为 5 的倍数、时间戳成组
  重复），做标定前必须先清洗；
- 题库标定（1PL/2PL、MFI、SE 停止规则）见 issue #40；cat 已预留覆盖文件接口。

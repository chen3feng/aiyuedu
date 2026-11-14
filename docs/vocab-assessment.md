# 词汇量评测：四种算法

> 实现：[`vocab.py`](../apps/api/app/services/vocab.py)（classic）、
> [`vocab_adaptive.py`](../apps/api/app/services/vocab_adaptive.py)（adaptive）、
> [`vocab_adaptive2.py`](../apps/api/app/services/vocab_adaptive2.py)（adaptive2）、
> [`vocab_cat.py`](../apps/api/app/services/vocab_cat.py)（cat）
> 测试：[`test_vocab.py`](../apps/api/tests/test_vocab.py)、
> [`test_vocab_adaptive.py`](../apps/api/tests/test_vocab_adaptive.py)、
> [`test_vocab_adaptive2.py`](../apps/api/tests/test_vocab_adaptive2.py)、
> [`test_vocab_cat.py`](../apps/api/tests/test_vocab_cat.py)
> 标定与趋势：[`vocab_calibration.py`](../apps/api/app/services/vocab_calibration.py)、
> [`vocab_trend.py`](../apps/api/app/services/vocab_trend.py)
> 诊断：[`diagnose_vocab_bands.py`](../apps/api/scripts/diagnose_vocab_bands.py)
> 欧路原版逆向与推导细节：[eudic-vocab-algorithm.md](eudic-vocab-algorithm.md)

## 1. 四种算法一览

| | **classic 经典分层** | **adaptive 自适应** | **adaptive2 双参数** | **cat 词频 CAT** |
| --- | --- | --- | --- | --- |
| `algo` | `classic` | `adaptive` | `adaptive2` | `cat` |
| 题量 | 固定 50 | 20 题起结果可用，最多 80 | 同 adaptive | 20 题起，SE 达标即停，最多 80 |
| 选题 | 10 段各 5 题，由易到难 | 当前档位 ±1；连对 4 题探顶 | 同 adaptive | 精确 rank ±80 内按 Fisher 信息量 |
| 模型 | 段认识率 | 一维贝叶斯 EAP（θ） | 二维 EAP（θ + α） | 一维 EAP，难度用精确 rank |
| 词汇量 | 段宽 × 认识率累加 | θ（50% 阈值） | 曲线面积 Σ 1000 × P(know) | θ |
| 区间 | 无 | 95% 估计区间 | 分数区间 + 面积区间 | 95% 估计区间 |
| 顺序无关 | 是（按段统计） | 是（似然乘积） | 是 | 是 |
| 定位 | 基线 / 对照 | 默认 | 实验，看曲线斜率 | 实验，等题库标定 |

**怎么选**：

1. 前端「词汇量评测」介绍页的「算法」开关，选择记在 `localStorage`，开始测试时下发；
2. 接口参数 `POST /vocab/test/start` body `{"algo": "cat"}`；
3. 服务端默认值环境变量 `VOCAB_ALGO`（默认 `classic`），对未显式下发的客户端生效。

未知 `algo` 返回 400（旧值 `eudic` 会自动归一化为 `adaptive`）。各算法的会话各自维护，
`/test/answer` 与 `/test/finish` 按 `session_id` 自动分发。

**历史**：classic 是最初实现，2026-09 为稳定性选定；2026-11 加入 adaptive（把
Elo 增量更新换成 EAP）、adaptive2（双参数）和 cat。classic 保留作基线，但它的
「面积口径」与另外三套的「阈值口径」不是同一个量，见 §7。

## 2. 公共基础

### 2.1 词表

Paul Nation BNC/COCA 25,000 词族（rank 1–25000），过滤后 **23,413** 个可作题目的词
（去掉无释义、非纯字母、敏感词黑名单、释义全部泄底的词，并按 lemma 去重）。

- classic：按 rank 切成 10 段；
- adaptive：每 1,000 词一档，共 25 档（0–24）；
- cat：直接用精确 rank 作为难度先验。

### 2.2 题型

四种算法题面一致（classic 于 2026-11 对齐）：

- 每题 **3 个中文释义 +「以上都不对」**，共 4 个选项；「以上都不对」固定为第 4 项（D）；
- 正确释义按 `CORRECT_PRESENT_RATE = 0.75` 的概率出现在前 3 个选项中，否则正确答案
  就是「以上都不对」；
- 另有独立的「不认识」按钮（前端第 5 个操作），不等同于选错；
- 干扰项：classic 从相邻频段 `[rank/2, rank×1.5]` 抽；adaptive/adaptive2/cat 优先同档、同词性，
  并避免释义互相包含。**四种算法都优先同词性干扰项**（2026-11b 起 classic 补齐），
  封掉「三个选项里只有一项词性对得上 → 直接排除」的盲猜通道；
- 词性解析统一走 `vocab.pos_of` / `pos_class`，兼容 `n.<美俚>蹩脚货` 这类词性后无空格的释义
  （旧实现按首个空格切分，约 1,700 词解析失败，会退化回混词性池）。

**释义泄底清洗**（`vocab.gloss`，2026-11b 起）：ECDICT 有一部分释义直接把答案写出来，
按义项粒度剔除、保留同一词的其他干净义项；整词全部泄底时才不作出题候选（约 90 词）：

| 类型 | 例子 | 处理 |
| --- | --- | --- |
| 别名 | `vt.<主英>=customize` | 去掉 `=xxx` 片段 |
| 词形引用 | `n. 丁香；cleave的过去式` | 去掉「…的过去式/三单/复数/变形」义项 |
| 专名 | `n. (Diem)人名；(德)迪姆` | 去掉人名/地名义项，保留音译 |
| 英文原词/括注 | `n. 大草原，热带草原（等于savanna）` | 去掉含英文的括号内容 |
| 非泄底 | `n. T字形…`、`n. 卡拉OK`、`CFC` | 单字母与全大写缩写保留 |

实测：397 条释义被裁剪、86 个词整词剔除；清洗后候选释义里不再出现 `=`、词形引用、
专名或小写英文词。

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
ts, session, algo, algo_version, user_id, n, rank, word, response,
include_correct, elapsed_ms
```

`include_correct` 表示正确释义是否在选项中（`false` 即本题正确选项为「以上都不对」），
`elapsed_ms` 是与上一题的间隔（首题为 `null`），`algo_version` 用于分版回放与标定。

各算法追加：classic `band / n_samples / estimate`；adaptive `level / score / se`；
adaptive2 再加 `alpha`；cat 再加 `b / a`（供后续题库标定）。

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
- 适合看趋势和量级，不适合与另外三套算法逐分比较（见 §7）。

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

## 4.5 adaptive2：双参数（θ + α）

单参数模型假设所有人的「认识概率—词频」曲线斜率相同，只估计一个能力点 θ。
现实中有人断崖式（斜率大），有人平缓地部分认识很多词（斜率小）。adaptive2 把
能力扩展为两个参数：

```text
p(know) = sigmoid(α × (θ - b) / 2500)
```

- **θ**：50% 认识阈值（分数尺度，0–25,000）；
- **α**：个人区分度，相对基准斜率 `1/2500` 的倍数，`1.0` 与单参数模型相同。

### 4.5.1 估计

在 `(θ, α)` 二维网格上做贝叶斯 EAP：θ 沿用 501 个网格点（步长 50），
α 取 `(0.5, 0.65, 0.8, 1.0, 1.25, 1.6, 2.0)` 共 7 档；先验
`θ ~ N(1000, 3000²)`、`log α ~ N(0, 0.35²)`。似然与 adaptive 相同（3PL +
「不认识」软惩罚），只是把 `p` 换成上面的双参数形式。

### 4.5.2 词汇量 = 曲线下面积

```text
词汇量 = Σ_level 1000 × sigmoid(α × (θ - b_level) / 2500)
```

不再只报 50% 阈值点，而是对整条「认识概率—词频」曲线积分。α 小（曲线平缓）
时面积通常大于 θ，α 大（断崖式）时接近或低于 θ。面积区间由二维后验按面积
加权取 2.5% / 97.5% 分位数得到。

> 注意：在无限词表上，对称 logistic 的面积严格等于 θ；这里的差异来自
> 0–25,000 的有限边界与曲线在边界附近的形状。因此 adaptive2 的主要增量是
> **α（曲线斜率）**与面积区间，而不是把面积当成另一个独立的分数。

### 4.5.3 参数

| 参数 | 值 |
| --- | --- |
| `ALPHA_GRID` | 0.5 / 0.65 / 0.8 / 1.0 / 1.25 / 1.6 / 2.0 |
| `ALPHA_PRIOR_LOG_SD` | 0.35 |
| 其余 | 与 adaptive 相同（题量、探顶、猜测率、FORM_SD） |

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

### 5.2 选题与停止

- 当前能力 θ（首题 1,500）；在 rank 落在 `θ ± 80` 的窗口内取候选；
- 按 3PL Fisher 信息量排序，取信息量最高的 12 题，按信息量加权随机（增加曝光多样性）；
- 最近 40 题不重复；
- **SE 停止规则**：答满 `MIN_QUESTIONS = 20` 后，若后验标准误 `se ≤ SE_STOP = 800`
  就自动结束（典型约 55–65 题），不必固定答满 80 题；`stop_reason` 返回
  `se` / `max` / `manual`；
- 信息量：

```text
p = sigmoid(a(θ - b)),  P = c + (1 - c)p
I(θ) = [a(1 - c)p(1 - p)]² / [P(1 - P)]
```

### 5.3 标定现状

日志里的历史 session 绝大多数是脚本模拟（同一天上千个、准确率为 5 的倍数、
时间戳成组重复），无法做逐词标定。cat 目前用词频先验；等真实作答积累到每词
≥30–50 次后，再拟合 1PL/2PL 并写入覆盖文件。

标定流水线已实现（`vocab_calibration.py` + `scripts/calibrate_vocab_items.py`）：

```bash
# 只打印清洗/就绪度报告，不写文件
uv run --directory apps/api python scripts/calibrate_vocab_items.py --dry-run

# 合成数据自检（验证 θ 恢复误差）
uv run --directory apps/api python scripts/calibrate_vocab_items.py --synthetic
```

清洗规则：剔除单日 session 数 > 100 的批量模拟日、答案全同、时长 < 1 秒、
题数 < 20 的 session；只用 `include_correct == true` 的标准题面作答。
就绪门槛为 ≥30 个真实 session、≥600 条作答、≥100 个词各 ≥30 次；不满足时
只报告、不写覆盖文件，避免用模拟数据拟合噪声。当前真实数据（2026-11）只有
27 个 session / 125 条可用作答，远未就绪。

### 5.4 参数

| 参数 | 值 |
| --- | --- |
| `MIN_QUESTIONS` / `MAX_QUESTIONS` | 20 / 80 |
| `SE_STOP` | 800（后验标准误阈值） |
| `CANDIDATE_WINDOW` | ±80 rank |
| `TOP_K` | 12 |
| `RECENT_LIMIT` | 40 |
| `DEFAULT_START` | 1500 |
| 默认 `a` | 1/2500 |

## 6. 多次测试：趋势与历史先验（issue #42）

单次测试的 95% 区间约 ±2,700 词，几百词的真实进步会被噪声淹没。`vocab_trend.py`
提供两件事：

### 6.1 趋势

- 只比较同一算法的记录（`score` 口径）；默认取最近一次测试所用的算法；
- 对 `vocab_size` 与时间做加权线性回归，权重 `1/σ²`，`σ = max(1500, se)`；
- 输出每月变化量、95% 区间、p 值与是否显著（`|斜率| > 1.96 × 标准误`，且至少 3 次测试）；
- 接口 `GET /vocab/trend?algo=...`，前端在历史页趋势图下方显示一句话结论。

### 6.2 历史先验

- 新测试开始时，取最近一次同算法测试的 `score` 作为 θ 先验均值；
- 先验 sd = `min(4500, 1500 + 15 × 间隔天数)`，超过 180 天不用；
- 先验很弱（sd ≥ 1,500），20–80 题的数据仍然主导；`VOCAB_HISTORY_PRIOR=false`
  可关闭，关闭后每次测试完全独立。

### 6.3 局限

- 历史记录跨算法不可比，趋势默认只看同一算法；
- 先验会让多次测试之间产生轻微相关；如果怀疑能力在短期内有突变，可关闭先验。

## 7. 怎么读这个分数

### 7.1 四种算法的「分」不是同一个量

| | classic | adaptive / adaptive2 / cat |
| --- | --- | --- |
| 定义 | 认识多少个词（面积） | 正确率 56% 对应的词频位置（阈值） |
| 对同一批答案 | 通常更高 | 更低 |

实测（2026-11-13，同一批 50 题答案）：classic 15,773 / 17,227，EAP 11,451 / 13,114。
2026-11 题面对齐后 classic 已和另外两套同题面，但估计量仍不同，**不要逐分比较**；
历史记录不重算。

### 7.2 不确定度

- 单次 80 题：后验 `se ≈ 700`，`FORM_SD = 1200` → 95% 区间约 **±2,700**；
- 实测 13 次 EAP 系测试（猜测校正上线后）：

  | 指标 | 值 |
  | --- | --- |
  | 中位数 | 11,859 |
  | 均值 | 11,715 |
  | 单次标准差 | 1,770 |
  | 均值标准误 | 约 490 |

  多次取中位数可以把标准误压到 ±800 以内。

### 7.3 与母语者的参照（词族口径）

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

## 8. API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/vocab/test/start` | body `{"algo"?: "classic"\|"adaptive"\|"adaptive2"\|"cat"}`；返回 `session_id`、`algo`、`rules`、第一题、实时进度 |
| POST | `/vocab/test/answer` | body `{session_id, choice, unknown}`；返回反馈、进度、下一题；答满或 SE 达标返回 `finished` + `result` |
| POST | `/vocab/test/finish` | body `{session_id}`；提前结束，幂等 |
| GET | `/vocab/tests` | 当前用户的历史记录（含 `algo`） |
| GET | `/vocab/trend` | 同一算法的趋势（`?algo=` 可选），返回每月斜率、区间与显著性 |

进度字段：`score`（classic 前 3 题为 `null`）、`total`、`correct`、`unknown`、
`wrong`、`converged`；adaptive/adaptive2/cat 另有 `level`、`score_interval`，
cat 还有 `se`、`stop_reason`，adaptive2 还有 `alpha`、`vocab_size`，结果另有 `ready`。

## 9. 测试与诊断

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
- 反盲猜：`test_gloss_removes_answer_leaks`（按义项清洗泄底片段）、
  `test_candidates_have_no_leaky_gloss`（候选释义无 `=`/词形引用/专名/英文词）、
  `test_pos_parsing`（词性后无空格也能解析）、
  `test_distractors_prefer_same_pos`（干扰项与目标同词性）；
- adaptive：`test_posterior_score_is_order_invariant`（顺序无关）、
  `test_interval_has_between_form_floor`（区间下限）、探顶三条规则；
- adaptive2：`test_recovers_theta_and_alpha`（合成数据恢复 θ/α）、
  `test_flat_curve_has_larger_area_at_low_ability`、`test_vocab_interval_contains_point_estimate`；
- cat：`test_bank_is_sorted_and_covers_all_levels`、`test_selection_follows_ability`、
  `test_se_stop_ends_before_max`（SE 停止）、`test_posterior_score_is_order_invariant`；
- 标定：`test_clean_sessions_drops_bulk_day_bots_and_short`、
  `test_fit_recovers_synthetic_theta`；
- 趋势：`test_trend_detects_upward_change`、`test_trend_flat_noise_not_significant`、
  `test_adaptive_start_uses_history_prior`；
- 回放：`test_load_sessions_filters_and_sorts`（会话聚合与过滤）、
  `test_replay_classic_perfect_is_max`（分层全对 → 25,000）、
  `test_replay_estimators_are_deterministic_and_in_range`；
- 仿真：`test_p_know_is_monotonic_in_theta_and_rank`、
  `test_classic_truth_is_close_to_area_truth`、`test_run_session_returns_bounded_estimate`。

## 10. 数据与标定

- 逐题日志用于离线分析（`data/logs/vocab_sessions.jsonl`），测试通过
  `conftest.py` 重定向到临时目录，不会污染真实日志；
- 历史日志里有大量脚本模拟 session（同一天上千个、准确率为 5 的倍数、时间戳成组
  重复），做标定前必须先清洗；
- 题库标定流水线：`scripts/calibrate_vocab_items.py`（清洗 → 1PL/2PL → 就绪度检查
  → 写 `data/calibration/vocab_cat_items.json`），详见 §5.3；
- 多次测试的趋势与历史先验见 §6，数据来自 `data/vocab_tests/vocab_tests.json`。

### 10.1 离线反事实回放

`scripts/replay_vocab_algorithms.py` 把日志里**同一条作答序列**（rank + response）
分别喂给四种估计器，直接比较估计量本身：

```bash
uv run --directory apps/api python scripts/replay_vocab_algorithms.py
uv run --directory apps/api python scripts/replay_vocab_algorithms.py --include-anonymous --since 2026-11-14
```

- 默认只回放真实用户会话（`user_id` 非空、≥20 题）；模拟/匿名会话要显式加上
  `--include-anonymous`；
- 报告按「源算法」分组给出四种估计的均值，以及同一会话内的两两差异；
- **classic 只适合回放分层抽样的序列**（classic 自己的会话）。把 adaptive/CAT 的
  序列喂给 classic 会低估（它只按已作答的频段累加），这类行不能横比；
- 回放是纯离线计算，不写历史、不写日志。

2026-11-14 的实测（305 个会话，其中 301 个 classic 模拟序列）：在分层序列上
classic / adaptive / adaptive2 / cat 的均值是 11,380 / 10,808 / 11,351 / 11,130，
两两差 29–572，均小于单条序列 ~1,150 的差异标准差；adaptive2 的面积定义与
classic 几乎重合，adaptive 的 θ 系统性低约 550，cat 高约 250。

### 10.2 可控仿真

回放只能看「估计器之间是否一致」，看不到「谁更接近真值」。仿真脚本按已知的
3PL 知识曲线生成作答，因此能直接算偏差与标准差：

```bash
uv run --directory apps/api python scripts/simulate_vocab_algorithms.py
uv run --directory apps/api python scripts/simulate_vocab_algorithms.py --theta 6000,12000,18000 --sessions 100
```

- 作答模型：认识 → 选对；不认识 → 以 `--guess-prop`（默认 0.48）尝试猜，
  猜对率 25%，有效蒙对率约 12%；
- `truth` 按各算法自己的定义：classic 是分段加权，adaptive2 是曲线面积，
  adaptive / cat 是 θ；报告同时给出面积真值，便于看口径差；
- 2026-11-14（每个能力点 30 次）：

| θ | classic | adaptive | adaptive2 | cat |
| --- | --- | --- | --- | --- |
| 6,000 | 4,898（−21.4%） | 5,911（−1.5%） | 6,456（−1.9%） | 6,084（+1.4%） |
| 12,000 | 10,427（−13.3%） | 11,598（−3.4%） | 12,003（−3.2%） | 11,678（−2.7%） |
| 18,000 | 16,670（−6.8%） | 17,197（−4.5%） | 17,388（−4.6%） | 17,234（−4.3%） |

  classic 的片段门槛（Wilson 下界 ≤ 12% 计 0）导致系统性低估；adaptive2 的
  波动最小（SD 600–700），cat 题量最少（56–76 题），adaptive 与 adaptive2 同题量
  但 SD 略高；adaptive / cat 的高能力端偏差主要来自先验向 1,000 收缩。

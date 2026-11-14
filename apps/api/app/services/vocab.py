"""词汇量评测：分层抽样 + 识别率×词频权重（比例累加）。

把 25000 词族按词频分成若干段（band），从每段各抽若干词，每段算「认识率」，
词汇量 = Σ 段宽 × 认识率。这是百词斩 / 欧路等词汇量测试的「识别率 × 词频权重」做法：

  优点：
    - 线性累加，每个词的贡献有界（≤ 段宽 / 该段已答数），分数天生平滑，
      同一轮内不会「突变」，也不会因自适应走位不同导致两次结果分叉；
    - 可无限测下去：段内样本越多，认识率越准，分数持续收敛。
  代价：同样题量下精度略低于「自适应阶梯 + logistic」，但 50 题即可到 ±5~7%。
  猜测：段认识率要显著高于蒙对率才计入，并扣掉蒙对部分（见 `_estimate`）。
"""
import bisect
import csv
import json
import math
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..config import settings
from . import vocab_tests

# —— 分层抽样参数 ——
# 词频分段边界（rank，半开区间 [BANDS[i], BANDS[i+1])；末段含右端点 25000）
BANDS = (0, 2000, 4000, 6000, 8000, 10000, 12000, 15000, 18000, 21000, 25000)
N_BANDS = len(BANDS) - 1                 # 10 段
MAX_VOCAB = 25000                        # 词族上限（Nation BNC/COCA 25000 基础词族）
ROUNDS = 5                               # 每段抽词轮数 → 总题量 = N_BANDS × ROUNDS
MAX_QUESTIONS = N_BANDS * ROUNDS         # 50
MIN_SAMPLES = 3                          # 至少 3 词才下发估值（前端显示「测评中…」）
SCORE_MAX_STEP = 800                     # 显示分单次最大变动，杜绝「突变」
# 不会时仍蒙对的概率：四选一 25% × 「不确定时仍会猜」的比例（观测约 45%–50%）。
# 与自适应算法共用同一套题面，取值保持一致（vocab_adaptive.GUESS_RATE）。
GUESS_RATE = 0.12
# 题面与 adaptive/CAT 对齐：3 个中文释义 +「以上都不对」，正确释义只出现 75% 的次数。
# 旧版永远把正确释义放进选项，可以用排除法/词形猜出来，各算法的分数不可比。
CORRECT_PRESENT_RATE = 0.75
NONE_OF_ABOVE = "以上都不对"
# 日志版本号：算法口径变化时递增，便于按版本回放与标定。
ALGO_VERSION = "2026-11b"

RULES = (
    "每题给出 3 个中文释义，正确意思可能不在其中（此时选「以上都不对」）；"
    "不认识请点「不认识」；"
    "不确定而猜错会被判为不认识。诚实作答，测评更准。"
)
RESULT_MESSAGE = (
    "词汇量按「分层抽样 + 识别率×词频权重」估计：把词频分成 10 段各抽词，"
    "用每段认识率加权累加出等效词汇量；蒙对的题已按猜测率折算回不认识。"
)

_BRACKET = re.compile(r"\[[^\]]*\]")
_FULL_BRACKET = re.compile(r"【[^】]*】")
_WORD_OK = re.compile(r"^[a-z][a-z'\-]+$")

# —— 释义泄底过滤 ——
# ECDICT 里有一部分释义直接把答案写出来：`vt.<主英>=customize`（别名）、
# `crow的过去式`（词形引用）、`n. (Diem)人名`（专名）、`n. haiku (Jap) 俳句`
# （英文原词）。这类选项一眼就能选中或排除，等于送分。按「义项」粒度剔除，
# 同一词的其他干净义项仍保留；整词都被剔除时不再作为题目候选。
_POS_HEAD = re.compile(r"^(?:\s*[a-z]+\s*\.\s*(?:[&/]\s*)?)+", re.I)
_POS_ANY = re.compile(
    r"(?:^|(?<=[；，,;（(／/&\s]))(?:[a-z]+\s*\.\s*(?:[&/]\s*)?)+", re.I
)
_LEAK_FORM = re.compile(
    r"的(?:过去式|过去分词|现在分词|三单形式|第三人称|复数形式|比较级|最高级|变形|简写|缩写)"
)
_LEAK_PROPER = re.compile(r"人名|地名|姓氏")
_LATIN = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_PAREN = re.compile(r"[（(][^（）()]*[）)]")
_SENSE_SPLIT = re.compile(r"[,，]")
# 截断到 32 字时可能留下半个词性标记（"…；vi…"），去掉它避免像英文泄漏。
_TRUNC_POS = re.compile(r"[；;]\s*[a-z]{1,5}…$")
# 粗粒度词性：同词性干扰项能封掉「按词性排除」的盲猜。
_POS_CLASS = {
    "n": "n", "v": "v", "vt": "v", "vi": "v", "aux": "v", "modal": "v",
    "a": "a", "adj": "a", "adv": "adv", "ad": "adv",
}


def pos_of(g: str) -> str:
    """取释义开头的词性标记，归一化为 ``n.`` / ``vt.`` 形式；无词性返回 ""。

    "n.<美俚>蹩脚货" → "n."；"vt.& vi. (使)自动化" → "vt."。
    """
    m = _POS_HEAD.match(g)
    if not m:
        return ""
    first = re.match(r"[a-z]+", m.group(0), re.I)
    return (first.group(0).lower() + ".") if first else ""


def pos_class(g: str) -> str:
    """粗粒度词性（n / v / a / adv，其余保留原标记），用于挑同词性干扰项。"""
    p = pos_of(g).rstrip(".")
    if not p:
        return "other"
    return _POS_CLASS.get(p, p)


def _latin_leak(text: str) -> bool:
    """释义里出现英文原词/别名（先去掉 n./vt./adv. 等词性标记）。

    单字母（T字形、X线、U形物）与全大写缩写（卡拉OK、CFC、DJ）不算泄底。
    """
    text = _POS_ANY.sub(" ", text)
    return any(len(tok) >= 2 and not tok.isupper() for tok in _LATIN.findall(text))


def _leaky(sense: str) -> bool:
    return bool(
        "=" in sense
        or _LEAK_FORM.search(sense)
        or _LEAK_PROPER.search(sense)
        or _latin_leak(sense)
    )


def _clean_group(g: str) -> str:
    """去掉一组释义中的泄底片段，返回其余义项；全被剔除时返回 ""。"""
    pos = pos_of(g)
    head = _POS_HEAD.match(g)
    body = g[len(head.group(0)):] if head else g
    body = body.strip(" ,，;；")
    # 括号里常是「(等于xxx)」「(xxx的过去式)」「(Diem)」等，整段去掉
    body = _PAREN.sub(lambda m: "" if _leaky(m.group(0)) else m.group(0), body)
    body = body.strip(" ,，;；")
    senses = [s.strip() for s in _SENSE_SPLIT.split(body) if s.strip()]
    keep = [s for s in senses if not _leaky(s)]
    if not keep:
        return ""
    return (pos + " " if pos else "") + "，".join(keep[:3])


@lru_cache(maxsize=1)
def _load_rows() -> list:
    with open(settings.wordlist_path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def _load_blacklist() -> frozenset:
    """少儿不宜敏感词黑名单（评测抽题时排除），缺文件/损坏则返回空。"""
    try:
        with open(settings.sensitive_blacklist_path, encoding="utf-8") as f:
            data = json.load(f)
        return frozenset(data.get("lemmas", []))
    except (OSError, json.JSONDecodeError):
        return frozenset()


def gloss(translation: str) -> str:
    """从 ECDICT 释义提取词义：保留词性前缀与多个义项，去掉 [医][计] 等领域标签。

    例："n. 技巧, 技术, 方法；[化] 工艺方法" → "n. 技巧，技术，方法"

    兼容 ECDICT 的「\\n」分行义项与「【物理学】」全角领域标签（reading.full_gloss 同理）。
    """
    if not translation:
        return ""
    groups: list[str] = []
    seen: set[str] = set()
    for line in translation.split("\n"):
        if line.strip().startswith("[网络]"):
            continue
        for g in line.split("；"):
            g = _FULL_BRACKET.sub("", g)
            g = g.strip(" ,，;；\n\t")
            if not g:
                continue
            if "[" in g or "]" in g:
                continue  # 领域义项（如 [医]、[计]）对少儿不友好，跳过
            if g not in seen:
                seen.add(g)
                groups.append(g)
    if not groups:
        for line in translation.split("\n"):
            seg = _FULL_BRACKET.sub("", _BRACKET.sub("", line)).strip(" ,，;；\n\t")
            if seg:
                groups = [seg]
                break

    # 每组最多保留前 3 个义项，最多取 2 组，避免选项过长；
    # 顺带剔除泄底义项（见 _clean_group），一组全泄底就顺延到下一组。
    trimmed: list[str] = []
    for g in groups:
        c = _clean_group(g)
        if c and c not in trimmed:
            trimmed.append(c)
        if len(trimmed) >= 2:
            break
    out = "；".join(trimmed)
    if len(out) > 32:
        out = _TRUNC_POS.sub("…", out[:32].rstrip(" ,，;；") + "…")
    return out


@lru_cache(maxsize=1)
def _candidates() -> list:
    """[(rank, lemma, gloss)] 按词族 rank 升序，仅保留可作题目的词。"""
    blacklist = _load_blacklist()
    rows = []
    for w in _load_rows():
        try:
            rank = int(w.get("rank", "") or w.get("frq", ""))
        except (TypeError, ValueError):
            continue
        if rank <= 0:
            continue
        lemma = w.get("lemma", "")
        if not _WORD_OK.match(lemma):
            continue
        if lemma in blacklist:
            continue
        g = gloss(w.get("translation", ""))
        if not g:
            continue
        rows.append((rank, lemma, g))
    rows.sort(key=lambda x: x[0])
    return rows


@lru_cache(maxsize=1)
def _pos_index() -> dict:
    """释义 → 粗粒度词性，避免出题时对同一批候选反复解析。"""
    return {g: pos_class(g) for _, _, g in _candidates()}


def _band_width(i: int) -> int:
    """第 i 段的词频宽度（用于加权累加）。"""
    return BANDS[i + 1] - BANDS[i]


def _band_of(rank: int) -> int:
    """rank 落在哪一段（半开区间，末段含右端点）。"""
    i = bisect.bisect_right(BANDS, rank) - 1
    return max(0, min(N_BANDS - 1, i))


def _make_question(target) -> dict:
    """把候选词 target=(rank, lemma, gloss) 做成一道四选一题（干扰项取相邻频段）。

    题面与 adaptive/CAT 一致：3 个中文释义 +「以上都不对」；正确释义只有
    `CORRECT_PRESENT_RATE` 的概率出现在选项里，否则正确答案就是「以上都不对」。
    这样各算法测的是同一种能力，分数才有可比性。
    """
    cands = _candidates()
    frqs = [c[0] for c in cands]
    r = target[0]
    lo = max(1, r // 2)
    hi = r + r // 2
    pool = cands[bisect.bisect_left(frqs, lo): bisect.bisect_right(frqs, hi)]
    if not pool:
        pool = cands

    include_correct = random.random() < CORRECT_PRESENT_RATE
    want = 2 if include_correct else 3
    distractors: list[str] = []
    seen = {target[2]}
    # 干扰项优先同词性（否则「只有一项词性对得上」就能直接排除），
    # 同词性不够再退到相邻频段，最后才用全词表兜底。
    index = _pos_index()
    tpos = index.get(target[2], "other")
    pools = [
        [c for c in pool if index.get(c[2], "other") == tpos],
        pool,
        cands,
    ]
    for src in pools:
        if len(distractors) >= want:
            break
        picks = [c for c in src if c[2] not in seen and c[1] != target[1]]
        random.shuffle(picks)
        for c in picks:
            if len(distractors) >= want:
                break
            seen.add(c[2])
            distractors.append(c[2])
    while len(distractors) < want:
        c = random.choice(cands)
        if c[2] not in seen:
            seen.add(c[2])
            distractors.append(c[2])

    if include_correct:
        distractors.append(target[2])
    # 只打乱释义，让「以上都不对」固定为最后一个选项（与 adaptive/CAT 一致）。
    random.shuffle(distractors)
    options = distractors + [NONE_OF_ABOVE]
    correct_gloss = target[2] if include_correct else NONE_OF_ABOVE
    return {
        "word": target[1],
        "rank": target[0],
        "options": options,
        "correct_index": options.index(correct_gloss),
        "correct_gloss": correct_gloss,
        "gloss": target[2],  # 词的真实含义；正确答案是「以上都不对」时用于答后反馈
    }


def _pick_in_band(i: int, avoid: set) -> dict:
    """在第 i 段内随机抽一道四选一题（避开最近出现过的词）。"""
    lo = BANDS[i]
    hi = BANDS[i + 1]
    cands = _candidates()
    frqs = [c[0] for c in cands]
    a = bisect.bisect_left(frqs, lo)
    b = bisect.bisect_right(frqs, hi) if i == N_BANDS - 1 else bisect.bisect_left(frqs, hi)
    seg = cands[a:b]
    if not seg:
        seg = cands  # 空段兜底（理论上不会发生，各段都有词）
    target = random.choice(seg)
    for _ in range(40):
        c = random.choice(seg)
        if c[1] not in avoid:
            target = c
            break
    return _make_question(target)


def _isotonic_noninc(values: list, weights: list) -> list:
    """把各段认识率拟合成「词越难、认识率越低」的非增曲线（PAV，加权最小二乘）。

    压制「尖峰」：低段不认识、却在高段「蒙对」四选一（纯猜 25%，实际有效
    蒙对率约 12%），会被误记成认识，从而把高分段严重抬高（例：把 rank≈24000
    的 cerecloth 蒙对，单题即 +4000×25% = 1000 分）。词越难、认识率应单调下降，
    尖峰违反此规律，属噪声。
    """
    n = len(values)
    blocks = [[i] for i in range(n)]

    def mean(idx: int) -> float:
        s = sum(values[j] * weights[j] for j in blocks[idx])
        t = sum(weights[j] for j in blocks[idx])
        return s / t if t else 0.0

    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(blocks) - 1:
            if mean(i) < mean(i + 1):  # 违反非增（后段反而更高）→ 合并
                blocks[i] += blocks[i + 1]
                del blocks[i + 1]
                changed = True
            else:
                i += 1

    out = [0.0] * n
    for blk in blocks:
        m = (sum(values[j] * weights[j] for j in blk)
             / sum(weights[j] for j in blk))
        for j in blk:
            out[j] = m
    return out


def _wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    """二项比例的 Wilson 置信下界（95%）。

    每段只有 5 个样本，表面认识率噪声很大：2/5（40%）与四选一纯猜区分不开。
    用下界判断「这一段是否显著高于蒙对」，避免把 2 道蒙对当成 40% 认识。
    """
    if n <= 0:
        return 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    margin = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (centre - margin) / denom)


def _estimate(sess: "TestSession") -> float:
    """词汇量 = Σ 段宽 × 认识率（只统计已作答的段）。

    认识率先做单调非增平滑（压制「尖峰」：低段不认识、却蒙对高段生僻词），
    然后做两道猜测处理：

    1. **显著性**：某段认识率的 Wilson 95% 下界 ≤ GUESS_RATE 时，视为该段
       没有高于蒙对的知识信号，计 0（每段只有 5 题，表面的 2/5 说明不了问题）；
    2. **猜测校正**：保留的段按 `(r - c) / (1 - c)` 扣掉蒙对的部分，`c = GUESS_RATE`。

    旧实现只在整段认识率点估计 ≤ 25% 时清零、且不做校正，会把高段偶然蒙对
    的 2-3 题当成认识，单段虚增上千词。
    """
    rates, weights, idxs = [], [], []
    for i in range(N_BANDS):
        n = sess.band_total.get(i, 0)
        if n > 0:
            rates.append(sess.band_known.get(i, 0) / n)
            weights.append(n)
            idxs.append(i)
    if not rates:
        return 0.0

    rates = _isotonic_noninc(rates, weights)
    total = 0.0
    for i, r in zip(idxs, rates):
        n = sess.band_total[i]
        known = sess.band_known.get(i, 0)
        if _wilson_lower(known, n) <= GUESS_RATE:
            continue
        know_rate = max(0.0, (r - GUESS_RATE) / (1.0 - GUESS_RATE))
        total += _band_width(i) * know_rate
    return total


@dataclass
class TestSession:
    id: str
    band_known: dict = field(default_factory=dict)   # 段号 -> 认识数
    band_total: dict = field(default_factory=dict)   # 段号 -> 作答数
    samples: list = field(default_factory=list)      # [(rank, is_known)] 供日志/调试
    recent: list = field(default_factory=list)       # 最近出现的词，避免重复
    current: Optional[dict] = None
    display: Optional[float] = None                  # 平滑显示的分数（带单次变动上限）
    total: int = 0
    correct: int = 0
    unknown: int = 0
    wrong: int = 0
    finished: bool = False
    history: list = field(default_factory=list)      # 每次估值，供调试
    user_id: Optional[str] = None                    # 归属用户；结束时落一条历史
    recorded: bool = False                           # 历史只记一次
    last_ts: float = 0.0                             # 上一题作答时间（算 elapsed_ms）


_sessions: dict[str, TestSession] = {}


def get_session(sid: str) -> Optional[TestSession]:
    return _sessions.get(sid)


def _public(q: dict) -> dict:
    """下发给前端的题目（不含正确答案）。"""
    return {"word": q["word"], "options": q["options"]}


def _progress(sess: TestSession, estimate: Optional[float] = None) -> dict:
    if estimate is None:
        estimate = _estimate(sess)
    # 显示分：朝真实估值逼近，但单次变动不超过 SCORE_MAX_STEP，避免「突变」
    if sess.display is None:
        sess.display = estimate
    else:
        delta = estimate - sess.display
        sess.display += max(-SCORE_MAX_STEP, min(SCORE_MAX_STEP, delta))
    show = sess.total >= MIN_SAMPLES
    score = int(round(sess.display)) if show else None
    return {
        "score": score,
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "converged": sess.finished,
    }


def start_test(user_id: Optional[str] = None) -> tuple[str, dict, dict]:
    sid = uuid.uuid4().hex
    sess = TestSession(id=sid, user_id=user_id)
    _sessions[sid] = sess
    sess.current = _pick_in_band(_next_band(sess), set())
    return sid, _public(sess.current), _progress(sess)


def _next_band(sess: TestSession) -> int:
    """取「词频最低、且未抽满」的段，把 50 题排成从易到难的单坡道。

    先把第 0 段（前 2000 常用词）抽满 `ROUNDS` 词，再进第 1 段……直到末段。
    旧轮询是「10 题一小坡、反复 5 次」，生僻词全程穿插、易受挫；本实现让孩子
    先建立信心、再逐渐探到词汇天花板。最终估值与顺序无关（各段仍是 5 样本）。
    """
    for i in range(N_BANDS):
        if sess.band_total.get(i, 0) < ROUNDS:
            return i
    return N_BANDS - 1  # 理论不可达（答满 MAX_QUESTIONS 即结束）


def _log_answer(sess: TestSession, q: dict, response: str, estimate: float) -> None:
    """追加一条评测记录（JSONL），供离线分析。日志失败不影响评测。"""
    try:
        path = Path(settings.vocab_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        elapsed_ms = (
            int(round((now - sess.last_ts) * 1000)) if sess.last_ts else None
        )
        sess.last_ts = now
        rec = {
            "ts": round(now, 3),
            "session": sess.id,
            "algo": "classic",
            "algo_version": ALGO_VERSION,
            "user_id": sess.user_id or "",
            "n": sess.total,
            "rank": q["rank"],
            "band": _band_of(q["rank"]),
            "word": q["word"],
            "response": response,
            "include_correct": q["correct_index"] != 3,
            "elapsed_ms": elapsed_ms,
            "n_samples": sess.total,
            "estimate": round(estimate, 1) if estimate else None,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _result(sess: TestSession) -> dict:
    vocab = int(round(_estimate(sess) / 10) * 10)
    return {
        "vocab_size": vocab,
        "score": vocab,
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "message": RESULT_MESSAGE,
    }


def submit_answer(sess: TestSession, choice: Optional[int], unknown: bool) -> dict:
    q = sess.current
    sess.total += 1
    rank = q["rank"]

    if unknown:
        sess.unknown += 1
        response = "unknown"
        is_known = False
    elif choice is not None and choice == q["correct_index"]:
        sess.correct += 1
        response = "correct"
        is_known = True
    else:
        sess.wrong += 1
        response = "wrong"
        is_known = False

    b = _band_of(rank)
    sess.band_total[b] = sess.band_total.get(b, 0) + 1
    if is_known:
        sess.band_known[b] = sess.band_known.get(b, 0) + 1
    sess.samples.append((rank, 1.0 if is_known else 0.0))
    sess.recent.append(q["word"])
    if len(sess.recent) > 15:
        sess.recent.pop(0)

    estimate = _estimate(sess)
    sess.history.append(estimate)
    _log_answer(sess, q, response, estimate)

    feedback = {
        "response": response,
        "word": q["word"],
        # 正确答案可能是「以上都不对」；前端用 word_gloss 展示词的真实含义。
        "correct_gloss": q["correct_gloss"],
        "word_gloss": q["gloss"],
    }
    progress = _progress(sess, estimate)

    if sess.total >= MAX_QUESTIONS:
        sess.finished = True
        _record(sess)
        return {"finished": True, "feedback": feedback, **progress, "result": _result(sess)}

    sess.current = _pick_in_band(_next_band(sess), set(sess.recent))
    return {"finished": False, "feedback": feedback, **progress, "question": _public(sess.current)}


def _record(sess: TestSession) -> None:
    """把完成的测评写进用户历史（幂等；匿名/未作答不记）。"""
    if sess.recorded or not sess.user_id or sess.total == 0:
        return
    sess.recorded = True
    result = _result(sess)
    vocab_tests.add(sess.user_id, {
        "ts": round(time.time(), 3),
        "algo": "classic",
        "score": result["score"],
        "vocab_size": result["vocab_size"],
        "total": result["total"],
        "correct": result["correct"],
        "wrong": result["wrong"],
        "unknown": result["unknown"],
    })


def finish_test(sess: TestSession) -> dict:
    """用户主动结束测评，返回最终成绩（幂等，可重复调用）。"""
    sess.finished = True
    _record(sess)
    return _result(sess)

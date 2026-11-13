"""词汇测试题库标定（issue #40）。

从逐题日志里清洗真实作答，拟合 1PL / 2PL 题目参数，并给出留出法评估。
只在数据量足够时输出覆盖文件；数据不足时明确报告「未就绪」，绝不用模拟
数据拟合噪声。

日志字段见 ``docs/vocab-assessment.md`` §2.3。标定只使用
``include_correct == true`` 的作答（标准「3 释义 + 以上都不对」题面），
把 ``correct`` 记为 1，``wrong`` / ``unknown`` 记为 0。

参数尺度：内部用 ``θ' = θ / 1000``、``b' = b / 1000``、``a' = a * 1000``，
这样 a' 约 0.4（词频先验 ``a = 1/2500``），梯度量级正常。
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Iterable

# 与 vocab_adaptive / vocab_cat 保持一致
GUESS_RATE = 0.12
SCALE = 2500.0
BASE_A_PRIME = 1000.0 / SCALE       # 0.4
MIN_SESSION_RESPONSES = 20
BULK_DAY_SESSIONS = 100             # 单日 session 数超过此值视为批量模拟
MIN_ITEM_RESPONSES = 30             # 每个词至少这么多次真实作答才标定
MIN_SESSIONS = 30
MIN_CALIBRATED_ITEMS = 100


def _sigmoid(x: float) -> float:
    x = max(-50.0, min(50.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def load_sessions(path: str) -> dict[str, list[dict]]:
    """读取 JSONL，按 session 分组。"""
    sessions: dict[str, list[dict]] = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = rec.get("session")
            if sid:
                sessions[sid].append(rec)
    for rows in sessions.values():
        rows.sort(key=lambda r: r.get("ts", 0))
    return dict(sessions)


def _day(rec: dict) -> str:
    return datetime.fromtimestamp(rec.get("ts", 0)).strftime("%Y-%m-%d")


def clean_sessions(
    sessions: dict[str, list[dict]],
    *,
    min_responses: int = MIN_SESSION_RESPONSES,
    bulk_day_sessions: int = BULK_DAY_SESSIONS,
) -> tuple[dict[str, list[dict]], dict]:
    """按可解释的规则剔除测试 / 模拟 session，返回保留结果与报告。"""
    report = Counter()
    day_counts = Counter(_day(rows[0]) for rows in sessions.values() if rows)
    bulk_days = {d for d, n in day_counts.items() if n > bulk_day_sessions}

    kept: dict[str, list[dict]] = {}
    for sid, rows in sessions.items():
        if not rows:
            report["empty"] += 1
            continue
        if _day(rows[0]) in bulk_days:
            report["bulk_day"] += 1
            continue
        if len(rows) < min_responses:
            report["too_short"] += 1
            continue
        span = rows[-1].get("ts", 0) - rows[0].get("ts", 0)
        if span < 1.0:
            report["bot_burst"] += 1
            continue
        responses = {r.get("response") for r in rows}
        if len(responses) <= 1:
            report["single_response"] += 1
            continue
        kept[sid] = rows
        report["kept"] += 1

    report["bulk_days"] = len(bulk_days)
    return kept, dict(report)


def observations(sessions: dict[str, list[dict]]) -> list[tuple[str, str, int, int]]:
    """(session, word, y, rank)；只用标准题面（正确释义在选项中）。"""
    obs: list[tuple[str, str, int, int]] = []
    for sid, rows in sessions.items():
        for r in rows:
            if not r.get("include_correct"):
                continue
            word = r.get("word")
            rank = r.get("rank")
            if not word or not isinstance(rank, int) or rank <= 0:
                continue
            y = 1 if r.get("response") == "correct" else 0
            obs.append((sid, word, y, rank))
    return obs


def _prob(theta: float, a: float, b: float) -> float:
    p = _sigmoid(a * (theta - b))
    return GUESS_RATE + (1.0 - GUESS_RATE) * p


def _grad_terms(theta: float, a: float, b: float, y: int) -> tuple[float, float, float]:
    """log-likelihood 对 θ, a, b 的梯度。"""
    p = _sigmoid(a * (theta - b))
    prob = GUESS_RATE + (1.0 - GUESS_RATE) * p
    dp = (1.0 - GUESS_RATE) * p * (1.0 - p)
    if y:
        inv = 1.0 / max(prob, 1e-12)
        return dp * a * inv, dp * (theta - b) * inv, -dp * a * inv
    inv = -1.0 / max(1.0 - prob, 1e-12)
    return dp * a * inv, dp * (theta - b) * inv, -dp * a * inv


def fit(
    obs: Iterable[tuple[str, str, int, int]],
    *,
    model: str = "2pl",
    epochs: int = 500,
    lr: float = 0.05,
) -> dict:
    """用 Adam 梯度上升拟合 1PL/2PL，返回 {'theta': {...}, 'items': {...}}。

    参数都工作在千词尺度：theta/b 单位 1000 词，a 为千词尺度的区分度。
    弱先验把 b 锚在词频 rank 上、a 锚在 0.4，避免小样本下漂移。
    """
    if model not in {"1pl", "2pl"}:
        raise ValueError(model)
    obs = list(obs)
    theta: dict[str, float] = defaultdict(lambda: 5.0)
    items: dict[str, dict] = {}
    item_rank: dict[str, int] = {}
    item_n: Counter = Counter()
    for _sid, word, _y, rank in obs:
        item_rank.setdefault(word, rank)
        item_n[word] += 1
        if word not in items:
            items[word] = {"a": BASE_A_PRIME, "b": rank / 1000.0}

    # Adam 状态
    m: dict[tuple, float] = defaultdict(float)
    v: dict[tuple, float] = defaultdict(float)
    step = 0
    beta1, beta2, eps = 0.9, 0.999, 1e-8

    def update(key: tuple, grad: float, value: float) -> float:
        nonlocal step
        m[key] = beta1 * m[key] + (1 - beta1) * grad
        v[key] = beta2 * v[key] + (1 - beta2) * grad * grad
        mhat = m[key] / (1 - beta1 ** step)
        vhat = v[key] / (1 - beta2 ** step)
        return value + lr * mhat / (math.sqrt(vhat) + eps)

    for _ in range(epochs):
        grads_theta: dict[str, float] = defaultdict(float)
        grads_a: dict[str, float] = defaultdict(float)
        grads_b: dict[str, float] = defaultdict(float)
        for sid, word, y, _rank in obs:
            it = items[word]
            gt, ga, gb = _grad_terms(theta[sid], it["a"], it["b"], y)
            grads_theta[sid] += gt
            grads_a[word] += ga
            grads_b[word] += gb

        # 弱先验：θ ~ N(5, 5²)，b ~ N(rank/1000, 1²)，a ~ N(0.4, 0.5²)
        for sid in grads_theta:
            grads_theta[sid] -= (theta[sid] - 5.0) / 25.0
        for word, it in items.items():
            rank_prior = item_rank[word] / 1000.0
            grads_b[word] -= (it["b"] - rank_prior) / 1.0
            grads_a[word] -= (it["a"] - BASE_A_PRIME) / 0.25

        step += 1
        for sid, g in grads_theta.items():
            theta[sid] = max(0.0, min(25.0, update(("t", sid), g, theta[sid])))
        for word, it in items.items():
            b = update(("b", word), grads_b[word], it["b"])
            it["b"] = max(0.0, min(25.0, b))
            if model == "2pl":
                a = update(("a", word), grads_a[word], it["a"])
                it["a"] = max(0.05, min(1.5, a))

    return {
        "theta": {sid: t * 1000.0 for sid, t in theta.items()},
        "items": {
            word: {
                "b": round(it["b"] * 1000.0, 1),
                "a": round(it["a"] / 1000.0, 8),
                "n": item_n[word],
            }
            for word, it in items.items()
        },
    }


def log_likelihood(obs: Iterable[tuple[str, str, int, int]], params: dict) -> float:
    total = 0.0
    for sid, word, y, _rank in obs:
        t = params["theta"].get(sid, 5000.0)
        it = params["items"].get(word)
        if it is None:
            continue
        prob = _prob(t, it["a"], it["b"])
        total += math.log(max(prob if y else 1.0 - prob, 1e-12))
    return total


def readiness(params: dict, sessions: int, obs: int) -> dict:
    calibrated = sum(1 for it in params["items"].values() if it["n"] >= MIN_ITEM_RESPONSES)
    ok = (
        sessions >= MIN_SESSIONS
        and obs >= MIN_SESSIONS * MIN_SESSION_RESPONSES
        and calibrated >= MIN_CALIBRATED_ITEMS
    )
    return {
        "ready": ok,
        "sessions": sessions,
        "observations": obs,
        "calibrated_items": calibrated,
        "required": {
            "sessions": MIN_SESSIONS,
            "observations": MIN_SESSIONS * MIN_SESSION_RESPONSES,
            "calibrated_items": MIN_CALIBRATED_ITEMS,
        },
    }


def calibrate(
    path: str,
    *,
    model: str = "2pl",
    min_item: int = MIN_ITEM_RESPONSES,
    epochs: int = 500,
) -> dict:
    """完整流程：读日志 → 清洗 → 拟合 → 就绪判断。"""
    sessions = load_sessions(path)
    kept, clean_report = clean_sessions(sessions)
    obs = observations(kept)
    params = fit(obs, model=model, epochs=epochs)
    report = readiness(params, len(kept), len(obs))
    report["clean"] = clean_report
    report["model"] = model
    report["params"] = params
    report["items"] = {
        w: it for w, it in params["items"].items() if it["n"] >= min_item
    }
    return report


def write_overrides(report: dict, out_path: str) -> None:
    """只写达到样本量门槛的词；b/a 已是 vocab_cat 需要的分数尺度。"""
    items = {
        w: {"b": it["b"], "a": it["a"]} for w, it in report["items"].items()
    }
    payload = {"version": 1, "source": "vocab_sessions.jsonl", "items": items}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def synthetic_observations(
    *,
    n_sessions: int = 80,
    n_items: int = 120,
    seed: int = 0,
) -> tuple[list[tuple[str, str, int, int]], dict]:
    """生成可复现的合成作答，用于自检拟合是否能恢复参数。"""
    import random

    rng = random.Random(seed)
    items = {}
    for i in range(n_items):
        rank = 200 + i * 180
        items[f"w{i}"] = {"b": float(rank), "a": 0.0004 * rng.choice([0.6, 1.0, 1.6])}
    truth_theta = {}
    obs: list[tuple[str, str, int, int]] = []
    for s in range(n_sessions):
        sid = f"s{s}"
        theta = rng.uniform(1500, 20000)
        truth_theta[sid] = theta
        for word, it in items.items():
            prob = _prob(theta, it["a"], it["b"])
            y = 1 if rng.random() < prob else 0
            obs.append((sid, word, y, int(it["b"])))
    return obs, {"theta": truth_theta, "items": items}

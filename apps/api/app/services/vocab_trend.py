"""多次测试的趋势估计与历史先验（issue #42）。

单次测试的 95% 区间约 ±2,700 词，几百词的真实进步会被噪声淹没。这里做两件事：

1. **趋势**：把同一算法下的历史测试按时间做加权线性回归（权重取测量方差），
   输出每月变化量、95% 区间与显著性。只有同一算法可比，跨算法不混算。
2. **历史成绩**：下一次测试开始时，用最近一次结果换算首题档位（见
   ``vocab_adaptive.start_test``）；不再作为后验先验，避免多次测试链式抬分。
   不确定度随间隔天数增长，超过 180 天不用。

分数口径：趋势用 ``vocab_size``（各算法自己的词汇量口径，按 ``algo_version``
分组，避免口径变化后混算）；起点用 ``score``（θ，50% 认识阈值）。
"""
from __future__ import annotations

import math
import time
from typing import Optional

from . import vocab_tests

# 单次测试的测量标准差下限（与 adaptive 的 FORM_SD 同量级）
BASE_SD = 1500.0
# 先验不确定度随间隔增长：每天增加 15 词，最多到 BASE_SD 的 3 倍
PRIOR_GROWTH_PER_DAY = 15.0
PRIOR_MAX_AGE_DAYS = 180
PRIOR_MAX_SD = BASE_SD * 3
# 只有这两套算法有 θ 分数；classic 是面积口径，不参与趋势/先验。
# adaptive2 在 2026-11f 并入 adaptive，只作为历史记录里的旧名字出现在别名表。
THETA_ALGOS = {"adaptive", "cat"}
_ALGO_ALIASES = {"eudic": "adaptive", "adaptive2": "adaptive"}
Z95 = 1.96


def _canonical_algo(algo: Optional[str]) -> Optional[str]:
    return _ALGO_ALIASES.get(algo or "", algo)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _records(user_id: Optional[str], algo: Optional[str]) -> list[dict]:
    items = vocab_tests.list_tests(user_id)
    if algo:
        algo = _canonical_algo(algo)
        items = [r for r in items if _canonical_algo(r.get("algo")) == algo]
    return [r for r in items if _canonical_algo(r.get("algo")) in THETA_ALGOS]


def _sigma(rec: dict) -> float:
    se = rec.get("se")
    if not isinstance(se, (int, float)) or se <= 0:
        return BASE_SD
    return max(BASE_SD, float(se))


def trend(user_id: Optional[str], algo: Optional[str] = None) -> dict:
    """同一算法的加权线性趋势；默认取最近一次测试所用的算法。"""
    all_records = vocab_tests.list_tests(user_id)
    if not algo:
        algo = next(
            (
                _canonical_algo(r.get("algo"))
                for r in all_records
                if _canonical_algo(r.get("algo")) in THETA_ALGOS
            ),
            None,
        )
    algo = _canonical_algo(algo)
    records = _records(user_id, algo)
    records = [r for r in records if isinstance(r.get("vocab_size"), (int, float))]
    # 口径变化后不跨版本比较：例如 adaptive 在 2026-11f 从 θ 改为曲线面积，
    # 新旧 vocab_size 不是同一个量。新版本至少积累两次测试后只比较新版本。
    versions = [r.get("algo_version") for r in records if r.get("algo_version")]
    if versions:
        latest = max(versions)
        same_version = [r for r in records if r.get("algo_version") == latest]
        if len(same_version) >= 2:
            records = same_version
    if not records:
        return {
            "algo": algo,
            "n": 0,
            "slope_per_month": None,
            "ci": None,
            "significant": False,
            "message": "还没有可比较的测试记录",
            "points": [],
        }

    records.sort(key=lambda r: r.get("ts", 0))
    t0 = records[0].get("ts", 0)
    xs = [(r.get("ts", 0) - t0) / 86400.0 for r in records]
    ys = [float(r["vocab_size"]) for r in records]
    ws = [1.0 / (_sigma(r) ** 2) for r in records]
    n = len(records)
    points = [
        {"ts": r.get("ts"), "vocab_size": int(round(y)), "sigma": round(1 / math.sqrt(w), 0)}
        for r, y, w in zip(records, ys, ws)
    ]

    if n < 2 or max(xs) - min(xs) < 0.5:
        return {
            "algo": algo,
            "n": n,
            "slope_per_month": None,
            "ci": None,
            "significant": False,
            "message": "至少需要两次不同日期的测试才能估计趋势",
            "points": points,
        }

    wsum = sum(ws)
    xbar = sum(w * x for w, x in zip(ws, xs)) / wsum
    ybar = sum(w * y for w, y in zip(ws, ys)) / wsum
    sxx = sum(w * (x - xbar) ** 2 for w, x in zip(ws, xs))
    sxy = sum(w * (x - xbar) * (y - ybar) for w, x, y in zip(ws, xs, ys))
    slope = sxy / sxx if sxx > 0 else 0.0
    se_slope = math.sqrt(1.0 / sxx) if sxx > 0 else float("inf")
    half = Z95 * se_slope
    significant = n >= 3 and math.isfinite(half) and abs(slope) > half
    p_value = (
        2.0 * (1.0 - _normal_cdf(abs(slope) / se_slope))
        if math.isfinite(se_slope) and se_slope > 0
        else 1.0
    )
    slope_month = slope * 30.0
    ci_month = [slope_month - half * 30.0, slope_month + half * 30.0]

    if not significant:
        message = f"近 {n} 次测试的变化不显著（每月 {slope_month:+.0f} 词，95% 区间跨 0）"
    elif slope_month > 0:
        message = f"近 {n} 次测试呈上升趋势：每月约 {slope_month:+.0f} 词（显著）"
    else:
        message = f"近 {n} 次测试呈下降趋势：每月约 {slope_month:+.0f} 词（显著）"

    return {
        "algo": algo,
        "n": n,
        "slope_per_month": round(slope_month, 1),
        "ci": [round(ci_month[0], 1), round(ci_month[1], 1)],
        "p_value": round(p_value, 3),
        "significant": significant,
        "message": message,
        "points": points,
    }


def history_prior(user_id: Optional[str], algo: str) -> Optional[dict]:
    """最近一次同算法测试的 θ 先验；无历史或过旧时返回 None。

    ``adaptive2`` 是 ``adaptive`` 的旧名字，读取历史时按别名合并。
    """
    records = _records(user_id, algo)
    if not records:
        return None
    last = max(records, key=lambda r: r.get("ts", 0))
    score = last.get("score")
    if not isinstance(score, (int, float)):
        return None
    age_days = max(0.0, (time.time() - last.get("ts", 0)) / 86400.0)
    if age_days > PRIOR_MAX_AGE_DAYS:
        return None
    sd = min(PRIOR_MAX_SD, BASE_SD + PRIOR_GROWTH_PER_DAY * age_days)
    return {
        "mean": float(score),
        "sd": sd,
        "age_days": round(age_days, 1),
        "last_ts": last.get("ts"),
    }

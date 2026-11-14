"""四种词汇量估计器的可控仿真（已知真实能力，比较偏差与稳定性）。

与 `replay_vocab_algorithms.py`（回放真实作答）互补：这里由脚本按已知的
3PL 知识曲线生成作答，所以知道「真值」，可以直接算偏差、标准差和题量。

作答模型：
  - 词在不同真实能力 θ 下的认识概率 p = sigmoid((θ - rank) / scale)；
  - 认识 → 选对；不认识 → 以 `--guess-prop` 的概率尝试猜（猜对率 25%），
    否则点「不认识」。有效蒙对率约 0.48 × 0.25 = 0.12，与算法的 GUESS_RATE 一致。

注意四种算法报的「真值」定义不同：
  - classic / adaptive2 / cat 报词汇量（分段加权 / 曲线面积）；
  - adaptive 报 θ（曲线中点），其 vocab_size 也取 θ。
报告里按各自定义给真值（`truth`），并另外列出面积真值供参考。

用法：
    uv run --directory apps/api python scripts/simulate_vocab_algorithms.py
    uv run --directory apps/api python scripts/simulate_vocab_algorithms.py --theta 6000,12000,18000
    uv run --directory apps/api python scripts/simulate_vocab_algorithms.py --sessions 100 --json /tmp/sim.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # 仓库根目录
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import vocab  # noqa: E402
from app.services import vocab_adaptive as adaptive  # noqa: E402
from app.services import vocab_adaptive2 as adaptive2  # noqa: E402
from app.services import vocab_cat as cat  # noqa: E402

ALGOS = ("classic", "adaptive", "adaptive2", "cat")
MODULES = {"classic": vocab, "adaptive": adaptive, "adaptive2": adaptive2, "cat": cat}
MAX_STEPS = 200


def p_know(theta: float, rank: float, scale: float) -> float:
    """给定真实能力 θ，认识 rank 位置词的概率（3PL 的 p 部分）。"""
    return 1.0 / (1.0 + math.exp(-(theta - rank) / scale))


def area_truth(theta: float, scale: float) -> float:
    """词汇量真值（面积口径，与 adaptive2 一致）：25 档 × 1,000 词。"""
    return sum(1000 * p_know(theta, 1000 * lv + 100, scale) for lv in range(25))


def classic_truth(theta: float, scale: float) -> float:
    """classic 的期望目标：每段宽度 × 段内平均认识率（段内均匀抽词）。"""
    total = 0.0
    for i in range(vocab.N_BANDS):
        lo, hi = vocab.BANDS[i], vocab.BANDS[i + 1]
        start = max(1, lo)
        step = max(1, (hi - start) // 50)
        ranks = range(start, hi, step)
        total += (hi - lo) * statistics.mean(p_know(theta, r, scale) for r in ranks)
    return total


def _answer(q: dict, theta: float, scale: float, guess_prop: float, rng: random.Random):
    """按真实能力作答；返回 (choice, unknown)。"""
    if rng.random() < p_know(theta, q["rank"], scale):
        return q["correct_index"], False
    if rng.random() < guess_prop:
        if rng.random() < 0.25:
            return q["correct_index"], False
        return (q["correct_index"] + 1 + rng.randrange(3)) % 4, False
    return None, True


def run_session(
    alg: str, theta: float, scale: float, guess_prop: float, rng: random.Random
) -> tuple[float, int]:
    """跑完一次完整测评，返回 (vocab_size, 题量)。"""
    mod = MODULES[alg]
    sid, _, _ = mod.start_test()
    sess = mod.get_session(sid)
    for _ in range(MAX_STEPS):
        q = sess.current
        choice, unknown = _answer(q, theta, scale, guess_prop, rng)
        resp = mod.submit_answer(sess, choice, unknown)
        if resp["finished"]:
            result = resp["result"]
            return float(result["vocab_size"]), int(result["total"])
    raise RuntimeError(f"{alg} 在 {MAX_STEPS} 题内没有结束")


def simulate(
    theta: float,
    sessions: int,
    algos: tuple[str, ...],
    scale: float,
    guess_prop: float,
    seed: int,
) -> dict:
    out = {
        "theta": theta,
        "area_truth": area_truth(theta, scale),
        "classic_truth": classic_truth(theta, scale),
        "algos": {},
    }
    for alg in algos:
        rng = random.Random(seed)
        ests, qs = [], []
        for _ in range(sessions):
            est, qn = run_session(alg, theta, scale, guess_prop, rng)
            ests.append(est)
            qs.append(qn)
        truth = {
            "classic": out["classic_truth"],
            "adaptive2": out["area_truth"],
            "adaptive": theta,
            "cat": out["area_truth"],
        }[alg]
        mean = statistics.mean(ests)
        out["algos"][alg] = {
            "mean": mean,
            "sd": statistics.pstdev(ests) if len(ests) > 1 else 0.0,
            "questions": statistics.mean(qs),
            "truth": truth,
            "bias": mean - truth,
            "bias_pct": (mean - truth) / truth * 100 if truth else 0.0,
        }
    return out


def print_report(results: list[dict], algos: tuple[str, ...]) -> None:
    print("真值口径：classic=分段加权，adaptive2/cat=曲线面积，adaptive=θ")
    print(f"{'theta':>6} {'alg':<10} {'mean':>7} {'sd':>6} {'q':>5} {'truth':>7} "
          f"{'bias':>7} {'bias%':>6}")
    for r in results:
        for alg in algos:
            s = r["algos"][alg]
            print(
                f"{r['theta']:6.0f} {alg:<10} {s['mean']:7.0f} {s['sd']:6.0f} "
                f"{s['questions']:5.1f} {s['truth']:7.0f} {s['bias']:+7.0f} "
                f"{s['bias_pct']:+6.1f}%"
            )
        print(f"{'':6} {'面积真值':<10} {r['area_truth']:7.0f}")
        print()


def _parse_thetas(value: str) -> list[float]:
    return [float(x) for x in value.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="四种词汇量估计器的可控仿真")
    parser.add_argument("--theta", default="6000,12000,18000",
                        help="真实能力，逗号分隔（默认 6000,12000,18000）")
    parser.add_argument("--sessions", type=int, default=30, help="每个能力点的测试次数")
    parser.add_argument("--algos", default=",".join(ALGOS), help="只跑其中几个算法")
    parser.add_argument("--scale", type=float, default=2500.0, help="知识曲线斜率")
    parser.add_argument("--guess-prop", type=float, default=0.48,
                        help="不会时仍尝试猜的比例（25%% 猜对 → 有效蒙对约 12%%）")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--json", default=None, help="把结果另存为 JSON")
    args = parser.parse_args()

    algos = tuple(a.strip() for a in args.algos.split(",") if a.strip())
    unknown = [a for a in algos if a not in ALGOS]
    if not algos or unknown:
        parser.error(f"--algos 只能取 {ALGOS}，收到 {args.algos}")
    if args.sessions < 1:
        parser.error("--sessions 至少为 1")

    started = time.time()
    results = [
        simulate(t, args.sessions, algos, args.scale, args.guess_prop, args.seed)
        for t in _parse_thetas(args.theta)
    ]
    print_report(results, algos)
    print(f"仿真完成：{len(results)} 个能力点 × {args.sessions} 次，"
          f"耗时 {time.time() - started:.1f}s")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"结果已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

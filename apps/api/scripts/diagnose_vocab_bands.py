"""诊断：分层抽样 + 比例累加 算法的稳定性 / 校准 / 运行轨迹。

驱动真实 vocab.py（start_test / submit_answer / finish_test），在两种模型下测试：
  1. 平滑 sigmoid 模型（用于校准：测得的 V 应能追踪真值）
  2. 尖峰模型（真实小孩：认识部分生僻词 + 漏掉部分常见词 + 25% 猜测），
     检验「同一轮内不突变」与「两次测评不分叉」。

运行：uv run --directory apps/api python scripts/diagnose_vocab_bands.py
"""
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.services import vocab


def p_know(rank, V, k):
    return 1.0 / (1.0 + (rank / V) ** k)


def make_smooth_profile(V, k, seed):
    rng = random.Random(seed)
    return {lemma: rng.random() < p_know(rank, V, k)
            for rank, lemma, _ in vocab._candidates()}


def make_spiky_profile(V, k, sigma, seed):
    """基底 sigmoid + 每词独立 personal 偏置 N(0,sigma)：会认识生僻词、漏常见词。"""
    rng = random.Random(seed)
    prof = {}
    for rank, lemma, _ in vocab._candidates():
        p = p_know(rank, V, k)
        p = max(0.0, min(1.0, p + rng.gauss(0, sigma)))
        prof[lemma] = rng.random() < p
    return prof


def respond(profile, q, guess_rate):
    """known→选对；not known→猜对/点不认识/猜错。"""
    if profile[q["word"]]:
        return q["correct_index"], False
    r = random.random()
    if r < guess_rate:
        return q["correct_index"], False
    if r < guess_rate + (1 - guess_rate) * 0.5:
        return None, True  # 点「不认识」
    return (q["correct_index"] + 1) % 4, False  # 猜错


def run_one(profile, guess_rate, seed):
    random.seed(seed)
    sid, _, _ = vocab.start_test()
    sess = vocab.get_session(sid)
    scores = []
    while not sess.finished:
        q = sess.current
        choice, unknown = respond(profile, q, guess_rate)
        r = vocab.submit_answer(sess, choice, unknown)
        if r.get("score") is not None:
            scores.append(r["score"])
    return scores, vocab.finish_test(sess)["vocab_size"], sess.total


if __name__ == "__main__":
    print("=== A. 校准（平滑模型，真值 V，各 12 轮）===")
    for V in [2000, 3600, 5000, 8000, 12000, 15000, 20000]:
        prof = make_smooth_profile(V, 4, seed=11)
        res = [run_one(prof, 0.0, seed=20000 + s)[1] for s in range(12)]
        mean, std = statistics.mean(res), statistics.stdev(res)
        print(f"  真值 {V:>6} → 测得 {round(mean):>6}  (偏差 {mean-V:+.0f})  "
              f"std={round(std)}  (±{round(100*std/max(1,mean))}%)")

    print("\n=== B. 稳定性（尖峰模型，真值 15000，60 轮）===")
    prof = make_spiky_profile(15000, 3.0, 0.30, seed=42)
    finals = []
    for s in range(60):
        _, final, _ = run_one(prof, 0.25, seed=1000 + s)
        finals.append(final)
    mean, std = statistics.mean(finals), statistics.stdev(finals)
    print(f"  final: mean={round(mean)}  std={round(std)}  (±{round(100*std/mean)}%)  "
          f"range=[{min(finals)}, {max(finals)}]")

    print("\n=== C. 运行中估值轨迹（尖峰模型，真值 15000，3 个 seed，逐词 score）===")
    for s in [0, 1, 2]:
        scores, final, total = run_one(make_spiky_profile(15000, 3.0, 0.30, seed=42),
                                       0.25, seed=5000 + s)
        first = total - len(scores) + 1
        print(f"  seed={s} ({total} 题，第 {first} 词起显示分，逐词分):")
        print("    " + " ".join(f"{v}" for v in scores))
        # 单步最大变动
        deltas = [abs(b - a) for a, b in zip(scores, scores[1:])]
        print(f"    单步最大变动={max(deltas)}，均值={round(statistics.mean(deltas))}，"
              f"最终={scores[-1]}")

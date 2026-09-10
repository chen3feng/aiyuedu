"""快速自检：词汇量评测服务（分层抽样 + 识别率×词频权重）。

跑四种极端作答，看分数是否落在合理区间、50 题自动结束、轨迹是否平滑。

运行：uv run --directory apps/api python scripts/smoke_vocab.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.services import vocab  # noqa: E402


def run(label, picker):
    sid, _, _ = vocab.start_test()
    sess = vocab.get_session(sid)
    n = 0
    scores = []
    while True:
        choice, unknown = picker(sess)
        ans = vocab.submit_answer(sess, choice, unknown)
        n += 1
        if ans.get("score") is not None:
            scores.append(ans["score"])
        if ans.get("finished"):
            r = vocab.finish_test(sess)
            print(
                f"[{label}] 题数={n} 词汇量={r['vocab_size']} "
                f"对={r['correct']} 不认识={r['unknown']} 错={r['wrong']}"
            )
            print(f"   得分轨迹(每5题): {scores[::5]}")
            return scores


if __name__ == "__main__":
    sid, question, _ = vocab.start_test()
    print("例题:", question["word"], "|", question["options"])

    run("全对", lambda s: (s.current["correct_index"], False))
    run("全不认识", lambda s: (None, True))
    run("全选错", lambda s: ((s.current["correct_index"] + 1) % 4, False))
    run("全选A(乱选)", lambda s: (0, False))

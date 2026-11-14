"""四种词汇量估计器的离线反事实回放（标定 #40 的配套分析）。

把日志里同一条作答序列（rank + response）分别喂给 classic / adaptive /
adaptive2 / cat，比较四者的最终估计。这样排除了「不同天、不同状态、不同
选题」的干扰，只剩估计量本身的差异，用来回答：

1. 四种算法的结果是否一致、偏差有多大；
2. adaptive2 的（θ, α）面积是否真的比 adaptive 多提供信息。

用法：
    uv run --directory apps/api python scripts/replay_vocab_algorithms.py
    uv run --directory apps/api python scripts/replay_vocab_algorithms.py --include-anonymous
    uv run --directory apps/api python scripts/replay_vocab_algorithms.py --since 2026-11-14
    uv run --directory apps/api python scripts/replay_vocab_algorithms.py --json /tmp/replay.json

默认只回放真实用户会话（`user_id` 非空）、至少 20 题；模拟/匿名会话需要显式
`--include-anonymous`。回放不写历史、不写日志，也不会修改任何数据文件。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # 仓库根目录
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import vocab  # noqa: E402
from app.services import vocab_adaptive as adaptive  # noqa: E402
from app.services import vocab_adaptive2 as adaptive2  # noqa: E402
from app.services import vocab_cat as cat  # noqa: E402

DEFAULT_LOG = ROOT / "data" / "logs" / "vocab_sessions.jsonl"
ALGOS = ("classic", "adaptive", "adaptive2", "cat")
RESPONSES = {"correct", "unknown", "wrong"}


# ---------- 读取与回放 ----------

def load_sessions(
    log_path: Path,
    min_answers: int = 20,
    include_anonymous: bool = False,
    since: float | None = None,
    max_answers: int = 80,
) -> list[dict]:
    """把 JSONL 按 session 聚合成作答序列 [(rank, response, word)]。"""
    groups: dict[str, dict] = {}
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid, rank, resp = r.get("session"), r.get("rank"), r.get("response")
            if not sid or rank is None or resp not in RESPONSES:
                continue
            if not include_anonymous and not r.get("user_id"):
                continue
            if since is not None and (r.get("ts") or 0) < since:
                continue
            g = groups.setdefault(sid, {"algo": r.get("algo") or "?", "rows": []})
            g["rows"].append((r.get("n") or 0, int(rank), resp, r.get("word") or ""))

    out: list[dict] = []
    for sid, g in groups.items():
        rows = sorted(g["rows"], key=lambda x: x[0])
        seq = [(rank, resp, word) for _, rank, resp, word in rows][:max_answers]
        if len(seq) >= min_answers:
            out.append({"session": sid, "source": g["algo"], "seq": seq})
    out.sort(key=lambda x: (x["source"], x["session"]))
    return out


def replay_classic(seq: list[tuple], max_answers: int = 50) -> float:
    """classic：按词的频段累计认识/作答数，再走 PAV + 猜测校正。"""
    sess = vocab.TestSession(id="replay")
    for rank, resp, _ in seq[:max_answers]:
        band = vocab._band_of(rank)
        sess.total += 1
        sess.band_total[band] = sess.band_total.get(band, 0) + 1
        if resp == "correct":
            sess.band_known[band] = sess.band_known.get(band, 0) + 1
    return vocab._estimate(sess)


def replay_adaptive(seq: list[tuple]) -> float:
    """adaptive：把每次作答按档位难度乘进后验。"""
    sess = adaptive.AdaptiveSession(id="replay")
    for rank, resp, _ in seq:
        adaptive._update_score(sess, {"level": adaptive._level_of(rank)}, resp)
    return sess.score


def replay_adaptive2(seq: list[tuple]) -> tuple[float, float]:
    """adaptive2：二维 (θ, α) 后验，输出曲线面积与 α。"""
    sess = adaptive2.Adaptive2Session(id="replay")
    for rank, resp, _ in seq:
        adaptive2._update_score(sess, {"level": adaptive._level_of(rank)}, resp)
    return adaptive2._vocab_area(sess.score, sess.alpha), sess.alpha


_bank_cache: dict | None = None


def _cat_bank() -> dict:
    global _bank_cache
    if _bank_cache is None:
        _bank_cache = {it["word"]: it for it in cat._bank()}
    return _bank_cache


def replay_cat(seq: list[tuple]) -> tuple[float, float]:
    """cat：按题库的 b/a 更新 (θ, α) 后验，输出曲线面积与 α。"""
    bank = _cat_bank()
    sess = cat.CatSession(id="replay")
    for rank, resp, word in seq:
        it = bank.get(word)
        b = it["b"] if it else float(rank)
        a = it["a"] if it else 1.0 / adaptive.SCALE
        cat._update_score(sess, {"b": b, "a": a}, resp)
    return adaptive2._vocab_area(sess.score, sess.alpha), sess.alpha


def replay_session(
    seq: list[tuple], classic_max: int = 50, algos: tuple[str, ...] = ALGOS
) -> dict:
    out: dict = {}
    if "classic" in algos:
        out["classic"] = replay_classic(seq, classic_max)
    if "adaptive" in algos:
        out["adaptive"] = replay_adaptive(seq)
    if "adaptive2" in algos:
        out["adaptive2"], out["alpha2"] = replay_adaptive2(seq)
    if "cat" in algos:
        out["cat"], out["alpha_cat"] = replay_cat(seq)
    return out


# ---------- 统计与输出 ----------

def _stats(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "sd": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def summarize(records: list[dict], algos: tuple[str, ...] = ALGOS) -> dict:
    """按源算法分组 + 全样本两两差异。"""
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_source[r["source"]].append(r["estimates"])

    sources = {}
    for source, ests in sorted(by_source.items()):
        sources[source] = {
            algo: _stats([e[algo] for e in ests]) for algo in algos
        }

    def pairwise(rows: list[dict]) -> dict:
        pairs = {}
        for i, a in enumerate(algos):
            for b in algos[i + 1:]:
                diffs = [e[a] - e[b] for e in rows]
                pairs[f"{a}-{b}"] = {
                    "mean": statistics.mean(diffs),
                    "sd": statistics.pstdev(diffs) if len(diffs) > 1 else 0.0,
                    "mean_abs": statistics.mean(abs(d) for d in diffs),
                }
        return pairs

    return {
        "sessions": len(records),
        "algos": list(algos),
        "sources": sources,
        "pairs": pairwise([r["estimates"] for r in records]),
        "pairs_by_source": {
            source: pairwise(ests) for source, ests in sorted(by_source.items())
        },
    }


def print_report(report: dict, records: list[dict], verbose: bool = False) -> None:
    algos = report["algos"]
    if verbose:
        print("=== 逐会话 ===")
        print(f"{'session':<10} {'source':<10} " + " ".join(f"{a:>9}" for a in algos))
        for r in records:
            e = r["estimates"]
            print(
                f"{r['session'][:8]:<10} {r['source']:<10} "
                + " ".join(f"{e[a]:9.0f}" for a in algos)
            )
        print()

    print(f"=== 按源算法分组（{report['sessions']} 个会话）===")
    print(f"{'source':<10} {'n':>4} " + " ".join(f"{a:>9}" for a in algos))
    for source, stats in report["sources"].items():
        n = stats[algos[0]]["n"]
        print(f"{source:<10} {n:>4} " + " ".join(f"{stats[a]['mean']:9.0f}" for a in algos))

    print("\n=== 两两差异（同一会话，A - B）===")
    print(f"{'source':<10} {'pair':<20} {'mean':>8} {'sd':>8} {'mean|d|':>8}")
    for source, pairs in report["pairs_by_source"].items():
        n = report["sources"][source][algos[0]]["n"]
        if n < 2:
            continue
        for pair, s in pairs.items():
            print(f"{source:<10} {pair:<20} {s['mean']:8.0f} {s['sd']:8.0f} {s['mean_abs']:8.0f}")

    print("\n=== 全部会话汇总 ===")
    print(f"{'pair':<20} {'mean':>8} {'sd':>8} {'mean|d|':>8}")
    for pair, s in report["pairs"].items():
        print(f"{pair:<20} {s['mean']:8.0f} {s['sd']:8.0f} {s['mean_abs']:8.0f}")


def _parse_since(value: str) -> float:
    """支持 2026-11-14 或 epoch 秒。"""
    try:
        return float(value)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def main() -> int:
    parser = argparse.ArgumentParser(description="四种词汇量估计器的离线回放对比")
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    parser.add_argument("--min-answers", type=int, default=20)
    parser.add_argument("--max-answers", type=int, default=80)
    parser.add_argument("--classic-answers", type=int, default=50,
                        help="classic 回放只取前 N 题（其真实题量是 50）")
    parser.add_argument("--include-anonymous", action="store_true",
                        help="连同模拟/匿名会话一起回放")
    parser.add_argument("--since", default=None, help="只回放该日期/时间之后的会话")
    parser.add_argument("--json", default=None, help="把结果另存为 JSON")
    parser.add_argument("--algos", default=",".join(ALGOS),
                        help="只回放其中几个估计器，逗号分隔（默认全部）")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    algos = tuple(a.strip() for a in args.algos.split(",") if a.strip())
    unknown = [a for a in algos if a not in ALGOS]
    if not algos or unknown:
        parser.error(f"--algos 只能取 {ALGOS}，收到 {args.algos}")

    since = _parse_since(args.since) if args.since else None
    sessions = load_sessions(
        Path(args.log),
        min_answers=args.min_answers,
        include_anonymous=args.include_anonymous,
        since=since,
        max_answers=args.max_answers,
    )
    if not sessions:
        print("没有符合条件的会话（检查 --min-answers / --since / --include-anonymous）")
        return 1

    started = time.time()
    records = [
        {
            "session": s["session"],
            "source": s["source"],
            "answers": len(s["seq"]),
            "estimates": replay_session(
                s["seq"], classic_max=args.classic_answers, algos=algos
            ),
        }
        for s in sessions
    ]
    report = summarize(records, algos)
    print_report(report, records, verbose=args.verbose)
    print(f"\n回放完成：{len(records)} 个会话，耗时 {time.time() - started:.1f}s")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"report": report, "sessions": records},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"结果已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

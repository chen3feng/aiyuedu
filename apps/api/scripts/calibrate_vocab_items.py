"""词汇测试题库标定 CLI（issue #40）。

用法：
    uv run --directory apps/api python scripts/calibrate_vocab_items.py
    uv run --directory apps/api python scripts/calibrate_vocab_items.py --dry-run
    uv run --directory apps/api python scripts/calibrate_vocab_items.py --synthetic

默认读取 ``data/logs/vocab_sessions.jsonl``，清洗真实作答后拟合 1PL/2PL。
数据量不足时只打印报告、不写覆盖文件；``--synthetic`` 用合成数据自检拟合。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # 仓库根目录
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import vocab_calibration as cal  # noqa: E402

DEFAULT_LOG = ROOT / "data" / "logs" / "vocab_sessions.jsonl"
DEFAULT_OUT = ROOT / "data" / "calibration" / "vocab_cat_items.json"


def _print_report(report: dict) -> None:
    clean = report.get("clean") or {}
    print("=== 清洗 ===")
    print(f"  保留 session: {clean.get('kept', 0)}")
    print(f"  剔除: {json.dumps({k: v for k, v in clean.items() if k != 'kept'}, ensure_ascii=False)}")
    print("=== 就绪度 ===")
    for key in ("ready", "sessions", "observations", "calibrated_items"):
        print(f"  {key}: {report.get(key)}")
    print(f"  门槛: {json.dumps(report.get('required'), ensure_ascii=False)}")
    print(f"  模型: {report.get('model')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="词汇测试题库标定")
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--model", choices=["1pl", "2pl"], default="2pl")
    parser.add_argument("--min-item", type=int, default=cal.MIN_ITEM_RESPONSES)
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true", help="只打印报告，不写文件")
    parser.add_argument("--synthetic", action="store_true", help="用合成数据自检拟合")
    args = parser.parse_args()

    if args.synthetic:
        obs, truth = cal.synthetic_observations()
        params = cal.fit(obs, model=args.model, epochs=args.epochs)
        errs = [
            abs(params["theta"][sid] - truth["theta"][sid])
            for sid in truth["theta"]
            if sid in params["theta"]
        ]
        errs.sort()
        print(f"合成数据：{len(truth['theta'])} sessions，{len(truth['items'])} items")
        print(f"θ 恢复误差：均值 {sum(errs)/len(errs):.0f}，中位数 {errs[len(errs)//2]:.0f}")
        return 0

    log = Path(args.log)
    if not log.exists():
        print(f"日志不存在：{log}", file=sys.stderr)
        return 1

    report = cal.calibrate(
        str(log), model=args.model, min_item=args.min_item, epochs=args.epochs
    )
    _print_report(report)
    if not report["ready"]:
        print("数据量不足，未写入覆盖文件。继续积累真实作答后再跑。")
        return 0

    if args.dry_run:
        print(f"[dry-run] 将写入 {len(report['items'])} 个词到 {args.out}")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cal.write_overrides(report, str(out))
    print(f"已写入 {len(report['items'])} 个词 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

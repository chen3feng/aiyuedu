"""一次性脚本：用 AI 给 readings.json 每篇文章补 title_zh。

背景：教学产品面向中国中小学生，文章标题必须有中文版。
58 篇老阅读全部只有英文 title，UI 显示对国内用户不友好。

用法：
  uv run --directory data python scripts/backfill_title_zh.py [--dry-run]

流程：
  - 读 data/readings/readings.json
  - 对每篇没有 title_zh 的文章，调用 ai.chat() 让 LLM 生成 ≤14 字的中文标题
  - 边生成边写回（每篇落盘，防止中途中断丢失）
  - 输出进度

跑前配置好 data/config/ai.json 默认 provider；本地 Ollama qwen3:14b
每篇约 5-10s，58 篇总计 5-10 分钟。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 让脚本能 import app.services.ai
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import ai  # noqa: E402

READINGS_PATH = ROOT / "data" / "readings" / "readings.json"

PROMPT_TMPL = (
    "你是一名英语分级阅读编辑。下面是一篇分级阅读文章的标题 + 开头 200 字。"
    "请给这篇起一个**简洁、有吸引力**的中文标题（≤14 字，适合小学生阅读）。\n"
    "**只输出中文标题本身**，不要任何标点 / 引号 / 解释 / 翻译。\n\n"
    "【标题】{title}\n"
    "【开头】{body}"
)


def backfill(dry_run: bool = False) -> None:
    if not READINGS_PATH.exists():
        sys.exit(f"not found: {READINGS_PATH}")

    readings = json.loads(READINGS_PATH.read_text(encoding="utf-8"))
    total = len(readings)
    pending = [r for r in readings if not r.get("title_zh")]
    print(f"总计 {total} 篇，待补 {len(pending)} 篇")
    if not pending:
        print("无需补全")
        return

    provider = ai.get_default_provider()
    if not provider:
        sys.exit("未配置默认 AI provider（data/config/ai.json）")
    print(f"使用 provider: {provider['name']} ({provider['model']})")
    print()

    done = 0
    failed = 0
    t0 = time.time()
    for r in pending:
        body = r.get("body", "")[:200].replace("\n", " ")
        prompt = PROMPT_TMPL.format(title=r.get("title", ""), body=body)
        try:
            content = ai.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=64,
            )
        except RuntimeError as e:
            print(f"  [{r['id']}] AI 失败：{e}")
            failed += 1
            continue
        title_zh = content.strip().strip("「」『』《》\"'").strip()
        # 去掉尾部残留的标点（模型偶有残留）
        for ch in "。.!?！？"):
            title_zh = title_zh.rstrip(ch)
        title_zh = title_zh.strip()
        if not title_zh or len(title_zh) > 30:
            # 太长或空多半是模型未按要求输出，丢弃
            print(f"  [{r['id']}] 跳过：'{title_zh[:50]}'")
            failed += 1
            continue
        r["title_zh"] = title_zh
        done += 1
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (len(pending) - done - failed) / rate if rate > 0 else 0
        print(f"  [{r['id']}] {title_zh}  ({done}/{len(pending)}  ~{eta:.0f}s left)")

        if not dry_run:
            # 边生成边落盘（断电/异常不会丢失已完成部分）
            READINGS_PATH.write_text(
                json.dumps(readings, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    elapsed = time.time() - t0
    print()
    print(f"完成：{done} 篇已补，{failed} 篇失败 / 跳过；耗时 {elapsed:.1f}s")
    if not dry_run:
        print(f"已写回 {READINGS_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    args = ap.parse_args()
    backfill(dry_run=args.dry_run)
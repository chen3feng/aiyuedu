"""一次性脚本：用 AI 给 readings.json 每篇文章补 title_zh。

背景：教学产品面向中国中小学生，文章标题必须有中文版。
58 篇老阅读全部只有英文 title，UI 显示对国内用户不友好。

用法（项目根目录直接跑，不需要切到 apps/api）：
  uv run python scripts/backfill_title_zh.py [--dry-run]
  # 或：python scripts/backfill_title_zh.py

依赖：httpx 库（脚本自带，没有的话 uv add httpx / pip install httpx）。
不依赖 apps/api 的 venv —— 直接读 data/config/ai.json 配置 + httpx 调模型。

跑前配置好 data/config/ai.json 默认 provider；本地 Ollama qwen3:14b
每篇约 5-10s，58 篇总计 5-10 分钟。边生成边落盘，断电不丢。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("缺少 httpx 依赖。请运行：uv add httpx 或 pip install httpx")

ROOT = Path(__file__).resolve().parents[1]
READINGS_PATH = ROOT / "data" / "readings" / "readings.json"
AI_CONFIG_PATH = ROOT / "data" / "config" / "ai.json"

PROMPT_TMPL = (
    "你是一名英语分级阅读编辑。下面是一篇分级阅读文章的标题 + 开头 200 字。"
    "请给这篇起一个**简洁、有吸引力**的中文标题（≤14 字，适合小学生阅读）。\n"
    "**只输出中文标题本身**，不要任何标点 / 引号 / 解释 / 翻译。\n\n"
    "**结构要求**：如果英文标题含 `:`（冒号分隔主副标题），中文必须保留这个结构——"
    "主标题用 `：`（中文全角冒号）与副标题分隔，例如 `主标题：副标题`。\n"
    "如果英文没有冒号，中文也不要加。\n\n"
    "【标题】{title}\n"
    "【开头】{body}"
)


def get_default_provider() -> dict | None:
    """读 data/config/ai.json → 取 default provider 配置。"""
    if not AI_CONFIG_PATH.exists():
        return None
    try:
        cfg = json.loads(AI_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    default_name = cfg.get("default")
    if not default_name:
        return None
    for p in cfg.get("providers") or []:
        if isinstance(p, dict) and p.get("name") == default_name:
            return p
    return None


def call_ai_chat(provider: dict, prompt: str) -> str:
    """POST /chat/completions，返回 assistant content；失败抛 RuntimeError。"""
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": provider["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 64,
        "temperature": 0.3,
    }
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=300.0)
    except httpx.HTTPError as e:
        raise RuntimeError(f"AI 调用失败：{e}") from e
    if resp.status_code != 200:
        snippet = resp.text[:200]
        raise RuntimeError(f"AI 返回 {resp.status_code}：{snippet}")
    try:
        data = resp.json()
        content = (data["choices"][0]["message"].get("content") or "").strip()
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError("AI 响应无法解析")
    if not content:
        raise RuntimeError("AI 返回空内容")
    return content


def clean_title(raw: str) -> str:
    """剥引号 / 末尾残留标点；超过 30 字直接丢弃。"""
    s = raw.strip().strip("「」『』《》\"'""''").strip()
    for ch in "。.!?！？":
        s = s.rstrip(ch)
    return s.strip()


def ensure_colon(english_title: str, chinese_title: str) -> str:
    """如果英文有冒号、中文没有，按 ~40% 位置补 `：`**。
    AI prompt 已要求保留冒号结构，但小模型偶有遗漏，本兜底保证一致性。
    """
    if ":" not in english_title:
        return chinese_title
    if "：" in chinese_title or ":" in chinese_title:
        return chinese_title
    n = len(chinese_title)
    if n < 4:
        return chinese_title
    # 主标题约占 40%；至少保留 2 字在冒号两侧
    split = max(2, min(n - 2, int(n * 0.4)))
    return chinese_title[:split] + "：" + chinese_title[split:]


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

    provider = get_default_provider()
    if not provider:
        sys.exit(f"未配置默认 AI provider（{AI_CONFIG_PATH}）")
    print(f"使用 provider: {provider['name']} ({provider['model']})")
    print()

    done = 0
    failed = 0
    t0 = time.time()
    for r in pending:
        body = (r.get("body") or "")[:200].replace("\n", " ")
        prompt = PROMPT_TMPL.format(title=r.get("title", ""), body=body)
        try:
            title_zh = clean_title(call_ai_chat(provider, prompt))
        except RuntimeError as e:
            print(f"  [{r['id']}] AI 失败：{e}")
            failed += 1
            continue
        if not title_zh or len(title_zh) > 30:
            print(f"  [{r['id']}] 跳过：'{title_zh[:50]}'")
            failed += 1
            continue
        # 兜底：英文有冒号时，中文没冒号自动补 `：`
        title_zh = ensure_colon(r.get("title", ""), title_zh)
        r["title_zh"] = title_zh
        done += 1
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (len(pending) - done - failed) / rate if rate > 0 else 0
        print(f"  [{r['id']}] {title_zh}  ({done}/{len(pending)}  ~{eta:.0f}s left)")

        if not dry_run:
            # 边生成边落盘（断电 / 异常不会丢失已完成部分）
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
"""写作平台：学生英文作文 + AI 逐句批改。

存储：data/writings/writings.json，结构 {user_id: {essay_id: essay}}。
单文件多用户 dict（沿用 services/users.py 模式）；读写加锁，弱家庭并发足够。

句子 / 词数工具复用 reading.py 的正则（拷贝而来，避免跨模块 import 私有函数）。
AI 失败按 ai_glosses 的 {ai_used, reason, raw} 模式优雅降级。
"""
from __future__ import annotations

import itertools
import json
import re
import threading
import time
import uuid
from pathlib import Path

from ..config import settings
from . import ai, prompts

_lock = threading.Lock()

# 单调递增序号，保证快速连续提交时 created_at 仍可严格区分顺序
_seq = itertools.count()


# 与 services/reading.py 同样的句子拆分 / 词 token 正则
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_TOKEN_RE = re.compile(
    r"([0-9]+(?:\.[0-9]+)?(?:st|nd|rd|th)?|[A-Za-z]+(?:'[A-Za-z]+)*)"
    r"|([^A-Za-z0-9]+)"
)


def split_sentences(body: str) -> list[str]:
    """按句末标点（.!? + 空白）拆句；保留原标点；过滤空白句。"""
    return [s.strip() for s in _SENT_SPLIT.split(body.strip()) if s.strip()]


def count_words(body: str) -> int:
    """仅按字母 / 数字 token 计数（与 reading._count 一致口径）。"""
    return sum(1 for m in _TOKEN_RE.finditer(body) if m.group(1))


# ---------- JSON 读写 ----------

def _read() -> dict:
    path = Path(settings.writings_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict) -> None:
    path = Path(settings.writings_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 业务函数 ----------

def _new_essay_id() -> str:
    """w-YYYYMMDD-<6 hex> 形式。UUID 后 6 位在快速提交场景下仍可能撞，
    改用 uuid4 整 8 位保证唯一；保留日期前缀便于人类识别顺序。
    """
    return time.strftime("w-%Y%m%d-", time.localtime(time.time())) + uuid.uuid4().hex[:8]


def _empty_report() -> dict:
    """AI 完全失败时返回的占位报告（前端可仍展示作文，但报告区空）。"""
    return {"sentences": [], "summary_table": [], "praise": ""}


def _build_prompt(prompt_meta: dict | None, target_words: int | None, original: str) -> str:
    """构造单轮 user 消息，沿用 admin.py 的 system-into-user 模式。"""
    title = (prompt_meta or {}).get("title_zh", "（自由写作）")
    body_zh = (prompt_meta or {}).get("body_zh", "")
    target = target_words or (prompt_meta or {}).get("target_words", 100)

    system = (
        "你是给中国中学生批改英语作文的老师。请对以下英文逐句批改，"
        "按下面的 JSON schema 输出。\n\n"
        "要求：\n"
        "- 找出每句的词汇 / 拼写 / 时态 / 单复数 / 主谓一致 / 缺主语 / "
        "中文直译 / 动词搭配 / 介词 错误\n"
        "- 每条错误给出「这条错在哪 + 一句话规则 + 最小修复」\n"
        '- 给出 "corrected"（最小修复）和 "polished"（更自然的表达）\n'
        '- 每句的 "polished_reason" 必须说明润色理由（如：用 walk through 更贴合、'
        '避免重复用词、把直接意译改成英文习惯表达等），中文一句话\n'
        '- 全文批完后给 "summary_table"：按错误类别列学生实例 + 应掌握规则\n'
        '- 最后 "praise" 一句话肯定孩子的亮点（中文）\n'
        "- **只输出 JSON**，不要任何解释文字、不要 markdown 围栏\n\n"
        "JSON schema：\n"
        "{\n"
        '  "sentences": [\n'
        "    {\n"
        '      "index": <1-based int>,\n'
        '      "original": "<原句>",\n'
        '      "errors": [\n'
        "        {\n"
        '          "category": "<拼写|单复数|时态|主谓一致|缺主语|中文直译|动词选择|介词|其他>",\n'
        '          "explanation": "<一句话中文>",\n'
        '          "fix": "<最小修复>"'
        "        }\n"
        "      ],\n"
        '      "corrected": "<最小修复后的整句>",\n'
        '      "polished": "<更自然的润色版>",\n'
        '      "polished_reason": "<为什么这样润色更好，一句话中文（如：用 walk through 比 walk in 更贴合漫步田野的意境；将 while 改为 and 表并列更清晰）>"\n'
        "    }\n"
        "  ],\n"
        '  "summary_table": [\n'
        "    {\n"
        '      "category": "<错误类别>",\n'
        '      "examples": ["<学生原词> → <正确>"],\n'
        '      "rule": "<一句话中文规则>"'
        "    }\n"
        "  ],\n"
        '  "praise": "<一句中文肯定>"\n'
        "}\n"
    )
    user = (
        f"【题目】{title}\n"
        f"【要求】{body_zh}\n"
        f"【目标字数】{target} 词\n\n"
        f"【学生作文】\n{original}"
    )
    return system + "\n\n" + user


def _parse_report(text: str) -> dict | None:
    """解析 AI 返回的批改 JSON。失败返回 None。"""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
        text = text.removeprefix("json").lstrip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def submit_essay(
    user_id: str,
    prompt_key: str | None,
    original: str,
    target_words: int | None = None,
) -> dict:
    """提交作文 → 调 AI 批改 → 落盘 → 返回完整 essay dict。

    AI 整体失败（RuntimeError）/ 响应无法解析时仍落盘，按 {ai_used:False, reason, raw}
    返回，前端可显示红条横幅 + 作文正文。
    """
    original = (original or "").strip()
    if not original:
        raise ValueError("作文不能为空")

    prompt_meta = prompts.get_prompt(prompt_key) if prompt_key else None
    target = target_words or (prompt_meta or {}).get("target_words", 100)

    # AI 批改
    ai_used = False
    reason: str | None = None
    raw: str = ""
    report: dict = _empty_report()
    if prompt_meta or not prompt_key:
        prompt = _build_prompt(prompt_meta, target, original)
        try:
            content = ai.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                # 长作文 (~30 句) 输出 ~6K token；本机慢模型宁可给足也不要 retry
                max_tokens=8192,
            )
        except RuntimeError as e:
            content = ""
            reason = f"AI 调用失败：{e}"
        raw = content[:200]
        if content:
            snippet = content[:120].replace("\n", " ")
            parsed = _parse_report(content)
            if parsed:
                report = parsed
                ai_used = True
            else:
                reason = f"AI 响应无法解析为 JSON（开头: {snippet!r}）"
        elif reason is None:
            # content 为空 + 无 RuntimeError 兜底（不应发生，ai.chat 已抛）
            reason = "AI 返回空内容"

    essay_id = _new_essay_id()
    # 用 time.time() + 进程内单调计数（纳秒级差）保证快速提交时仍可区分顺序
    created_at = round(time.time() + next(_seq) * 1e-9, 9)
    essay = {
        "id": essay_id,
        "created_at": created_at,
        "prompt_key": prompt_key,
        "prompt_title_zh": (prompt_meta or {}).get("title_zh"),
        "prompt_title_en": (prompt_meta or {}).get("title_en"),
        "prompt_body_zh": (prompt_meta or {}).get("body_zh"),
        "target_words": target,
        "word_count": count_words(original),
        "original": original,
        "report": report,
        "ai_used": ai_used,
        "model": _current_model_name(),
        "reason": reason,
        "raw": raw,
    }

    with _lock:
        data = _read()
        data.setdefault(user_id, {})[essay_id] = essay
        _write(data)
    return essay


def list_essays(user_id: str) -> list[dict]:
    """某用户所有作文，按 created_at 倒序（同时间按 id 倒序保稳定）。"""
    data = _read().get(user_id) or {}
    items = [dict(e) for e in data.values()]
    items.sort(key=lambda e: (e.get("created_at", 0), e.get("id", "")), reverse=True)
    return items


def get_essay(user_id: str, essay_id: str) -> dict | None:
    user = _read().get(user_id) or {}
    e = user.get(essay_id)
    return dict(e) if e else None


def delete_essay(user_id: str, essay_id: str) -> bool:
    with _lock:
        data = _read()
        user = data.get(user_id)
        if not user or essay_id not in user:
            return False
        del user[essay_id]
        if not user:
            del data[user_id]
        else:
            data[user_id] = user
        _write(data)
        return True


def _current_model_name() -> str:
    """当前默认 AI 提供者的 model 名；供 essay.ai_used 展示。仅失败时无意义。"""
    try:
        provider = ai.get_default_provider()
        return provider["model"] if provider else ""
    except Exception:
        return ""
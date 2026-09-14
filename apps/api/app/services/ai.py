"""AI 提供者配置 + 实际调用（data/config/ai.json）。

后台管理系统增删改 AI 提供者（OpenAI 兼容端点：name / base_url / api_key / model），
并维护「默认提供者」。小文件、每次读盘（无缓存），跨进程即时可见。

`chat()` 通过默认提供者发起一次 OpenAI 兼容的 chat completion 请求。
"""
import json
import threading
from pathlib import Path

import httpx

from ..config import settings

_lock = threading.Lock()


def _empty() -> dict:
    """每次返回全新结构，避免调用方 append 污染模块级共享列表。"""
    return {"providers": [], "default": None}


def _read() -> dict:
    """读 ai.json → {providers: [{name, base_url, api_key, model}], default}。

    缺失/损坏返回空配置。"""
    path = Path(settings.ai_config_path)
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty()
    providers = [
        p for p in (data.get("providers") or [])
        if isinstance(p, dict) and p.get("name")
    ]
    default = data.get("default") if isinstance(data, dict) else None
    if not any(p["name"] == default for p in providers):
        default = None
    return {"providers": providers, "default": default}


def _write(cfg: dict) -> None:
    path = Path(settings.ai_config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _validate(name: str, base_url: str, model: str) -> tuple[str, str, str]:
    name = (name or "").strip()
    base_url = (base_url or "").strip()
    model = (model or "").strip()
    if not name:
        raise ValueError("提供者名称不能为空")
    if not model:
        raise ValueError("模型名不能为空")
    if not base_url.lower().startswith(("http://", "https://")):
        raise ValueError("url 须以 http:// 或 https:// 开头")
    return name, base_url, model


def list_providers() -> list[dict]:
    """全部提供者（含完整 api_key，供后台编辑回填）。"""
    return _read()["providers"]


def get_provider(name: str) -> dict | None:
    for p in _read()["providers"]:
        if p["name"] == name:
            return dict(p)
    return None


def add_provider(name: str, base_url: str, api_key: str, model: str) -> dict:
    """新增提供者；name 重复或字段非法抛 ValueError。返回新提供者。"""
    name, base_url, model = _validate(name, base_url, model)
    api_key = (api_key or "").strip()
    with _lock:
        cfg = _read()
        if any(p["name"] == name for p in cfg["providers"]):
            raise ValueError(f"提供者已存在: {name}")
        provider = {"name": name, "base_url": base_url, "api_key": api_key, "model": model}
        cfg["providers"].append(provider)
        _write(cfg)
        return dict(provider)


def update_provider(
    name: str,
    *,
    new_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> dict:
    """更新提供者（字段为 None 时保留原值）；支持重命名（同步改 default 引用）。

    不存在抛 ValueError。返回更新后的提供者。"""
    with _lock:
        cfg = _read()
        for p in cfg["providers"]:
            if p["name"] == name:
                break
        else:
            raise ValueError(f"提供者不存在: {name}")

        target = new_name if new_name is not None else name
        target = target.strip()
        if not target:
            raise ValueError("提供者名称不能为空")
        if target != name and any(p["name"] == target for p in cfg["providers"]):
            raise ValueError(f"提供者已存在: {target}")
        if base_url is not None:
            base_url = base_url.strip()
            if not base_url.lower().startswith(("http://", "https://")):
                raise ValueError("url 须以 http:// 或 https:// 开头")
        if model is not None and not model.strip():
            raise ValueError("模型名不能为空")

        for p in cfg["providers"]:
            if p["name"] == name:
                p["name"] = target
                if base_url is not None:
                    p["base_url"] = base_url.strip()
                if api_key is not None:
                    p["api_key"] = api_key.strip()
                if model is not None:
                    p["model"] = model.strip()
                updated = dict(p)
        if cfg["default"] == name:
            cfg["default"] = target
        _write(cfg)
        return updated


def delete_provider(name: str) -> bool:
    """删除提供者；不存在返回 False。删除默认提供者时 default 置 None。"""
    with _lock:
        cfg = _read()
        kept = [p for p in cfg["providers"] if p["name"] != name]
        if len(kept) == len(cfg["providers"]):
            return False
        cfg["providers"] = kept
        if cfg["default"] == name:
            cfg["default"] = None
        _write(cfg)
        return True


def get_default() -> str | None:
    return _read()["default"]


def set_default(name: str) -> None:
    """设置默认提供者；name 不存在抛 ValueError。"""
    name = (name or "").strip()
    with _lock:
        cfg = _read()
        if not any(p["name"] == name for p in cfg["providers"]):
            raise ValueError(f"提供者不存在: {name}")
        cfg["default"] = name
        _write(cfg)


def get_default_provider() -> dict | None:
    """默认提供者完整配置；无默认返回 None。"""
    name = get_default()
    return get_provider(name) if name else None


def chat(
    messages: list[dict],
    *,
    temperature: float | None = None,
    max_tokens: int = 8192,
) -> str:
    """调用默认提供者做一次 chat completion，返回 assistant 的文本 content。

    - 未配置默认提供者 / 网络错误 / 非 200 / 空 content → 抛 RuntimeError（可读信息）。
    - 推理模型（如 deepseek-flash）只读 message.content，忽略 reasoning_content。
    """
    provider = get_default_provider()
    if not provider:
        raise RuntimeError("未配置默认 AI 提供者")

    url = provider["base_url"].rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": provider["model"],
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"调用 AI 失败：{exc}") from exc

    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            detail = resp.text[:200]
        raise RuntimeError(f"AI 返回 {resp.status_code}" + (f"：{detail}" if detail else ""))

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError):
        content = ""
    if not content:
        raise RuntimeError("AI 返回空内容")
    return content

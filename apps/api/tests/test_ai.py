"""AI 提供者配置的单元测试（用 tmp 文件隔离真实 ai.json）。

覆盖：add/list/get、字段校验、update（含重命名同步 default）、delete（默认置 None）、
set_default、文件缺失/损坏降级。

运行：uv run --directory apps/api pytest -q
"""
import pytest

from app.config import settings
from app.services import ai


@pytest.fixture(autouse=True)
def _tmp_ai_config(tmp_path, monkeypatch):
    path = tmp_path / "ai.json"
    monkeypatch.setattr(settings, "ai_config_path", str(path))
    return path


def test_add_and_list():
    ai.add_provider("DeepSeek", "https://api.deepseek.com/v1", "sk-abc", "deepseek-chat")
    providers = ai.list_providers()
    assert [p["name"] for p in providers] == ["DeepSeek"]
    assert providers[0]["model"] == "deepseek-chat"
    assert providers[0]["base_url"] == "https://api.deepseek.com/v1"


def test_add_validation():
    with pytest.raises(ValueError):
        ai.add_provider("", "https://x/v1", "k", "m")  # 空名称
    with pytest.raises(ValueError):
        ai.add_provider("A", "ftp://x", "k", "m")  # 非 http(s)
    with pytest.raises(ValueError):
        ai.add_provider("A", "https://x/v1", "k", "")  # 空模型
    ai.add_provider("A", "https://x/v1", "k", "m")
    with pytest.raises(ValueError):
        ai.add_provider("A", "https://x/v1", "k", "m")  # 重名


def test_update_and_rename_syncs_default():
    ai.add_provider("A", "https://a/v1", "ka", "ma")
    ai.add_provider("B", "https://b/v1", "kb", "mb")
    ai.set_default("A")
    ai.update_provider("A", new_name="A2", model="m2")
    assert ai.get_default() == "A2"
    p = ai.get_provider("A2")
    assert p["model"] == "m2"
    assert p["base_url"] == "https://a/v1"  # 未改字段保留


def test_update_missing_raises():
    with pytest.raises(ValueError):
        ai.update_provider("nope", model="m")


def test_delete_default_resets():
    ai.add_provider("A", "https://a/v1", "ka", "ma")
    ai.set_default("A")
    assert ai.delete_provider("A") is True
    assert ai.get_default() is None
    assert ai.list_providers() == []


def test_delete_missing():
    assert ai.delete_provider("nope") is False


def test_set_default_missing_raises():
    with pytest.raises(ValueError):
        ai.set_default("nope")


def test_missing_file_degrades():
    # fixture 指向 tmp 空目录，ai.json 尚未创建
    assert ai.list_providers() == []
    assert ai.get_default() is None


def test_corrupt_file_degrades(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "ai_config_path", str(path))
    assert ai.list_providers() == []
    assert ai.get_default() is None


def test_default_provider_roundtrip():
    ai.add_provider("A", "https://a/v1", "ka", "ma")
    ai.set_default("A")
    p = ai.get_default_provider()
    assert p["name"] == "A"
    assert p["api_key"] == "ka"


# ---------- chat 调用 ----------


class _Resp:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self._content = content
        self.text = content

    def json(self):
        return self._content


def test_chat_returns_content(monkeypatch):
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp(
        200, {"choices": [{"message": {"content": "你好"}}]}))
    ai.add_provider("P", "https://x/v1", "k", "m")
    ai.set_default("P")
    assert ai.chat([{"role": "user", "content": "hi"}]) == "你好"


def test_chat_no_default_raises():
    with pytest.raises(RuntimeError):
        ai.chat([{"role": "user", "content": "hi"}])


def test_chat_http_error_raises(monkeypatch):
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp(
        500, {"error": {"message": "boom"}}))
    ai.add_provider("P", "https://x/v1", "k", "m")
    ai.set_default("P")
    with pytest.raises(RuntimeError):
        ai.chat([{"role": "user", "content": "hi"}])


def test_chat_empty_content_raises(monkeypatch):
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp(
        200, {"choices": [{"message": {"content": ""}}]}))
    ai.add_provider("P", "https://x/v1", "k", "m")
    ai.set_default("P")
    with pytest.raises(RuntimeError):
        ai.chat([{"role": "user", "content": "hi"}])


def test_chat_url_and_payload(monkeypatch):
    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["json"] = kw["json"]
        captured["headers"] = kw["headers"]
        return _Resp(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    ai.add_provider("P", "https://api.deepseek.com", "k", "m")
    ai.set_default("P")
    ai.chat([{"role": "user", "content": "hi"}])
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["json"]["model"] == "m"
    assert captured["json"]["max_tokens"] == 8192

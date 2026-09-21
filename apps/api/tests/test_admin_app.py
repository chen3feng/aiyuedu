"""admin app（8001）整应用层测试：Basic 认证门禁 + API key 脱敏。"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.admin_app import admin_app
from app.config import settings
from app.services import ai, reading, topics


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "test-secret")
    monkeypatch.setattr(settings, "ai_config_path", str(tmp_path / "ai.json"))
    monkeypatch.setattr(settings, "topics_path", str(tmp_path / "topics.json"))
    monkeypatch.setattr(settings, "readings_path", str(tmp_path / "readings.json"))
    reading._readings_cache["mtime"] = None
    reading._readings_cache["data"] = None
    (tmp_path / "readings.json").write_text("[]", encoding="utf-8")
    return TestClient(admin_app)


def _basic(password: str, username: str = "admin") -> dict:
    raw = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


# ---------- 认证门禁 ----------

def test_admin_api_requires_login(client: TestClient) -> None:
    resp = client.get("/api/topics")
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("WWW-Authenticate", "")


def test_admin_static_index_requires_login(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 401


def test_admin_collections_wrapper_requires_login(client: TestClient) -> None:
    resp = client.get("/api/collections")
    assert resp.status_code == 401


def test_admin_login_wrong_password(client: TestClient) -> None:
    resp = client.get("/api/topics", headers=_basic("wrong"))
    assert resp.status_code == 401


def test_admin_login_wrong_username(client: TestClient) -> None:
    resp = client.get("/api/topics", headers=_basic("test-secret", username="root"))
    assert resp.status_code == 401


def test_admin_login_correct_password(client: TestClient) -> None:
    resp = client.get("/api/topics", headers=_basic("test-secret"))
    assert resp.status_code == 200


# ---------- API key 脱敏 ----------

def test_provider_list_masks_api_key(client: TestClient) -> None:
    ai.add_provider(
        "DeepSeek", "https://api.deepseek.com/v1", "sk-secret-key-1234", "deepseek-chat"
    )
    resp = client.get("/api/ai/providers", headers=_basic("test-secret"))
    assert resp.status_code == 200
    item = resp.json()["items"][0]

    # 明文绝不能出现在响应里
    assert "sk-secret-key-1234" not in resp.text
    assert item["api_key"] == "****1234"
    assert item["has_key"] is True


def test_provider_without_key(client: TestClient) -> None:
    ai.add_provider("Local", "http://localhost:11434/v1", "", "qwen3")
    resp = client.get("/api/ai/providers", headers=_basic("test-secret"))
    item = resp.json()["items"][0]
    assert item["api_key"] == ""
    assert item["has_key"] is False


def test_update_with_null_key_keeps_existing(client: TestClient) -> None:
    ai.add_provider("A", "https://a/v1", "sk-real-key-9876", "m")
    resp = client.put(
        "/api/ai/providers/A",
        headers=_basic("test-secret"),
        json={"model": "m2", "api_key": None},
    )
    assert resp.status_code == 200
    # 进程内仍能取到完整原 key（chat 调用不受影响）
    assert ai.get_provider("A")["api_key"] == "sk-real-key-9876"
    assert ai.get_provider("A")["model"] == "m2"


def test_update_with_empty_key_keeps_existing(client: TestClient) -> None:
    ai.add_provider("A", "https://a/v1", "sk-real-key-9876", "m")
    resp = client.put(
        "/api/ai/providers/A",
        headers=_basic("test-secret"),
        json={"model": "m2", "api_key": ""},
    )
    assert resp.status_code == 200
    assert ai.get_provider("A")["api_key"] == "sk-real-key-9876"


def test_update_with_new_key_replaces(client: TestClient) -> None:
    ai.add_provider("A", "https://a/v1", "sk-old-1111", "m")
    resp = client.put(
        "/api/ai/providers/A",
        headers=_basic("test-secret"),
        json={"api_key": "sk-new-2222"},
    )
    assert resp.status_code == 200
    assert ai.get_provider("A")["api_key"] == "sk-new-2222"

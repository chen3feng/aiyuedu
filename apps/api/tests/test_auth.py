"""账号 / 登录态 / 匿名数据迁移 / 生词本 / 测试历史 / 阅读进度 测试。"""
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import auth, notebook, reading, users, vocab, vocab_adaptive, vocab_tests, writing

DATA_FILES = (
    "accounts_path",
    "sessions_path",
    "users_path",
    "writings_path",
    "notebooks_path",
    "vocab_tests_path",
    "reading_log_path",
)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """把账号与所有业务存储重定向到临时目录。"""
    for attr in DATA_FILES:
        monkeypatch.setattr(settings, attr, str(tmp_path / f"{attr}.json"))
    return tmp_path


@pytest.fixture
def client(stores):
    return TestClient(app)


# ---------- 密码哈希 ----------

def test_password_hash_roundtrip():
    stored = auth.hash_password("secret123")
    assert stored.startswith("pbkdf2_sha256$")
    assert auth.verify_password("secret123", stored)
    assert not auth.verify_password("wrong", stored)
    assert not auth.verify_password("secret123", "garbage")
    assert not auth.verify_password("secret123", "")


def test_password_hash_is_salted():
    assert auth.hash_password("secret123") != auth.hash_password("secret123")


# ---------- 注册 / 登录 / 会话 ----------

def test_register_returns_token_and_resolves_user(stores):
    token, account, imported = auth.register("Alice", "secret123")
    assert imported == {}
    assert account["username"] == "Alice"
    assert auth.resolve_user_id(f"Bearer {token}", "device-1") == account["user_id"]
    assert auth.resolve_session(token)["user_id"] == account["user_id"]


def test_resolve_user_id_falls_back_to_device(stores):
    assert auth.resolve_user_id(None, "device-1") == "device-1"
    assert auth.resolve_user_id("Bearer nope", "device-1") == "device-1"
    assert auth.resolve_user_id("Basic abc", "device-1") == "device-1"
    assert auth.resolve_user_id(None, None) == "anonymous"


def test_login_username_is_case_insensitive(stores):
    _, account, _ = auth.register("Alice", "secret123")
    token, logged = auth.login("  alice  ", "secret123")
    assert logged["user_id"] == account["user_id"]
    assert auth.resolve_session(token) is not None


def test_duplicate_username_rejected(stores):
    auth.register("Alice", "secret123")
    with pytest.raises(auth.AuthError) as exc:
        auth.register("alice", "secret123")
    assert exc.value.status == 409


@pytest.mark.parametrize("username,password,status", [
    ("a", "secret123", 422),
    ("ab", "123", 422),
    ("a\x00b", "secret123", 422),
])
def test_register_validation(stores, username, password, status):
    with pytest.raises(auth.AuthError) as exc:
        auth.register(username, password)
    assert exc.value.status == status


def test_login_wrong_password(stores):
    auth.register("Alice", "secret123")
    with pytest.raises(auth.AuthError) as exc:
        auth.login("Alice", "wrong-pass")
    assert exc.value.status == 401


def test_logout_invalidates_token(stores):
    token, _, _ = auth.register("Alice", "secret123")
    auth.logout(token)
    assert auth.resolve_session(token) is None


def test_change_password_keeps_current_session(stores):
    token, account, _ = auth.register("Alice", "secret123")
    other, _ = auth.login("Alice", "secret123")
    auth.change_password(account["user_id"], "secret123", "newpass1", keep_token=token)
    assert auth.resolve_session(token) is not None
    assert auth.resolve_session(other) is None
    auth.login("Alice", "newpass1")


def test_change_password_rejects_wrong_old(stores):
    _, account, _ = auth.register("Alice", "secret123")
    with pytest.raises(auth.AuthError) as exc:
        auth.change_password(account["user_id"], "nope", "newpass1")
    assert exc.value.status == 401


def test_admin_reset_password(stores):
    token, account, _ = auth.register("Alice", "secret123")
    username, temp = auth.admin_reset_password(account["user_id"])
    assert username == "Alice"
    assert len(temp) == 10
    assert auth.resolve_session(token) is None
    auth.login("Alice", temp)


def test_account_stats_counts(stores):
    _, account, _ = auth.register("Alice", "secret123")
    users.upsert_profile(account["user_id"], {"vocab_size": 4200})
    notebook.add_item(account["user_id"], "apple", "苹果")
    stats = auth.account_stats()
    row = next(r for r in stats if r["user_id"] == account["user_id"])
    assert row["username"] == "Alice"
    assert row["vocab_size"] == 4200
    assert row["notebook"] == 1


# ---------- 匿名数据迁移 / 删除账号 ----------

def test_register_imports_anonymous_data(stores):
    device = "device-abc"
    users.upsert_profile(device, {"vocab_size": 4000})
    notebook.add_item(device, "apple", "苹果")
    vocab_tests.add(device, {"ts": 1.0, "algo": "adaptive", "score": 4000})
    writing._write({device: {"w1": {"id": "w1", "created_at": 1.0}}})
    reading.record_reading("r001", 4000, 0.5, 30, [], device)

    token, account, imported = auth.register("Alice", "secret123", device_user_id=device)
    uid = account["user_id"]

    assert imported == {
        "profile": 1,
        "writings": 1,
        "notebook": 1,
        "vocab_tests": 1,
        "reading_records": 1,
    }
    assert users.get_profile(uid)["vocab_size"] == 4000
    assert [e["id"] for e in writing.list_essays(uid)] == ["w1"]
    assert notebook.list_items(uid)[0]["word"] == "apple"
    assert vocab_tests.list_tests(uid)[0]["score"] == 4000
    assert reading.list_progress(uid)[0]["reading_id"] == "r001"
    # 原设备数据已搬空
    assert users.get_profile(device)["vocab_size"] is None
    assert writing.list_essays(device) == []


def test_delete_account_removes_all_data(stores):
    device = "device-abc"
    users.upsert_profile(device, {"vocab_size": 4000})
    notebook.add_item(device, "apple", "苹果")
    vocab_tests.add(device, {"ts": 1.0, "algo": "adaptive", "score": 4000})
    writing._write({device: {"w1": {"id": "w1", "created_at": 1.0}}})
    reading.record_reading("r001", 4000, 0.5, 30, [], device)

    token, account, _ = auth.register("Alice", "secret123", device_user_id=device)
    uid = account["user_id"]
    auth.delete_account(uid, "secret123")

    assert auth.get_account(uid) is None
    assert auth.resolve_session(token) is None
    assert users.get_profile(uid)["vocab_size"] is None
    assert writing.list_essays(uid) == []
    assert notebook.list_items(uid) == []
    assert vocab_tests.list_tests(uid) == []
    assert reading.list_progress(uid) == []


# ---------- 接口层 ----------

def test_api_register_me_and_scope(client):
    resp = client.post("/auth/register", json={"username": "bob", "password": "secret123"})
    assert resp.status_code == 200
    body = resp.json()
    token, uid = body["token"], body["user"]["user_id"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["username"] == "bob"

    client.put("/users/me", json={"vocab_size": 5000}, headers=headers)
    assert client.get("/users/me", headers=headers).json()["vocab_size"] == 5000
    # 匿名设备看不到账号数据
    anon = client.get("/users/me", headers={"X-User-Id": "device-x"})
    assert anon.json()["vocab_size"] is None

    # 无 token 的 /auth/me 是 401
    assert client.get("/auth/me").status_code == 401
    # 无效 token 不泄露账号，回退匿名
    assert auth.resolve_user_id("Bearer bogus", "device-x") == "device-x"


def test_api_login_logout_and_password(client):
    client.post("/auth/register", json={"username": "bob", "password": "secret123"})
    login = client.post("/auth/login", json={"username": "bob", "password": "secret123"})
    assert login.status_code == 200
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401

    login2 = client.post("/auth/login", json={"username": "bob", "password": "secret123"})
    headers = {"Authorization": f"Bearer {login2.json()['token']}"}
    bad = client.put(
        "/auth/password",
        json={"old_password": "nope", "new_password": "newpass1"},
        headers=headers,
    )
    assert bad.status_code == 401
    ok = client.put(
        "/auth/password",
        json={"old_password": "secret123", "new_password": "newpass1"},
        headers=headers,
    )
    assert ok.status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 200


def test_api_delete_account(client):
    body = client.post(
        "/auth/register", json={"username": "bob", "password": "secret123"}
    ).json()
    headers = {"Authorization": f"Bearer {body['token']}"}
    resp = client.request("DELETE", "/auth/account", json={"password": "secret123"}, headers=headers)
    assert resp.status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_api_vocab_and_notebook_use_account(client):
    body = client.post(
        "/auth/register", json={"username": "bob", "password": "secret123"}
    ).json()
    headers = {"Authorization": f"Bearer {body['token']}"}
    client.post("/notebook", json={"word": "Apple", "gloss": "苹果"}, headers=headers)
    items = client.get("/notebook", headers=headers).json()["items"]
    assert [i["word"] for i in items] == ["apple"]
    # 匿名设备看不到账号生词本
    assert client.get("/notebook", headers={"X-User-Id": "device-x"}).json()["items"] == []

    start = client.post("/vocab/test/start", json={"algo": "adaptive"}, headers=headers)
    sid = start.json()["session_id"]
    q = start.json()["question"]
    client.post(
        "/vocab/test/answer",
        json={"session_id": sid, "choice": q["options"].index(q["options"][0])},
        headers=headers,
    )
    client.post("/vocab/test/finish", json={"session_id": sid}, headers=headers)
    tests = client.get("/vocab/tests", headers=headers).json()["items"]
    assert len(tests) == 1 and tests[0]["algo"] == "adaptive"


def test_api_reading_progress(client, stores):
    reading.record_reading("r001", 4000, 0.5, 30, [], "device-1")
    resp = client.get("/readings/progress", headers={"X-User-Id": "device-1"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["reading_id"] == "r001"
    assert items[0]["completed_ratio"] == 0.5


# ---------- 生词本 / 测试历史 服务 ----------

def test_notebook_upsert_and_remove(stores):
    notebook.add_item("u1", "Apple", "苹果", "/ˈæpl/", "r1")
    notebook.add_item("u1", "apple", "苹果（更新）")
    items = notebook.list_items("u1")
    assert len(items) == 1
    assert items[0]["gloss"] == "苹果（更新）"
    assert items[0]["phonetic"] == ""  # 后一次覆盖
    assert notebook.remove_item("u1", "APPLE") is True
    assert notebook.list_items("u1") == []
    assert notebook.remove_item("u1", "apple") is False


def test_notebook_requires_word(stores):
    with pytest.raises(ValueError):
        notebook.add_item("u1", "  ")


def test_vocab_history_recorded_once(stores):
    sid, q, _ = vocab_adaptive.start_test("u1")
    sess = vocab_adaptive.get_session(sid)
    vocab_adaptive.submit_answer(sess, 0, False)
    vocab_adaptive.finish_test(sess)
    vocab_adaptive.finish_test(sess)  # 幂等
    items = vocab_tests.list_tests("u1")
    assert len(items) == 1
    assert items[0]["algo"] == "adaptive"
    assert items[0]["total"] == 1


def test_vocab_history_anonymous_not_recorded(stores):
    sid, _, _ = vocab.start_test("")
    sess = vocab.get_session(sid)
    vocab.finish_test(sess)
    assert vocab_tests.list_tests("") == []


def test_reading_progress_latest_per_reading(stores):
    reading.record_reading("r001", 4000, 0.2, 10, [], "u1")
    reading.record_reading("r001", 4000, 0.8, 40, [], "u1")
    reading.record_reading("r002", 4000, 0.1, 5, [], "u1")
    reading.record_reading("r001", 4000, 1.0, 99, [], "u2")
    items = reading.list_progress("u1")
    assert {i["reading_id"] for i in items} == {"r001", "r002"}
    latest = next(i for i in items if i["reading_id"] == "r001")
    assert latest["completed_ratio"] == 0.8


def test_reading_move_and_delete_records(stores):
    reading.record_reading("r001", 4000, 0.2, 10, [], "src")
    assert reading.move_user_records("src", "dst") == 1
    assert reading.list_progress("src") == []
    assert reading.list_progress("dst")[0]["reading_id"] == "r001"
    assert reading.delete_user_records("dst") == 1
    assert reading.list_progress("dst") == []


# ---------- 后台 ----------

def test_admin_user_list_and_reset(stores):
    from app.routers import admin

    _, account, _ = auth.register("Alice", "secret123")
    listing = admin.list_users()
    assert any(u["user_id"] == account["user_id"] for u in listing["items"])
    reset = admin.reset_password(account["user_id"])
    assert reset["username"] == "Alice"
    auth.login("Alice", reset["temp_password"])
    with pytest.raises(HTTPException) as exc:
        admin.reset_password("missing")
    assert exc.value.status_code == 404


def test_accounts_file_has_no_plaintext_password(stores):
    auth.register("Alice", "secret123")
    raw = json.loads((stores / "accounts_path.json").read_text(encoding="utf-8"))
    account = next(iter(raw.values()))
    assert account["password_hash"].startswith("pbkdf2_sha256$")
    assert "secret123" not in json.dumps(raw)

"""账号与登录态：用户名 + 密码注册/登录，Bearer token 会话。

存储：
  data/users/accounts.json  {user_id: account}
  data/users/sessions.json  {sha256(token): {user_id, created_at, last_used_at}}

开发阶段不要求保密，但密码仍用 PBKDF2 哈希、token 只存哈希，避免明文落盘。
账号的 user_id 直接作为现有各业务存储（档案/作文/阅读记录/生词本/测试历史）的 key。
"""
from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
import uuid

from ..config import settings
from . import notebook, reading, users, vocab_tests, writing
from .storage import atomic_write_json, load_json_or

USERNAME_MIN = 2
USERNAME_MAX = 20
PASSWORD_MIN = 6
PBKDF2_ITERATIONS = 120_000
SESSION_TOUCH_SECONDS = 300

_lock = threading.Lock()
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class AuthError(Exception):
    """带 HTTP 语义的认证错误；路由层转成 HTTPException。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------- 用户名 / 密码 ----------

def normalize_username(username: str) -> str:
    return (username or "").strip()


def username_key(username: str) -> str:
    return normalize_username(username).casefold()


def validate_username(username: str) -> str:
    name = normalize_username(username)
    if not (USERNAME_MIN <= len(name) <= USERNAME_MAX):
        raise AuthError(f"用户名需为 {USERNAME_MIN}-{USERNAME_MAX} 个字符", 422)
    if _CONTROL.search(name):
        raise AuthError("用户名不能包含控制字符", 422)
    return name


def validate_password(password: str) -> None:
    if len(password or "") < PASSWORD_MIN:
        raise AuthError(f"密码至少 {PASSWORD_MIN} 位", 422)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            (password or "").encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iters),
        )
        return secrets.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ---------- 存储 ----------

def _read_accounts() -> dict:
    data = load_json_or(settings.accounts_path, {})
    return data if isinstance(data, dict) else {}


def _write_accounts(data: dict) -> None:
    atomic_write_json(settings.accounts_path, data)


def _read_sessions() -> dict:
    data = load_json_or(settings.sessions_path, {})
    return data if isinstance(data, dict) else {}


def _write_sessions(data: dict) -> None:
    atomic_write_json(settings.sessions_path, data)


def get_account(user_id: str | None) -> dict | None:
    if not user_id:
        return None
    account = _read_accounts().get(user_id)
    return dict(account) if isinstance(account, dict) else None


def _find_by_username(username: str) -> dict | None:
    key = username_key(username)
    for account in _read_accounts().values():
        if isinstance(account, dict) and account.get("username_key") == key:
            return dict(account)
    return None


def list_accounts() -> list[dict]:
    return [dict(a) for a in _read_accounts().values() if isinstance(a, dict)]


def account_stats() -> list[dict]:
    """后台用户列表：账号 + 各业务记录数。"""
    out = []
    for account in list_accounts():
        uid = account["user_id"]
        prof = users.get_profile(uid)
        out.append({
            "user_id": uid,
            "username": account.get("username", ""),
            "created_at": account.get("created_at"),
            "last_login_at": account.get("last_login_at"),
            "vocab_size": prof.get("vocab_size"),
            "writings": writing.count(uid),
            "reading_records": len(reading.list_progress(uid)),
            "notebook": notebook.count(uid),
            "vocab_tests": vocab_tests.count(uid),
        })
    out.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    return out


# ---------- 会话 / token ----------

def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _create_session(user_id: str) -> str:
    token = _new_token()
    now = round(time.time(), 3)
    with _lock:
        sessions = _read_sessions()
        sessions[_token_key(token)] = {
            "user_id": user_id,
            "created_at": now,
            "last_used_at": now,
        }
        _write_sessions(sessions)
    return token


def resolve_session(token: str | None) -> dict | None:
    if not token:
        return None
    key = _token_key(token)
    sess = _read_sessions().get(key)
    if not isinstance(sess, dict):
        return None
    account = get_account(sess.get("user_id"))
    if account is None:
        return None
    now = time.time()
    if now - (sess.get("last_used_at") or 0) > SESSION_TOUCH_SECONDS:
        with _lock:
            sessions = _read_sessions()
            cur = sessions.get(key)
            if isinstance(cur, dict):
                cur["last_used_at"] = round(now, 3)
                _write_sessions(sessions)
    return account


def resolve_user_id(authorization: str | None, x_user_id: str | None) -> str:
    """Bearer 有效 → 账号 id；否则回退匿名设备 id。"""
    account = resolve_session(bearer_token(authorization))
    if account:
        return account["user_id"]
    return x_user_id or "anonymous"


def require_account(authorization: str | None) -> dict:
    account = resolve_session(bearer_token(authorization))
    if account is None:
        raise AuthError("请先登录", 401)
    return account


def _delete_sessions(user_id: str, keep_token: str | None = None) -> None:
    keep_key = _token_key(keep_token) if keep_token else None
    with _lock:
        sessions = _read_sessions()
        changed = False
        for key in list(sessions):
            if sessions[key].get("user_id") == user_id and key != keep_key:
                del sessions[key]
                changed = True
        if changed:
            _write_sessions(sessions)


# ---------- 注册 / 登录 / 退出 ----------

def register(
    username: str,
    password: str,
    device_user_id: str | None = None,
) -> tuple[str, dict, dict]:
    name = validate_username(username)
    validate_password(password)
    key = username_key(name)

    with _lock:
        accounts = _read_accounts()
        if any(
            isinstance(a, dict) and a.get("username_key") == key
            for a in accounts.values()
        ):
            raise AuthError("用户名已被占用", 409)
        user_id = uuid.uuid4().hex
        now = round(time.time(), 3)
        account = {
            "user_id": user_id,
            "username": name,
            "username_key": key,
            "password_hash": hash_password(password),
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        }
        accounts[user_id] = account
        _write_accounts(accounts)

    imported: dict = {}
    if device_user_id and device_user_id not in ("", "anonymous") and device_user_id != user_id:
        imported = migrate_user_data(device_user_id, user_id)

    token = _create_session(user_id)
    return token, account, imported


def login(username: str, password: str) -> tuple[str, dict]:
    account = _find_by_username(username)
    if account is None or not verify_password(password, account.get("password_hash", "")):
        raise AuthError("用户名或密码错误", 401)
    with _lock:
        accounts = _read_accounts()
        cur = accounts.get(account["user_id"])
        if isinstance(cur, dict):
            cur["last_login_at"] = round(time.time(), 3)
            _write_accounts(accounts)
    token = _create_session(account["user_id"])
    return token, account


def logout(token: str | None) -> None:
    if not token:
        return
    with _lock:
        sessions = _read_sessions()
        if sessions.pop(_token_key(token), None) is not None:
            _write_sessions(sessions)


# ---------- 修改密码 / 管理员重置 / 删除账号 ----------

def change_password(
    user_id: str,
    old_password: str,
    new_password: str,
    keep_token: str | None = None,
) -> None:
    account = get_account(user_id)
    if account is None:
        raise AuthError("账号不存在", 404)
    if not verify_password(old_password, account.get("password_hash", "")):
        raise AuthError("当前密码不正确", 401)
    validate_password(new_password)
    if old_password == new_password:
        raise AuthError("新密码不能与当前密码相同", 422)

    with _lock:
        accounts = _read_accounts()
        cur = accounts.get(user_id)
        if not isinstance(cur, dict):
            raise AuthError("账号不存在", 404)
        cur["password_hash"] = hash_password(new_password)
        cur["updated_at"] = round(time.time(), 3)
        _write_accounts(accounts)
    _delete_sessions(user_id, keep_token=keep_token)


def _temp_password(length: int = 10) -> str:
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def admin_reset_password(user_id: str) -> tuple[str, str]:
    account = get_account(user_id)
    if account is None:
        raise AuthError("账号不存在", 404)
    temp = _temp_password()
    with _lock:
        accounts = _read_accounts()
        cur = accounts.get(user_id)
        if not isinstance(cur, dict):
            raise AuthError("账号不存在", 404)
        cur["password_hash"] = hash_password(temp)
        cur["updated_at"] = round(time.time(), 3)
        _write_accounts(accounts)
    _delete_sessions(user_id)
    return account.get("username", ""), temp


def delete_account(user_id: str, password: str) -> None:
    account = get_account(user_id)
    if account is None:
        raise AuthError("账号不存在", 404)
    if not verify_password(password, account.get("password_hash", "")):
        raise AuthError("密码不正确", 401)

    with _lock:
        accounts = _read_accounts()
        accounts.pop(user_id, None)
        _write_accounts(accounts)
    _delete_sessions(user_id)
    users.delete_user(user_id)
    writing.delete_user(user_id)
    notebook.delete_user(user_id)
    vocab_tests.delete_user(user_id)
    reading.delete_user_records(user_id)


# ---------- 匿名数据迁移 ----------

def migrate_user_data(src: str, dst: str) -> dict:
    """把 src 的匿名学习数据整体搬到 dst；返回各类搬移数量。"""
    if not src or not dst or src == dst or src == "anonymous":
        return {}
    imported: dict[str, int] = {}
    n = users.move_user(src, dst)
    if n:
        imported["profile"] = n
    n = writing.move_user(src, dst)
    if n:
        imported["writings"] = n
    n = notebook.move_user(src, dst)
    if n:
        imported["notebook"] = n
    n = vocab_tests.move_user(src, dst)
    if n:
        imported["vocab_tests"] = n
    n = reading.move_user_records(src, dst)
    if n:
        imported["reading_records"] = n
    return imported

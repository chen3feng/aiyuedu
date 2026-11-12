"""多用户档案：按 user_id 隔离的阅读主题偏好、词汇量等属性。

数据存 JSON 文件（data/users/users.json，运行期生成，gitignore）。
当前身份是前端生成的不透明 user_id（匿名设备 ID）；后续微信登录/一号多孩时，
只需把 user_id 换成所选孩子的 id，本服务与存储结构不变。

低并发家庭场景：读直接读盘，写加锁做读-改-写，避免并发覆盖。
"""
import threading
import time

from ..config import settings
from .storage import atomic_write_json, load_json_or

_lock = threading.Lock()


def default_profile() -> dict:
    """新用户默认档案：无主题偏好、未评测词汇量。"""
    return {
        "topic_preferences": [],
        "vocab_size": None,
        "updated_at": 0.0,
    }


def _read() -> dict:
    """读 users.json → {user_id: profile}；缺失或损坏返回空。"""
    data = load_json_or(settings.users_path, {})
    return data if isinstance(data, dict) else {}


def _write(users: dict) -> None:
    atomic_write_json(settings.users_path, users)


def get_profile(user_id: str | None) -> dict:
    """返回某用户档案；未见过或 user_id 为空时返回默认（不落盘）。"""
    if not user_id:
        return default_profile()
    return dict(_read().get(user_id) or default_profile())


def get_vocab_size(user_id: str | None) -> int | None:
    """某用户已评测的词汇量；未评测返回 None。"""
    return get_profile(user_id).get("vocab_size") if user_id else None


def upsert_profile(user_id: str, patch: dict) -> dict:
    """合并写入用户档案，返回最新档案。patch 键：topic_preferences / vocab_size。"""
    with _lock:
        users = _read()
        prof = dict(users.get(user_id) or default_profile())
        if "topic_preferences" in patch:
            prof["topic_preferences"] = patch["topic_preferences"]
        if "vocab_size" in patch:
            prof["vocab_size"] = patch["vocab_size"]
        prof["updated_at"] = round(time.time(), 3)
        users[user_id] = prof
        _write(users)
        return dict(prof)


def move_user(src: str, dst: str) -> int:
    """把 src 的档案整体搬到 dst；返回搬移条数（0/1）。"""
    with _lock:
        users = _read()
        prof = users.pop(src, None)
        if prof is None:
            return 0
        users[dst] = prof
        _write(users)
        return 1


def delete_user(user_id: str) -> None:
    with _lock:
        users = _read()
        if users.pop(user_id, None) is not None:
            _write(users)

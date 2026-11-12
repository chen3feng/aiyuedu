"""词汇测试历史：按 user_id 保存每次测评的最终结果。

存储：data/vocab_tests/vocab_tests.json，结构 {user_id: [record, ...]}。
record: {ts, algo, score, vocab_size, total, correct, wrong, unknown}
"""
import threading

from ..config import settings
from .storage import atomic_write_json, load_json_or

_lock = threading.Lock()


def _read() -> dict:
    data = load_json_or(settings.vocab_tests_path, {})
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    atomic_write_json(settings.vocab_tests_path, data)


def add(user_id: str | None, record: dict) -> dict | None:
    """追加一条测试记录；匿名用户（无 user_id）不落盘。"""
    if not user_id:
        return None
    rec = dict(record)
    with _lock:
        data = _read()
        data.setdefault(user_id, []).append(rec)
        _write(data)
    return rec


def list_tests(user_id: str | None) -> list[dict]:
    """某用户的测试历史，按时间倒序。"""
    if not user_id:
        return []
    items = _read().get(user_id) or []
    return sorted(
        (dict(it) for it in items if isinstance(it, dict)),
        key=lambda it: it.get("ts", 0),
        reverse=True,
    )


def count(user_id: str | None) -> int:
    if not user_id:
        return 0
    return len(_read().get(user_id) or [])


def move_user(src: str, dst: str) -> int:
    with _lock:
        data = _read()
        items = data.pop(src, None)
        if not items:
            return 0
        data.setdefault(dst, []).extend(items)
        _write(data)
        return len(items)


def delete_user(user_id: str) -> None:
    with _lock:
        data = _read()
        if data.pop(user_id, None) is not None:
            _write(data)

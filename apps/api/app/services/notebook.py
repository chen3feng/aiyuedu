"""生词本：按 user_id 隔离的单词收藏。

存储：data/notebooks/notebooks.json，结构 {user_id: [item, ...]}。
每个 item: {word, gloss, phonetic, reading_id, ts}。同一用户按 word 去重。
"""
import threading
import time

from ..config import settings
from .storage import atomic_write_json, load_json_or

_lock = threading.Lock()


def _read() -> dict:
    data = load_json_or(settings.notebooks_path, {})
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    atomic_write_json(settings.notebooks_path, data)


def list_items(user_id: str | None) -> list[dict]:
    """某用户的生词本，按加入时间倒序。"""
    if not user_id:
        return []
    items = _read().get(user_id) or []
    return sorted(
        (dict(it) for it in items if isinstance(it, dict)),
        key=lambda it: it.get("ts", 0),
        reverse=True,
    )


def add_item(
    user_id: str,
    word: str,
    gloss: str = "",
    phonetic: str = "",
    reading_id: str = "",
) -> dict:
    """加入生词本；同词已存在则更新释义/来源，不重复添加。"""
    word = (word or "").strip().lower()
    if not word:
        raise ValueError("单词不能为空")
    item = {
        "word": word,
        "gloss": (gloss or "").strip(),
        "phonetic": (phonetic or "").strip(),
        "reading_id": (reading_id or "").strip(),
        "ts": round(time.time(), 3),
    }
    with _lock:
        data = _read()
        items = data.setdefault(user_id, [])
        for i, old in enumerate(items):
            if isinstance(old, dict) and old.get("word") == word:
                item["ts"] = old.get("ts") or item["ts"]
                items[i] = item
                break
        else:
            items.append(item)
        _write(data)
    return dict(item)


def remove_item(user_id: str, word: str) -> bool:
    word = (word or "").strip().lower()
    with _lock:
        data = _read()
        items = data.get(user_id)
        if not items:
            return False
        kept = [it for it in items if not (isinstance(it, dict) and it.get("word") == word)]
        if len(kept) == len(items):
            return False
        if kept:
            data[user_id] = kept
        else:
            del data[user_id]
        _write(data)
        return True


def count(user_id: str | None) -> int:
    if not user_id:
        return 0
    return len(_read().get(user_id) or [])


def move_user(src: str, dst: str) -> int:
    """把 src 的生词本整体搬到 dst；返回搬移条数。"""
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

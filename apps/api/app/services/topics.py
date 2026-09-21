"""阅读主题库：主题 key 与中文名的唯一事实源（data/topics/topics.json）。

后台管理系统增删主题、前端阅读端按主题过滤/展示中文名，都读这里。
小文件、每次读盘（无缓存），跨进程（主 API 与 admin app）改动即时可见。
"""
import re
import threading

from ..config import settings
from .storage import atomic_write_json, load_json_or

_KEY_RE = re.compile(r"^[a-z][a-z0-9-]*$")

_lock = threading.Lock()


def _read() -> list[dict]:
    """读 topics.json → [{key, label_zh}]；缺失/损坏返回空。"""
    data = load_json_or(settings.topics_path, [])
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, dict) and t.get("key")]


def _write(topics: list[dict]) -> None:
    atomic_write_json(settings.topics_path, topics)


def list_topics() -> list[dict]:
    """全部主题 [{key, label_zh}]，按文件顺序。"""
    return _read()


def get_topic_keys() -> list[str]:
    return [t["key"] for t in _read()]


def topic_label(key: str) -> str:
    """主题中文名；未知 key 返回原 key。"""
    for t in _read():
        if t["key"] == key:
            return t["label_zh"]
    return key


def add_topic(key: str, label_zh: str) -> dict:
    """新增主题；key 非法或已存在抛 ValueError。返回新主题。"""
    key = (key or "").strip()
    label_zh = (label_zh or "").strip()
    if not _KEY_RE.match(key):
        raise ValueError(f"主题 key 非法（须小写字母开头，仅含 a-z0-9-）: {key}")
    if not label_zh:
        raise ValueError("主题中文名不能为空")
    with _lock:
        topics = _read()
        if any(t["key"] == key for t in topics):
            raise ValueError(f"主题已存在: {key}")
        topic = {"key": key, "label_zh": label_zh}
        topics.append(topic)
        _write(topics)
        return dict(topic)


def delete_topic(key: str) -> bool:
    """删除主题；不存在返回 False。引用检查由调用方负责。"""
    with _lock:
        topics = _read()
        kept = [t for t in topics if t["key"] != key]
        if len(kept) == len(topics):
            return False
        _write(kept)
        return True

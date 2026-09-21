"""atomic_write_json 的契约测试。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.services import ai
from app.services.storage import atomic_write_json, load_json_or


def test_atomic_write_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "a.json"
    atomic_write_json(p, {"x": 1, "中文": ["a", "b"]})
    assert json.loads(p.read_text(encoding="utf-8")) == {
        "x": 1,
        "中文": ["a", "b"],
    }


def test_atomic_write_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "deep" / "b.json"
    atomic_write_json(p, [1, 2])
    assert json.loads(p.read_text(encoding="utf-8")) == [1, 2]


def test_atomic_write_replaces_whole_file_not_append(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    atomic_write_json(p, {"old": "x" * 200})
    atomic_write_json(p, {"new": 1})
    # 旧内容必须完全消失（直接 open('w') 也满足，这里主要防改回追加模式）
    assert json.loads(p.read_text(encoding="utf-8")) == {"new": 1}


def test_atomic_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    p = tmp_path / "d.json"
    atomic_write_json(p, {"v": 1})
    leftovers = [q for q in tmp_path.iterdir() if q.name != p.name]
    assert leftovers == []


def test_atomic_write_failure_keeps_old_file_and_cleans_tmp(tmp_path: Path) -> None:
    p = tmp_path / "e.json"
    atomic_write_json(p, {"good": True})

    class Boom:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(p, {"boom": Boom()})

    # 旧文件完好，无临时文件残留
    assert json.loads(p.read_text(encoding="utf-8")) == {"good": True}
    leftovers = [q for q in tmp_path.iterdir() if q.name != p.name]
    assert leftovers == []


# ---------- load_json_or ----------

def test_load_json_or_valid(tmp_path: Path) -> None:
    p = tmp_path / "ok.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    assert load_json_or(p, {}) == {"a": 1}


def test_load_json_or_missing(tmp_path: Path) -> None:
    assert load_json_or(tmp_path / "nope.json", []) == []


def test_load_json_or_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{broken", encoding="utf-8")
    assert load_json_or(p, {"x": 0}) == {"x": 0}


def test_load_json_or_callable_default(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("[", encoding="utf-8")
    out = load_json_or(p, dict)
    assert out == {} and isinstance(out, dict)


# ---------- ai.parse_json_object ----------

def test_parse_json_object_plain() -> None:
    assert ai.parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_object_fenced_with_lang() -> None:
    text = '```json\n{"a": 1, "b": "x"}\n```'
    assert ai.parse_json_object(text) == {"a": 1, "b": "x"}


def test_parse_json_object_fenced_without_lang() -> None:
    text = '```\n{"a": 1}\n```'
    assert ai.parse_json_object(text) == {"a": 1}


def test_parse_json_object_surrounded_by_prose() -> None:
    text = '好的，结果如下：\n{"a": 1}\n以上。'
    assert ai.parse_json_object(text) == {"a": 1}


def test_parse_json_object_brace_inside_string() -> None:
    text = '{"a": "weird } value"}'
    assert ai.parse_json_object(text) == {"a": "weird } value"}


def test_parse_json_object_invalid() -> None:
    assert ai.parse_json_object("{not json") is None
    assert ai.parse_json_object("") is None
    assert ai.parse_json_object("[1, 2]") is None
    assert ai.parse_json_object("no braces here") is None


def test_atomic_write_concurrent_threads_end_with_valid_json(tmp_path: Path) -> None:
    p = tmp_path / "f.json"
    atomic_write_json(p, {"i": 0})

    def writer(i: int) -> None:
        for _ in range(20):
            atomic_write_json(p, {"i": i})

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 每次 replace 要么旧版要么新版，文件必然是合法 JSON
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data in [{"i": i} for i in range(8)]
    leftovers = [q for q in tmp_path.iterdir() if q.name != p.name]
    assert leftovers == []

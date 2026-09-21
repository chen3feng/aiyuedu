"""atomic_write_json 的契约测试。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.services.storage import atomic_write_json


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

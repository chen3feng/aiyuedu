"""作品集 service 测试：CRUD + flatten + 跨 collection 查找章节。

覆盖：
- create_collection：字段默认 + 错误（重复 id / 空 title / 非法 id）
- get_collection / list_collections / update_collection / delete_collection
- get_chapter / get_chapter_for_reading
- flatten_chapter_to_reading 视图形态
- 索引 _index.json 重建
"""
import json
from pathlib import Path

import pytest

from app.services import collections
from app.config import settings


@pytest.fixture
def isolated_collections(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "collections_dir", str(tmp_path))
    monkeypatch.setattr(settings, "collections_index", str(tmp_path / "_index.json"))
    return tmp_path


def _sample_coll(cid: str = "alice", n: int = 2) -> dict:
    return {
        "id": cid,
        "title": "Alice's Adventures",
        "title_zh": "爱丽丝梦游仙境",
        "author": "Lewis Carroll",
        "source": "gutenberg://11",
        "total_chapters": n,
        "cover_url": "https://example.com/cover.jpg",
        "intro_zh": "简介",
        "intro_en": "Intro",
        "glossary": {"rabbit": "兔子"},
        "polysemy": {},
        "chapters": [
            {
                "id": f"r-{cid}-{i+1}",
                "index": i + 1,
                "title": f"Chapter {i+1}",
                "title_zh": f"第 {i+1} 章",
                "body": f"Body of chapter {i+1}. " * 10,
                "target_level": 3000,
                "glosses": {f"c{i+1}word": f"词 {i+1}"},
                "terms": {},
                "skip": [],
                "quizzes": [],
            }
            for i in range(n)
        ],
    }


# ---------- CRUD ----------

def test_create_and_get(isolated_collections):
    coll = collections.create_collection(_sample_coll())
    assert coll["id"] == "alice"
    assert coll["total_chapters"] == 2
    fetched = collections.get_collection("alice")
    assert fetched["title"] == "Alice's Adventures"
    assert fetched["chapters"][0]["index"] == 1


def test_create_duplicate_raises(isolated_collections):
    collections.create_collection(_sample_coll("dup"))
    with pytest.raises(ValueError, match="已存在"):
        collections.create_collection(_sample_coll("dup"))


def test_create_invalid_id_raises(isolated_collections):
    with pytest.raises(ValueError, match="非法"):
        collections.create_collection(_sample_coll("Bad ID!"))  # 含空格 + 大写
    with pytest.raises(ValueError, match="非法"):
        collections.create_collection(_sample_coll("-leading-dash"))


def test_create_empty_title_raises(isolated_collections):
    with pytest.raises(ValueError, match="title"):
        collections.create_collection({"id": "x", "title": ""})


def test_update_collection(isolated_collections):
    collections.create_collection(_sample_coll())
    updated = collections.update_collection("alice", {
        "title": "New Title",
        "intro_zh": "新简介",
        "glossary": {"rabbit": "白兔"},
    })
    assert updated["title"] == "New Title"
    assert updated["intro_zh"] == "新简介"
    assert updated["glossary"]["rabbit"] == "白兔"
    # 落盘
    assert collections.get_collection("alice")["title"] == "New Title"


def test_update_nonexistent_returns_none(isolated_collections):
    assert collections.update_collection("nope", {"title": "x"}) is None


def test_delete_collection(isolated_collections):
    collections.create_collection(_sample_coll("doomed"))
    assert collections.delete_collection("doomed") is True
    assert collections.get_collection("doomed") is None
    assert collections.delete_collection("doomed") is False


# ---------- 列表 / 索引 ----------

def test_list_empty(isolated_collections):
    assert collections.list_collections() == []


def test_list_returns_summary(isolated_collections):
    collections.create_collection(_sample_coll("a", n=3))
    collections.create_collection(_sample_coll("b", n=1))
    items = collections.list_collections()
    assert {x["id"] for x in items} == {"a", "b"}
    a = next(x for x in items if x["id"] == "a")
    assert a["total_chapters"] == 3
    assert a["glossary_size"] == 1
    assert a["title"] == "Alice's Adventures"


def test_index_json_rebuilt_on_persist(isolated_collections):
    collections.create_collection(_sample_coll("x"))
    idx = Path(settings.collections_index)
    assert idx.exists()
    data = json.loads(idx.read_text(encoding="utf-8"))
    assert any(d["id"] == "x" for d in data)
    # 删除后索引也应更新
    collections.delete_collection("x")
    data2 = json.loads(idx.read_text(encoding="utf-8"))
    assert all(d["id"] != "x" for d in data2)


# ---------- 章节查找 ----------

def test_get_chapter_by_index(isolated_collections):
    collections.create_collection(_sample_coll("c1", n=3))
    coll, ch = collections.get_chapter("c1", 2)
    assert ch["index"] == 2
    assert ch["title"] == "Chapter 2"
    assert coll["id"] == "c1"


def test_get_chapter_not_found(isolated_collections):
    collections.create_collection(_sample_coll("c2", n=2))
    assert collections.get_chapter("c2", 99) is None
    assert collections.get_chapter("nope", 1) is None


def test_get_chapter_for_reading_scans_all_collections(isolated_collections):
    collections.create_collection(_sample_coll("a", n=2))
    collections.create_collection(_sample_coll("b", n=3))
    coll, ch = collections.get_chapter_for_reading("r-b-2")
    assert coll["id"] == "b"
    assert ch["index"] == 2
    # 没找到
    assert collections.get_chapter_for_reading("r-nope-1") is None


# ---------- flatten 视图 ----------

def test_flatten_chapter_to_reading_shape(isolated_collections):
    coll = collections.create_collection(_sample_coll("flat", n=1))
    chapter = coll["chapters"][0]
    rv = collections.flatten_chapter_to_reading(coll, chapter)
    # 视图关键字段都在
    assert rv["id"] == chapter["id"]
    assert rv["collection_id"] == "flat"
    assert rv["chapter_index"] == 1
    assert rv["chapter_title"] == "Chapter 1"
    assert rv["title"] == "Chapter 1"
    assert rv["body"] == chapter["body"]
    assert rv["glosses"] == chapter["glosses"]
    assert rv["collection_glossary"]["rabbit"] == "兔子"
    assert rv["collection"]["id"] == "flat"
    assert rv["collection"]["title"] == "Alice's Adventures"
    assert rv["collection"]["total_chapters"] == 1
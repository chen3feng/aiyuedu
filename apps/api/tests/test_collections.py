"""作品集 service 测试：CRUD + flatten + 跨 collection 查找章节。

覆盖：
- create_collection：字段默认 + 错误（重复 id / 空 title / 非法 id）
- get_collection / list_collections / update_collection / delete_collection
- get_chapter / get_chapter_for_reading
- flatten_chapter_to_reading 视图形态
- 索引 _index.json 重建
"""
import json
import threading
import time
from pathlib import Path

import pytest

from app.services import collections
from app.config import settings
from app.services import reading as reading_service  # noqa: F401 (test isolation needs reset)


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


# ---------- 章节 AI 释义 ----------

def _wait_chapter_done(coll_id: str, ch_idx: int, timeout: float = 3.0) -> dict:
    """轮询章节 ai_status 变成 done 或 error（后台线程跑完后才稳定）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        c = collections.get_collection(coll_id)
        if c is None:
            return {}
        ch = next((x for x in c["chapters"] if x["index"] == ch_idx), None)
        if ch and ch.get("ai_status") in ("done", "error"):
            return ch
        time.sleep(0.05)
    raise AssertionError(f"超时：章节 {ch_idx} 未跑完")


def test_extract_chapter_vocab_returns_context(isolated_collections):
    """annotate 找不到的词不会被提出；能找到的会带首次出现句。"""
    body = "Sara ventured into a quaint attic. The attic was dim."
    items = collections._extract_chapter_vocab(body, level=100)  # level=100 → 几乎所有词都是新词
    lemmas = {it["lemma"] for it in items}
    assert "attic" in lemmas
    assert "quaint" in lemmas
    assert "venture" in lemmas
    # "sara" 是专名，会被 _classify 当噪声过滤
    assert "sara" not in lemmas
    for it in items:
        assert it["lemma"]
        assert "context" in it
        assert "dict_gloss" in it
    # attic 的首次出现句应包含原词
    attic = next(it for it in items if it["lemma"] == "attic")
    assert "attic" in attic["context"].lower()


def test_analyze_chapter_writes_glosses_and_status(isolated_collections, monkeypatch):
    """mock AI 返回有效 JSON → 章节写回 glosses + ai_status=done。"""
    coll = collections.create_collection(_sample_coll("aic1", n=1))
    # 用含罕见词的章节 body（sample body 全是常见词，不会触发 AI）
    coll["chapters"][0]["body"] = "Sara ventured into a quaint attic. The attic was dim."
    collections._persist(coll)

    monkeypatch.setattr(
        collections.ai, "chat",
        lambda *a, **k: json.dumps({"attic": "阁楼", "quaint": "古雅的"}, ensure_ascii=False),
    )
    result = collections.analyze_chapter("aic1", 1)
    assert result["ai_used"] is True
    assert result["chapter"]["ai_status"] == "done"
    assert result["chapter"]["ai_reason"] == ""
    assert result["chapter"]["glosses"].get("attic") == "阁楼"
    assert result["chapter"]["glosses"].get("quaint") == "古雅的"


def test_analyze_chapter_records_ai_failure(isolated_collections, monkeypatch):
    """mock AI 抛 RuntimeError → ai_status=error + reason 带回诊断信息。"""
    coll = collections.create_collection(_sample_coll("aic2", n=1))
    coll["chapters"][0]["body"] = "Sara ventured into a quaint attic. The attic was dim."
    collections._persist(coll)

    monkeypatch.setattr(
        collections.ai, "chat",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模型挂了")),
    )
    result = collections.analyze_chapter("aic2", 1)
    assert result["ai_used"] is False
    assert "模型挂了" in result["reason"]
    ch = result["chapter"]
    assert ch["ai_status"] == "error"
    assert ch["ai_reason"]


def test_analyze_chapter_merges_when_not_force(isolated_collections, monkeypatch):
    """force=False 时合并现有 glosses 与新 glosses（同 key AI 覆盖）。"""
    coll = collections.create_collection(_sample_coll("aic3", n=1))
    coll["chapters"][0]["body"] = "Sara ventured into a quaint attic."
    coll["chapters"][0]["glosses"] = {"existing": "旧义"}
    collections._persist(coll)

    monkeypatch.setattr(
        collections.ai, "chat",
        lambda *a, **k: json.dumps({"attic": "阁楼"}, ensure_ascii=False),
    )
    result = collections.analyze_chapter("aic3", 1, force=False)
    # 现有词条被保留
    assert result["chapter"]["glosses"].get("existing") == "旧义"
    # 新提取的 attic 被加入
    assert result["chapter"]["glosses"].get("attic") == "阁楼"


def test_analyze_chapter_force_replaces(isolated_collections, monkeypatch):
    coll = collections.create_collection(_sample_coll("aic4", n=1))
    coll["chapters"][0]["body"] = "Sara ventured into a quaint attic."
    coll["chapters"][0]["glosses"] = {"stale": "旧"}
    collections._persist(coll)

    monkeypatch.setattr(
        collections.ai, "chat",
        lambda *a, **k: json.dumps({"attic": "阁楼"}, ensure_ascii=False),
    )
    result = collections.analyze_chapter("aic4", 1, force=True)
    assert "stale" not in result["chapter"]["glosses"]
    assert result["chapter"]["glosses"].get("attic") == "阁楼"


def test_analyze_chapter_missing_returns_none(isolated_collections):
    assert collections.analyze_chapter("does-not-exist", 1) is None
    collections.create_collection(_sample_coll("aic5", n=1))
    assert collections.analyze_chapter("aic5", 999) is None


def test_analyze_collection_skips_done(isolated_collections):
    """已 done 的章节不会被重新调度。"""
    coll = collections.create_collection(_sample_coll("batch", n=3))
    coll["chapters"][0]["ai_status"] = "done"
    coll["chapters"][1]["ai_status"] = "pending"
    coll["chapters"][2]["ai_status"] = "error"
    collections._persist(coll)

    # mock AI 极快返回（让后台线程立即完成）
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        collections.ai, "chat",
        lambda *a, **k: json.dumps({}, ensure_ascii=False),
    )
    try:
        result = collections.analyze_collection("batch")
        assert sorted(result["scheduled"]) == [2, 3]
        # 等后台线程跑完
        _wait_chapter_done("batch", 2)
        _wait_chapter_done("batch", 3)
    finally:
        monkey.undo()


def test_reconcile_collection_mixed_glosses(isolated_collections):
    """同一词不同章节不同 gloss → 写入 polysemy；相同 gloss → 写入 glossary。"""
    coll = collections.create_collection(_sample_coll("rec", n=3))
    coll["chapters"][0]["glosses"] = {"apple": "苹果", "bank": "银行"}
    coll["chapters"][1]["glosses"] = {"apple": "苹果", "bank": "河岸", "pear": "梨"}
    coll["chapters"][2]["glosses"] = {"apple": "苹果", "bank": "银行"}
    collections._persist(coll)

    new = collections.reconcile_collection("rec")
    assert new["glossary"]["apple"] == "苹果"           # 全书一致 → glossary
    assert new["glossary"]["bank"] == "银行"            # canonical = 最多 sense
    assert new["glossary"]["pear"] == "梨"
    assert set(new["polysemy"].keys()) == {"bank"}
    assert set(new["polysemy"]["bank"].keys()) == {"银行", "河岸"}
    assert sorted(new["polysemy"]["bank"]["银行"]) == [1, 3]
    assert sorted(new["polysemy"]["bank"]["河岸"]) == [2]


def test_reconcile_collection_missing_returns_none(isolated_collections):
    assert collections.reconcile_collection("ghost") is None
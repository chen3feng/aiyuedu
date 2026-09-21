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

def _wait_chapter_done(coll_id: str, ch_idx: int, timeout: float = 15.0) -> dict:
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
        # 等后台线程跑完 — 显式 join 避免 mock 被 undo 时线程还在跑导致超时
        for t in result["threads"]:
            t.join(timeout=15.0)
            assert not t.is_alive(), f"线程 {t.name} 未在 15s 内完成"
        # 校验 ai_status 已写入
        coll = collections.get_collection("batch")
        assert coll["chapters"][1]["ai_status"] in ("done", "error")
        assert coll["chapters"][2]["ai_status"] in ("done", "error")
    finally:
        monkey.undo()


def test_analyze_collection_no_status_clobber(isolated_collections):
    """并发多章分析：任何线程的写回都不得把别人刚写的 ai_status 覆盖回 pending。

    回归测试：曾因「读快照在锁外、写文件在锁内」，最后落盘的线程拿旧快照
    把其他章节的 done/error 覆盖回 pending（线程全部 join 成功但状态丢失）。
    """
    import random

    n = 6
    coll = collections.create_collection(_sample_coll("race", n=n))
    for ch in coll["chapters"]:
        ch["ai_status"] = "pending"
        ch["body"] = "Sara ventured into a quaint attic. " * 3
    collections._persist(coll)

    def fake_chat(*a, **k):
        time.sleep(random.random() * 0.02)  # 拉开线程竞争窗口
        return json.dumps({"attic": "阁楼", "quaint": "古雅的"}, ensure_ascii=False)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(collections.ai, "chat", fake_chat)
    try:
        result = collections.analyze_collection("race")
        assert result["scheduled"] == list(range(1, n + 1))
        for t in result["threads"]:
            t.join(timeout=15.0)
            assert not t.is_alive(), f"线程 {t.name} 未在 15s 内完成"
        coll = collections.get_collection("race")
        for ch in coll["chapters"]:
            assert ch["ai_status"] in ("done", "error"), (
                f"ch{ch['index']} 状态被并发覆盖: {ch['ai_status']!r}"
            )
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

# ---------- 章节编辑 ----------

def test_update_chapter_fields(isolated_collections):
    """title / title_zh / body / target_level 全量更新并落盘。"""
    collections.create_collection(_sample_coll("edit", n=2))
    ch = collections.update_chapter("edit", 1, {
        "title": "Chapter One",
        "title_zh": "第一章",
        "body": "New body text. " * 5,
        "target_level": 5000,
    })
    assert ch["title"] == "Chapter One"
    assert ch["title_zh"] == "第一章"
    assert ch["body"].startswith("New body text.")
    assert ch["target_level"] == 5000
    # 落盘 + 其他章不受影响
    fetched = collections.get_collection("edit")
    assert fetched["chapters"][0]["title"] == "Chapter One"
    assert fetched["chapters"][1]["title"] == "Chapter 2"


def test_update_chapter_partial(isolated_collections):
    """只传 title_zh：body / target_level / glosses 原样保留。"""
    collections.create_collection(_sample_coll("part", n=1))
    coll = collections.get_collection("part")
    coll["chapters"][0]["body"] = "Original body."
    coll["chapters"][0]["glosses"] = {"attic": "阁楼"}
    coll["chapters"][0]["target_level"] = 3000
    collections._persist(coll)

    ch = collections.update_chapter("part", 1, {"title_zh": "第一章"})
    assert ch["body"] == "Original body."
    assert ch["target_level"] == 3000
    assert ch["glosses"] == {"attic": "阁楼"}


def test_update_chapter_body_resets_ai_status(isolated_collections):
    """body 实际变更 → ai_status 重置 pending + 提示 reason；glosses 保留。"""
    collections.create_collection(_sample_coll("rst", n=1))
    coll = collections.get_collection("rst")
    coll["chapters"][0]["ai_status"] = "done"
    coll["chapters"][0]["glosses"] = {"attic": "阁楼"}
    collections._persist(coll)

    ch = collections.update_chapter("rst", 1, {"body": "Edited body."})
    assert ch["ai_status"] == "pending"
    assert "重跑" in ch["ai_reason"]
    assert ch["glosses"] == {"attic": "阁楼"}  # 词条保留，重跑时覆盖


def test_update_chapter_same_body_keeps_ai_status(isolated_collections):
    """body 传了但内容相同 → 不重置（保存其他字段不算编辑正文）。"""
    collections.create_collection(_sample_coll("same", n=1))
    coll = collections.get_collection("same")
    coll["chapters"][0]["ai_status"] = "done"
    collections._persist(coll)
    body = coll["chapters"][0]["body"]

    ch = collections.update_chapter("same", 1, {"body": body, "title_zh": "改标题"})
    assert ch["ai_status"] == "done"
    assert ch["title_zh"] == "改标题"


def test_update_chapter_missing_returns_none(isolated_collections):
    assert collections.update_chapter("ghost", 1, {"title": "x"}) is None
    collections.create_collection(_sample_coll("miss", n=1))
    assert collections.update_chapter("miss", 999, {"title": "x"}) is None


# ---------- 章节词汇 / 短语编辑 + AI 校准 ----------

def test_update_chapter_glosses_and_terms(isolated_collections):
    """glosses / terms 整体替换并落盘；只动词条不重置 ai_status。"""
    collections.create_collection(_sample_coll("gt", n=1))
    coll = collections.get_collection("gt")
    coll["chapters"][0]["ai_status"] = "done"
    coll["chapters"][0]["glosses"] = {"old": "旧"}
    collections._persist(coll)

    ch = collections.update_chapter("gt", 1, {
        "glosses": {"attic": "阁楼", "": "空键应被滤掉"},
        "terms": {"in want of": "需要"},
    })
    assert ch["glosses"] == {"attic": "阁楼"}
    assert ch["terms"] == {"in want of": "需要"}
    assert ch["ai_status"] == "done"  # 词条编辑不重置
    # 落盘
    assert collections.get_collection("gt")["chapters"][0]["terms"] == {"in want of": "需要"}


def test_ai_calibrate_overrides_with_context(isolated_collections, monkeypatch):
    """AI 给出语境义 → 覆盖现有义；手工词条（提取不覆盖的）也喂给 AI。"""
    coll = collections.create_collection(_sample_coll("cal1", n=1))
    body = "Sara ventured into a quaint attic. The attic was dim."
    # body 换成含生词的（sample body 全是常见词）
    coll["chapters"][0]["body"] = body
    collections._persist(coll)

    seen = {}
    def fake_chat(messages, **k):
        prompt = messages[0]["content"]
        seen["prompt"] = prompt
        return json.dumps({
            "attic": "阁楼", "quaint": "古雅的",
            "happy": "开心的",           # 手工词条（不在提取结果里）
            "in want of": "缺乏",        # 短语
        }, ensure_ascii=False)

    monkeypatch.setattr(collections.ai, "chat", fake_chat)
    r = collections.ai_calibrate_vocab(
        body, level=100,
        glosses={"quaint": "古怪的", "happy": "高兴的"},  # quaint 会被 AI 校准覆盖
        terms={"in want of": "想要"},
    )
    assert r["ai_used"] is True
    assert r["glosses"]["quaint"] == "古雅的"      # AI 覆盖
    assert r["glosses"]["happy"] == "开心的"        # 手工词条被校准
    assert r["terms"]["in want of"] == "缺乏"
    # 手工词条带正文语境喂给 AI
    assert "happy" in seen["prompt"]
    assert "Sara ventured" in seen["prompt"]


def test_ai_calibrate_failure_keeps_original(isolated_collections, monkeypatch):
    """AI 挂掉 → 原样返回 + reason；条目一条不丢。"""
    coll = collections.create_collection(_sample_coll("cal2", n=1))
    body = "Sara ventured into a quaint attic."
    monkeypatch.setattr(
        collections.ai, "chat",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模型挂了")),
    )
    r = collections.ai_calibrate_vocab(
        body, level=100,
        glosses={"attic": "阁楼"},
        terms={"in want of": "需要"},
    )
    assert r["ai_used"] is False
    assert "模型挂了" in r["reason"]
    assert r["glosses"] == {"attic": "阁楼"}
    assert r["terms"] == {"in want of": "需要"}


def test_ai_calibrate_ai_missing_keeps_current(isolated_collections, monkeypatch):
    """AI 漏掉某条 → 该条保持原值（合并保证不丢词条）。"""
    coll = collections.create_collection(_sample_coll("cal3", n=1))
    body = "Sara ventured into a quaint attic."
    monkeypatch.setattr(
        collections.ai, "chat",
        lambda *a, **k: json.dumps({"attic": "阁楼"}, ensure_ascii=False),  # 漏了 quaint
    )
    r = collections.ai_calibrate_vocab(
        body, level=100,
        glosses={"attic": "顶楼", "quaint": "古怪的"},
        terms={},
    )
    assert r["glosses"]["attic"] == "阁楼"        # AI 给了 → 覆盖
    assert r["glosses"]["quaint"] == "古怪的"     # AI 漏了 → 保持


# ---------- AI 短语提取 ----------

def test_ai_gloss_terms_skips_short_body():
    """正文 < 200 词：不调 AI，直接跳过（reason=None，不算失败）。"""
    r = collections._ai_gloss_terms("A very short chapter.", 3000)
    assert r == {"terms": {}, "ai_used": False, "reason": None, "raw": ""}


def test_ai_gloss_terms_parses_and_filters(isolated_collections, monkeypatch):
    """AI 返回短语 JSON：键小写化、单词键过滤（terms 只收多词表达）。"""
    monkeypatch.setattr(
        collections.ai, "chat",
        lambda *a, **k: json.dumps(
            {"In Want Of": "需要", "took possession of": "占有", "room": "房间"},
            ensure_ascii=False,
        ),
    )
    r = collections._ai_gloss_terms("word " * 250, 3000)
    assert r["ai_used"] is True
    assert r["terms"] == {"in want of": "需要", "took possession of": "占有"}
    assert "room" not in r["terms"]


def test_ai_gloss_terms_failure_returns_empty(isolated_collections, monkeypatch):
    monkeypatch.setattr(
        collections.ai, "chat",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模型挂了")),
    )
    r = collections._ai_gloss_terms("word " * 250, 3000)
    assert r["terms"] == {}
    assert r["ai_used"] is False
    assert "模型挂了" in r["reason"]


def _terms_fake_chat():
    """两次 AI 调用（单词 + 短语）按提示词内容分别应答。"""
    def fake(messages, **_kw):
        if "挑选短语" in messages[0]["content"]:
            return json.dumps(
                {"in want of": "需要", "took possession of": "占有"}, ensure_ascii=False
            )
        return json.dumps({"fortune": "财产"}, ensure_ascii=False)
    return fake


def test_analyze_chapter_writes_terms(isolated_collections, monkeypatch):
    coll = collections.create_collection(_sample_coll("at1", n=1))
    body = (
        "She was in want of help and took possession of the room. "
        "The quick brown fox jumps over the lazy dog every day. " * 40
    )
    coll["chapters"][0]["body"] = body
    collections._persist(coll)
    monkeypatch.setattr(collections.ai, "chat", _terms_fake_chat())

    r = collections.analyze_chapter("at1", 1)
    assert r["terms_count"] == 2
    ch = r["chapter"]
    assert ch["terms"]["in want of"] == "需要"
    assert ch["terms"]["took possession of"] == "占有"
    assert ch["ai_status"] == "done"
    # 本章单词全在 3000 词内 → items 空，reason 落「无生词」（done 不标红，既有行为）
    assert ch["ai_reason"] == "无生词"


def test_analyze_chapter_terms_merge_then_force_replace(isolated_collections, monkeypatch):
    """非 force：手工/旧短语保留合并；force：terms 整体替换。"""
    coll = collections.create_collection(_sample_coll("at2", n=1))
    body = (
        "She was in want of help and took possession of the room. "
        "The quick brown fox jumps over the lazy dog every day. " * 40
    )
    coll["chapters"][0]["body"] = body
    coll["chapters"][0]["terms"] = {"old phrase": "旧义"}
    collections._persist(coll)
    monkeypatch.setattr(collections.ai, "chat", _terms_fake_chat())

    r = collections.analyze_chapter("at2", 1)
    terms = r["chapter"]["terms"]
    assert terms["old phrase"] == "旧义"          # 手工加的保留
    assert terms["in want of"] == "需要"

    r = collections.analyze_chapter("at2", 1, force=True)
    terms = r["chapter"]["terms"]
    assert "old phrase" not in terms              # force 整体替换
    assert terms["in want of"] == "需要"
    assert terms["took possession of"] == "占有"


def test_backfill_terms_only_done_and_terms_empty(isolated_collections, monkeypatch):
    """回填只挑 done 且 terms 空的章节，且不动 glosses / ai_status。"""
    coll = collections.create_collection(_sample_coll("bt", n=3))
    long_body = (
        "She was in want of help and took possession of the room. "
        "The quick brown fox jumps over the lazy dog every day. " * 40
    )
    for i, ch in enumerate(coll["chapters"]):
        ch["body"] = long_body
        ch["ai_status"] = "done"
    coll["chapters"][1]["terms"] = {"kept phrase": "保留"}   # 非空 → 跳过
    coll["chapters"][2]["ai_status"] = "pending"             # 非 done → 跳过
    collections._persist(coll)
    monkeypatch.setattr(collections.ai, "chat", _terms_fake_chat())

    r = collections.backfill_terms("bt")
    assert r["scheduled"] == [1]
    for t in r["threads"]:
        t.join()

    cur = collections.get_collection("bt")
    ch1, ch2, ch3 = cur["chapters"]
    assert ch1["terms"].get("in want of") == "需要"
    assert ch1["glosses"] == {"c1word": "词 1"}       # glosses 原封不动
    assert ch1["ai_status"] == "done"
    assert ch2["terms"] == {"kept phrase": "保留"}     # 没被动
    assert ch3["terms"] == {}


def test_backfill_terms_missing_returns_none(isolated_collections):
    assert collections.backfill_terms("nope") is None

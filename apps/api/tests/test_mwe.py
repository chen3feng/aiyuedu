"""多词短语（MWE）匹配器单元测试：连续短语 trie + 可分离短语（verb ... particle）。"""
from app.services import mwe


def test_match_contiguous_phrase():
    spans = mwe.match_spans(["i", "will", "throw", "up", "now"])
    assert (2, 4) in [(s, e) for s, e, _ in spans]
    entry = next(en for s, e, en in spans if s == 2)
    assert entry["text"] == "throw up"
    assert entry["gloss"]


def test_match_separable_phrase():
    # take ... apart：宾语夹在中间
    spans = mwe.match_spans(["take", "it", "apart"])
    assert len(spans) == 1
    s, e, en = spans[0]
    assert (s, e) == (0, 3)
    assert en["text"] == "take apart"


def test_match_separable_with_longer_gap():
    spans = mwe.match_spans(["take", "the", "old", "clock", "apart"])
    assert len(spans) == 1
    assert spans[0][0] == 0 and spans[0][1] == 5


def test_separable_gap_beyond_limit_not_matched():
    # 间隔 5 个词 > SEPARABLE_MAX_GAP，不应匹配
    assert mwe.match_spans(["take", "a", "b", "c", "d", "e", "apart"]) == []


def test_longest_phrase_matches_fully():
    # "at the end of"（4 词）整体匹配，不被拆成更短片段
    spans = mwe.match_spans(["at", "the", "end", "of", "time"])
    assert any(en["text"] == "at the end of" for _, _, en in spans)


def test_no_match_on_unknown_words():
    assert mwe.match_spans(["zzzz", "qqqq", "yyyy"]) == []


# ---------- 文章级术语（match_terms） ----------

def test_match_terms_returns_term_spans():
    terms = {"conservation of momentum": "动量守恒", "greenhouse effect": "温室效应"}
    spans = mwe.match_terms(
        ["the", "conservation", "of", "momentum", "holds"], terms
    )
    assert len(spans) == 1
    s, e, en = spans[0]
    assert (s, e) == (1, 4)
    assert en["type"] == "term"
    assert en["gloss"] == "动量守恒"


def test_match_terms_empty_terms():
    assert mwe.match_terms(["any", "words"], {}) == []


# ---------- 短语并入全局 mwe.json（add_phrases） ----------

def test_add_phrases_dedupes_and_appends(tmp_path, monkeypatch):
    from app.config import settings

    path = tmp_path / "mwe.json"
    path.write_text(
        '{"items": [{"text": "throw up", "gloss": "呕吐", "type": "phrasal_verb", "separable": false}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "mwe_path", str(path))
    mwe._load.cache_clear()

    added = mwe.add_phrases([
        {"text": "throw up", "gloss": "呕吐"},      # 已存在，跳过
        {"text": "take over", "gloss": "接管"},     # 新增
        {"text": "", "gloss": "空文本"},             # 非法，跳过
        {"text": "no gloss", "gloss": ""},          # 非法，跳过
    ])
    assert added == 1

    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    texts = {it["text"] for it in data["items"]}
    assert texts == {"throw up", "take over"}

"""分级阅读服务（生词判定 + 词形还原 + 逐行对照）的单元与回归测试。

覆盖：
  - 句子切分、token 切分（标点剥离、数字、撇号、连字符拆词）；
  - 词形还原（屈折/不规则/派生/专名/所有格）；
  - 生词判定与逐行标注（已知词无注释、生词附释义与 rank）；
  - 生词率统计（标点与数字不计入）；
  - 阅读记录落 JSONL。

运行：uv run --directory apps/api pytest -q
"""
import json

import pytest

from app.services import reading


# ---------- 句子与 token 切分 ----------

def test_sentences_split_on_terminal_punctuation():
    s = reading._sentences("The fox jumped. It ran fast! Did it? 9.58 seconds.")
    assert s == ["The fox jumped.", "It ran fast!", "Did it?", "9.58 seconds."]


def test_tokenize_splits_punctuation_and_keeps_contraction():
    toks = reading._tokenize("can't you see the hand-drawn map?")
    kinds = [(t["kind"], t["text"]) for t in toks]
    assert ("word", "can't") in kinds
    # 连字符作为标点拆出，便于左右分别查词族
    assert kinds == [
        ("word", "can't"), ("punct", " "), ("word", "you"), ("punct", " "),
        ("word", "see"), ("punct", " "), ("word", "the"), ("punct", " "),
        ("word", "hand"), ("punct", "-"), ("word", "drawn"), ("punct", " "),
        ("word", "map"), ("punct", "?"),
    ]


def test_tokenize_keeps_decimal_as_one_token():
    toks = reading._tokenize("he ran in 9.58 seconds")
    assert ("word", "9.58") in [(t["kind"], t["text"]) for t in toks]


# ---------- 词形还原（词族头） ----------

@pytest.mark.parametrize(
    "surface,expected",
    [
        ("jumped", "jump"),            # 屈折
        ("went", "go"),                # 不规则动词
        ("children", "child"),         # 不规则复数
        ("beautiful", "beauty"),       # 派生
        ("environmentalism", "environment"),  # 派生（透明复合不占基础排名）
        ("dogs", "dog"),               # 规则复数
        ("better", "better"),          # 不规则比较级——Nation 里 better 是独立词族头
        ("can't", "can"),              # 缩略词
        ("good", "good"),              # 词族头直查
        ("zzzznonexistent", "zzzznonexistent"),  # 未知词返回自身
    ],
)
def test_head_of(surface, expected):
    assert reading._head_of(surface) == expected


def test_head_of_possessive():
    assert reading._head_of("dog's") == "dog"


# ---------- 生词判定 ----------

def test_common_word_is_known_at_default_level():
    e = reading._classify("the", 3600)
    assert e["known"] is True


def test_rare_word_is_new_with_gloss():
    # "dinosaur" 词族 rank 4248 > 3600，应判生词且带中文释义
    e = reading._classify("dinosaur", 3600)
    assert e["known"] is False
    assert e["gloss"]


def test_number_is_always_known():
    e = reading._classify("9.58", 3600)
    assert e["known"] is True and e.get("num") is True


def test_function_words_are_known():
    # a / an 词表生成时被过滤，靠停用表判已知
    assert reading._classify("a", 3600)["known"] is True
    assert reading._classify("an", 3600)["known"] is True


def test_common_content_words_missing_from_wordlist_are_known():
    # run / past 词族头在词表生成时被过滤，靠补充表判已知
    assert reading._classify("ran", 3600)["known"] is True
    assert reading._classify("past", 3600)["known"] is True


def test_capitalized_name_treated_as_proper_noun():
    # 大写且不在词表（人名/地名）→ 专有名词，按已知处理、不占生词
    assert reading._classify("Jamaica", 3600)["known"] is True
    assert reading._classify("Sam", 3600)["known"] is True and reading._classify("Sam", 3600).get("proper") is True


def test_capitalized_head_word_still_looked_up():
    # 大写但能查到词族的词仍正常判定（Dinosaur -> dinosaur rank 4248 → 生词）
    e = reading._classify("Dinosaur", 3600)
    assert e["known"] is False and e["gloss"]


def test_level_threshold_controls_known():
    # 同一词在不同 level 下判定不同
    assert reading._classify("molecule", 100)["known"] is False
    assert reading._classify("molecule", 25000)["known"] is True


# ---------- 逐行标注与统计 ----------

def test_annotate_builds_lines_with_word_level_flags():
    ann = reading.annotate("The fox jumped over the lazy dog.", 3600)
    assert ann["word_count"] == 7
    words = ann["lines"][0]["words"]
    # 词 token 数与标点分开：The fox jumped over the lazy dog . -> 7 词 + 1 句点
    text = "".join(w["w"] for w in words)
    assert text == "The fox jumped over the lazy dog."
    assert sum(1 for w in words if not w.get("punct")) == 7


def test_stats_counts_words_excluding_numbers_and_punct():
    st = reading.stats("He ran 9.58 seconds in 2009.", 3600)
    # 词：He ran seconds in -> 4 词；9.58 / 2009 是数字，不计入
    assert st["word_count"] == 4
    assert 0.0 <= st["new_word_rate"] <= 1.0


def test_new_word_rate_is_fraction():
    body = "The common words are here and the flagitious lexeme follows."
    st = reading.stats(body, 100)
    assert st["new_word_count"] >= 1
    assert st["new_word_rate"] == pytest.approx(st["new_word_count"] / st["word_count"], abs=1e-3)


# ---------- 路由层（直接调用端点函数） ----------

def test_get_reading_returns_lines():
    from app.routers import reading as reading_router
    resp = reading_router.get_reading("r001", 3600)
    assert resp["id"] == "r001"
    assert resp["lines"]
    assert 0.0 <= resp["new_word_rate"] <= 1.0


def test_get_reading_unknown_raises_404():
    from app.routers import reading as reading_router
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        reading_router.get_reading("nope", 3600)
    assert exc.value.status_code == 404


def test_list_readings_filters_by_topic():
    from app.routers import reading as reading_router
    resp = reading_router.list_readings(3600, topic="science")
    assert resp["items"]
    assert all(i["topic"] == "science" for i in resp["items"])


def test_record_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(reading.settings, "reading_log_path", str(tmp_path / "r.jsonl"))
    reading.record_reading("r001", 3600, 1.0, 120, ["wavelength"])
    line = (tmp_path / "r.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["reading_id"] == "r001"
    assert rec["new_word_clicks"] == ["wavelength"]


# ---------- 生词 ruby 标注 + 文末生词表（完整意思） ----------

def test_full_gloss_keeps_all_senses():
    assert reading.full_gloss("n. 技巧, 技术, 方法；[化] 工艺方法") == "n. 技巧, 技术, 方法"
    assert reading.full_gloss("") == ""


def test_annotate_ruby_marks_new_word_with_context_gloss():
    ann = reading.annotate(
        "A dinosaur walked.", 100,
        {"dinosaur": "恐龙", "walk": "走"},
    )
    html = ann["lines"][0]["html"]
    assert "<ruby>dinosaur<rt>恐龙</rt></ruby>" in html
    assert "<ruby>walked<rt>走</rt></ruby>" in html
    # 已知词（a）不入 ruby
    assert not html.startswith("<ruby>a")


def test_annotate_vocabulary_has_complete_meaning():
    ann = reading.annotate(
        "The propeller spun.", 100,
        {"propel": "螺旋桨"},
        {"propel": "n. 螺旋桨，推进器"},
        {"propel": {"word": "propeller", "phonetic": "prəˈpelə"}},
    )
    voc = {v["lemma"]: v for v in ann["vocabulary"]}
    assert voc["propel"]["word"] == "propeller"              # 展示原型（派生词独立词条）
    assert voc["propel"]["phonetic"] == "prəˈpelə"           # 与展示词匹配的音标
    assert voc["propel"]["gloss"] == "螺旋桨"                 # 语境义
    assert voc["propel"]["full_gloss"] == "n. 螺旋桨，推进器"  # 完整义覆盖


def test_annotate_vocabulary_default_word_is_lemma():
    # 无 headwords 覆盖时：展示词 = 词族头（原型），与音标/发音一致
    ann = reading.annotate("A dinosaur walked.", 100)
    voc = {v["lemma"]: v for v in ann["vocabulary"]}
    assert voc["dinosaur"]["word"] == "dinosaur"
    assert voc["walk"]["word"] == "walk"


def test_annotate_ruby_only_first_occurrence():
    # 同一生词只在首次出现时注释中文，复现不再注释
    ann = reading.annotate("The robot fixed a robot.", 100, {"robot": "机器人"})
    html = ann["lines"][0]["html"]
    assert html.count("<ruby>robot") == 1   # 仅首次注释
    assert html.count("robot") == 2          # 两次都保留原文


def test_annotate_defaults_without_glosses():
    # 无 glosses 时：ruby 用词典义（gloss 裁剪版），vocabulary 仍带完整义
    ann = reading.annotate("A dinosaur walked.", 100)
    assert ann["lines"][0]["html"]
    assert ann["vocabulary"]
    for v in ann["vocabulary"]:
        assert v["full_gloss"]  # 词表生词必有完整义


def test_get_reading_returns_vocabulary_and_body():
    from app.routers import reading as reading_router
    resp = reading_router.get_reading("r001", 3600)
    assert resp["body"]
    assert resp["vocabulary"]
    lemmas = {v["lemma"] for v in resp["vocabulary"]}
    assert "particle" in lemmas
    particle = next(v for v in resp["vocabulary"] if v["lemma"] == "particle")
    assert particle["word"] == "particle"   # 展示原型（屈折还原为词族头）
    assert particle["gloss"] == "微粒"
    assert particle["full_gloss"]

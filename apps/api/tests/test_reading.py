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

from app.services import ecdict, reading


@pytest.fixture(autouse=True)
def _no_ecdict_db(tmp_path, monkeypatch):
    """隔离真实 811MB stardict.db：指向不存在的路径，使 _classify 走「无词库降级」路径，
    让本文件各测试不依赖词库内容、离线可确定运行（词库相关行为在 test_ecdict.py 与下方
    显式建库的测试中覆盖）。"""
    monkeypatch.setattr(ecdict.settings, "ecdict_path", str(tmp_path / "no-stardict.db"))
    ecdict._lookup_row.cache_clear()
    ecdict.has_db.cache_clear()


def _make_ecdict(tmp_path, monkeypatch, rows):
    """建一个带 schema 与指定行的临时 stardict.db，覆盖 autouse 无库夹具。"""
    import sqlite3

    path = tmp_path / "stardict.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE stardict (word TEXT UNIQUE COLLATE NOCASE, phonetic TEXT, "
        "translation TEXT, pos TEXT, tag TEXT, bnc INTEGER, frq INTEGER)"
    )
    con.executemany("INSERT INTO stardict VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    monkeypatch.setattr(ecdict.settings, "ecdict_path", str(path))
    ecdict._lookup_row.cache_clear()
    ecdict.has_db.cache_clear()


# ---------- 句子与 token 切分 ----------

def test_sentences_split_on_terminal_punctuation():
    s = reading._sentences("The fox jumped. It ran fast! Did it? 9.58 seconds.")
    assert s == ["The fox jumped.", "It ran fast!", "Did it?", "9.58 seconds."]


def test_sentences_collapses_soft_wrap_in_lf():
    """古腾堡正文行宽 70 字符强制换行（LF）：非段落分隔，需折叠为空格。"""
    body = "Once on a dark winter's day, when the fog hung so thick and\nheavy in the streets of London."
    s = reading._sentences(body)
    assert s == ["Once on a dark winter's day, when the fog hung so thick and heavy in the streets of London."]


def test_sentences_collapses_soft_wrap_in_crlf():
    """古腾堡正文用 CRLF（Windows）行尾：同样需折叠为单句。"""
    body = "Once on a dark winter's day, when the fog hung so thick and\r\nheavy in the streets."
    s = reading._sentences(body)
    assert s == ["Once on a dark winter's day, when the fog hung so thick and heavy in the streets."]


def test_sentences_keeps_paragraph_break():
    """段落分隔（\n\n / \r\n\r\n）必须保留作为句子边界，不能折叠。"""
    body = "First paragraph ends here.\n\nSecond paragraph starts here."
    s = reading._sentences(body)
    assert len(s) == 2
    assert s[0] == "First paragraph ends here."
    assert s[1] == "Second paragraph starts here."


def test_sentences_keeps_paragraph_break_with_crlf():
    body = "First paragraph ends here.\r\n\r\nSecond paragraph starts here."
    s = reading._sentences(body)
    assert len(s) == 2
    assert s[0] == "First paragraph ends here."
    assert s[1] == "Second paragraph starts here."


def test_sentences_keeps_mr_and_mrs_abbreviations():
    """缩写点不能被当句末标点 — "Mr. Bennet" / "Mrs. Long" 必须完整。"""
    body = (
        "Mr. Bennet was among the earliest. "
        "Mrs. Bennet, however, was not."
    )
    s = reading._sentences(body)
    assert s == [
        "Mr. Bennet was among the earliest.",
        "Mrs. Bennet, however, was not.",
    ]


def test_sentences_keeps_multiple_abbreviations_in_one_sentence():
    body = "Mr. Bennet met Dr. Smith and Prof. Jones at St. Mary's."
    s = reading._sentences(body)
    assert s == ["Mr. Bennet met Dr. Smith and Prof. Jones at St. Mary's."]


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


def test_tokenize_keeps_ordinal_as_one_token():
    # 序数 20th/21st/2nd 整体按数字，不拆出 th/st/nd 碎片
    toks = reading._tokenize("the 20th century and the 21st and 2nd")
    kinds = [(t["kind"], t["text"]) for t in toks]
    assert ("word", "20th") in kinds
    assert ("word", "21st") in kinds
    assert ("word", "2nd") in kinds
    assert not any(t["text"] in ("th", "st", "nd", "rd") for t in toks)


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


def test_head_of_out_of_wordlist_inflection_reduces():
    # 词表外单词的屈折也要还原去重：rovers→rover、orbiters→orbiter
    assert reading._head_of("rovers") == "rover"
    assert reading._head_of("orbiters") == "orbiter"


def test_annotate_dedups_out_of_wordlist_plural():
    # 词表外复数与单数合并成同一生词条目，只入生词表一次
    ann = reading.annotate("The rover drove past the rovers and orbiters.", 3600)
    lemmas = [v["lemma"] for v in ann["vocabulary"]]
    assert lemmas.count("rover") == 1
    assert lemmas.count("orbiter") == 1


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


def test_classify_ecdict_fallback_fills_gloss(tmp_path, monkeypatch):
    # 词表外单词（orbiter 不在 Nation 词表）→ 查 ECDICT 补释义，不再空释义
    _make_ecdict(tmp_path, monkeypatch, [("orbiter", "ˈɔːbɪtə", "n. 轨道飞行器, 人造卫星", "n:100", "", 0, 0)])
    e = reading._classify("orbiter", 3600)
    assert e["known"] is False
    assert e["lemma"] == "orbiter"
    assert e["gloss"]
    assert e["full_gloss"]


def test_classify_noise_fragment_skipped(tmp_path, monkeypatch):
    # 词库有词条但无干净释义（[计]/[网络] 噪声）→ 噪声，不计词、不进生词表
    _make_ecdict(tmp_path, monkeypatch, [("r", None, "[计] 半径, 比例", "", "", 0, 0)])
    e = reading._classify("r", 3600)
    assert e.get("noise") is True
    assert e["known"] is True


def test_network_only_detects_no_clean_line():
    # 释义仅 [网络]/【网络】行时为真；有任一干净行时为假
    assert reading._network_only("[网络] 硬编码；写死") is True
    assert reading._network_only("工作流程") is False
    assert reading._network_only("n. 轨道\n[网络] 轨道") is False


def test_classify_prefers_clean_head_over_network_only_inflected(tmp_path, monkeypatch):
    # workflows 仅 [网络] 噪声，而词族头 workflow 有干净释义 → 取词族头
    _make_ecdict(tmp_path, monkeypatch, [
        ("workflows", None, "[网络] 工作流文档库；流程", "", "", 0, 0),
        ("workflow", None, " 工作流程", "", "", 0, 0),
    ])
    e = reading._classify("workflows", 3600)
    assert e["known"] is False
    assert e["lemma"] == "workflow"
    assert e["gloss"] == "工作流程"
    assert e["full_gloss"] == "工作流程"


def test_classify_single_letter_is_noise_without_db():
    # 单字母（数学符号/单位）无需词库硬判噪声
    for ch in "rvegms":
        assert reading._classify(ch, 3600).get("noise") is True


def test_classify_out_of_wordlist_without_db_is_empty_gloss_new_word():
    # 词库缺失时降级：词表外单词仍是生词（空释义待后台补全），而非被误判为噪声
    e = reading._classify("orbiter", 3600)
    assert e["known"] is False
    assert e["lemma"] == "orbiter"
    assert e["gloss"] == ""


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
    resp = reading_router.get_reading("r001", 3600, None)
    assert resp["id"] == "r001"
    assert resp["lines"]
    assert 0.0 <= resp["new_word_rate"] <= 1.0


def test_get_reading_unknown_raises_404():
    from app.routers import reading as reading_router
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        reading_router.get_reading("nope", 3600, None)
    assert exc.value.status_code == 404


def test_list_readings_filters_by_topic():
    from app.routers import reading as reading_router
    resp = reading_router.list_readings(3600, "science", None)
    assert resp["items"]
    assert all("science" in i["topics"] for i in resp["items"])


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


def test_full_gloss_drops_network_noise_line():
    # ECDICT 的「[网络] ...」整行是抓取噪声，须连同其子义项一起丢弃
    assert reading.full_gloss("n. 温室效应\n[网络] 造成温室效应；快乐工人；植物生长剂") == "n. 温室效应"


def test_short_gloss_single_sense():
    # 多词性/多义项只取第一个义项，去词性前缀与领域噪声
    assert reading.short_gloss("n. 土地，战场，场地；a. 土地的，地面上的") == "土地"
    assert reading.short_gloss("应用，应用程序; 相联并行处理器") == "应用"
    assert reading.short_gloss("n. 时差") == "时差"


def test_short_gloss_strips_pos_and_network_noise():
    assert reading.short_gloss("vt. 使…；vi. 发生") == "使…"
    assert reading.short_gloss("n. 温室效应\n[网络] 造成温室效应；快乐工人") == "温室效应"
    assert reading.short_gloss("") == ""


def test_short_gloss_falls_back_to_network_only_line():
    # 现代技术词常仅 [网络] 一行（hardcoding/refactoring/datacenters 等）；与 full_gloss
    # 一致，此时退而取该行核心义，避免「生词本有义、行内 ruby 空」。
    assert reading.short_gloss("[网络] 硬编码；写死") == "硬编码"
    assert reading.short_gloss("[网络] 重构；代码重构；重整") == "重构"
    assert reading.short_gloss("[网络] 数据中心；资料中心；参观唯一机房") == "数据中心"


def test_short_gloss_strips_parenthetical_notes():
    # ECDICT 的括注（复数/第三人称/语法说明/括住定语）剥掉，只留核心义
    assert reading.short_gloss("n. 化石燃料( fossil fuel的名词复数 )") == "化石燃料"
    assert reading.short_gloss("n. 屋顶( rooftop的复数形式 )") == "屋顶"
    assert reading.short_gloss("(不污染大气的)洁净能源(指电和原子能等)") == "洁净能源"
    assert reading.short_gloss("n. 上帝们；众神，诸神，泛指神灵（god的复数）") == "上帝们"


def test_short_gloss_strips_angle_tags():
    # ECDICT 的尖括号语体/地区标签（<非正> <英> 等）剥掉
    assert reading.short_gloss("<非正>小心翼翼") == "小心翼翼"
    assert reading.short_gloss("<英>室友") == "室友"


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


def test_annotate_term_does_not_span_comma():
    # 术语/多词不得跨非空白标点：列表里的 "rice, noodles" 不是 "rice noodles"
    ann = reading.annotate(
        "I ate rice, noodles, and bread.", 3600, terms={"rice noodles": "米粉"}
    )
    html = ann["lines"][0]["html"]
    assert "<ruby>rice" not in html  # 不应把 rice+noodles 合成一个术语
    assert ", ," not in html          # 不得出现双逗号


def test_annotate_adjacent_term_has_no_double_space():
    # 仅空白分隔的相邻术语应整体注音，且不产生双空格（此前 surface 与内部空格重复输出）
    ann = reading.annotate(
        "I cook with cooking oil daily.", 3600, terms={"cooking oil": "食用油"}
    )
    html = ann["lines"][0]["html"]
    assert "<ruby>cooking oil<rt>食用油</rt></ruby>" in html
    assert "  " not in html  # 无双空格


def test_annotate_only_glosses_skips_uncurated_new_word():
    # 读者端（only_glosses）：词表外生词若不进 glosses，不注 ruby、不进生词表
    ann = reading.annotate(
        "A dinosaur and a quokka walked.", 100, {"dinosaur": "恐龙"}, only_glosses=True
    )
    html = ann["lines"][0]["html"]
    assert "<ruby>dinosaur" in html    # 在 glosses → 注
    assert "<ruby>quokka" not in html  # 不在 glosses → 不注（即便它是生词）
    assert "quokka" not in {v["lemma"] for v in ann["vocabulary"]}


def test_annotate_defaults_without_glosses():
    # 无 glosses 时：ruby 用词典义（gloss 裁剪版），vocabulary 仍带完整义
    ann = reading.annotate("A dinosaur walked.", 100)
    assert ann["lines"][0]["html"]
    assert ann["vocabulary"]
    for v in ann["vocabulary"]:
        assert v["full_gloss"]  # 词表生词必有完整义


def test_annotate_skip_drops_new_word():
    # 后台手工删掉的生词：不注音、不进生词表、不计生词数
    ann = reading.annotate("A dinosaur walked.", 100, {"dinosaur": "恐龙"}, skip=["dinosaur"])
    html = ann["lines"][0]["html"]
    assert "<ruby>dinosaur" not in html
    assert not any(v["lemma"] == "dinosaur" for v in ann["vocabulary"])
    assert ann["new_word_count"] == 1  # 只剩 walk


def test_stats_skip_not_counted_as_new():
    st = reading.stats("A dinosaur walked.", 100, skip=["dinosaur"])
    assert st["new_word_count"] == 1


def test_get_reading_returns_vocabulary_and_body():
    from app.routers import reading as reading_router
    resp = reading_router.get_reading("r001", 3600, None)
    assert resp["body"]
    assert resp["vocabulary"]
    lemmas = {v["lemma"] for v in resp["vocabulary"]}
    assert "particle" in lemmas
    particle = next(v for v in resp["vocabulary"] if v["lemma"] == "particle")
    assert particle["word"] == "particle"   # 展示原型（屈折还原为词族头）
    assert particle["gloss"] == "微粒"
    assert particle["full_gloss"]


# ---------- 课后小测（quiz） ----------

def test_every_reading_has_three_valid_choice_quizzes():
    # 每篇 3 题，当前只支持选择题；字段设计对判断题等未来题型保持可扩展（type 区分）
    # 无题的导入稿（如 036）允许 0 题；英文解析稿允许无中文解释（zh/en 二选一）
    for r in reading.list_readings():
        quizzes = r.get("quizzes", [])
        assert len(quizzes) in (0, 3), f"{r['id']} 应为 0 或 3 道题"
        for q in quizzes:
            assert q["type"] == "choice"
            assert q["question"]
            opts = q["options"]
            assert len(opts) == 4, f"{r['id']} 选项须为 4 个"
            assert all(isinstance(o, dict) and "text" in o and "correct" in o for o in opts)
            assert sum(1 for o in opts if o["correct"]) >= 1, f"{r['id']} 至少一个正确选项"
            assert q["explanation_zh"] or q["explanation_en"]


def test_get_reading_returns_quizzes():
    from app.routers import reading as reading_router
    resp = reading_router.get_reading("r001", 3600, None)
    assert len(resp["quizzes"]) == 3
    q = resp["quizzes"][0]
    assert set(q) >= {"type", "question", "options", "explanation_zh", "explanation_en"}
    assert all({"text", "correct"} <= set(o) for o in q["options"])


def test_record_writes_user_id(tmp_path, monkeypatch):
    monkeypatch.setattr(reading.settings, "reading_log_path", str(tmp_path / "r.jsonl"))
    reading.record_reading("r001", 3600, 1.0, 120, ["wavelength"], user_id="u1")
    line = (tmp_path / "r.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["user_id"] == "u1"


def test_list_readings_level_defaults_to_user_vocab(tmp_path, monkeypatch):
    from app.routers import reading as reading_router
    from app.services import users as users_service
    monkeypatch.setattr(users_service.settings, "users_path", str(tmp_path / "u.json"))
    users_service.upsert_profile("u1", {"vocab_size": 4200})
    # level=None 时应落到 u1 的词汇量 4200，与显式传 4200 结果一致
    by_profile = reading_router.list_readings(None, None, "u1")["items"]
    by_explicit = reading_router.list_readings(4200, None, "u1")["items"]
    assert [(i["id"], i["new_word_rate"]) for i in by_profile] == [
        (i["id"], i["new_word_rate"]) for i in by_explicit
    ]


# ---------- 多词短语（MWE）标注 ----------
# 阅读端不再匹配全局短语库（mwe.json），只匹配文章级术语（terms）。
# 全局短语仅用于后台「自动定级」提词参考，避免作者未选定的短语（如 "work well"）被误注。

def test_global_phrase_not_annotated_in_reading():
    # "take over" 是全局短语库里的短语，但阅读端不注（除非作者把它加进 terms）
    ann = reading.annotate("I will take over the company.", 3600)
    html = ann["lines"][0]["html"]
    assert "<ruby>take over" not in html


def test_separable_phrase_not_annotated_in_reading():
    # "take it apart" 是可分离短语，同样不注
    ann = reading.annotate("Take it apart now.", 3600)
    html = ann["lines"][0]["html"]
    assert "<ruby>Take" not in html


def test_stats_counts_phrase_words_individually():
    # 全局短语不再合并成一个词：throw + up 各算一个词
    st = reading.stats("I will throw up now.", 3600)
    assert st["word_count"] == 5


# ---------- 文章级术语（term）标注 ----------

def test_annotate_term_ruby_every_occurrence():
    # 术语每次出现都注 ruby（与生词「仅首次」不同）
    body = "The conservation of momentum law and the conservation of momentum rule."
    ann = reading.annotate(body, 25000, terms={"conservation of momentum": "动量守恒"})
    html = ann["lines"][0]["html"]
    assert html.count("<ruby>conservation of momentum<rt>动量守恒</rt></ruby>") == 2


def test_annotate_term_not_in_vocab_and_not_new():
    ann = reading.annotate(
        "The greenhouse effect warms Earth.", 25000, terms={"greenhouse effect": "温室效应"}
    )
    # 术语不计生词、不进生词表
    assert ann["new_word_count"] == 0
    assert not any("greenhouse" in v["lemma"] for v in ann["vocabulary"])


def test_annotate_term_marks_known_and_term_flag():
    ann = reading.annotate(
        "Study the greenhouse effect now.", 25000, terms={"greenhouse effect": "温室效应"}
    )
    term = next(w for w in ann["lines"][0]["words"] if w.get("term"))
    assert term["w"] == "greenhouse effect"
    assert term["known"] is True
    assert term["gloss"] == "温室效应"


def test_stats_term_counts_words_but_not_new():
    # 术语词数 +1（greenhouse effect 算 1 个单元），生词数 +0
    st = reading.stats(
        "The greenhouse effect warms Earth.", 25000, terms={"greenhouse effect": "温室效应"}
    )
    assert st["word_count"] == 4
    assert st["new_word_count"] == 0


def test_annotate_without_terms_unchanged():
    # 不传 terms 时行为与旧版一致（greenhouse 走逐词判定）
    ann = reading.annotate("The greenhouse effect warms Earth.", 25000)
    assert not any(w.get("term") for w in ann["lines"][0]["words"])


# ---------- 旧存冗长释义归一（行内 ruby 只显示单一义） ----------

def test_annotate_single_word_gloss_normalized_to_short():
    # 文章 glosses 旧存「词性前缀+多义项」时，行内 ruby 也应归一为短义
    ann = reading.annotate(
        "The ground is wet.", 100,
        glosses={"ground": "n. 土地，战场，场地；a. 土地的，地面上的"},
    )
    html = ann["lines"][0]["html"]
    assert "<rt>土地</rt>" in html
    assert "战场" not in html


def test_annotate_term_gloss_normalized_to_short():
    # 文章 terms 旧存带词性前缀的释义，行内 ruby 归一为短义
    ann = reading.annotate(
        "Time differences matter.", 25000, terms={"time differences": "n. 时差"}
    )
    term = next(w for w in ann["lines"][0]["words"] if w.get("term"))
    assert term["gloss"] == "时差"


def test_annotate_hand_edited_short_gloss_preserved():
    # 人工改过的干净短义（含括号/省略号）不被短义归一破坏
    ann = reading.annotate(
        "The orbit decays.", 100, glosses={"orbit": "环绕…运行"}
    )
    html = ann["lines"][0]["html"]
    assert "<rt>环绕…运行</rt>" in html


def test_build_glosses_excludes_multiword_phrases():
    # 多词短语只进 multiword/terms，不混入 glosses（避免带空格的多词键）
    g = reading.build_glosses("I will take over the company.", 3600)
    assert "take over" not in g
    assert all(" " not in k for k in g)


# ---------- 斜体强调 <em>（古腾堡 _text_ 导入转换而来） ----------

def test_annotate_em_passes_through_to_html():
    """<em> 在 ruby html 里原样保留（v-html 渲染斜体），不被转义、不拆碎。"""
    r = reading.annotate('"<em>You</em> want to tell me," she said.', level=3600)
    line = r["lines"][0]
    assert '"<em>You</em> want to tell me," she said.' == line["html"]


def test_annotate_em_words_stay_clean():
    """words 不带任何标记（供逐词点击 + 前端 TTS 拼文本），词上打 em 标志。"""
    r = reading.annotate('"<em>You</em> want to tell me," she said.', level=3600)
    line = r["lines"][0]
    joined = "".join(w["w"] for w in line["words"])
    assert '"You want to tell me," she said.' == joined
    assert "\x01" not in joined and "\x02" not in joined
    you = next(w for w in line["words"] if w["w"] == "You")
    assert you.get("em") is True
    want = next(w for w in line["words"] if w["w"] == "want")
    assert not want.get("em")


def test_annotate_em_adjacent_punct_tokens():
    """掩码与相邻标点合并成一个 token（如 '\x02,' / '"\x01'）也能正确还原。"""
    r = reading.annotate("He called <em>her</em>, loudly.", level=3600)
    line = r["lines"][0]
    assert "He called <em>her</em>, loudly." == line["html"]
    joined = "".join(w["w"] for w in line["words"])
    assert "He called her, loudly." == joined


def test_annotate_em_does_not_pollute_word_count():
    """<em> 标签不是词：不计词数、不进生词表。"""
    r = reading.annotate("The <em>quaint</em> attic was dim.", level=100)
    assert r["word_count"] == 5
    assert "em" not in [v["lemma"] for v in r["vocabulary"]]


def test_annotate_sentence_split_inside_em():
    """句点在 <em> 内也要切句；切点上的闭合标签被丢弃（浏览器自动补全）。"""
    r = reading.annotate("<em>I insist.</em> He left.", level=3600)
    assert len(r["lines"]) == 2
    assert r["lines"][0]["html"].endswith("<em>I insist.")
    assert r["lines"][1]["html"] == "He left."
    # 逐词模式：第一行的词仍带 em 标志
    assert any(w.get("em") for w in r["lines"][0]["words"])


def test_annotate_word_inside_em_still_glossed():
    """<em> 里的生词照常提取与 ruby 注释（标签只是外壳）。"""
    r = reading.annotate("She entered a <em>quaint</em> attic.", level=100)
    line = r["lines"][0]
    assert "<em><ruby>quaint" in line["html"]
    assert "quaint" in [v["lemma"] for v in r["vocabulary"]]

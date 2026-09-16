"""ECDICT SQLite 查询与多词扫描的单元测试（用临时 sqlite 隔离真实 stardict.db）。

覆盖：
  - lookup 点查（大小写不敏感、缺失返回 None）；
  - scan_multiword 最长优先、不重叠；
  - 短语/术语判别（首词 pos 含 v → 短语，否则术语）；
  - 首词大写（专名短语）跳过、[地名] 噪声跳过；
  - db 缺失优雅降级。

运行：uv run --directory apps/api pytest -q
"""
import sqlite3

import pytest

from app.services import ecdict


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    from app.config import settings

    path = tmp_path / "stardict.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE stardict (word TEXT UNIQUE COLLATE NOCASE, phonetic TEXT, "
        "translation TEXT, pos TEXT, tag TEXT, bnc INTEGER, frq INTEGER)"
    )
    rows = [
        ("throw", None, "v. 扔", "v:94", "", 0, 0),
        ("throw up", None, "呕吐", "", "", 0, 0),
        ("greenhouse", None, "n. 温室", "n:100", "", 0, 0),
        ("greenhouse effect", None, "温室效应", "", "", 0, 0),
        ("conservation", None, "n. 保护", "n:100", "", 0, 0),
        ("conservation of momentum", None, "动量守恒", "", "", 0, 0),
        ("United States", None, "美国", "", "[地名]", 0, 0),
        ("a chain", None, "一条链子\n一个链条\n一系列", "", "", 0, 0),
        ("chain", None, "n. 链子", "n:100", "", 0, 0),
        ("the last", None, "最后的；最后一个", "", "", 0, 0),
        ("solar system", None, "太阳系", "", "", 0, 0),
    ]
    con.executemany("INSERT INTO stardict VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    monkeypatch.setattr(settings, "ecdict_path", str(path))
    return path


def test_lookup_found(fake_db):
    r = ecdict.lookup("throw")
    assert r["word"] == "throw"
    assert r["pos"] == "v:94"


def test_lookup_case_insensitive(fake_db):
    r = ecdict.lookup("THROW")
    assert r is not None and r["word"] == "throw"


def test_lookup_missing(fake_db):
    assert ecdict.lookup("zzzzz") is None


def test_scan_discriminates_phrase_vs_term(fake_db):
    # throw up 首词 throw 是动词 → 短语；greenhouse effect 首词是名词 → 术语
    items = ecdict.scan_multiword("They will throw up and study the greenhouse effect.")
    by_text = {m["text"]: m for m in items}
    assert by_text["throw up"]["kind"] == "phrase"
    assert by_text["greenhouse effect"]["kind"] == "term"


def test_scan_longest_first_no_partial(fake_db):
    # "greenhouse effect" 整体命中，不再把 "greenhouse" 单独拆出
    texts = [m["text"] for m in ecdict.scan_multiword("the greenhouse effect warms us.")]
    assert "greenhouse effect" in texts
    assert "greenhouse" not in texts


def test_scan_skips_uppercase_first_word(fake_db):
    # 首词大写视为专名短语（United States），跳过
    items = ecdict.scan_multiword("We visited the United States.")
    assert not any("united" in m["text"] for m in items)


def test_scan_does_not_span_punctuation(fake_db):
    # 非空白标点为硬边界：列表里的 "throw, up" 不是 "throw up"，不得误配
    items = ecdict.scan_multiword("Please throw, up, and away.")
    assert not any(m["text"] == "throw up" for m in items)


def test_scan_skips_function_word_first(fake_db):
    # 冠词/虚词开头（"a chain"/"the last"）不是术语；跳过虚词后实义词仍可匹配
    # （"the solar system" 跳过 the 后命中 "solar system"）。
    items = ecdict.scan_multiword("It is a chain and the last, in the solar system.")
    texts = [m["text"] for m in items]
    assert "a chain" not in texts
    assert "the last" not in texts
    assert "solar system" in texts


def test_missing_db_degrades_gracefully(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ecdict_path", "/nonexistent/stardict.db")
    assert ecdict.lookup("throw") is None
    assert ecdict.scan_multiword("throw up") == []

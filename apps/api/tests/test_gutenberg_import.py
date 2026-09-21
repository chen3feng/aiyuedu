"""古腾堡导入服务测试：slug 生成 + 导入建集 + collections 兼容入口。"""
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import gutenberg, gutenberg_import
from app.services import collections as collections_service


@pytest.fixture
def isolated_collections(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "collections_dir", str(tmp_path))
    monkeypatch.setattr(settings, "collections_index", str(tmp_path / "_index.json"))
    return tmp_path


def _fake_book() -> dict:
    return {
        "title": "The Great Book",
        "author": "Jane Doe",
        "source": "gutenberg://1234",
        "cover_url": "https://example.com/c.jpg",
        "summary": "A nice summary.",
        "text": "...",
    }


def _fake_chapters() -> list:
    return [SimpleNamespace(index=1, title="Chapter One", body="Hello there.")]


# ---------- slug_from_title ----------

def test_slug_strips_articles_and_punctuation() -> None:
    assert gutenberg_import.slug_from_title("The Adventures of Tom!", "fb") == "adventures-of-tom"


def test_slug_falls_back_when_no_words() -> None:
    assert gutenberg_import.slug_from_title("!!!", "gutenberg-9") == "gutenberg-9"


def test_slug_truncates_long_title_to_first_words() -> None:
    title = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    assert gutenberg_import.slug_from_title(title, "fb") == "alpha-beta-gamma-delta-epsilon"


# ---------- import_from_gutenberg ----------

def test_import_creates_collection_and_triggers_analysis(isolated_collections, monkeypatch) -> None:
    monkeypatch.setattr(gutenberg, "fetch_book", lambda bid: _fake_book())
    monkeypatch.setattr(gutenberg, "split_chapters", lambda text: _fake_chapters())
    started: list[str] = []
    monkeypatch.setattr(collections_service, "analyze_collection", lambda cid: started.append(cid))

    coll = gutenberg_import.import_from_gutenberg(1234)

    assert coll["id"] == "great-book"
    assert coll["title"] == "The Great Book"
    assert coll["author"] == "Jane Doe"
    assert coll["source"] == "gutenberg://1234"
    assert coll["total_chapters"] == 1
    assert started == ["great-book"]
    # 文件已落盘，章节 id 带 collection 前缀
    assert collections_service.get_collection("great-book") is not None
    ch = coll["chapters"][0]
    assert ch["id"] == "r-great-book-1"
    assert ch["title"] == "Chapter One"
    assert ch["body"] == "Hello there."


def test_import_duplicate_slug_gets_bookid_suffix(isolated_collections, monkeypatch) -> None:
    monkeypatch.setattr(gutenberg, "fetch_book", lambda bid: _fake_book())
    monkeypatch.setattr(gutenberg, "split_chapters", lambda text: _fake_chapters())
    monkeypatch.setattr(collections_service, "analyze_collection", lambda cid: None)

    first = gutenberg_import.import_from_gutenberg(1234)
    second = gutenberg_import.import_from_gutenberg(1234)

    assert first["id"] == "great-book"
    assert second["id"] == "great-book-1234"


def test_collections_shim_delegates_to_gutenberg_import(monkeypatch) -> None:
    """collections.import_from_gutenberg 保留为兼容入口，实际委托新模块。"""
    calls: list[int] = []
    monkeypatch.setattr(
        gutenberg_import, "import_from_gutenberg",
        lambda bid: calls.append(bid) or {"id": "x"},
    )

    assert collections_service.import_from_gutenberg(7) == {"id": "x"}
    assert calls == [7]

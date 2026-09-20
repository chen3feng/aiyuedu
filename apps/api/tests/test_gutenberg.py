"""古腾堡 service 测试：strip + split_chapters 单元测试（无网络）。

fetch_book 需联网，不在单元测试里跑（手测 / 集成测试覆盖）。
"""
from app.services import gutenberg


def test_strip_gutenberg_boilerplate_basic():
    text = (
        "Project Gutenberg header\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK, TEST ***\n"
        "Prologue line\n"
        "Chapter 1\n"
        "Body of chapter 1.\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK, TEST ***\n"
        "Produced by somebody\n"
    )
    out = gutenberg.strip_gutenberg_boilerplate(text)
    assert "*** START" not in out
    assert "*** END" not in out
    assert "Prologue line" in out
    assert "Chapter 1" in out
    assert "Body of chapter 1." in out
    # 不强求剥 "Produced by..."（很多书没这段）
    # 末尾是 strip 后的内容


def test_split_chapters_chapter_i_style():
    """CHAPTER I. / II. / III. 风格；过短的 II/III 会被合并到 I。"""
    text = (
        "Prologue\n"
        "\n"
        "CHAPTER I.\n"
        "First chapter body line 1.\n"
        "First chapter body line 2.\n"
        "\n"
        "\n"
        "CHAPTER II.\n"
        "Second chapter body.\n"
        "\n"
        "CHAPTER III.\n"
        "Third chapter body.\n"
    )
    chapters = gutenberg.split_chapters(text)
    # chapter II (3 词) 与 I 合并；III 单独留
    assert len(chapters) == 2
    assert chapters[0].title == "CHAPTER I."
    assert "First chapter body line 1." in chapters[0].body
    assert "Second chapter body" in chapters[0].body
    assert chapters[1].title == "CHAPTER III."


def test_split_chapters_handles_bracket_suffixed_toc_heading():
    """古腾堡目录页用 'Chapter I.]' 这种带尾部 ] 的标记 — 必须识别为章节标题。"""
    text = (
        "Heading to Chapter LXI.                                              472\n"
        "\n"
        "The End                                                              476\n"
        "\n"
        "\n"
        "[Illustration: ·PRIDE AND PREJUDICE·\n"
        "\n"
        "\n"
        "\n"
        "Chapter I.]\n"
        "\n"
        "\n"
        "It is a truth universally acknowledged, that a single man in possession\n"
        "of a good fortune must be in want of a wife.\n"
        "\n"
        "\n"
        "CHAPTER II.\n"
        "Mr. Bennet was among the earliest.\n"
        "\n"
        "CHAPTER III.\n"
        "Not all that Mrs. Bennet could ask.\n"
    )
    chapters = gutenberg.split_chapters(text)
    titles = [ch.title for ch in chapters]
    assert "Chapter I.]" in titles, f"Chapter I lost. Got: {titles}"
    # I/II 都很短 → 合并；III 单独
    assert any("CHAPTER III." in t for t in titles)


def test_split_chapters_chapter_arabic_style():
    text = (
        "Chapter 1\n"
        "Body one.\n"
        "\n"
        "Chapter 2\n"
        "Body two.\n"
    )
    chapters = gutenberg.split_chapters(text)
    # 两者都太短，第一对合并：chapter 1 标题保留，body 合并
    assert len(chapters) == 1
    assert chapters[0].title == "Chapter 1"
    assert "Body one." in chapters[0].body
    assert "Body two." in chapters[0].body


def test_split_chapters_numbered_with_separate_title():
    """Gutenberg 常见格式：编号 + 标题分两行（'1' / 'Sara'）"""
    # 每章 900 词（避免被短章合并吞掉）
    long_body = "word " * 900
    text = (
        "A Little Princess\n"
        "\n"
        "1\n"
        "Sara\n"
        f"{long_body}\n"
        "\n"
        "2\n"
        "French Lesson\n"
        f"{long_body}\n"
    )
    chapters = gutenberg.split_chapters(text)
    assert len(chapters) == 2
    assert chapters[0].title == "1 Sara"
    assert chapters[1].title == "2 French Lesson"
    assert long_body.split()[0] in chapters[0].body
    assert long_body.split()[0] in chapters[1].body


def test_split_chapters_drops_preface():
    """前言 / TOC 等非章节前置内容自动丢掉（没标题）。"""
    text = (
        "Some preface text without a chapter heading.\n"
        "More preface content.\n"
        "\n"
        "CHAPTER I.\n"
        "Real chapter body.\n"
    )
    chapters = gutenberg.split_chapters(text)
    assert len(chapters) == 1
    assert chapters[0].title == "CHAPTER I."


def test_split_chapters_strips_table_of_contents():
    """开头有 TOC（≥10 条编号 + 标题）时剥掉。"""
    toc_lines = "\n".join(f" {i+1}.  Chapter {i+1}" for i in range(15))
    long_body = "word " * 900
    text = (
        "Book title\n"
        "\n"
        f"{toc_lines}\n"
        "\n"
        "1\n"
        "Sara\n"
        f"{long_body}\n"
        "\n"
        "2\n"
        "French Lesson\n"
        f"{long_body}\n"
    )
    chapters = gutenberg.split_chapters(text)
    # TOC 剥掉，剩 2 真章节
    assert len(chapters) == 2
    assert "More preface" not in chapters[0].body
    assert long_body.split()[0] in chapters[0].body
    assert long_body.split()[0] in chapters[1].body


def test_split_chapters_short_chapters_merged():
    """过短章节（<800 词）应与下一章合并。"""
    body = "word " * 100  # 100 词，太短
    text = (
        f"CHAPTER I.\n{body}\n"
        "\n"
        f"CHAPTER II.\n{'word ' * 2000}\n"
    )
    chapters = gutenberg.split_chapters(text)
    # 第一章 100 词 < min_words=800 → 与第二章合并
    assert len(chapters) == 1
    assert chapters[0].word_count == 100 + 2000


def test_split_chapters_long_chapter_split_with_cont_marker():
    """过长章节（>max_words）拆成多块，第二块起加（续 N/M）后缀。"""
    body = "word " * 6000  # 6000 词 > max_words=5000
    text = (
        "CHAPTER I.\n"
        f"{body}\n\n\n"
        f"{'word ' * 1000}\n"  # 间隔空段
        "\n\n\n"
        f"{'word ' * 500}\n"
    )
    chapters = gutenberg.split_chapters(text)
    # 至少 2 块
    assert len(chapters) >= 2
    # 第一块保留原标题，后续加「（续 X/Y）」
    assert chapters[0].title == "CHAPTER I."
    if len(chapters) > 1:
        assert "（续" in chapters[1].title


def test_split_chapters_empty_text():
    assert gutenberg.split_chapters("") == []
    assert gutenberg.split_chapters("\n\n\n") == []


def test_split_chapters_preserves_word_count():
    """拆分不丢词。"""
    body1 = "alpha " * 50  # 50 词
    body2 = "beta " * 50
    text = f"CHAPTER I.\n{body1}\n\nCHAPTER II.\n{body2}\n"
    chapters = gutenberg.split_chapters(text)
    total = sum(c.word_count for c in chapters)
    assert total == 100  # 不丢词
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
    """扉页插图块的闭合 ] 挂在 "Chapter I.]" 标题行尾 — 剥插图后标题必须幸存。"""
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
    assert "Chapter I." in titles, f"Chapter I lost. Got: {titles}"
    assert "It is a truth" in chapters[0].body
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


def test_split_chapters_chapter_roman_with_subtitle():
    """「CHAPTER I.」+ 次行副标题（书名式大小写 + 空行与正文相隔）→ 合并为标题。"""
    long_body = "word " * 900
    text = (
        "CHAPTER I.\n"
        "Down the Rabbit-Hole\n"
        "\n"
        "Alice was beginning to get very tired.\n"
        f"{long_body}\n"
        "\n"
        "CHAPTER II.\n"
        "The Pool of Tears\n"
        "\n"
        f"{long_body}\n"
    )
    chapters = gutenberg.split_chapters(text)
    assert len(chapters) == 2
    assert chapters[0].title == "CHAPTER I. Down the Rabbit-Hole"
    assert "Down the Rabbit-Hole" not in chapters[0].body
    assert "Alice was beginning" in chapters[0].body
    assert chapters[1].title == "CHAPTER II. The Pool of Tears"


def test_split_chapters_subtitle_with_question_mark():
    """副标题以问号结尾（Who Stole the Tarts?）仍要合并。"""
    long_body = "word " * 900
    text = f"CHAPTER XI.\nWho Stole the Tarts?\n\n{long_body}\n"
    chapters = gutenberg.split_chapters(text)
    assert chapters[0].title == "CHAPTER XI. Who Stole the Tarts?"


def test_split_chapters_heading_body_not_treated_as_subtitle():
    """P&P 样式：「CHAPTER I.」直接跟正文首句（长句/句号结尾/无空行相隔）→ 不合并。"""
    long_body = "word " * 900
    text = (
        "CHAPTER I.\n"
        "It is a truth universally acknowledged, that a single man in possession "
        "of a good fortune must be in want of a wife.\n"
        f"{long_body}\n"
        "\n"
        "CHAPTER II.\n"
        "Mr. Bennet was among the earliest.\n"
        f"{long_body}\n"
    )
    chapters = gutenberg.split_chapters(text)
    assert len(chapters) == 2
    assert chapters[0].title == "CHAPTER I."
    assert "It is a truth" in chapters[0].body


def test_split_chapters_short_first_sentence_not_subtitle():
    """正文首句很短（Body one.）且带句号：即使后面有空行也不升格为副标题。"""
    long_body = "word " * 900
    text = f"Chapter 1\nBody one.\n\n{long_body}\n"
    chapters = gutenberg.split_chapters(text)
    assert chapters[0].title == "Chapter 1"
    assert "Body one." in chapters[0].body


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

def test_underscores_to_em():
    """古腾堡 _text_ 斜体标记 → <em>；分隔线/跨段不动。"""
    assert gutenberg.underscores_to_em("_her_") == "<em>her</em>"
    assert gutenberg.underscores_to_em("_of a good fortune_") == "<em>of a good fortune</em>"
    # 词首非空白：分隔线与空内容装饰不匹配
    assert gutenberg.underscores_to_em("______") == "______"
    assert gutenberg.underscores_to_em("_ _ _ _") == "_ _ _ _"
    assert gutenberg.underscores_to_em("plain text") == "plain text"
    # 跨软回车（折行截断的斜体）要转
    assert gutenberg.underscores_to_em("_a\nb_") == "<em>a\nb</em>"
    # 跨段落（内容含空行）不转
    assert gutenberg.underscores_to_em("_a\n\nb_") == "_a\n\nb_"


def test_split_chapters_converts_underscore_italics_in_body_only():
    """拆章节后 body 里的 _text_ → <em>；标题保持原样。"""
    long_body = "word " * 900
    text = (
        "CHAPTER I.\n"
        "\"_You_ must know that Mrs. Long says the house is _taken\nby a young man_.\"\n"
        f"{long_body}\n"
    )
    chapters = gutenberg.split_chapters(text)
    assert chapters[0].title == "CHAPTER I."
    b = chapters[0].body
    assert "<em>You</em>" in b
    # 跨软回车的斜体
    assert "<em>taken\nby a young man</em>" in b
    assert "_You_" not in b


# ---------- 插图注记剥离 ----------

def test_strip_illustrations_bare():
    """裸 [Illustration]（无 caption）删除，前后段落保留一个空行。"""
    text = "First para.\n\n[Illustration]\n\nSecond para."
    assert gutenberg.strip_illustrations(text) == "First para.\n\nSecond para."


def test_strip_illustrations_with_nested_brackets():
    """带 caption 且嵌套 [...] 的块整块删（1894 插图版版权注样式）。"""
    text = (
        'Before.\n\n[Illustration:\n\n“He came down to see the place”\n\n'
        '[_Copyright 1894 by George Allen._]]\n\nAfter.'
    )
    assert gutenberg.strip_illustrations(text) == "Before.\n\nAfter."


def test_strip_illustrations_crlf_and_multiblock():
    """CRLF 行尾 + 连续多块都能删净。"""
    text = "A.\r\n\r\n[Illustration]\r\n\r\n[Illustration: cap]\r\n\r\nB."
    assert gutenberg.strip_illustrations(text) == "A.\r\n\r\nB."


def test_strip_illustrations_unclosed_left_untouched():
    """畸形未闭合块不动（宁留勿删），后面正常块照删。"""
    text = "Keep [Illustration: broken\n\nand [Illustration] gone.\n"
    out = gutenberg.strip_illustrations(text)
    assert "[Illustration: broken" in out
    assert "[Illustration]" not in out


def test_strip_illustrations_keeps_other_brackets():
    """非插图方括号（如 [sic]）不受影响。"""
    text = "He left [sic] early.\n\n[Illustration]\n\nEnd."
    assert gutenberg.strip_illustrations(text) == "He left [sic] early.\n\nEnd."


def test_split_chapters_strips_illustrations_in_body():
    """导入管线：拆章节时插图注记一并剥离（正文干净）。"""
    long_body = "word " * 900
    text = (
        "CHAPTER I.\n"
        "It is a truth.\n\n"
        "[Illustration:\n\n“Cap”\n\n[_Copyright 1894._]]\n\n"
        "More narrative.\n\n"
        f"{long_body}\n"
    )
    chapters = gutenberg.split_chapters(text)
    assert "[Illustration" not in chapters[0].body
    assert "It is a truth." in chapters[0].body
    assert "More narrative." in chapters[0].body


def test_strip_illustrations_heading_line_survives():
    """闭合 ] 挂在章节标题行尾（扉页样式）：标题幸存，只吞 ]。"""
    text = (
        "[Illustration: ·PRIDE AND PREJUDICE·\n\n\n\n\nChapter I.]\n\n\n"
        "It is a truth."
    )
    out = gutenberg.strip_illustrations(text)
    assert "Chapter I." in out
    assert "[Illustration" not in out
    assert "It is a truth." in out


def test_strip_illustrations_nested_bracket_line_is_caption():
    """闭合行前缀非标题（版权注 [_Copyright …_]）→ 仍是 caption，整块删。"""
    text = "A.\n\n[Illustration:\n\n“quote”\n\n[_Copyright 1894 by George Allen._]]\n\nB."
    assert gutenberg.strip_illustrations(text) == "A.\n\nB."


# ---------- /* … */ 排版指令 / 装饰星标 ----------

def test_unwrap_nind_directives():
    text = "Jane read it aloud.\n\n     /* NIND “My dear friend, */\n\n     “Letter body.”"
    out = gutenberg.unwrap_format_directives(text)
    assert "/* NIND" not in out and "*/" not in out
    # 内层称呼与缩进保留
    assert "     “My dear friend," in out


def test_unwrap_right_and_bare_directives():
    """RIGHT 信头剥关键字留正文；无关键字的裸指令只剥壳。"""
    text = (
        "as you will hear.\n\n"
        '     /* RIGHT “Hunsford, Kent, 15th October. */\n\n'
        "Dear Sir,\n\n"
        '     /* “My dear Sir, */\n\n'
        "     “Letter body.”"
    )
    out = gutenberg.unwrap_format_directives(text)
    assert "/*" not in out and "*/" not in out and "RIGHT" not in out
    assert "     “Hunsford, Kent, 15th October." in out
    assert "     “My dear Sir," in out


def test_unwrap_inline_directive():
    """指令行被并入上一行时，壳与多余空格一起清理，正文保持可读。"""
    text = "as you will hear.”       /* RIGHT “Hunsford, Kent. */ \r\nDear Sir,"
    out = gutenberg.unwrap_format_directives(text)
    assert "/*" not in out
    assert "hear.” “Hunsford, Kent." in out


def test_drop_asterism_three_star_rows():
    """爱丽丝式：连续三段星号行（7/6/7），整组删除只留一个段落分隔。"""
    text = (
        "She finished it off.\r\n\r\n"
        "*      *      *      *      *      *      *\r\n\r\n"
        "    *      *      *      *      *      *\r\n\r\n"
        "*      *      *      *      *      *      *\r\n\r\n"
        "“What a curious feeling!”"
    )
    out = gutenberg.drop_asterism_paragraphs(text)
    assert "*" not in out
    assert out == "She finished it off.\r\n\r\n“What a curious feeling!”"


def test_drop_asterism_single_row():
    """小公主式：单行 "* * *" 删除；非星号正文不动。"""
    text = "Hard up for bread.\r\n\r\n     *    *    *\r\n\r\nSara found comfort."
    out = gutenberg.drop_asterism_paragraphs(text)
    assert "*" not in out
    assert out == "Hard up for bread.\r\n\r\nSara found comfort."


def test_split_chapters_cleans_asterisks_and_nind():
    """整条流水线：NIND 称呼还原、星标段消失，且章节正常切出。"""
    text = (
        "CHAPTER I.\r\n\r\n"
        "Jane read it aloud.\r\n\r\n"
        "     /* NIND “My dear friend, */\r\n\r\n"
        "She finished it off.\r\n\r\n"
        "*      *      *\r\n\r\n"
        "“What a curious feeling!”\r\n\r\n"
        "CHAPTER II.\r\n\r\n" + "Next chapter body. " * 200
    )
    chapters = gutenberg.split_chapters(text)
    body = chapters[0].body
    assert "NIND" not in body and "*" not in body
    assert "“My dear friend," in body

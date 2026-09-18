"""写作题库（起步 8 题；后续可后台管理 + 难度分级）。

每个 prompt 包含：
- key: 机器标识
- title_zh / title_en: 双语标题
- body_zh: 题目要求（学生看到的中文描述）
- target_words: 目标字数（中学生常见 80-150 词）

复用说明：MVP 阶段写死在代码里即可，规模起来后再做后台管理。
"""
from typing import TypedDict


class Prompt(TypedDict):
    key: str
    title_zh: str
    title_en: str
    body_zh: str
    target_words: int


_PROMPTS: list[Prompt] = [
    {
        "key": "autumn-fields",
        "title_zh": "秋日田野",
        "title_en": "Autumn Fields",
        "body_zh": "用英语写一段秋日田野的景色描写。80-150 词。",
        "target_words": 120,
    },
    {
        "key": "my-favorite-hobby",
        "title_zh": "我最喜欢的爱好",
        "title_en": "My Favorite Hobby",
        "body_zh": "介绍你最喜欢的一项爱好（运动 / 画画 / 音乐 / 读书 / …），说明为什么喜欢以及它给你带来什么。80-150 词。",
        "target_words": 120,
    },
    {
        "key": "my-best-friend",
        "title_zh": "我最好的朋友",
        "title_en": "My Best Friend",
        "body_zh": "介绍你最好的朋友：他/她是什么样的人，你们一起做过什么，为什么喜欢他/她。80-150 词。",
        "target_words": 120,
    },
    {
        "key": "a-memorable-trip",
        "title_zh": "一次难忘的旅行",
        "title_en": "A Memorable Trip",
        "body_zh": "描述一次让你印象深刻的旅行：你去了哪里、做了什么、最难忘的是什么。80-150 词。",
        "target_words": 120,
    },
    {
        "key": "my-dream-job",
        "title_zh": "我梦想的职业",
        "title_en": "My Dream Job",
        "body_zh": "描述你未来想从事的职业：是什么、为什么想做、需要哪些准备。80-150 词。",
        "target_words": 120,
    },
    {
        "key": "weekend-story",
        "title_zh": "上周末发生的事",
        "title_en": "Last Weekend Story",
        "body_zh": "用过去式写一段上周末发生的事：去了哪里、见了谁、做了什么、感觉如何。80-150 词。",
        "target_words": 120,
    },
    {
        "key": "my-classroom",
        "title_zh": "我的教室",
        "title_en": "My Classroom",
        "body_zh": "描述你的教室：座位、同学、老师、墙上有什么、最喜欢教室里的什么。80-150 词。",
        "target_words": 120,
    },
    {
        "key": "if-i-had-a-superpower",
        "title_zh": "如果我有超能力",
        "title_en": "If I Had a Superpower",
        "body_zh": "如果你拥有一种超能力（飞 / 隐身 / 时间旅行 / …），你会选什么？你会用它做什么？80-150 词。",
        "target_words": 120,
    },
]


def list_prompts() -> list[Prompt]:
    return [dict(p) for p in _PROMPTS]


def get_prompt(key: str) -> Prompt | None:
    for p in _PROMPTS:
        if p["key"] == key:
            return dict(p)
    return None
"""一次性迁移：把 data/readings/readings.json 的孤儿短文按主题并入 4 本主题作品集。

迁移后：
- readings.json 清空（[]）
- 新增 4 个 collection：science-stories / history-stories / sports-stories /
  adventure-stories（在阅读列表「全部」及各自主题 tab 中出现）
- 每篇短文成为一章，保留原 id（r001…）与全部字段
  （body/glosses/full_glosses/headwords/terms/quizzes/skip/title_zh…），
  用户阅读记录与生词本引用不受影响

用法：
  uv run --directory apps/api python scripts/migrate_orphans_to_anthologies.py [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import collections, reading

# 主题 → 作品集元数据；intro 中 {n} 为实际篇数
TOPIC_META: dict[str, dict] = {
    "science": {
        "id": "science-stories",
        "title": "Science Stories",
        "title_zh": "科学故事集",
        "intro_zh": "{n} 篇科普短文，覆盖太空探索、能源、数学与技术、自然与生命等主题。",
        "intro_en": "{n} short science readings on space, energy, mathematics, "
                    "technology, nature and life.",
    },
    "history": {
        "id": "history-stories",
        "title": "History Stories",
        "title_zh": "历史故事集",
        "intro_zh": "{n} 篇历史短文，讲述中国与世界历史上的人物与事件。",
        "intro_en": "{n} short history readings about people and events in "
                    "China and the world.",
    },
    "sports": {
        "id": "sports-stories",
        "title": "Sports Stories",
        "title_zh": "体育故事集",
        "intro_zh": "{n} 篇体育主题短文，从足球赛场到奥林匹克。",
        "intro_en": "{n} short sports readings, from the football pitch to "
                    "the Olympic Games.",
    },
    "adventure": {
        "id": "adventure-stories",
        "title": "Adventure Stories",
        "title_zh": "冒险与文学故事集",
        "intro_zh": "{n} 篇冒险与文学主题短文，包括科幻、探案与武侠故事。",
        "intro_en": "{n} short adventure and literature readings: science "
                    "fiction, detective stories and wuxia tales.",
    },
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--force", action="store_true",
        help="目标作品集已存在时先删除再重建",
    )
    args = ap.parse_args()

    items = reading._load_readings()
    if not items:
        print("readings.json 已空，无需迁移")
        return

    grouped: dict[str, list] = {t: [] for t in TOPIC_META}
    for r in items:
        rtopics = r.get("topics") or ([r["topic"]] if r.get("topic") else [])
        # 本脚本只处理「单主题且属于固定四主题」的短文，异常项直接停下让人看
        if len(rtopics) != 1 or rtopics[0] not in grouped:
            raise SystemExit(f"{r['id']} 主题异常: {rtopics}")
        grouped[rtopics[0]].append(r)

    for topic, meta in TOPIC_META.items():
        cid = meta["id"]
        if collections.get_collection(cid) is not None:
            if not args.force:
                raise SystemExit(f"collection 已存在: {cid}（如需重建加 --force）")
            collections.delete_collection(cid)

        members = grouped[topic]
        chapters = []
        for i, r in enumerate(members, start=1):
            ch = dict(r)
            ch["index"] = i  # 章内序号从 1 起；id 等原字段全部保留
            chapters.append(ch)

        n = len(members)
        collections.create_collection({
            "id": meta["id"],
            "title": meta["title"],
            "title_zh": meta["title_zh"],
            "intro_zh": meta["intro_zh"].format(n=n),
            "intro_en": meta["intro_en"].format(n=n),
            "topics": [topic],
            "chapters": chapters,
        })
        print(f"{cid}: {n} 章")

    reading._save_readings([])
    print("readings.json 已清空，迁移完成")


if __name__ == "__main__":
    main()

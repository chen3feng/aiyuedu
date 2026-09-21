"""全本级批量任务：多章并发 AI 释义、短语回填、全书词汇表对齐。

从 services/collections.py 拆出（后者只管存储 / CRUD / 章节编辑）。
与 chapter_ai 一样，锁 / 落盘 / 读取原语在函数体内从 collections 延迟导入，
保证批量任务与 CRUD 共用同一把 _lock，同时规避循环导入。
"""
from __future__ import annotations

import threading

from . import chapter_ai


def analyze_collection(collection_id: str) -> dict | None:
    """对全本所有未 done 的章节并发跑 AI（在后台线程里调用）。

    返回启动摘要：{"scheduled": [chapter_indices], "threads": [...]}
    collection 不存在返回 None。返回的 threads 列表供调用方 join（测试 / 重启场景）。
    """
    from .collections import _lock, _persist_locked, get_collection

    coll = get_collection(collection_id)
    if coll is None:
        return None
    scheduled: list[int] = []
    for ch in coll["chapters"]:
        if ch.get("ai_status") != "done":
            scheduled.append(ch["index"])
    if not scheduled:
        return {"scheduled": [], "collection": coll, "threads": []}

    def _run(idx: int) -> None:
        try:
            chapter_ai.analyze_chapter(collection_id, idx, force=False)
        except Exception:
            # 标记失败，不让线程死循环（同样原子读改写）
            with _lock:
                cur = get_collection(collection_id)
                if cur is None:
                    return
                c = next(
                    (c for c in cur.get("chapters") or [] if c.get("index") == idx),
                    None,
                )
                if c is not None:
                    c["ai_status"] = "error"
                    c["ai_reason"] = "后台线程异常"
                    _persist_locked(cur)

    threads = []
    for idx in scheduled:
        t = threading.Thread(target=_run, args=(idx,), daemon=True)
        t.start()
        threads.append(t)
    return {"scheduled": scheduled, "collection": coll, "threads": threads}


def backfill_terms(collection_id: str, *, only_empty: bool = True) -> dict | None:
    """为已完成章节并发补短语：只写 chapter.terms，不动 glosses / ai_status。

    用于导入时短语功能尚未上线、全本 done 后需要回填的场景（force 重跑会
    覆盖手工 gloss 释义，故另走此路径）。only_empty=True 时只补 terms 为空的章节。
    返回 {"scheduled", "threads"}；collection 不存在返回 None。
    """
    from .collections import _lock, _persist_locked, get_collection

    def _find(coll: dict, idx: int) -> dict | None:
        return next(
            (c for c in coll.get("chapters") or [] if c.get("index") == idx),
            None,
        )

    with _lock:
        coll = get_collection(collection_id)
        if coll is None:
            return None
        scheduled = [
            c["index"]
            for c in coll.get("chapters") or []
            if c.get("ai_status") == "done"
            and (not only_empty or not (c.get("terms") or {}))
        ]
    if not scheduled:
        return {"scheduled": [], "threads": []}

    def _run(idx: int) -> None:
        # 读 body（持锁快照）→ AI 不持锁 → 合并写回（原子）
        with _lock:
            cur = get_collection(collection_id)
            if cur is None:
                return
            ch = _find(cur, idx)
            if ch is None:
                return
            body = ch.get("body") or ""
            level = ch.get("target_level") or 3000
        r = chapter_ai.ai_gloss_terms(body, level)
        if not r["terms"]:
            return
        with _lock:
            cur = get_collection(collection_id)
            if cur is None:
                return
            ch = _find(cur, idx)
            if ch is None:
                return
            merged = dict(ch.get("terms") or {})
            merged.update(r["terms"])
            ch["terms"] = merged
            _persist_locked(cur)

    threads = []
    for idx in scheduled:
        t = threading.Thread(target=_run, args=(idx,), daemon=True)
        t.start()
        threads.append(t)
    return {"scheduled": scheduled, "threads": threads}


def reconcile_collection(collection_id: str) -> dict | None:
    """对齐全书词汇表：扫描所有 chapter.glosses，写入 collection.glossary + polysemy。

    规则：
    - 同一词所有章节 gloss 一致 → glossary[lemma] = gloss；polysemy 不收录
    - 同一词不同章节 gloss 不同 → glossary[lemma] = 出现次数最多的 gloss；
      polysemy[lemma][gloss] = [章节 index 列表]
    """
    from .collections import _lock, _persist_locked, get_collection

    coll = get_collection(collection_id)
    if coll is None:
        return None

    # lemma → gloss → [chapter_index]
    bucket: dict[str, dict[str, list[int]]] = {}
    for ch in coll["chapters"]:
        for lemma, gloss in (ch.get("glosses") or {}).items():
            if not lemma or not gloss:
                continue
            bucket.setdefault(lemma, {}).setdefault(gloss, []).append(ch["index"])

    glossary: dict[str, str] = {}
    polysemy: dict[str, dict[str, list[int]]] = {}
    for lemma, glosses in bucket.items():
        if len(glosses) == 1:
            glossary[lemma] = next(iter(glosses.keys()))
        else:
            polysemy[lemma] = {g: sorted(chs) for g, chs in glosses.items()}
            # canonical = 出现章节最多的 gloss
            canonical = max(glosses.items(), key=lambda kv: len(kv[1]))[0]
            glossary[lemma] = canonical

    # 写回放锁内：避免与并发 analyze_chapter 互相覆盖
    with _lock:
        cur = get_collection(collection_id)
        if cur is None:
            return None
        cur["glossary"] = glossary
        cur["polysemy"] = polysemy
        _persist_locked(cur)
        return cur

"""作品集 / 书籍服务：每个 collection 一个 JSON 文件（含 metadata + glossary + chapters）。

存储：
- data/collections/<id>.json — 单本书完整数据
- data/collections/_index.json — 轻量列表（首页用）
- chapters 数组嵌在 collection 文件里，不外置到 readings.json
  （这样一本 = 一个文件，git diff 自包含、导出/共享 = 单文件）

API 不暴露 chapter 子概念，统一以 reading 视图呈现
（前端看到的 reading 实体带 collection_id / chapter_index / chapter_title）。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from . import ai
from ..config import settings

_lock = threading.Lock()


def _collection_path(id: str) -> Path:
    """单本 collection 文件路径：data/collections/<id>.json"""
    # 防路径穿越：只允许字母数字 + 短横线
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", id):
        raise ValueError(f"collection id 非法（仅小写字母数字 + 短横线）: {id}")
    return Path(settings.collections_dir) / f"{id}.json"


# ---------- 列表 / 单本 ----------

def list_collections() -> list[dict]:
    """所有 collection 的轻量列表（基于 _index.json；缺则现扫）。

    索引里的条目若对应文件已删，自动剔除并重写索引，避免指向死文件。
    """
    idx_path = Path(settings.collections_index)
    if idx_path.exists():
        try:
            raw = json.loads(idx_path.read_text(encoding="utf-8")) or []
        except (json.JSONDecodeError, OSError):
            raw = None
        if raw is not None:
            d = Path(settings.collections_dir)
            live = [e for e in raw if (d / f"{e.get('id', '')}.json").exists()]
            if len(live) != len(raw):
                with _lock:
                    _write_index_atomic(live)
            return live
    # 兜底：扫目录
    return _scan_list()


def _scan_list() -> list[dict]:
    """扫 data/collections/*.json 重建轻量列表（不读 chapters 内容，只读元数据）。"""
    items: list[dict] = []
    d = Path(settings.collections_dir)
    if not d.exists():
        return items
    for p in sorted(d.glob("*.json")):
        if p.name == "_index.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        items.append({
            "id": data.get("id", p.stem),
            "title": data.get("title", ""),
            "title_zh": data.get("title_zh", ""),
            "author": data.get("author", ""),
            "cover_url": data.get("cover_url", ""),
            "total_chapters": len(data.get("chapters") or []),
            "source": data.get("source", ""),
            "glossary_size": len(data.get("glossary") or {}),
            "created_at": data.get("created_at", 0),
        })
    return items


def get_collection(id: str) -> dict | None:
    """读完整 collection（含 chapters + glossary + polysemy）；不存在返 None。"""
    p = _collection_path(id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def get_chapter(collection_id: str, chapter_index: int) -> tuple[dict, dict] | None:
    """返回 (collection, chapter) 或 None。index 从 1 开始。"""
    coll = get_collection(collection_id)
    if coll is None:
        return None
    for ch in coll.get("chapters") or []:
        if ch.get("index") == chapter_index:
            return coll, ch
    return None


def get_chapter_for_reading(reading_id: str) -> tuple[dict, dict] | None:
    """按 reading_id 找章节（扫所有 collection）。找到返回 (collection, chapter)。"""
    d = Path(settings.collections_dir)
    if not d.exists():
        return None
    for p in sorted(d.glob("*.json")):
        if p.name == "_index.json":
            continue
        try:
            coll = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for ch in coll.get("chapters") or []:
            if ch.get("id") == reading_id:
                return coll, ch
    return None


# ---------- 写入 ----------

def _write_index_atomic(items: list[dict]) -> None:
    """原子写入 _index.json：临时文件 + os.replace，避免并发 open('w') 撕文件。

    调用方需已持有 _lock（或保证单线程），否则多个并发调用仍可能竞争临时文件名。
    """
    idx = Path(settings.collections_index)
    idx.parent.mkdir(parents=True, exist_ok=True)
    tmp = idx.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, idx)


def _persist(collection: dict) -> None:
    """单文件落盘 + 原子更新 _index.json（持锁版本，外部调用入口）。"""
    with _lock:
        _persist_locked(collection)


def _persist_locked(collection: dict) -> None:
    """_persist 的无锁版本：调用方必须已持有 _lock。

    用于「读最新 → 改 → 落盘」需要原子的场景（analyze_chapter 并发写回）：
    只锁写不锁读的话，并发线程会用旧快照覆盖别人刚写的状态。
    """
    d = Path(settings.collections_dir)
    d.mkdir(parents=True, exist_ok=True)
    cid = collection["id"]
    path = _collection_path(cid)
    path.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_index_atomic(_scan_list())


def create_collection(data: dict) -> dict:
    """新建 collection。data 需含 id, title；其他字段可选。"""
    cid = (data.get("id") or "").strip()
    if not cid:
        raise ValueError("collection id 不能为空")
    # 默认自动生成短 id
    if cid == "_auto":
        cid = "c-" + uuid.uuid4().hex[:8]
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title 不能为空")
    collection = {
        "id": cid,
        "title": title,
        "title_zh": (data.get("title_zh") or "").strip(),
        "author": (data.get("author") or "").strip(),
        "source": (data.get("source") or "").strip(),
        "total_chapters": len(data.get("chapters") or []),
        "cover_url": (data.get("cover_url") or "").strip(),
        "intro_zh": (data.get("intro_zh") or "").strip(),
        "intro_en": (data.get("intro_en") or "").strip(),
        "created_at": round(time.time(), 3),
        "glossary": dict(data.get("glossary") or {}),
        "polysemy": dict(data.get("polysemy") or {}),
        "chapters": list(data.get("chapters") or []),
    }
    # 查重 + 落盘放同一锁段：否则两个并发 create 同 id 都能通过检查
    with _lock:
        if get_collection(cid) is not None:
            raise ValueError(f"collection 已存在: {cid}")
        _persist_locked(collection)
    return collection


def update_collection(id: str, data: dict) -> dict | None:
    """改字段（metadata + glossary + polysemy + chapters）。"""
    # 读 → 改 → 落盘整个放锁内：并发 update 不互相覆盖
    with _lock:
        cur = get_collection(id)
        if cur is None:
            return None
        for k in ("title", "title_zh", "author", "source", "cover_url", "intro_zh", "intro_en"):
            if k in data:
                cur[k] = (data.get(k) or "").strip()
        for k in ("glossary", "polysemy"):
            if k in data and data[k] is not None:
                cur[k] = dict(data[k])
        if "chapters" in data and data["chapters"] is not None:
            cur["chapters"] = list(data["chapters"])
            cur["total_chapters"] = len(cur["chapters"])
        _persist_locked(cur)
        return cur


def delete_collection(id: str) -> bool:
    p = _collection_path(id)
    with _lock:
        if not p.exists():
            return False
        p.unlink()
        _write_index_atomic(_scan_list())
    return True


# ---------- 古腾堡导入 ----------

def _slug_from_title(title: str, fallback: str) -> str:
    """从英文书名生成 collection id（限长 + 去前缀噪音）。"""
    # 去掉常见前缀（The / A / An）
    s = re.sub(r"^(the|a|an)\s+", "", (title or "").lower(), flags=re.IGNORECASE)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    # 限长 40 字符，按词边界截断
    if len(s) > 40:
        s = "-".join(s.split("-")[:5])
    return s or fallback


def import_from_gutenberg(book_id: int) -> dict:
    """从古腾堡拉取 + 拆章节 → 创建 collection 文件。

    不做 AI 标注（词汇分析留给后台「重跑 AI 分析」按钮）。

    返回完整 collection dict。失败抛 RuntimeError。
    """
    # 避免循环引用
    from . import gutenberg

    data = gutenberg.fetch_book(book_id)
    chapters = gutenberg.split_chapters(data["text"])

    cid = _slug_from_title(data["title"], f"gutenberg-{book_id}")
    # 已存在则加后缀
    if get_collection(cid) is not None:
        cid = f"{cid}-{book_id}"

    chapter_dicts = []
    for ch in chapters:
        cid_ch = f"r-{cid}-{ch.index}"
        chapter_dicts.append({
            "index": ch.index,
            "id": cid_ch,
            "title": ch.title,
            "title_zh": "",  # 待后台 AI 补
            "body": ch.body,
            "target_level": 3000,  # 默认初中级
            "glosses": {},
            "terms": {},
            "skip": [],
            "quizzes": [],
        })

    collection = {
        "id": cid,
        "title": data["title"],
        "title_zh": "",  # 待后台 AI 补
        "author": data["author"],
        "source": data["source"],
        "total_chapters": len(chapter_dicts),
        "cover_url": data.get("cover_url") or "",
        "intro_zh": "",  # 待后台 AI 补
        "intro_en": data.get("summary") or "",
        "created_at": round(time.time(), 3),
        "glossary": {},
        "polysemy": {},
        "ai_status": "pending",  # pending / analyzing / done / error
        "ai_reason": "",
        "chapters": chapter_dicts,
    }
    # 自动启动全本 AI 释义（后台线程）：导入即可用，学生打开章节能看到生词
    _persist(collection)
    analyze_collection(cid)
    return collection


# ---------- 章节 AI 释义（提取生词 + 跨章一致性） ----------

import re as _re_html
_HTML_TAG_RE = _re_html.compile(r"<[^>]+>")


def update_chapter(collection_id: str, chapter_index: int, data: dict) -> dict | None:
    """编辑单章：title / title_zh / body / target_level（只更新传入的字段）。

    body 实际变更时把 ai_status 重置为 pending（glosses 已过期，提示重跑 AI；
    词条保留，重跑 force=True 会覆盖）。返回更新后的 chapter；不存在返 None。
    读改写全程持锁，与并发 AI 写回互不覆盖。
    """

    def _find(coll: dict) -> dict | None:
        return next(
            (c for c in coll.get("chapters") or [] if c.get("index") == chapter_index),
            None,
        )

    with _lock:
        cur = get_collection(collection_id)
        if cur is None:
            return None
        ch = _find(cur)
        if ch is None:
            return None
        body_changed = False
        if "title" in data and data["title"] is not None:
            ch["title"] = str(data["title"]).strip()
        if "title_zh" in data and data["title_zh"] is not None:
            ch["title_zh"] = str(data["title_zh"]).strip()
        if "body" in data and data["body"] is not None:
            new_body = str(data["body"])
            body_changed = new_body != ch.get("body")
            ch["body"] = new_body
        if "target_level" in data and data["target_level"] is not None:
            ch["target_level"] = int(data["target_level"])
        if body_changed:
            ch["ai_status"] = "pending"
            ch["ai_reason"] = "正文已编辑，词条可能过期，建议重跑 AI"
        _persist_locked(cur)
        return ch


def _extract_chapter_vocab(body: str, level: int) -> list[dict]:
    """提取章节候选生词（按 level 过滤 + 每词首次出现句）。

    返回 [{"lemma": str, "context": str, "dict_gloss": str}, ...]
    """
    from . import reading  # 避免循环导入

    r = reading.annotate(body, level=level)
    # 收集每词首次出现的句子（用纯文本，去 markup）
    first_sent: dict[str, str] = {}
    for line in r["lines"]:
        text = _HTML_TAG_RE.sub("", line["html"]).strip()
        if not text:
            continue
        for w in line["words"]:
            lemma = w.get("lemma")
            if lemma and lemma not in first_sent:
                first_sent[lemma] = text

    items: list[dict] = []
    seen: set[str] = set()
    for v in r["vocabulary"]:
        lemma = v["lemma"]
        if lemma in seen or not lemma:
            continue
        seen.add(lemma)
        items.append({
            "lemma": lemma,
            "context": first_sent.get(lemma, ""),
            "dict_gloss": v.get("gloss") or "",
        })
    return items


def _ai_gloss_vocab(items: list[dict]) -> dict:
    """调用默认 AI 为生词列表生成语境义。

    输入: [{"lemma", "context", "dict_gloss"}, ...]
    返回: {"glosses": {lemma: gloss}, "ai_used", "reason", "raw"}
    """
    if not items:
        return {"glosses": {}, "ai_used": False, "reason": "无生词", "raw": ""}

    lines = [
        f"- {it['lemma']}（词典义：{it['dict_gloss'] or '无'}）\n  首次出现句：{it['context']}"
        for it in items
    ]
    prompt = (
        "你是英语分级阅读的编辑，为初中英语学习者做生词的中文释义。\n"
        "下面是某书某一章里的生词清单（附词典义 + 首次出现的句子），"
        "请结合上下文语境，为每个词给出 1~6 个字的中文释义，"
        "只取该句里最贴切的含义（多义词务必按句意取舍，不要列出全部义项）。\n\n"
        "【生词清单】\n" + "\n".join(lines) + "\n\n"
        "只输出一个 JSON 对象，键为词条文本，值为中文释义。"
        "不要输出 JSON 以外的任何内容（不要 markdown 围栏）。"
    )
    ai_map: dict = {}
    ai_used = False
    reason: str | None = None
    raw = ""
    try:
        content = ai.chat([{"role": "user", "content": prompt}], temperature=0.2)
    except RuntimeError as e:
        content = ""
        reason = f"AI 调用失败：{e}"
    raw = content[:200]
    if content:
        snippet = content[:120].replace("\n", " ")
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            # 容错：尝试剥离 markdown 围栏
            stripped = content.strip()
            if stripped.startswith("```"):
                stripped = _re_html.sub(r"^```\w*\n?", "", stripped)
                stripped = stripped.rstrip("`").rstrip()
            try:
                parsed = json.loads(stripped)
            except (json.JSONDecodeError, TypeError):
                parsed = None
        if isinstance(parsed, dict) and parsed:
            ai_map = parsed
            ai_used = True
        else:
            reason = f"AI 响应无法解析为 JSON（开头: {snippet!r}）"
    elif reason is None:
        reason = "AI 返回空内容"

    glosses: dict[str, str] = {}
    for it in items:
        lemma = it["lemma"]
        ai_g = str(ai_map.get(lemma) or "").strip()
        if ai_g:
            glosses[lemma] = ai_g
        elif it["dict_gloss"]:
            glosses[lemma] = it["dict_gloss"]  # AI 没给则词典义兜底
    return {"glosses": glosses, "ai_used": ai_used, "reason": reason, "raw": raw}


def analyze_chapter(
    collection_id: str,
    chapter_index: int,
    *,
    force: bool = False,
) -> dict | None:
    """对单章跑 AI 释义：提取生词 → 调 AI → 写回 chapter.glosses + ai_status。

    返回 {"collection", "chapter", "items_count", "ai_used", "reason", "raw"}；
    collection / 章节不存在返回 None。
    force=True 时即使 ai_status=done 也重跑（用于「重跑 AI 释义」按钮）。

    并发安全：标记 analyzing 与写回结果两段都持 _lock 做「读最新 → 改 → 落盘」。
    若只锁写不锁读，多章并发时后落盘的线程会拿旧快照把别人刚写的状态
    覆盖回去（表现为章节 ai_status 卡在 pending / analyzing）。
    AI 调用不持锁——耗时长，不能阻塞其他章节的写回。
    """

    def _find(coll: dict) -> dict | None:
        return next(
            (c for c in coll.get("chapters") or [] if c.get("index") == chapter_index),
            None,
        )

    # 第一段：标记 analyzing（原子读改写）
    with _lock:
        coll = get_collection(collection_id)
        if coll is None:
            return None
        chapter = _find(coll)
        if chapter is None:
            return None
        level = chapter.get("target_level") or 3000
        body = chapter.get("body") or ""
        chapter["ai_status"] = "analyzing"
        chapter["ai_reason"] = ""
        _persist_locked(coll)

    items = _extract_chapter_vocab(body, level)
    result = _ai_gloss_vocab(items)

    # 第二段：写回结果（重新读最新快照再合并，同样原子）
    with _lock:
        cur = get_collection(collection_id)
        if cur is None:
            return None
        ch = _find(cur)
        if ch is None:
            return None

        if force:
            ch["glosses"] = dict(result["glosses"])
        else:
            merged = dict(ch.get("glosses") or {})
            merged.update(result["glosses"])
            ch["glosses"] = merged
        if result["ai_used"] or not items:
            # AI 成功，或本章没有生词（不算失败，避免「无生词」标红）
            ch["ai_status"] = "done"
            ch["ai_reason"] = "" if result["ai_used"] else (result["reason"] or "")
        else:
            ch["ai_status"] = "error"
            ch["ai_reason"] = result["reason"] or "未知错误"
        _persist_locked(cur)
        return {
            "collection": cur,
            "chapter": ch,
            "items_count": len(items),
            "ai_used": result["ai_used"],
            "reason": result["reason"],
            "raw": result["raw"],
        }


def analyze_collection(collection_id: str) -> dict | None:
    """对全本所有未 done 的章节并发跑 AI（在后台线程里调用）。

    返回启动摘要：{"scheduled": [chapter_indices], "threads": [...]}
    collection 不存在返回 None。返回的 threads 列表供调用方 join（测试 / 重启场景）。
    """
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
            analyze_chapter(collection_id, idx, force=False)
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


def reconcile_collection(collection_id: str) -> dict | None:
    """对齐全书词汇表：扫描所有 chapter.glosses，写入 collection.glossary + polysemy。

    规则：
    - 同一词所有章节 gloss 一致 → glossary[lemma] = gloss；polysemy 不收录
    - 同一词不同章节 gloss 不同 → glossary[lemma] = 出现次数最多的 gloss；
      polysemy[lemma][gloss] = [章节 index 列表]
    """
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


# ---------- reading 视图适配 ----------

def flatten_chapter_to_reading(coll: dict, chapter: dict) -> dict:
    """把嵌在 collection 里的 chapter 转成 reading 视图（带 collection 元数据）。"""
    return {
        "id": chapter["id"],
        "collection_id": coll["id"],
        "chapter_index": chapter.get("index"),
        "chapter_title": chapter.get("title"),
        "title": chapter.get("title") or chapter["id"],
        "title_zh": chapter.get("title_zh") or "",
        "subtitle": "",
        "topics": [],
        "target_level": chapter.get("target_level"),
        "glosses": chapter.get("glosses") or {},
        # collection.glossary 合并展示：chapter 优先
        "collection_glossary": coll.get("glossary") or {},
        "full_glosses": {},
        "headwords": {},
        "terms": chapter.get("terms") or {},
        "skip": chapter.get("skip") or [],
        "body": chapter.get("body") or "",
        "quizzes": chapter.get("quizzes") or [],
        "ai_status": chapter.get("ai_status") or "pending",
        "ai_reason": chapter.get("ai_reason") or "",
        "collection": {
            "id": coll["id"],
            "title": coll.get("title", ""),
            "title_zh": coll.get("title_zh", ""),
            "author": coll.get("author", ""),
            "cover_url": coll.get("cover_url", ""),
            "total_chapters": len(coll.get("chapters") or []),
        },
    }
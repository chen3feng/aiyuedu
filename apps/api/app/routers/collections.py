"""作品集 API：CRUD + 详情（含完整 chapters）+ 古腾堡导入。"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..services import collections

router = APIRouter(prefix="/collections", tags=["collections"])


class CollectionIn(BaseModel):
    id: str = ""
    title: str = ""
    title_zh: str = ""
    author: str = ""
    source: str = ""
    cover_url: str = ""
    intro_zh: str = ""
    intro_en: str = ""
    glossary: dict[str, str] = {}
    polysemy: dict = {}
    chapters: list[dict] = []


class ImportGutenbergIn(BaseModel):
    book_id: int


def _uid(user_id: str | None) -> str:
    return user_id or "anonymous"


@router.get("")
def list_all(_user_id: str | None = Header(None, alias="X-User-Id")):
    """所有 collection 列表（轻量：只元数据 + 章节数 + glossary 大小）。"""
    return {"items": collections.list_collections()}


@router.get("/{collection_id}")
def get(collection_id: str, _user_id: str | None = Header(None, alias="X-User-Id")):
    coll = collections.get_collection(collection_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="作品集不存在")
    return coll


@router.post("")
def create(payload: CollectionIn, _user_id: str | None = Header(None, alias="X-User-Id")):
    try:
        return collections.create_collection(payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/import-gutenberg")
def import_gutenberg(payload: ImportGutenbergIn,
                    _user_id: str | None = Header(None, alias="X-User-Id")):
    """从古腾堡 book_id 拉取 + 拆章节 → 创建 collection 文件。

    失败（网络 / 不存在）抛 502。AI 标注（词汇、标题翻译）后续单章重跑。
    """
    try:
        return collections.import_from_gutenberg(payload.book_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/{collection_id}")
def update(collection_id: str, payload: CollectionIn,
          _user_id: str | None = Header(None, alias="X-User-Id")):
    coll = collections.update_collection(collection_id, payload.model_dump())
    if coll is None:
        raise HTTPException(status_code=404, detail="作品集不存在")
    return coll


@router.delete("/{collection_id}")
def delete(collection_id: str, _user_id: str | None = Header(None, alias="X-User-Id")):
    if not collections.delete_collection(collection_id):
        raise HTTPException(status_code=404, detail="作品集不存在")
    return {"ok": True}


class AnalyzeChapterIn(BaseModel):
    force: bool = False  # True = 即使已完成也重跑（管理员「重跑 AI 释义」按钮）


@router.post("/{collection_id}/chapters/{chapter_index}/analyze")
def analyze_chapter(collection_id: str, chapter_index: int,
                     payload: AnalyzeChapterIn | None = None,
                     _user_id: str | None = Header(None, alias="X-User-Id")):
    """对单章跑 AI 释义：提取生词 → 调 AI → 写回 chapter.glosses + ai_status。

    返回 {"chapter", "items_count", "ai_used", "reason", "raw"}；不存在返回 404。
    """
    force = bool(payload and payload.force)
    result = collections.analyze_chapter(collection_id, chapter_index, force=force)
    if result is None:
        raise HTTPException(status_code=404, detail="作品集或章节不存在")
    return result


@router.post("/{collection_id}/analyze-all")
def analyze_all(collection_id: str,
                _user_id: str | None = Header(None, alias="X-User-Id")):
    """对全本所有未 done 的章节并发跑 AI（后台线程）。

    返回 {"scheduled": [chapter_indices]}；不存在返回 404。
    """
    result = collections.analyze_collection(collection_id)
    if result is None:
        raise HTTPException(status_code=404, detail="作品集不存在")
    return {"scheduled": result["scheduled"]}


@router.post("/{collection_id}/reconcile")
def reconcile(collection_id: str,
              _user_id: str | None = Header(None, alias="X-User-Id")):
    """对齐全书词汇表：扫描所有 chapter.glosses → 写入 collection.glossary + polysemy。

    规则：同词所有章节 gloss 一致 → glossary[lemma]；不同 → polysemy[lemma][gloss]=[ch_indices]。
    """
    coll = collections.reconcile_collection(collection_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="作品集不存在")
    return {"ok": True, "glossary_size": len(coll["glossary"]),
            "polysemy_size": len(coll["polysemy"])}
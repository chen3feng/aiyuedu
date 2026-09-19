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
"""生词本接口：按当前用户隔离。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import current_user_id
from ..services import notebook

router = APIRouter(prefix="/notebook", tags=["notebook"])


class AddIn(BaseModel):
    word: str
    gloss: str = ""
    phonetic: str = ""
    reading_id: str = ""


@router.get("")
def list_items(user_id: str = Depends(current_user_id)):
    return {"items": notebook.list_items(user_id)}


@router.post("")
def add_item(payload: AddIn, user_id: str = Depends(current_user_id)):
    try:
        item = notebook.add_item(
            user_id, payload.word, payload.gloss, payload.phonetic, payload.reading_id
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return item


@router.delete("/{word}")
def remove_item(word: str, user_id: str = Depends(current_user_id)):
    if not notebook.remove_item(user_id, word):
        raise HTTPException(status_code=404, detail="生词不存在")
    return {"ok": True}

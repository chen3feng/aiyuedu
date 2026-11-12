"""写作平台 API：题目列表 + 作文 CRUD + AI 批改触发。

API 契约：
- GET    /writings/prompts               题目列表（不需要 user_id）
- POST   /writings                       提交作文 → AI 批改 → 落盘
- GET    /writings                       列用户自己所有作文（按时间倒序）
- GET    /writings/{essay_id}            取一篇
- DELETE /writings/{essay_id}            删除

登录 token 优先；未登录时用 X-User-Id，缺失则 "anonymous"，与 routers/users.py 一致。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import current_user_id
from ..services import prompts, writing

router = APIRouter(prefix="/writings", tags=["writing"])


def _uid(user_id: str | None) -> str:
    return user_id or "anonymous"


class SubmitIn(BaseModel):
    prompt_key: str | None = None
    original: str = ""
    target_words: int | None = None


@router.get("/prompts")
def list_prompts():
    return {"items": prompts.list_prompts()}


@router.post("")
def submit(payload: SubmitIn, user_id: str = Depends(current_user_id)):
    try:
        return writing.submit_essay(
            _uid(user_id), payload.prompt_key, payload.original, payload.target_words
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("")
def list_my(user_id: str = Depends(current_user_id)):
    return {"items": writing.list_essays(_uid(user_id))}


@router.get("/{essay_id}")
def get(essay_id: str, user_id: str = Depends(current_user_id)):
    essay = writing.get_essay(_uid(user_id), essay_id)
    if essay is None:
        raise HTTPException(status_code=404, detail="作文不存在")
    return essay


@router.delete("/{essay_id}")
def delete(essay_id: str, user_id: str = Depends(current_user_id)):
    if not writing.delete_essay(_uid(user_id), essay_id):
        raise HTTPException(status_code=404, detail="作文不存在")
    return {"ok": True}

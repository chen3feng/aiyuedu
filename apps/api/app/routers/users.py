"""用户档案接口：登录 token 优先，否则按 X-User-Id 识别匿名用户。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import current_user_id
from ..services import topics, users

router = APIRouter(prefix="/users", tags=["users"])


class ProfileIn(BaseModel):
    topic_preferences: list[str] | None = None
    vocab_size: int | None = Field(None, ge=0)


def _uid(user_id: str | None) -> str:
    # 无 header 时落到固定默认用户，便于匿名访问也能读写档案
    return user_id or "anonymous"


@router.get("/me")
def get_me(user_id: str = Depends(current_user_id)):
    uid = _uid(user_id)
    prof = users.get_profile(uid)
    prof["user_id"] = uid
    return prof


@router.put("/me")
def put_me(payload: ProfileIn, user_id: str = Depends(current_user_id)):
    uid = _uid(user_id)
    patch: dict = {}
    if payload.topic_preferences is not None:
        for t in payload.topic_preferences:
            if t not in topics.get_topic_keys():
                raise HTTPException(status_code=422, detail=f"未知主题: {t}")
        patch["topic_preferences"] = payload.topic_preferences
    if payload.vocab_size is not None:
        patch["vocab_size"] = payload.vocab_size
    prof = users.upsert_profile(uid, patch)
    prof["user_id"] = uid
    return prof

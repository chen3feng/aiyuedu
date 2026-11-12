"""FastAPI 依赖：从请求头解析当前用户。

登录用户用 `Authorization: Bearer <token>`；未登录时回退 `X-User-Id`（匿名设备 ID）。
"""
from fastapi import Header, HTTPException

from .services import auth


def current_user_id(
    authorization: str | None = Header(None),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> str:
    """业务接口用：登录优先，否则匿名设备 id，最后 "anonymous"。"""
    return auth.resolve_user_id(authorization, x_user_id)


def current_account(
    authorization: str | None = Header(None),
) -> dict:
    """必须登录的接口用：无有效 token 直接 401。"""
    try:
        return auth.require_account(authorization)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


def bearer_token(
    authorization: str | None = Header(None),
) -> str | None:
    return auth.bearer_token(authorization)

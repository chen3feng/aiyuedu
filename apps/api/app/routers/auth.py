"""账号接口：注册 / 登录 / 退出 / 当前用户 / 改密 / 注销。"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ..deps import current_account
from ..services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str
    password: str
    # 注册前本机匿名学习数据的设备 id；传入则把数据搬到新账号
    device_user_id: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


class DeleteIn(BaseModel):
    password: str


def _public(account: dict) -> dict:
    return {
        "user_id": account["user_id"],
        "username": account.get("username", ""),
        "created_at": account.get("created_at"),
    }


@router.post("/register")
def register(payload: RegisterIn):
    try:
        token, account, imported = auth.register(
            payload.username, payload.password, payload.device_user_id
        )
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"token": token, "user": _public(account), "imported": imported}


@router.post("/login")
def login(payload: LoginIn):
    try:
        token, account = auth.login(payload.username, payload.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"token": token, "user": _public(account)}


@router.post("/logout")
def logout(authorization: str | None = Header(None)):
    auth.logout(auth.bearer_token(authorization))
    return {"ok": True}


@router.get("/me")
def me(account: dict = Depends(current_account)):
    return _public(account)


@router.put("/password")
def change_password(
    payload: PasswordIn,
    authorization: str | None = Header(None),
    account: dict = Depends(current_account),
):
    try:
        auth.change_password(
            account["user_id"],
            payload.old_password,
            payload.new_password,
            keep_token=auth.bearer_token(authorization),
        )
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"ok": True}


@router.delete("/account")
def delete_account(payload: DeleteIn, account: dict = Depends(current_account)):
    try:
        auth.delete_account(account["user_id"], payload.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"ok": True}

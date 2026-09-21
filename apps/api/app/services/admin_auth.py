"""后台管理 HTTP Basic 认证。

admin app（8001）以 0.0.0.0 暴露在局域网，此前所有接口免登录。
现统一要求 Basic 认证：用户名固定 ``admin``，口令取 ``settings.admin_password``
（环境变量 ``ADMIN_PASSWORD``，默认 ``changeme`` 必须覆盖）。

作为 app 级 dependency 挂在 admin_app 上，对全部路由（含静态首页）生效。
"""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ..config import settings

security = HTTPBasic(realm="aiyuedu-admin")

REALM_HEADER = 'Basic realm="aiyuedu-admin"'


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    password = settings.admin_password
    # compare_digest 防时序侧信道；两项分开比再合并，避免短路
    user_ok = secrets.compare_digest(credentials.username.encode("utf-8"), b"admin")
    pw_ok = secrets.compare_digest(credentials.password.encode("utf-8"), password.encode("utf-8"))
    if not (user_ok and pw_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="后台用户名或口令错误",
            headers={"WWW-Authenticate": REALM_HEADER},
        )

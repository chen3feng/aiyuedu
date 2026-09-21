"""后台管理应用：独立端口（8001）运行，HTTP Basic 登录（admin / ADMIN_PASSWORD）。

启动：
  ADMIN_PASSWORD=xxx uv run --directory apps/api uvicorn \
      app.admin_app:admin_app --host 0.0.0.0 --port 8001
"""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import settings
from .routers import admin, collections
from .services.admin_auth import require_admin

STATIC_DIR = Path(__file__).parent / "static" / "admin"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    if settings.admin_password == "changeme":
        logging.getLogger("uvicorn.error").warning(
            "Admin 仍在使用默认口令 changeme——请设置环境变量 ADMIN_PASSWORD 后重启"
        )
    yield


# dependencies 对全部路由生效（静态首页也要先登录）
admin_app = FastAPI(
    title="English Learning Admin",
    dependencies=[Depends(require_admin)],
    lifespan=_lifespan,
)

admin_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

admin_app.include_router(admin.router)

# 作品集路由也以 /api 前缀暴露：admin 前端硬编码 /api 前缀
# （主 app 端口 8000 学生端仍以裸 /collections 调用 — 共享同一 router）
_api_wrapper = APIRouter(prefix="/api", tags=["admin-collections"])
_api_wrapper.include_router(collections.router)
admin_app.include_router(_api_wrapper)


@admin_app.get("/", include_in_schema=False)
def admin_index():
    return FileResponse(str(STATIC_DIR / "index.html"))

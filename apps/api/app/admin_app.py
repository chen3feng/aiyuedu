"""后台管理应用：独立端口（8001）运行，免登录。

启动：uv run --directory apps/api uvicorn app.admin_app:admin_app --host 0.0.0.0 --port 8001
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .routers import admin, collections

STATIC_DIR = Path(__file__).parent / "static" / "admin"

admin_app = FastAPI(title="English Learning Admin")

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

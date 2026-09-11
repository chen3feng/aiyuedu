"""后台管理应用：独立端口（8001）运行，免登录。

启动：uv run --directory apps/api uvicorn app.admin_app:admin_app --host 0.0.0.0 --port 8001
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .routers import admin

STATIC_DIR = Path(__file__).parent / "static" / "admin"

admin_app = FastAPI(title="English Learning Admin")

admin_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

admin_app.include_router(admin.router)


@admin_app.get("/", include_in_schema=False)
def admin_index():
    return FileResponse(str(STATIC_DIR / "index.html"))

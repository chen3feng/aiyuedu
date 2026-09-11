from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import engine
from .routers import reading, tts, users, vocab

app = FastAPI(title=settings.app_name)

# 开发阶段放开跨域（前端 H5 运行在另一端口），上线再收紧白名单
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vocab.router)
app.include_router(reading.router)
app.include_router(tts.router)
app.include_router(users.router)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/db")
def health_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "db": str(exc)}

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import reading, tts, users, vocab, writing, collections

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
app.include_router(writing.router)
app.include_router(collections.router)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}

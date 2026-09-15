"""后台管理 API（挂载于独立 admin app，端口 8001，免登录）。

主题增删 + 文章 CRUD + 自动定级/提取生词预览。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import admin, ai, reading, topics

router = APIRouter(prefix="/api", tags=["admin"])


# ---------- 入参模型 ----------

class QuizOptionIn(BaseModel):
    text: str = ""
    correct: bool = False


class QuizIn(BaseModel):
    type: str = "choice"
    question: str = ""
    options: list[QuizOptionIn] = []
    explanation_zh: str = ""
    explanation_en: str = ""


class ArticleIn(BaseModel):
    title: str = ""
    subtitle: str = ""
    body: str = ""
    topics: list[str] = []
    target_level: int | None = Field(None, ge=0)
    glosses: dict[str, str] = {}
    full_glosses: dict[str, str] = {}
    headwords: dict[str, dict] = {}
    multiword: list[dict] = []
    skip: list[str] = []
    quizzes: list[QuizIn] = []


class TopicIn(BaseModel):
    key: str
    label_zh: str


class AnalyzeIn(BaseModel):
    body: str
    level: int | None = Field(None, ge=0)


class AIProviderIn(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    model: str


class AIProviderUpdateIn(BaseModel):
    new_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class AIDefaultIn(BaseModel):
    name: str


class AIGlossIn(BaseModel):
    body: str
    level: int | None = Field(None, ge=0)


# ---------- 主题 ----------

@router.get("/topics")
def list_topics():
    result = []
    for t in topics.list_topics():
        cnt = sum(1 for r in reading.list_readings() if t["key"] in (r.get("topics") or []))
        result.append({"key": t["key"], "label_zh": t["label_zh"], "article_count": cnt})
    return {"items": result}


@router.post("/topics")
def add_topic(payload: TopicIn):
    try:
        return topics.add_topic(payload.key, payload.label_zh)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/topics/{key}")
def delete_topic(key: str):
    in_use = [r["id"] for r in reading.list_readings() if key in (r.get("topics") or [])]
    if in_use:
        raise HTTPException(status_code=409, detail=f"主题 {key} 正被 {len(in_use)} 篇文章引用，无法删除")
    if not topics.delete_topic(key):
        raise HTTPException(status_code=404, detail="主题不存在")
    return {"ok": True}


# ---------- 文章 ----------

@router.get("/articles")
def list_articles():
    return {"items": admin.list_articles()}


@router.get("/articles/{reading_id}")
def get_article(reading_id: str):
    a = admin.get_article_edit(reading_id)
    if a is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    return a


@router.post("/articles/analyze")
def analyze_article(payload: AnalyzeIn):
    return admin.analyze(payload.body, payload.level)


@router.post("/articles/ai-glosses")
def ai_glosses(payload: AIGlossIn):
    try:
        return admin.ai_glosses(payload.body, payload.level)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/articles")
def create_article(payload: ArticleIn):
    try:
        return admin.create_article(payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.put("/articles/{reading_id}")
def update_article(reading_id: str, payload: ArticleIn):
    try:
        article = admin.update_article(reading_id, payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if article is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    return article


@router.delete("/articles/{reading_id}")
def delete_article(reading_id: str):
    if not admin.delete_article(reading_id):
        raise HTTPException(status_code=404, detail="文章不存在")
    return {"ok": True}


# ---------- AI 提供者 ----------

@router.get("/ai/providers")
def list_ai_providers():
    return {"items": ai.list_providers()}


@router.post("/ai/providers")
def add_ai_provider(payload: AIProviderIn):
    try:
        return ai.add_provider(payload.name, payload.base_url, payload.api_key, payload.model)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.put("/ai/providers/{name}")
def update_ai_provider(name: str, payload: AIProviderUpdateIn):
    try:
        return ai.update_provider(
            name,
            new_name=payload.new_name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model=payload.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/ai/providers/{name}")
def delete_ai_provider(name: str):
    if not ai.delete_provider(name):
        raise HTTPException(status_code=404, detail="提供者不存在")
    return {"ok": True}


@router.get("/ai/default")
def get_ai_default():
    return {"default": ai.get_default()}


@router.put("/ai/default")
def set_ai_default(payload: AIDefaultIn):
    try:
        ai.set_default(payload.name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True}

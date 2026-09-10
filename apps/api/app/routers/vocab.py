from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import vocab

router = APIRouter(prefix="/vocab", tags=["vocab"])


class AnswerIn(BaseModel):
    session_id: str
    choice: int | None = None
    unknown: bool = False


class FinishIn(BaseModel):
    session_id: str


@router.post("/test/start")
def start():
    sid, question, progress = vocab.start_test()
    return {
        "session_id": sid,
        "rules": vocab.RULES,
        "question": question,
        **progress,
    }


@router.post("/test/answer")
def answer(payload: AnswerIn):
    sess = vocab.get_session(payload.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    if sess.finished:
        raise HTTPException(status_code=400, detail="该测评已完成")
    return vocab.submit_answer(sess, payload.choice, payload.unknown)


@router.post("/test/finish")
def finish(payload: FinishIn):
    sess = vocab.get_session(payload.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return {"finished": True, "result": vocab.finish_test(sess)}

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..deps import current_user_id
from ..services import vocab, vocab_eudic, vocab_tests

router = APIRouter(prefix="/vocab", tags=["vocab"])

# 算法开关：classic = 固定分层抽样，eudic = 自适应 Elo/IRT。
_ALGOS = {"classic": vocab, "eudic": vocab_eudic}


class StartIn(BaseModel):
    algo: str | None = None


class AnswerIn(BaseModel):
    session_id: str
    choice: int | None = None
    unknown: bool = False


class FinishIn(BaseModel):
    session_id: str


def _service_and_session(sid: str):
    """按会话 id 找到所属算法模块（两套算法各自维护会话）。"""
    for svc in _ALGOS.values():
        sess = svc.get_session(sid)
        if sess is not None:
            return svc, sess
    return None, None


@router.post("/test/start")
def start(payload: StartIn | None = None, user_id: str = Depends(current_user_id)):
    algo = ((payload.algo if payload else None) or settings.vocab_algo).lower()
    svc = _ALGOS.get(algo)
    if svc is None:
        raise HTTPException(status_code=400, detail=f"未知算法：{algo}")
    sid, question, progress = svc.start_test(user_id)
    return {
        "session_id": sid,
        "algo": algo,
        "rules": svc.RULES,
        "question": question,
        **progress,
    }


@router.post("/test/answer")
def answer(payload: AnswerIn):
    svc, sess = _service_and_session(payload.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    if sess.finished:
        raise HTTPException(status_code=400, detail="该测评已完成")
    return svc.submit_answer(sess, payload.choice, payload.unknown)


@router.post("/test/finish")
def finish(payload: FinishIn):
    svc, sess = _service_and_session(payload.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return {"finished": True, "result": svc.finish_test(sess)}


@router.get("/tests")
def list_tests(user_id: str = Depends(current_user_id)):
    return {"items": vocab_tests.list_tests(user_id)}

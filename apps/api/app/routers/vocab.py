from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..deps import current_user_id
from ..services import vocab, vocab_adaptive2, vocab_cat, vocab_tests
from ..services import vocab_trend

router = APIRouter(prefix="/vocab", tags=["vocab"])

# 算法开关：classic = 固定分层抽样，
# adaptive / adaptive2 = 双参数自适应（θ + α，词汇量按曲线面积）；
# 2026-11f 起 adaptive 也走二维引擎（固定斜率会把平缓曲线读成更高的 θ），
# cat = 词频题库 CAT（精确 rank + 最大信息量选题）。
_ALGOS = {
    "classic": vocab,
    "adaptive": vocab_adaptive2,
    "adaptive2": vocab_adaptive2,
    "cat": vocab_cat,
}
# 二维引擎的两个入口（用同一个模块，按算法名区分历史与日志）。
_DUAL_ALGOS = {"adaptive", "adaptive2"}
# 兼容旧客户端/本地缓存里的 "eudic"（算法改名前的值），归一化为 adaptive。
_ALIASES = {"eudic": "adaptive"}


class StartIn(BaseModel):
    algo: str | None = None


class AnswerIn(BaseModel):
    session_id: str
    choice: int | None = None
    unknown: bool = False


class FinishIn(BaseModel):
    session_id: str


def _service_and_session(sid: str):
    """按会话 id 找到所属算法模块（各套算法各自维护会话）。"""
    for svc in set(_ALGOS.values()):
        sess = svc.get_session(sid)
        if sess is not None:
            return svc, sess
    return None, None


@router.post("/test/start")
def start(payload: StartIn | None = None, user_id: str = Depends(current_user_id)):
    algo = ((payload.algo if payload else None) or settings.vocab_algo).lower()
    algo = _ALIASES.get(algo, algo)
    svc = _ALGOS.get(algo)
    if svc is None:
        raise HTTPException(status_code=400, detail=f"未知算法：{algo}")
    if algo in _DUAL_ALGOS:
        sid, question, progress = vocab_adaptive2.start_test(user_id, algo=algo)
    else:
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


@router.get("/trend")
def trend(algo: str | None = None, user_id: str = Depends(current_user_id)):
    """同一算法的多次测试趋势（issue #42）。"""
    return vocab_trend.trend(user_id, algo)

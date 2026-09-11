from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..services import tts

router = APIRouter(prefix="/tts", tags=["tts"])


@router.get("")
async def synthesize(
    text: str = Query(..., min_length=1, max_length=tts.MAX_TEXT_LEN),
    voice: str | None = None,
    rate: str = Query(tts.DEFAULT_RATE),
    pitch: str = Query(tts.DEFAULT_PITCH),
):
    """文本 -> MP3 音频流。`voice` 传 edge-tts 音色 ID（见 services/tts.VOICES）。"""
    if not text.strip():
        raise HTTPException(status_code=400, detail="文本不能为空")
    voice = tts.resolve_voice(voice)
    return StreamingResponse(
        tts.stream(text, voice, rate, pitch),
        media_type="audio/mpeg",
    )

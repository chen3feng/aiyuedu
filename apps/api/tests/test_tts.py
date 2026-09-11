"""TTS（edge-tts）服务与路由的单元测试。

不真正联网调用 edge-tts，通过 monkeypatch 模拟 Communicate / stream，
验证音色校验、音频流过滤、路由响应类型与参数校验。

运行：uv run --directory apps/api pytest -q
"""
import pytest
from fastapi import HTTPException

from app.services import tts as tts_service
from app.routers import tts as tts_router


# ---------- 音色校验 ----------

def test_resolve_voice_known():
    assert tts_service.resolve_voice("zh-CN-XiaoxiaoNeural") == "zh-CN-XiaoxiaoNeural"


def test_resolve_voice_unknown_falls_back_to_default():
    assert tts_service.resolve_voice("xx-XX-FakeNeural") == tts_service.DEFAULT_VOICE


def test_resolve_voice_none_uses_default():
    assert tts_service.resolve_voice(None) == tts_service.DEFAULT_VOICE


# ---------- 音频流过滤（只取 audio 块） ----------

class _FakeCommunicate:
    def __init__(self, text, voice, rate=None, pitch=None):
        pass

    async def stream(self):
        yield {"type": "audio", "data": b"a"}
        yield {"type": "WordBoundary", "data": b"x"}  # 非音频块应被跳过
        yield {"type": "audio", "data": b"b"}


def test_stream_yields_audio_chunks_only(monkeypatch):
    monkeypatch.setattr(tts_service.edge_tts, "Communicate", _FakeCommunicate)
    async def collect():
        return [c async for c in tts_service.stream("hi", "en-US-JennyNeural", "+0%", "+0Hz")]

    chunks = pytest.importorskip("asyncio").run(collect())
    assert chunks == [b"a", b"b"]


# ---------- 路由层 ----------

async def _fake_stream(text, voice, rate, pitch):
    yield b"ID3"  # 假 MP3 头


def test_synthesize_returns_audio_stream(monkeypatch):
    monkeypatch.setattr(tts_service, "stream", _fake_stream)
    import asyncio

    resp = asyncio.run(
        tts_router.synthesize("hello", None, tts_service.DEFAULT_RATE, tts_service.DEFAULT_PITCH)
    )
    assert resp.media_type == "audio/mpeg"


def test_synthesize_rejects_blank_text():
    import asyncio

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            tts_router.synthesize("   ", None, tts_service.DEFAULT_RATE, tts_service.DEFAULT_PITCH)
        )
    assert exc.value.status_code == 400

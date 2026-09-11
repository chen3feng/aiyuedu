"""TTS 语音合成：edge-tts（微软 Edge 免费在线神经语音）。

音色可控、无需 API Key、跨平台一致（比浏览器 Web Speech API 稳定）。
浏览器 TTS 仍保留在前端，作为「免费试用」档的降级路径（见前端 utils/tts.ts）。

P1 简化：只做「文本 -> MP3 音频流」，不返回音素/词级时间戳（逐词高亮留到接
讯飞/Coqui 后再做）；不做音频缓存（每请求实时合成，规模上来再接对象存储）。
"""
import edge_tts

# 少儿友好的默认音色：美式女声（自然清晰）
DEFAULT_VOICE = "en-US-JennyNeural"
DEFAULT_RATE = "+0%"
DEFAULT_PITCH = "+0Hz"
# 单次合成文本上限（字符），超长由前端切句或降级浏览器 TTS
MAX_TEXT_LEN = 3000

# 应用内可选音色（中/英，少儿友好为主）；不在表内则回退默认，避免任意值打到 edge-tts 报错。
VOICES = frozenset(
    {
        "en-US-JennyNeural",
        "en-US-AriaNeural",
        "en-US-MichelleNeural",
        "en-US-GuyNeural",
        "en-US-ChristopherNeural",
        "en-GB-SoniaNeural",
        "en-GB-RyanNeural",
        "zh-CN-XiaoxiaoNeural",
        "zh-CN-XiaoyiNeural",
        "zh-CN-YunxiNeural",
        "zh-CN-YunxiaNeural",
        "zh-CN-YunjianNeural",
        "zh-CN-YunyangNeural",
    }
)


def resolve_voice(voice: str | None) -> str:
    """校验并规范化音色 ID；空/未知回退默认。"""
    if voice and voice in VOICES:
        return voice
    return DEFAULT_VOICE


async def stream(text: str, voice: str, rate: str, pitch: str):
    """逐块产出 MP3 字节流，供 StreamingResponse 直接下发（不落地缓存）。"""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            yield chunk["data"]

// TTS API 客户端：拼装后端 edge-tts 音频地址（GET /tts?text=&voice=&rate=）
import { API_BASE } from "./request";

// lang -> edge-tts 音色 ID（少儿友好）。后端白名单见 services/tts.VOICES。
const VOICE_BY_LANG: Record<string, string> = {
  "en-US": "en-US-JennyNeural",
  "en-GB": "en-GB-SoniaNeural",
  "zh-CN": "zh-CN-XiaoxiaoNeural",
};

export const DEFAULT_VOICE = VOICE_BY_LANG["en-US"];

// 稍慢语速（-10% ≈ 0.9x），贴合中小学生听力
export const DEFAULT_RATE = "-10%";

export function voiceForLang(lang: string): string {
  return VOICE_BY_LANG[lang] || DEFAULT_VOICE;
}

export function ttsUrl(text: string, lang = "en-US", rate = DEFAULT_RATE): string {
  const voice = voiceForLang(lang);
  return (
    `${API_BASE}/tts?text=${encodeURIComponent(text)}` +
    `&voice=${encodeURIComponent(voice)}&rate=${encodeURIComponent(rate)}`
  );
}

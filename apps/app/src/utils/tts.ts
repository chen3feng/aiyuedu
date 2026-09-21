// 语音合成统一封装：
//   - 优先后端 edge-tts（音色可控、跨平台一致）；
//   - 加载失败时回退浏览器 Web Speech API（未来「免费试用」档走浏览器）；
//   - 非 H5 平台（小程序）暂不支持，返回 false 由调用方降级。
import { ttsUrl } from "../api/tts";

let audio: HTMLAudioElement | null = null;

function stopAudio(): void {
  if (audio) {
    audio.pause();
    audio.onended = null;
    audio.onerror = null;
    audio.src = "";
    audio = null;
  }
}

// ---------- 屏幕常亮：播放期间防息屏（Screen Wake Lock API） ----------
// 阅读语音（尤其全文朗读）耗时较长，期间保持屏幕常亮；结束/停止时释放。
// 浏览器不支持或用户拒绝时静默降级（屏幕会照常暗下，不影响功能）。
type WakeLockSentinel = { released?: boolean; release: () => Promise<void> };

let wakeLock: WakeLockSentinel | null = null;
let wakeDesired = false;

function releaseWake(): void {
  wakeDesired = false;
  if (wakeLock) {
    wakeLock.release().catch(() => {});
    wakeLock = null;
  }
}

async function acquireWake(): Promise<void> {
  // #ifdef H5
  wakeDesired = true;
  try {
    const nav = navigator as Navigator & {
      wakeLock?: { request: (type: "screen") => Promise<WakeLockSentinel> };
    };
    if (nav.wakeLock) {
      const lock = await nav.wakeLock.request("screen");
      if (wakeDesired) {
        wakeLock = lock;
      } else {
        lock.release().catch(() => {});
      }
    }
  } catch {
    // 忽略：不支持 / 权限拒绝 / 页面不可见
  }
  // #endif
}

// 结束回调统一收口：先释放常亮再调业务 onEnd。
function finish(onEnd?: () => void): () => void {
  return () => {
    releaseWake();
    onEnd?.();
  };
}

// 切后台时浏览器自动释放 wake lock；回到前台若仍在播放则重新申请。
// #ifdef H5
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (
      document.visibilityState === "visible" &&
      wakeDesired &&
      (!wakeLock || wakeLock.released)
    ) {
      wakeLock = null;
      acquireWake();
    }
  });
}
// #endif

// 浏览器 TTS（回退档 / 未来免费试用档）
function browserSpeak(text: string, lang: string, onEnd?: () => void): boolean {
  // #ifdef H5
  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    const synth = window.speechSynthesis;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang;
    u.rate = 0.9;
    if (onEnd) {
      u.onend = onEnd;
      u.onerror = onEnd;
    }
    synth.speak(u);
    return true;
  }
  // #endif
  return false;
}

// 浏览器逐句朗读（回退档 / 免费试用档）：按句入队，onstart 时回调当前句下标
function browserSpeakLines(
  sentences: string[],
  lang: string,
  onLine?: (i: number) => void,
  onEnd?: () => void,
): boolean {
  // #ifdef H5
  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    const synth = window.speechSynthesis;
    synth.cancel();
    let remaining = sentences.length;
    sentences.forEach((s, idx) => {
      const u = new SpeechSynthesisUtterance(s);
      u.lang = lang;
      u.rate = 0.9;
      u.onstart = () => onLine?.(idx);
      const done = () => {
        remaining -= 1;
        if (remaining <= 0 && onEnd) onEnd();
      };
      u.onend = done;
      u.onerror = done;
      synth.speak(u);
    });
    return true;
  }
  // #endif
  return false;
}

// 播放后端 edge-tts 音频；失败则回退浏览器 TTS。fallback 返回 false 表示也不可用。
function playUrl(url: string, fallback: () => boolean, onEnd?: () => void): boolean {
  // #ifdef H5
  stopAudio();
  const a = new Audio(url);
  let fellBack = false;
  const fail = () => {
    if (fellBack) return;
    fellBack = true;
    if (!fallback() && onEnd) onEnd();
  };
  a.onerror = fail;
  a.onended = () => {
    if (onEnd) onEnd();
  };
  const p = a.play();
  if (p && typeof p.catch === "function") p.catch(fail);
  audio = a;
  return true;
  // #endif
  // #ifndef H5
  return fallback();
  // #endif
}

export function speak(text: string, lang = "en-US"): boolean {
  if (!text) return false;
  acquireWake();
  return playUrl(ttsUrl(text, lang), () => browserSpeak(text, lang, finish()), finish());
}

// 逐句朗读：后端 edge-tts 每句一个音频、顺序播放，onLine 回调当前句下标（供高亮 + 滚屏）。
// 首句失败视为后端不可用，整体回退浏览器逐句朗读；后续单句失败仅跳过。
export function speakLines(
  sentences: string[],
  lang = "en-US",
  onLine?: (i: number) => void,
  onEnd?: () => void,
): boolean {
  // #ifdef H5
  if (typeof window === "undefined") return false;
  if (!sentences.length) {
    onEnd?.();
    return true;
  }
  acquireWake();
  stopAudio();
  const done = finish(onEnd); // 释放常亮 + 业务回调，统一只走一次
  // 并行预取：new Audio(url) 立即触发加载，播放时无网络空档
  const audios = sentences.map((s) => new Audio(ttsUrl(s, lang)));
  let i = 0;
  const advance = () => {
    if (i >= audios.length) {
      done();
      return;
    }
    const idx = i++;
    onLine?.(idx);
    const a = audios[idx];
    let settled = false;
    const failOrNext = () => {
      if (settled) return;
      settled = true;
      if (idx === 0) {
        stopAudio();
        browserSpeakLines(sentences, lang, onLine, done);
      } else {
        advance();
      }
    };
    a.onended = () => {
      if (!settled) {
        settled = true;
        advance();
      }
    };
    a.onerror = failOrNext;
    a.play().catch(failOrNext);
    audio = a;
  };
  advance();
  return true;
  // #endif
  // #ifndef H5
  return browserSpeakLines(sentences, lang, onLine, onEnd);
  // #endif
}

// 停止朗读（后端音频 + 浏览器 TTS 都停）
export function stopSpeak(): void {
  releaseWake();
  stopAudio();
  // #ifdef H5
  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
  // #endif
}

// UI 语言：中英双语，默认「跟随系统」，可在设置页覆盖。
// 语言设置存本地 storage（ui_lang），取值 auto | zh-CN | en。
import { createI18n } from "vue-i18n";
import { ref } from "vue";
import zh from "./zh-CN";
import en from "./en";

export type Lang = "zh-CN" | "en";
export type LangSetting = "auto" | Lang;

const STORAGE_KEY = "ui_lang";

// 系统语言 -> 支持的语言（非中文一律回退英文）
export function systemLang(): Lang {
  const lang = (uni.getSystemInfoSync().language || "zh-CN").toLowerCase();
  return lang.startsWith("zh") ? "zh-CN" : "en";
}

export function resolveLang(setting: LangSetting): Lang {
  return setting === "auto" ? systemLang() : setting;
}

function storedSetting(): LangSetting {
  const v = uni.getStorageSync(STORAGE_KEY);
  return v === "zh-CN" || v === "en" || v === "auto" ? (v as LangSetting) : "auto";
}

export const i18n = createI18n({
  legacy: false, // 组合式 API：组件内 useI18n()
  locale: resolveLang(storedSetting()),
  fallbackLocale: "zh-CN",
  messages: { "zh-CN": zh, en },
});

// 当前「设置项」（供设置页高亮与切换，响应式）
export const langSetting = ref<LangSetting>(storedSetting());

export function setLanguage(setting: LangSetting): void {
  langSetting.value = setting;
  uni.setStorageSync(STORAGE_KEY, setting);
  i18n.global.locale.value = resolveLang(setting);
}

// 写作平台 API：题目列表 + 作文 CRUD + AI 批改
import { request } from "./request";

export interface Prompt {
  key: string;
  title_zh: string;
  title_en: string;
  body_zh: string;
  target_words: number;
}

export interface EssayError {
  category: string;
  explanation: string;
  fix: string;
}

export interface EssaySentenceReport {
  index: number;
  original: string;
  errors: EssayError[];
  corrected: string;
  polished: string;
  polished_reason?: string;
}

export interface SummaryTableRow {
  category: string;
  examples: string[];
  rule: string;
}

export interface EssayReport {
  sentences: EssaySentenceReport[];
  summary_table: SummaryTableRow[];
  praise: string;
}

export interface Essay {
  id: string;
  created_at: number | string;
  prompt_key?: string | null;
  prompt_title_zh?: string | null;
  prompt_title_en?: string | null;
  prompt_body_zh?: string | null;
  target_words?: number;
  word_count: number;
  original: string;
  report: EssayReport | null;
  ai_used: boolean;
  model: string;
  reason: string | null;
}

export const listPrompts = () =>
  request<{ items: Prompt[] }>("/writings/prompts");

export const listEssays = () =>
  request<{ items: Essay[] }>("/writings");

export const getEssay = (id: string) =>
  request<Essay>(`/writings/${id}`);

export const deleteEssay = (id: string) =>
  request<{ ok: boolean }>(`/writings/${id}`, { method: "DELETE" });

// 写作批改可能耗时 60-180s（本地 Ollama 慢模型），显式传 timeout 防止前端误判超时
const LONG_TIMEOUT = 5 * 60 * 1000; // 5 分钟

export const submitEssay = (data: {
  prompt_key?: string;
  original: string;
  target_words?: number;
}) =>
  request<Essay>("/writings", {
    method: "POST",
    data,
    timeout: LONG_TIMEOUT,
  });
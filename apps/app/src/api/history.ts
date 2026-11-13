// 学习记录 API：词汇测试历史 + 阅读进度
import { request } from "./request";

export interface VocabTestRecord {
  ts: number;
  algo: string;
  score: number;
  vocab_size: number;
  total: number;
  correct: number;
  wrong: number;
  unknown: number;
  se?: number;
  alpha?: number;
}

export interface VocabTrend {
  algo: string | null;
  n: number;
  slope_per_month: number | null;
  ci: [number, number] | null;
  p_value?: number;
  significant: boolean;
  message: string;
  points: { ts: number; vocab_size: number; sigma: number }[];
}

export interface ReadingProgress {
  reading_id: string;
  title: string;
  title_zh: string;
  collection_id: string | null;
  collection_title: string | null;
  chapter_index: number | null;
  level: number | null;
  completed_ratio: number;
  seconds: number;
  ts: number;
}

export const listVocabTests = () => request<{ items: VocabTestRecord[] }>("/vocab/tests");

export const getVocabTrend = (algo?: string) =>
  request<VocabTrend>(`/vocab/trend${algo ? `?algo=${encodeURIComponent(algo)}` : ""}`);

export const listReadingProgress = () =>
  request<{ items: ReadingProgress[] }>("/readings/progress");

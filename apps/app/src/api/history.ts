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

export const listReadingProgress = () =>
  request<{ items: ReadingProgress[] }>("/readings/progress");

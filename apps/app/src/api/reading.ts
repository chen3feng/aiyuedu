// 分级阅读 API 客户端：阅读列表、逐行对照详情、阅读记录上报
import { request } from "./request";

export interface ReadingSummary {
  id: string;
  title: string;
  topic: string;
  topic_label: string;
  target_level: number | null;
  word_count: number;
  new_word_rate: number;
}

export interface ReadingWord {
  w: string;
  known?: boolean;
  gloss?: string;
  full_gloss?: string;
  rank?: number;
  phonetic?: string;
  punct?: boolean;
  num?: boolean;
  proper?: boolean;
  stop?: boolean;
  lemma?: string;
}

export interface ReadingLine {
  words: ReadingWord[];
  html: string;
}

export interface VocabItem {
  word: string;
  lemma: string;
  phonetic: string;
  gloss: string;
  full_gloss: string;
}

export interface ReadingDetail {
  id: string;
  title: string;
  topic: string;
  topic_label: string;
  target_level: number | null;
  body: string;
  word_count: number;
  new_word_count: number;
  new_word_rate: number;
  lines: ReadingLine[];
  vocabulary: VocabItem[];
}

export interface RecordPayload {
  level: number;
  completed_ratio: number;
  seconds: number;
  new_word_clicks: string[];
}

export const listReadings = (level: number, topic?: string) => {
  const data: Record<string, unknown> = { level };
  if (topic) data.topic = topic;
  return request<{ items: ReadingSummary[] }>("/readings", { data });
};

export const getReading = (id: string, level: number) =>
  request<ReadingDetail>(`/readings/${id}`, { data: { level } });

export const recordReading = (id: string, payload: RecordPayload) =>
  request<{ ok: boolean; reading_id: string }>(`/readings/${id}/record`, {
    method: "POST",
    data: payload as unknown as Record<string, unknown>,
  });

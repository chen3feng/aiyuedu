// 分级阅读 API 客户端：阅读列表、逐行对照详情、阅读记录上报
import { request } from "./request";

export interface ReadingSummary {
  id: string;
  title: string;
  title_zh?: string;
  topics: string[];
  topic_labels: string[];
  target_level: number | null;
  word_count: number;
  new_word_rate: number;
  // collection 摘要字段（孤儿 reading 没有）
  is_collection?: boolean;
  total_chapters?: number;
  author?: string;
  cover_url?: string;
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
  phrase?: boolean; // 多词短语（take over / throw up），整段一个生词单元
  em?: boolean; // 斜体强调（正文 <em> 内；ruby html 自带标签，此标志供逐词模式加样式）
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
  phrase?: boolean; // 多词短语，word/lemma 为短语 canonical 文本
}

export interface ReadingDetail {
  id: string;
  title: string;
  title_zh?: string;
  subtitle: string;
  topics: string[];
  topic_labels: string[];
  target_level: number | null;
  body: string;
  word_count: number;
  new_word_count: number;
  new_word_rate: number;
  lines: ReadingLine[];
  vocabulary: VocabItem[];
  quizzes: Quiz[];
  // collection 章节字段
  collection_id?: string;
  chapter_index?: number;
  chapter_title?: string;
  collection_glossary?: Record<string, string>;
  collection?: {
    id: string;
    title: string;
    title_zh?: string;
    author?: string;
    cover_url?: string;
    total_chapters: number;
  };
  chapters?: Array<{
    index: number;
    id: string;
    title?: string;
    title_zh?: string;
  }>;
}

// 课后小测题目。当前只渲染 `choice`；`type` 字段为未来题型（如判断题 `truefalse`）预留，
// 不同题型用不同字段：choice 用 options[{text, correct}]（可多个 correct 项），truefalse 用 answer(布尔)。
export type QuizType = "choice" | "truefalse";

export interface ChoiceQuiz {
  type: "choice";
  question: string;
  options: { text: string; correct: boolean }[]; // 每项：选项内容 + 是否正确答案（可多个）
  explanation_en: string; // 英文解答（默认展示）
  explanation_zh: string; // 中文解答（UI 为中文时额外展示）
}

export interface TrueFalseQuiz {
  type: "truefalse";
  question: string;
  answer: boolean;
  explanation_en: string;
  explanation_zh: string;
}

export type Quiz = ChoiceQuiz | TrueFalseQuiz;

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

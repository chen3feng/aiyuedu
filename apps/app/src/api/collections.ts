// 作品集 / 书籍 API
import { request } from "./request";

export interface CollectionChapter {
  index: number;
  id: string;
  title?: string;
  title_zh?: string;
  body?: string;
  target_level?: number | null;
  glosses?: Record<string, string>;
  terms?: Record<string, string>;
  skip?: string[];
  quizzes?: unknown[];
}

export interface CollectionDetail {
  id: string;
  title: string;
  title_zh?: string;
  author?: string;
  source?: string;
  total_chapters: number;
  cover_url?: string;
  intro_zh?: string;
  intro_en?: string;
  created_at?: number;
  glossary: Record<string, string>;
  polysemy: Record<string, unknown>;
  chapters: CollectionChapter[];
}

export const getCollection = (id: string) =>
  request<CollectionDetail>(`/collections/${id}`);
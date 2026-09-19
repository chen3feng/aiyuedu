// 作品集 / 书籍 API
import { request } from "./request";

export interface CollectionSummary {
  id: string;
  title: string;
  title_zh?: string;
  author?: string;
  cover_url?: string;
  total_chapters: number;
  source?: string;
  glossary_size: number;
  created_at?: number;
}

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

export const listCollections = () =>
  request<{ items: CollectionSummary[] }>("/collections");

export const getCollection = (id: string) =>
  request<CollectionDetail>(`/collections/${id}`);

export const createCollection = (data: Partial<CollectionDetail> & { title: string }) =>
  request<CollectionDetail>("/collections", { method: "POST", data });

export const updateCollection = (id: string, data: Partial<CollectionDetail>) =>
  request<CollectionDetail>(`/collections/${id}`, { method: "PUT", data });

export const deleteCollection = (id: string) =>
  request<{ ok: boolean }>(`/collections/${id}`, { method: "DELETE" });
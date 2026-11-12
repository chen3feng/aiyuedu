// 生词本 API：按当前用户隔离，登录后跨设备同步
import { request } from "./request";

export interface NotebookItem {
  word: string;
  gloss: string;
  phonetic: string;
  reading_id: string;
  ts: number;
}

export const listNotebook = () => request<{ items: NotebookItem[] }>("/notebook");

export const addNotebookItem = (item: {
  word: string;
  gloss?: string;
  phonetic?: string;
  reading_id?: string;
}) => request<NotebookItem>("/notebook", { method: "POST", data: item });

export const removeNotebookItem = (word: string) =>
  request<{ ok: boolean }>(`/notebook/${encodeURIComponent(word)}`, { method: "DELETE" });

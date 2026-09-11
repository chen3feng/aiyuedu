// 词汇量评测 API 客户端（对接 FastAPI 后端，分层抽样 + 识别率×词频权重）
import { request } from "./request";

export interface Question {
  word: string;
  options: string[];
}

export interface Progress {
  score: number | null;
  total: number;
  correct: number;
  unknown: number;
  wrong: number;
  converged?: boolean;
}

export interface StartResp extends Progress {
  session_id: string;
  rules: string;
  question: Question;
}

export interface Feedback {
  response: "correct" | "unknown" | "wrong";
  word: string;
  correct_gloss: string;
}

export interface Result {
  vocab_size: number;
  score: number;
  total: number;
  correct: number;
  unknown: number;
  wrong: number;
  message: string;
}

export interface AnswerResp extends Progress {
  finished: boolean;
  feedback: Feedback;
  question?: Question;
  result?: Result;
}

export const startTest = () =>
  request<StartResp>("/vocab/test/start", { method: "POST" });

export const answer = (sessionId: string, choice: number | null, unknown: boolean) =>
  request<AnswerResp>("/vocab/test/answer", {
    method: "POST",
    data: { session_id: sessionId, choice, unknown },
  });

export const finishTest = (sessionId: string) =>
  request<{ finished: boolean; result: Result }>("/vocab/test/finish", {
    method: "POST",
    data: { session_id: sessionId },
  });

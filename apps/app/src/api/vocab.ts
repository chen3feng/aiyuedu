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
  /** 自适应算法的当前置信区间（经典算法不返回） */
  score_interval?: [number, number];
  /** 当前词频档位（自适应算法） */
  level?: number;
}

export interface StartResp extends Progress {
  session_id: string;
  algo: VocabAlgo;
  rules: string;
  question: Question;
}

export interface Feedback {
  response: "correct" | "unknown" | "wrong";
  word: string;
  /** 正确选项文本，用于高亮选项；「以上都不对」时就是这四个字 */
  correct_gloss: string;
  /** 该词的真实含义，用于答后反馈（「以上都不对」时展示这个） */
  word_gloss?: string;
}

export interface Result {
  vocab_size: number;
  score: number;
  total: number;
  correct: number;
  unknown: number;
  wrong: number;
  message: string;
  /** 自适应算法的 95% 置信区间（经典算法不返回） */
  score_interval?: [number, number];
  /** 双参数算法：词汇量（曲线面积）的 95% 区间 */
  vocab_interval?: [number, number];
  /** 双参数算法：个人区分度（相对基准斜率，1.0 = 单参数模型） */
  alpha?: number;
}

export interface AnswerResp extends Progress {
  finished: boolean;
  feedback: Feedback;
  question?: Question;
  result?: Result;
}

export type VocabAlgo = "classic" | "adaptive" | "adaptive2" | "cat";

/** 算法改名前的历史记录/本地缓存仍可能带 "eudic"，统一归一化为 adaptive。 */
export function normalizeAlgo(algo?: string): VocabAlgo {
  return algo === "eudic" ? "adaptive" : ((algo as VocabAlgo) || "classic");
}

export const startTest = (algo?: VocabAlgo) =>
  request<StartResp>("/vocab/test/start", {
    method: "POST",
    data: algo ? { algo } : {},
  });

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

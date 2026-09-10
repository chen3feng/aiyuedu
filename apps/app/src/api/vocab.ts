// 词汇量评测 API 客户端（对接 FastAPI 后端，分层抽样 + 识别率×词频权重）
const API_BASE = "http://127.0.0.1:8000";

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

function request<T>(path: string, data?: Record<string, unknown>): Promise<T> {
  return new Promise((resolve, reject) => {
    uni.request({
      url: API_BASE + path,
      method: "POST",
      data,
      header: { "Content-Type": "application/json" },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data as T);
        } else {
          const detail = (res.data as { detail?: string } | undefined)?.detail;
          reject(new Error(detail || `请求失败 (${res.statusCode})`));
        }
      },
      fail: (err) => reject(new Error(err.errMsg || "网络错误")),
    });
  });
}

export const startTest = () => request<StartResp>("/vocab/test/start");

export const answer = (sessionId: string, choice: number | null, unknown: boolean) =>
  request<AnswerResp>("/vocab/test/answer", { session_id: sessionId, choice, unknown });

export const finishTest = (sessionId: string) =>
  request<{ finished: boolean; result: Result }>("/vocab/test/finish", { session_id: sessionId });

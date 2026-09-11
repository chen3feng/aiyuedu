// 通用请求封装：对接 FastAPI 后端，支持 GET/POST，统一错误处理
export const API_BASE = "http://127.0.0.1:8000";

interface RequestOptions {
  method?: "GET" | "POST";
  data?: Record<string, unknown>;
}

export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", data } = options;
  return new Promise((resolve, reject) => {
    uni.request({
      url: API_BASE + path,
      method,
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

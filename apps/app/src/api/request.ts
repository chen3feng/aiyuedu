// 通用请求封装：对接 FastAPI 后端，支持 GET/POST/PUT，统一错误处理
// 身份：X-User-Id 请求头（匿名设备 ID），见 utils/user.ts
import { getUserId } from "../utils/user";

// 后端 API 地址：H5 下跟随页面域名（桌面 localhost、手机局域网 IP 均自动适配），
// 非 H5（小程序等）回退到本机地址，便于本地联调。
function apiBase(): string {
  // #ifdef H5
  if (typeof window !== "undefined" && window.location?.hostname) {
    return `http://${window.location.hostname}:8000`;
  }
  // #endif
  return "http://127.0.0.1:8000";
}

export const API_BASE = apiBase();

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  data?: Record<string, unknown>;
}

export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", data } = options;
  return new Promise((resolve, reject) => {
    uni.request({
      url: API_BASE + path,
      method,
      data,
      header: { "Content-Type": "application/json", "X-User-Id": getUserId() },
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

// 通用请求封装：对接 FastAPI 后端，支持 GET/POST/PUT/DELETE，统一错误处理
// 身份：登录用户带 Authorization: Bearer <token>；同时带 X-User-Id 作为匿名回退。
import { clearAuth, getToken, getUserId } from "../utils/user";

// 后端 API 端口：默认 8000；可用 VITE_API_PORT 覆盖（例如 8000 被其它服务占用时）。
const API_PORT = import.meta.env.VITE_API_PORT || "8000";
// 完整 API 地址覆盖：公网隧道 / 独立 API 域名时使用（优先于 hostname:port）。
const API_BASE_OVERRIDE = import.meta.env.VITE_API_BASE as string | undefined;

// 后端 API 地址：H5 下跟随页面域名（桌面 localhost、手机局域网 IP 均自动适配），
// 非 H5（小程序等）回退到本机地址，便于本地联调。
function apiBase(): string {
  if (API_BASE_OVERRIDE) return API_BASE_OVERRIDE;
  // #ifdef H5
  if (typeof window !== "undefined" && window.location?.hostname) {
    return `http://${window.location.hostname}:${API_PORT}`;
  }
  // #endif
  return `http://127.0.0.1:${API_PORT}`;
}

export const API_BASE = apiBase();

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  data?: Record<string, unknown>;
  /** H5 / 小程序超时毫秒；不传走平台默认（小程序默认 60s，容易误判超时） */
  timeout?: number;
}

/** 401 时回登录页；登录/注册接口自身的 401 只当作表单错误。 */
function handleUnauthorized(path: string): void {
  if (path === "/auth/login" || path === "/auth/register") return;
  clearAuth();
  if (path.startsWith("/auth/")) return;
  const pages = getCurrentPages();
  const current = pages[pages.length - 1]?.route || "";
  if (current.startsWith("pages/auth/")) return;
  uni.navigateTo({ url: "/pages/auth/login" });
}

export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", data } = options;
  const header: Record<string, string> = {
    "Content-Type": "application/json",
    "X-User-Id": getUserId(),
  };
  const token = getToken();
  if (token) header.Authorization = `Bearer ${token}`;
  return new Promise((resolve, reject) => {
    uni.request({
      url: API_BASE + path,
      method,
      data,
      header,
      // 长请求（写作批改需 60-180s）显式传 timeout 避免小程序端 60s 默认截断
      ...(options.timeout ? { timeout: options.timeout } : {}),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data as T);
        } else {
          if (res.statusCode === 401) handleUnauthorized(path);
          const detail = (res.data as { detail?: string } | undefined)?.detail;
          reject(new Error(detail || `请求失败 (${res.statusCode})`));
        }
      },
      fail: (err) => reject(new Error(err.errMsg || "网络错误")),
    });
  });
}

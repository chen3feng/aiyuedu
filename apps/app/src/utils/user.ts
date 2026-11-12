// 当前用户身份：
// - 登录用户：auth_token + auth_user（跨设备同步）
// - 匿名用户：本机稳定 UUID（X-User-Id），未登录也能用
const STORAGE_KEY = "user_id";
const TOKEN_KEY = "auth_token";
const AUTH_USER_KEY = "auth_user";
const ONBOARDED_KEY = "onboarded";

export interface AuthUser {
  user_id: string;
  username: string;
  created_at?: number;
}

function genUUID(): string {
  const cryptoObj = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (cryptoObj?.randomUUID) return cryptoObj.randomUUID();
  return "u-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

export function getUserId(): string {
  const cached = uni.getStorageSync(STORAGE_KEY);
  if (typeof cached === "string" && cached) return cached;
  const id = genUUID();
  uni.setStorageSync(STORAGE_KEY, id);
  return id;
}

export function getToken(): string | null {
  const token = uni.getStorageSync(TOKEN_KEY);
  return typeof token === "string" && token ? token : null;
}

export function setToken(token: string): void {
  uni.setStorageSync(TOKEN_KEY, token);
}

export function getAuthUser(): AuthUser | null {
  const cached = uni.getStorageSync(AUTH_USER_KEY);
  return cached && typeof cached === "object" ? (cached as AuthUser) : null;
}

/** 登录 / 注册成功后保存登录态。 */
export function setAuth(token: string, user: AuthUser): void {
  setToken(token);
  uni.setStorageSync(AUTH_USER_KEY, user);
}

/** 退出登录：清 token / 账号缓存 / 匿名设备 id（下次 getUserId 会生成新 id）。 */
export function clearAuth(): void {
  uni.removeStorageSync(TOKEN_KEY);
  uni.removeStorageSync(AUTH_USER_KEY);
  uni.removeStorageSync(STORAGE_KEY);
}

export function isLoggedIn(): boolean {
  return getToken() !== null;
}

export function markOnboarded(): void {
  uni.setStorageSync(ONBOARDED_KEY, 1);
}

export function isOnboarded(): boolean {
  return Boolean(uni.getStorageSync(ONBOARDED_KEY));
}

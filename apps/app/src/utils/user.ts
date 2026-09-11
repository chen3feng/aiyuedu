// 当前用户标识：匿名设备 ID（稳定 UUID）。后续微信登录/一号多孩时，把这里换成所选孩子的 id。
const STORAGE_KEY = "user_id";

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

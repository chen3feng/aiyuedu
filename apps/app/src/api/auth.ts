// 账号 API：注册 / 登录 / 退出 / 当前用户 / 改密 / 注销
import { request } from "./request";
import type { AuthUser } from "../utils/user";

export interface AuthResp {
  token: string;
  user: AuthUser;
  imported?: Record<string, number>;
}

export interface MeResp extends AuthUser {}

export const register = (username: string, password: string, deviceUserId: string) =>
  request<AuthResp>("/auth/register", {
    method: "POST",
    data: { username, password, device_user_id: deviceUserId },
  });

export const login = (username: string, password: string) =>
  request<AuthResp>("/auth/login", {
    method: "POST",
    data: { username, password },
  });

export const logout = () => request<{ ok: boolean }>("/auth/logout", { method: "POST" });

export const getMe = () => request<MeResp>("/auth/me");

export const changePassword = (oldPassword: string, newPassword: string) =>
  request<{ ok: boolean }>("/auth/password", {
    method: "PUT",
    data: { old_password: oldPassword, new_password: newPassword },
  });

export const deleteAccount = (password: string) =>
  request<{ ok: boolean }>("/auth/account", {
    method: "DELETE",
    data: { password },
  });

// 用户档案 API 客户端：阅读主题偏好、词汇量（身份由请求头 X-User-Id 携带，见 request.ts）
import { request } from "./request";

export interface UserProfile {
  user_id: string;
  topic_preferences: string[];
  vocab_size: number | null;
  updated_at: number;
}

export type ProfilePatch = Partial<Pick<UserProfile, "topic_preferences" | "vocab_size">>;

export const getProfile = () => request<UserProfile>("/users/me");

export const saveProfile = (patch: ProfilePatch) =>
  request<UserProfile>("/users/me", {
    method: "PUT",
    data: patch as unknown as Record<string, unknown>,
  });

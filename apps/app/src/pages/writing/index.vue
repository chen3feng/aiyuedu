<template>
  <view class="page">
    <view class="topbar">
      <text class="title">{{ t("writing.listTitle") }}</text>
      <button class="btn-primary" @click="goPickPrompt">+ {{ t("writing.start") }}</button>
    </view>

    <view v-if="loading" class="loading">{{ t("common.loading") }}</view>
    <view v-else-if="error" class="error">{{ error }}</view>
    <view v-else-if="!items.length" class="empty">
      <view class="empty-icon">📝</view>
      <text>{{ t("writing.empty") }}</text>
      <text class="empty-hint">{{ t("writing.emptyHint") }}</text>
    </view>
    <view v-else class="cards">
      <view v-for="e in items" :key="e.id" class="card" @click="openReport(e.id)">
        <view class="card-top">
          <text class="title-text">{{ promptTitle(e) }}</text>
          <view class="status" :class="{ ok: e.ai_used, err: !e.ai_used }">
            {{ e.ai_used ? "✓" : t("writing.aiFailed") }}
          </view>
        </view>
        <view class="card-body">
          <text class="snippet">{{ snippet(e.original) }}</text>
        </view>
        <view class="meta">
          <text class="meta-item">{{ t("writing.wordCount", { n: e.word_count }) }}</text>
          <text class="meta-item">·</text>
          <text class="meta-item">{{ formatTime(e.created_at) }}</text>
        </view>
        <view class="actions">
          <button class="btn-link" @click.stop="openReport(e.id)">{{ t("writing.viewReport") }}</button>
          <button class="btn-danger" @click.stop="onDelete(e.id)">{{ t("writing.delete") }}</button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { listEssays, deleteEssay } from "../../api/writing";
import type { Essay, Prompt } from "../../api/writing";
import { getUserId } from "../../utils/user";

const { t, locale } = useI18n();

const items = ref<Essay[]>([]);
const loading = ref(false);
const error = ref("");

function promptTitle(e: Essay): string {
  if (locale.value === "en" && e.prompt_title_en) return e.prompt_title_en;
  return e.prompt_title_zh || "（自由写作）";
}

function snippet(body: string): string {
  const s = body.replace(/\s+/g, " ").trim();
  return s.length > 60 ? s.slice(0, 60) + "…" : s;
}

function formatTime(at: number | string): string {
  let n: number;
  if (typeof at === "number") n = at;
  else {
    n = Number(at);
    if (isNaN(n)) n = Date.now() / 1000;
  }
  // 兼容秒和毫秒
  if (n < 1e12) n *= 1000;
  const d = new Date(n);
  const pad = (x: number) => String(x).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function fetchList() {
  loading.value = true;
  error.value = "";
  try {
    const resp = await listEssays();
    items.value = resp.items;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function goPickPrompt() {
  uni.navigateTo({ url: "/pages/writing/compose?pick=1" });
}

function openReport(id: string) {
  uni.navigateTo({ url: `/pages/writing/report?id=${id}` });
}

async function onDelete(id: string) {
  const ok = await new Promise<boolean>((resolve) => {
    uni.showModal({
      title: t("writing.deleteConfirm"),
      success: (r) => resolve(!!r.confirm),
      fail: () => resolve(false),
    });
  });
  if (!ok) return;
  try {
    await deleteEssay(id);
    items.value = items.value.filter((e) => e.id !== id);
  } catch (err) {
    error.value = (err as Error).message;
  }
}

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.writing") });
  fetchList();
});
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 24rpx 32rpx 60rpx;
  box-sizing: border-box;
}
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
}
.title {
  font-size: 38rpx;
  font-weight: 700;
  color: var(--ink);
}
.btn-primary {
  background: var(--brand);
  color: #fff;
  font-size: 26rpx;
  padding: 12rpx 28rpx;
  border-radius: 999rpx;
  border: none;
}
.loading,
.error {
  text-align: center;
  color: var(--ink-4);
  font-size: 28rpx;
  padding: 80rpx 0;
}
.error {
  color: var(--danger);
}
.empty {
  text-align: center;
  color: var(--ink-4);
  padding: 120rpx 40rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16rpx;
  font-size: 28rpx;
}
.empty-icon {
  font-size: 80rpx;
}
.empty-hint {
  color: var(--ink-4);
  font-size: 24rpx;
}
.cards {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}
.card {
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx 32rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12rpx;
}
.title-text {
  font-size: 30rpx;
  font-weight: 600;
  color: var(--ink);
}
.status {
  font-size: 22rpx;
  padding: 4rpx 14rpx;
  border-radius: 8rpx;
  flex-shrink: 0;
}
.status.ok {
  color: var(--success);
  background: #e7faf0;
}
.status.err {
  color: var(--danger);
  background: var(--danger-bg);
}
.card-body {
  margin-bottom: 16rpx;
}
.snippet {
  font-size: 26rpx;
  color: var(--ink-3);
  line-height: 1.5;
}
.meta {
  display: flex;
  gap: 12rpx;
  font-size: 24rpx;
  color: var(--ink-4);
  margin-bottom: 16rpx;
}
.actions {
  display: flex;
  gap: 16rpx;
  border-top: 1rpx solid #f0f2f8;
  padding-top: 16rpx;
}
.btn-link {
  background: var(--soft);
  color: var(--brand);
  font-size: 24rpx;
  padding: 8rpx 24rpx;
  border-radius: 8rpx;
  border: none;
  flex: 1;
}
.btn-danger {
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 24rpx;
  padding: 8rpx 24rpx;
  border-radius: 8rpx;
  border: none;
}
</style>
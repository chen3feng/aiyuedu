<template>
  <Card class="p28" @click="emit('open')">
    <view class="card-top">
      <text class="title-text">{{ promptTitle }}</text>
      <view class="status" :class="{ ok: essay.ai_used, err: !essay.ai_used }">
        {{ essay.ai_used ? "✓" : t("writing.aiFailed") }}
      </view>
    </view>
    <view class="card-body">
      <text class="snippet">{{ snippet(essay.original) }}</text>
    </view>
    <view class="meta">
      <text class="meta-item">{{ t("writing.wordCount", { n: essay.word_count }) }}</text>
      <text class="meta-item">·</text>
      <text class="meta-item">{{ formatTime(essay.created_at) }}</text>
    </view>
    <view class="actions">
      <button class="btn-link" @click.stop="emit('open')">{{ t("writing.viewReport") }}</button>
      <button class="btn-danger" @click.stop="emit('delete')">{{ t("writing.delete") }}</button>
    </view>
  </Card>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { Essay } from "../api/writing";
import Card from "./Card.vue";

const props = defineProps<{ essay: Essay }>();
const emit = defineEmits<{ open: []; delete: [] }>();

const { t, locale } = useI18n();

const promptTitle = computed(() => {
  if (locale.value === "en" && props.essay.prompt_title_en) return props.essay.prompt_title_en;
  return props.essay.prompt_title_zh || "（自由写作）";
});

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
</script>

<style scoped>
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

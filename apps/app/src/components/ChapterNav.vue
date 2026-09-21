<template>
  <!-- 章节导航：上一章 / 位置 / 下一章（仅 collection 章节显示） -->
  <view v-if="detail?.collection && detail.chapters" class="chapter-nav">
    <button class="nav-btn" :disabled="!prev" @click="goPrev">
      ← {{ prev ? t("reading.reader.prevChapter", { title: prev.title || "" }) : t("reading.reader.firstChapter") }}
    </button>
    <text class="chapter-pos">
      {{ t("reading.reader.chapterPos", { n: detail.chapter_index ?? 1, total: detail.collection.total_chapters }) }}
    </text>
    <button class="nav-btn" :disabled="!next" @click="goNext">
      {{ next ? t("reading.reader.nextChapter", { title: next.title || "" }) : t("reading.reader.lastChapter") }} →
    </button>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { ReadingDetail } from "../api/reading";

const props = defineProps<{ detail: ReadingDetail | null }>();
const { t } = useI18n();

const prev = computed(() => {
  const d = props.detail;
  if (!d?.chapters || d.chapter_index == null) return null;
  return d.chapters.find((c) => c.index === d.chapter_index! - 1) ?? null;
});
const next = computed(() => {
  const d = props.detail;
  if (!d?.chapters || d.chapter_index == null) return null;
  return d.chapters.find((c) => c.index === d.chapter_index! + 1) ?? null;
});

function goChapter(ch: { id: string }) {
  uni.redirectTo({ url: `/pages/reading/reader?id=${ch.id}` });
}
function goPrev() {
  if (prev.value) goChapter(prev.value);
}
function goNext() {
  if (next.value) goChapter(next.value);
}
</script>

<style scoped>
.chapter-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16rpx;
  margin-top: 28rpx;
  padding: 16rpx;
  background: var(--bg);
  border-radius: 12rpx;
}
.nav-btn {
  flex: 1;
  background: #fff;
  color: var(--brand);
  font-size: 24rpx;
  padding: 14rpx 16rpx;
  border-radius: 999rpx;
  border: 1rpx solid var(--soft);
}
.nav-btn[disabled] {
  color: var(--line);
  background: #f9fafe;
}
.chapter-pos {
  font-size: 24rpx;
  color: var(--ink-3);
  font-weight: 600;
  flex-shrink: 0;
}
</style>

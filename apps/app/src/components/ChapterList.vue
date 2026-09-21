<template>
  <Card class="p24 mb">
    <text class="card-label">{{ label }}</text>
    <view
      v-for="ch in chapters"
      :key="ch.id"
      class="chapter-row"
      @click="emit('open', ch.id)"
    >
      <view class="ch-num">
        <text>{{ ch.index }}</text>
      </view>
      <view class="ch-info">
        <text v-if="ch.title_zh" class="ch-title-zh">{{ ch.title_zh }}</text>
        <text class="ch-title">{{ ch.title }}</text>
      </view>
      <text class="ch-arrow">›</text>
    </view>
    <StateView v-if="!chapters.length" type="empty" class="compact" :message="emptyText" />
  </Card>
</template>

<script setup lang="ts">
import type { CollectionChapter } from "../api/collections";
import Card from "./Card.vue";
import StateView from "./StateView.vue";

withDefaults(
  defineProps<{
    chapters: CollectionChapter[];
    label?: string;
    emptyText?: string;
  }>(),
  { label: "章节列表", emptyText: "暂无章节" },
);
const emit = defineEmits<{ open: [id: string] }>();
</script>

<style scoped>
.card-label {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 16rpx;
}
.chapter-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 16rpx 0;
  border-top: 1rpx solid #f0f2f8;
}
.chapter-row:first-of-type {
  border-top: none;
}
.chapter-row:active {
  background: #f9fafe;
}
.ch-num {
  width: 48rpx;
  height: 48rpx;
  border-radius: 50%;
  background: var(--soft);
  color: var(--brand);
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22rpx;
  flex-shrink: 0;
}
.ch-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.ch-title-zh {
  font-size: 28rpx;
  font-weight: 500;
  color: var(--ink);
}
.ch-title {
  font-size: 22rpx;
  color: var(--ink-4);
}
.ch-arrow {
  font-size: 36rpx;
  color: var(--line);
  flex-shrink: 0;
}
</style>

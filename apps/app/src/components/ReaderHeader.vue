<template>
  <view class="header">
    <view class="head-top">
      <view class="title-block">
        <text v-if="detail.title_zh" class="title-zh">{{ detail.title_zh }}</text>
        <text class="title">{{ detail.title }}</text>
      </view>
      <view class="tags">
        <text v-for="(label, i) in tags" :key="i" class="tag">{{ label }}</text>
      </view>
    </view>
    <view class="meta">
      <text class="meta-item">{{ t("reading.reader.words", { n: detail.word_count }) }}</text>
      <text class="meta-item">{{ t("reading.reader.newWords", { n: detail.new_word_count }) }}</text>
      <text class="meta-item">{{ t("reading.reader.newWordRate", { n: (detail.new_word_rate * 100).toFixed(1) }) }}</text>
    </view>
    <view class="toolbar">
      <view class="mode-switch">
        <view class="mode" :class="{ active: mode === 'ruby' }" @click="emit('update:mode', 'ruby')">
          {{ t("reading.reader.rubyMode") }}
        </view>
        <view class="mode" :class="{ active: mode === 'original' }" @click="emit('update:mode', 'original')">
          {{ t("reading.reader.originalMode") }}
        </view>
      </view>
      <view class="speak-all" :class="{ playing }" @click="emit('toggle-speak-all')">
        {{ playing ? t("reading.reader.stopSpeak") : t("reading.reader.speakAll") }}
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { ReadingDetail } from "../api/reading";
import { topicTags } from "../utils/topics";

const props = defineProps<{
  detail: ReadingDetail;
  mode: "ruby" | "original";
  playing: boolean;
}>();
const emit = defineEmits<{
  "update:mode": [mode: "ruby" | "original"];
  "toggle-speak-all": [];
}>();

const { t } = useI18n();

const tags = computed(() => topicTags(props.detail));
</script>

<style scoped>
.header {
  background: #fff;
  border-radius: 20rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.head-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16rpx;
}
.title-block {
  flex: 1;
  margin-right: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}
.title-zh {
  font-size: 40rpx;
  font-weight: 800;
  color: var(--ink);
  line-height: 1.3;
}
.title {
  font-size: 28rpx;
  font-weight: 500;
  color: var(--ink-4);
  line-height: 1.4;
}
.tags {
  display: flex;
  gap: 8rpx;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.tag {
  flex-shrink: 0;
  font-size: 22rpx;
  color: var(--brand);
  background: var(--soft);
  padding: 6rpx 16rpx;
  border-radius: 8rpx;
}
.meta {
  display: flex;
  gap: 28rpx;
}
.meta-item {
  font-size: 24rpx;
  color: var(--ink-4);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 20rpx;
  margin-top: 24rpx;
}
.mode-switch {
  flex: 1;
  display: flex;
  background: var(--soft);
  border-radius: 12rpx;
  padding: 6rpx;
}
.mode {
  flex: 1;
  text-align: center;
  padding: 14rpx 0;
  font-size: 26rpx;
  color: var(--ink-3);
  border-radius: 8rpx;
}
.mode.active {
  background: #fff;
  color: var(--brand);
  font-weight: 600;
}
.speak-all {
  flex-shrink: 0;
  padding: 14rpx 28rpx;
  font-size: 26rpx;
  font-weight: 600;
  color: var(--brand);
  background: var(--soft);
  border-radius: 12rpx;
}
.speak-all.playing {
  color: var(--danger);
  background: var(--danger-bg);
}
</style>

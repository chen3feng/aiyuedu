<template>
  <view class="page">
    <view class="tabs">
      <view
        v-for="t in tabs"
        :key="t.key"
        class="tab"
        :class="{ active: activeTopic === t.key }"
        @click="setTopic(t.key)"
      >
        {{ t.label }}
      </view>
    </view>

    <view v-if="loading" class="loading">加载中…</view>
    <view v-else-if="error" class="error">{{ error }}</view>
    <view v-else class="cards">
      <view v-for="r in items" :key="r.id" class="card" @click="open(r.id)">
        <view class="card-top">
          <text class="title">{{ r.title }}</text>
          <text class="tag">{{ r.topic_label }}</text>
        </view>
        <view class="meta">
          <text class="meta-item">{{ r.word_count }} 词</text>
          <text class="meta-item">生词率 {{ (r.new_word_rate * 100).toFixed(1) }}%</text>
        </view>
      </view>
      <view v-if="!items.length" class="empty">该主题暂无文章</view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { listReadings } from "../../api/reading";
import type { ReadingSummary } from "../../api/reading";

const tabs = [
  { key: "", label: "全部" },
  { key: "science", label: "科普/科技" },
  { key: "sports", label: "体育/游戏/汽车" },
  { key: "history", label: "历史/名人" },
  { key: "adventure", label: "冒险/科幻/悬疑" },
];

// 读者词汇量：优先用评测结果（若已存），否则默认初一估算 3600
const level = ref<number>(Number(uni.getStorageSync("vocab_size")) || 3600);
const activeTopic = ref("");
const items = ref<ReadingSummary[]>([]);
const loading = ref(false);
const error = ref("");

onLoad(() => {
  fetchList();
});

async function fetchList() {
  loading.value = true;
  error.value = "";
  try {
    const resp = await listReadings(level.value, activeTopic.value || undefined);
    items.value = resp.items;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function setTopic(key: string) {
  activeTopic.value = key;
  fetchList();
}

function open(id: string) {
  uni.navigateTo({ url: `/pages/reading/reader?id=${id}&level=${level.value}` });
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f4f6fb;
  padding: 24rpx 32rpx;
  box-sizing: border-box;
}
.tabs {
  display: flex;
  gap: 16rpx;
  overflow-x: auto;
  padding-bottom: 8rpx;
  margin-bottom: 24rpx;
}
.tab {
  flex-shrink: 0;
  padding: 14rpx 28rpx;
  border-radius: 999rpx;
  background: #fff;
  color: #6a7591;
  font-size: 26rpx;
}
.tab.active {
  background: #4f7cff;
  color: #fff;
  font-weight: 600;
}
.loading,
.error,
.empty {
  text-align: center;
  color: #8a94ad;
  font-size: 28rpx;
  padding: 80rpx 0;
}
.error {
  color: #fa5151;
}
.cards {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}
.card {
  background: #fff;
  border-radius: 20rpx;
  padding: 32rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.card:active {
  transform: scale(0.99);
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20rpx;
}
.title {
  font-size: 34rpx;
  font-weight: 700;
  color: #1f2d50;
  flex: 1;
  margin-right: 20rpx;
}
.tag {
  flex-shrink: 0;
  font-size: 22rpx;
  color: #4f7cff;
  background: #eef2fb;
  padding: 6rpx 16rpx;
  border-radius: 8rpx;
}
.meta {
  display: flex;
  gap: 32rpx;
}
.meta-item {
  font-size: 24rpx;
  color: #8a94ad;
}
</style>

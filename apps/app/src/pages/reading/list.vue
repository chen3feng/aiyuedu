<template>
  <view class="page">
    <view class="tabs">
      <view
        v-for="tab in tabs"
        :key="tab.key"
        class="tab"
        :class="{ active: activeTopic === tab.key }"
        @click="setTopic(tab.key)"
      >
        {{ t(tab.labelKey) }}
      </view>
    </view>

    <view v-if="loading" class="loading">{{ t("common.loading") }}</view>
    <view v-else-if="error" class="error">{{ error }}</view>
    <view v-else class="cards">
      <view v-for="r in items" :key="r.id" class="card" @click="open(r.id)">
        <view class="card-top">
          <view class="title-block">
            <text v-if="r.title_zh" class="title-zh">{{ r.title_zh }}</text>
            <text class="title">{{ r.title }}</text>
          </view>
          <view class="tags">
            <text v-for="(label, i) in topicTags(r)" :key="i" class="tag">{{ label }}</text>
          </view>
        </view>
        <view class="meta">
          <text class="meta-item">{{ t("reading.list.wordCount", { n: r.word_count }) }}</text>
          <text class="meta-item">{{ t("reading.list.newWordRate", { n: (r.new_word_rate * 100).toFixed(1) }) }}</text>
        </view>
      </view>
      <view v-if="!items.length" class="empty">{{ t("reading.list.empty") }}</view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { listReadings } from "../../api/reading";
import type { ReadingSummary } from "../../api/reading";
import { getProfile } from "../../api/users";

const { t } = useI18n();

const tabs = [
  { key: "", labelKey: "reading.list.all" },
  { key: "science", labelKey: "topic.science" },
  { key: "sports", labelKey: "topic.sports" },
  { key: "history", labelKey: "topic.history" },
  { key: "adventure", labelKey: "topic.adventure" },
];

// 多主题中文名直接来自后端 topic_labels；标签缺失回退主题 key
function topicTags(r: ReadingSummary): string[] {
  const labels = r.topic_labels || [];
  return (r.topics || []).map((k, i) => labels[i] || k);
}

// 读者词汇量：优先用评测结果（若已存），否则默认初一估算 3600
const level = ref<number>(Number(uni.getStorageSync("vocab_size")) || 3600);
const activeTopic = ref("");
const items = ref<ReadingSummary[]>([]);
const loading = ref(false);
const error = ref("");

onLoad(() => {
  applyPrefThenFetch();
});

async function applyPrefThenFetch() {
  if (!activeTopic.value) {
    try {
      const p = await getProfile();
      if (p.topic_preferences && p.topic_preferences.length) {
        activeTopic.value = p.topic_preferences[0];
      }
    } catch {
      /* 后端不可用则保持「全部」 */
    }
  }
  fetchList();
}

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.reading") });
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
  align-items: flex-start;
  margin-bottom: 20rpx;
}
.title-block {
  flex: 1;
  margin-right: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.title-zh {
  font-size: 34rpx;
  font-weight: 700;
  color: #1f2d50;
  line-height: 1.3;
}
.title {
  font-size: 24rpx;
  color: #8a94ad;
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

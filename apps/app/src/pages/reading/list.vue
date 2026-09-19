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

    <!-- 书籍 tab：作品集网格 -->
    <view v-if="currentView === 'collections'">
      <view v-if="loadingCollections" class="loading">{{ t("common.loading") }}</view>
      <view v-else-if="collectionsError" class="error">{{ collectionsError }}</view>
      <view v-else class="collections-grid">
        <view v-for="c in collections" :key="c.id" class="coll-card" @click="openCollection(c.id)">
          <view class="coll-cover">
            <image v-if="c.cover_url" :src="c.cover_url" mode="aspectFill" class="cover-img"></image>
            <text v-else class="cover-fallback">{{ (c.title_zh || c.title).slice(0, 2) }}</text>
          </view>
          <view class="coll-info">
            <text v-if="c.title_zh" class="coll-title-zh">{{ c.title_zh }}</text>
            <text class="coll-title">{{ c.title }}</text>
            <text class="coll-author">{{ c.author }}</text>
            <view class="coll-meta">
              <text class="meta-item">{{ c.total_chapters }} 章</text>
              <text v-if="c.glossary_size" class="meta-item">· {{ c.glossary_size }} 词</text>
            </view>
          </view>
        </view>
        <view v-if="!collections.length" class="empty">{{ t("reading.list.empty") }}</view>
      </view>
    </view>

    <!-- 文章列表（按主题） -->
    <view v-else>
      <view v-if="loading" class="loading">{{ t("common.loading") }}</view>
      <view v-else-if="error" class="error">{{ error }}</view>
      <view v-else class="cards">
        <view v-for="r in items" :key="r.id" class="card" @click="open(r.id)">
          <view class="card-top">
            <view class="title-block">
              <text v-if="r.title_zh" class="title-zh">{{ r.title_zh }}</text>
              <text class="title">{{ r.title }}</text>
              <text v-if="r.collection_title_zh || r.collection_title" class="coll-tag">
                {{ r.collection_title_zh || r.collection_title }} · {{ r.chapter_index }}/{{ r.collection_total_chapters }}
              </text>
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
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { listReadings } from "../../api/reading";
import type { ReadingSummary } from "../../api/reading";
import { listCollections, type CollectionSummary } from "../../api/collections";
import { getProfile } from "../../api/users";

const { t, locale } = useI18n();

// 顶部 tab：第一项是「全部 / 书籍」切换，后四项是 topics
type Tab = { key: string; labelKey: string; view: "list" | "collections" };
const tabs: Tab[] = [
  { key: "", labelKey: "reading.list.all", view: "list" },
  { key: "books", labelKey: "reading.reader.collections", view: "collections" },
  { key: "science", labelKey: "topic.science", view: "list" },
  { key: "sports", labelKey: "topic.sports", view: "list" },
  { key: "history", labelKey: "topic.history", view: "list" },
  { key: "adventure", labelKey: "topic.adventure", view: "list" },
];

const currentView = computed<"list" | "collections">(() => {
  const tab = tabs.find((t) => t.key === activeTopic.value);
  return tab?.view ?? "list";
});

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

// 书籍 tab 状态
const collections = ref<CollectionSummary[]>([]);
const loadingCollections = ref(false);
const collectionsError = ref("");

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

async function fetchCollections() {
  loadingCollections.value = true;
  collectionsError.value = "";
  try {
    const resp = await listCollections();
    collections.value = resp.items;
  } catch (e) {
    collectionsError.value = (e as Error).message;
  } finally {
    loadingCollections.value = false;
  }
}

function setTopic(key: string) {
  activeTopic.value = key;
  const tab = tabs.find((t) => t.key === key);
  if (tab?.view === "collections") {
    if (!collections.value.length && !loadingCollections.value) fetchCollections();
  } else {
    fetchList();
  }
}

function open(id: string) {
  uni.navigateTo({ url: `/pages/reading/reader?id=${id}&level=${level.value}` });
}

function openCollection(id: string) {
  uni.navigateTo({ url: `/pages/reading/collection-detail?id=${id}` });
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

/* 书籍网格 */
.collections-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20rpx;
}
.coll-card {
  background: #fff;
  border-radius: 16rpx;
  overflow: hidden;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.coll-card:active {
  transform: scale(0.99);
}
.coll-cover {
  width: 100%;
  aspect-ratio: 3 / 4;
  background: linear-gradient(135deg, #4f7cff 0%, #6c5ce7 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
.cover-img {
  width: 100%;
  height: 100%;
}
.cover-fallback {
  font-size: 80rpx;
  font-weight: 800;
  color: #fff;
}
.coll-info {
  padding: 16rpx 20rpx 20rpx;
}
.coll-title-zh {
  display: block;
  font-size: 30rpx;
  font-weight: 700;
  color: #1f2d50;
  line-height: 1.3;
}
.coll-title {
  display: block;
  font-size: 22rpx;
  color: #8a94ad;
  margin-top: 4rpx;
}
.coll-author {
  display: block;
  font-size: 22rpx;
  color: #6a7591;
  margin-top: 8rpx;
}
.coll-meta {
  display: flex;
  gap: 8rpx;
  font-size: 22rpx;
  color: #8a94ad;
  margin-top: 8rpx;
}

/* 列表中 collection 章节的小标识 */
.coll-tag {
  display: block;
  font-size: 22rpx;
  color: #4f7cff;
  background: #eef2fb;
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
  margin-top: 6rpx;
  align-self: flex-start;
}
</style>

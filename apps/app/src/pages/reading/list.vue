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

    <StateView v-if="loading" type="loading" :message="t('common.loading')" />
    <StateView v-else-if="error" type="error" :message="error" />
    <view v-else class="cards">
      <Card
        v-for="r in items"
        :key="r.id" 
        :class="{ 'book-card': r.is_collection }"
        @click="open(r)"
      >
        <!-- 作品集整体入口：书籍卡片 -->
        <template v-if="r.is_collection">
          <view class="book-row">
            <BookCover
              :cover-url="r.cover_url"
              :fallback="(r.title_zh || r.title).slice(0, 2)"
            />
            <view class="book-info">
              <text v-if="r.title_zh" class="book-title-zh">{{ r.title_zh }}</text>
              <text class="book-title">{{ r.title }}</text>
              <text v-if="r.author" class="book-author">{{ r.author }}</text>
              <text v-if="latestForCollection(r.id)" class="book-progress">
                {{ t("reading.list.lastChapter", { n: latestForCollection(r.id)!.chapter_index ?? 1 }) }}
                · {{ pct(latestForCollection(r.id)!.completed_ratio) }}
              </text>
              <text v-else class="book-chapters">📖 {{ r.total_chapters }} {{ t("reading.list.chapters") }}</text>
            </view>
            <text class="book-arrow">›</text>
          </view>
        </template>

        <!-- 单篇阅读文章 -->
        <template v-else>
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
            <text v-if="progressOf(r.id)" class="meta-item continue">
              {{ t("reading.list.continue") }} · {{ pct(progressOf(r.id)!.completed_ratio) }}
            </text>
          </view>
          <view v-if="progressOf(r.id)" class="progress-track">
            <view class="progress-fill" :style="{ width: pct(progressOf(r.id)!.completed_ratio) }" />
          </view>
        </template>
      </Card>
      <StateView v-if="!items.length" type="empty" :message="t('reading.list.empty')" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { listReadings } from "../../api/reading";
import { listReadingProgress, type ReadingProgress } from "../../api/history";
import StateView from "../../components/StateView.vue";
import Card from "../../components/Card.vue";
import BookCover from "../../components/BookCover.vue";
import type { ReadingSummary } from "../../api/reading";
import { getProfile } from "../../api/users";
import { topicTags, TOPICS } from "../../utils/topics";

const { t } = useI18n();

// 顶部 tab：全部 + 4 个主题（书籍作为「全部」里的整体入口出现，不单独建 tab）
const tabs = [{ key: "", labelKey: "reading.list.all" }, ...TOPICS.map(
  (tp) => ({ key: tp.key, labelKey: tp.labelKey }),
)];

// 读者词汇量：优先用评测结果（若已存），否则默认初一估算 3600
const level = ref<number>(Number(uni.getStorageSync("vocab_size")) || 3600);
const activeTopic = ref("");
const items = ref<ReadingSummary[]>([]);
const progress = ref<ReadingProgress[]>([]);
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
    const [resp, prog] = await Promise.all([
      listReadings(level.value, activeTopic.value || undefined),
      listReadingProgress().catch(() => ({ items: [] as ReadingProgress[] })),
    ]);
    items.value = resp.items;
    progress.value = prog.items;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function progressOf(readingId: string): ReadingProgress | undefined {
  return progress.value.find((p) => p.reading_id === readingId);
}

/** 作品集：取各章节里最后读的那一章。 */
function latestForCollection(collectionId: string): ReadingProgress | undefined {
  return progress.value
    .filter((p) => p.collection_id === collectionId)
    .sort((a, b) => b.ts - a.ts)[0];
}

function pct(ratio: number) {
  return `${Math.round(Math.min(1, Math.max(0, ratio || 0)) * 100)}%`;
}

function setTopic(key: string) {
  activeTopic.value = key;
  fetchList();
}

function open(r: ReadingSummary) {
  if (r.is_collection) {
    // 有进度直接续读上次章节，否则进书籍详情
    const latest = latestForCollection(r.id);
    if (latest) {
      const lv = latest.level || level.value;
      uni.navigateTo({
        url: `/pages/reading/reader?id=${encodeURIComponent(latest.reading_id)}&level=${lv}`,
      });
      return;
    }
    uni.navigateTo({ url: `/pages/reading/collection-detail?id=${r.id}` });
  } else {
    uni.navigateTo({ url: `/pages/reading/reader?id=${r.id}&level=${level.value}` });
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
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
  color: var(--ink-3);
  font-size: 26rpx;
}
.tab.active {
  background: var(--brand);
  color: #fff;
  font-weight: 600;
}
.cards {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
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
  color: var(--ink);
  line-height: 1.3;
}
.title {
  font-size: 24rpx;
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
  gap: 32rpx;
}
.meta-item {
  font-size: 24rpx;
  color: var(--ink-4);
}
.meta-item.continue {
  color: var(--brand);
  font-weight: 600;
}
.progress-track {
  margin-top: 16rpx;
  height: 8rpx;
  border-radius: 999rpx;
  background: var(--soft);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 999rpx;
  background: var(--brand);
}

/* 作品集（书籍）整体入口卡片 */
.book-card {
  padding: 24rpx 28rpx;
}
.book-row {
  display: flex;
  align-items: center;
  gap: 20rpx;
}
.book-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}
.book-title-zh {
  font-size: 30rpx;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.3;
}
.book-title {
  font-size: 22rpx;
  color: var(--ink-4);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}
.book-author {
  font-size: 22rpx;
  color: var(--ink-3);
}
.book-chapters {
  font-size: 22rpx;
  color: var(--brand);
  background: var(--soft);
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
  align-self: flex-start;
  margin-top: 4rpx;
}
.book-progress {
  font-size: 22rpx;
  color: var(--brand);
  font-weight: 600;
  margin-top: 4rpx;
}
.book-arrow {
  font-size: 40rpx;
  color: var(--line);
  flex-shrink: 0;
}
</style>

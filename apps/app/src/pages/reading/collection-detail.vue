<template>
  <view class="page">
    <StateView v-if="loading" type="loading" :message="t('common.loading')" />
    <StateView v-else-if="error" type="error" :message="error" />
    <view v-else-if="detail">
      <!-- 书籍信息卡 -->
      <view class="header">
        <BookCover
          size="lg"
          :cover-url="detail.cover_url"
          :fallback="(detail.title_zh || detail.title).slice(0, 2)"
        />
        <view class="meta-block">
          <text v-if="detail.title_zh" class="title-zh">{{ detail.title_zh }}</text>
          <text class="title">{{ detail.title }}</text>
          <text v-if="detail.author" class="author">{{ detail.author }}</text>
          <text v-if="detail.intro_zh" class="intro">{{ detail.intro_zh }}</text>
          <view class="stats">
            <text class="stat-item">📖 {{ detail.total_chapters }} 章</text>
            <text v-if="glossaryCount" class="stat-item">📚 {{ glossaryCount }} 词</text>
          </view>
        </view>
      </view>

      <!-- 章节列表 -->
      <ChapterList :chapters="detail.chapters" @open="openChapter" />

      <!-- 全书统一词汇表 -->
      <Card class="p24 mb" v-if="glossaryCount" >
        <text class="card-label">全书词汇表（{{ glossaryCount }}）</text>
        <view class="glossary-grid">
          <view v-for="(gloss, word) in detail.glossary" :key="word" class="gl-item">
            <text class="gl-word">{{ word }}</text>
            <text class="gloss">{{ gloss }}</text>
          </view>
        </view>
      </Card>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { getCollection } from "../../api/collections";
import type { CollectionDetail } from "../../api/collections";
import StateView from "../../components/StateView.vue";
import Card from "../../components/Card.vue";
import BookCover from "../../components/BookCover.vue";
import ChapterList from "../../components/ChapterList.vue";

const { t } = useI18n();

const detail = ref<CollectionDetail | null>(null);
const loading = ref(false);
const error = ref("");

const glossaryCount = computed(() => Object.keys(detail.value?.glossary || {}).length);

async function fetchDetail(id: string) {
  loading.value = true;
  error.value = "";
  try {
    detail.value = await getCollection(id);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function openChapter(id: string) {
  uni.navigateTo({ url: `/pages/reading/reader?id=${id}` });
}

onLoad((query) => {
  if (query?.id) fetchDetail(String(query.id));
});

onShow(() => {
  uni.setNavigationBarTitle({
    title: detail.value?.title_zh || detail.value?.title || t("nav.reading"),
  });
});
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 24rpx 32rpx 60rpx;
  box-sizing: border-box;
}

.header {
  display: flex;
  gap: 24rpx;
  background: #fff;
  border-radius: 20rpx;
  padding: 24rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.meta-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
  min-width: 0;
}
.title-zh {
  font-size: 36rpx;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.3;
}
.title {
  font-size: 24rpx;
  color: var(--ink-4);
}
.author {
  font-size: 24rpx;
  color: var(--ink-3);
  margin-top: 4rpx;
}
.intro {
  font-size: 24rpx;
  color: var(--ink-3);
  line-height: 1.5;
  margin-top: 8rpx;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.stats {
  display: flex;
  gap: 16rpx;
  font-size: 22rpx;
  color: var(--ink-4);
  margin-top: auto;
}
.stat-item {
  background: var(--bg);
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
}

.card-label {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 16rpx;
}
.glossary-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12rpx 16rpx;
}
.gl-item {
  display: flex;
  flex-direction: column;
  padding: 8rpx 0;
}
.gl-word {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--ink);
}
.gloss {
  font-size: 22rpx;
  color: var(--ink-3);
}
</style>
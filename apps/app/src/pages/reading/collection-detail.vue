<template>
  <view class="page">
    <view v-if="loading" class="loading">{{ t("common.loading") }}</view>
    <view v-else-if="error" class="error">{{ error }}</view>
    <view v-else-if="detail">
      <!-- 书籍信息卡 -->
      <view class="header">
        <view class="cover-wrap">
          <image v-if="detail.cover_url" :src="detail.cover_url" mode="aspectFill" class="cover"></image>
          <view v-else class="cover cover-fallback">
            <text>{{ (detail.title_zh || detail.title).slice(0, 2) }}</text>
          </view>
        </view>
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
      <view class="card">
        <text class="card-label">章节列表</text>
        <view
          v-for="ch in detail.chapters"
          :key="ch.index"
          class="chapter-row"
          @click="openChapter(ch.id)"
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
        <view v-if="!detail.chapters.length" class="empty">暂无章节</view>
      </view>

      <!-- 全书统一词汇表 -->
      <view v-if="glossaryCount" class="card">
        <text class="card-label">全书词汇表（{{ glossaryCount }}）</text>
        <view class="glossary-grid">
          <view v-for="(gloss, word) in detail.glossary" :key="word" class="gl-item">
            <text class="gl-word">{{ word }}</text>
            <text class="gloss">{{ gloss }}</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { getCollection } from "../../api/collections";
import type { CollectionDetail } from "../../api/collections";

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
  background: #f4f6fb;
  padding: 24rpx 32rpx 60rpx;
  box-sizing: border-box;
}
.loading {
  text-align: center;
  color: #8a94ad;
  font-size: 28rpx;
  padding: 80rpx 0;
}
.error {
  color: #fa5151;
  text-align: center;
  padding: 80rpx 0;
  font-size: 28rpx;
}
.empty {
  text-align: center;
  color: #8a94ad;
  font-size: 26rpx;
  padding: 40rpx 0;
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
.cover-wrap {
  flex-shrink: 0;
  width: 180rpx;
  height: 240rpx;
  border-radius: 12rpx;
  overflow: hidden;
  background: linear-gradient(135deg, #4f7cff 0%, #6c5ce7 100%);
}
.cover {
  width: 100%;
  height: 100%;
}
.cover-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
}
.cover-fallback text {
  font-size: 60rpx;
  font-weight: 800;
  color: #fff;
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
  color: #1f2d50;
  line-height: 1.3;
}
.title {
  font-size: 24rpx;
  color: #8a94ad;
}
.author {
  font-size: 24rpx;
  color: #6a7591;
  margin-top: 4rpx;
}
.intro {
  font-size: 24rpx;
  color: #6a7591;
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
  color: #8a94ad;
  margin-top: auto;
}
.stat-item {
  background: #f4f6fb;
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
}

.card {
  background: #fff;
  border-radius: 20rpx;
  padding: 24rpx 28rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.card-label {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1f2d50;
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
  background: #eef2fb;
  color: #4f7cff;
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
  color: #1f2d50;
}
.ch-title {
  font-size: 22rpx;
  color: #8a94ad;
}
.ch-arrow {
  font-size: 36rpx;
  color: #c5cee0;
  flex-shrink: 0;
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
  color: #1f2d50;
}
.gloss {
  font-size: 22rpx;
  color: #6a7591;
}
</style>
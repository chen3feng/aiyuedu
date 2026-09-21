<template>
  <!-- collection 章节面包屑：书名 → 当前章 -->
  <view v-if="detail?.collection" class="breadcrumb">
    <text class="crumb-link" @click="goCollection">
      {{ detail.collection.title_zh || detail.collection.title }}
    </text>
    <text class="crumb-sep">›</text>
    <text class="crumb-current">{{ detail.title_zh || detail.chapter_title || detail.title }}</text>
  </view>
</template>

<script setup lang="ts">
import type { ReadingDetail } from "../api/reading";

const props = defineProps<{ detail: ReadingDetail | null }>();

function goCollection() {
  // collection-detail 是固定页面，跳转不依赖 reader 状态，组件内自行处理
  const cid = props.detail?.collection?.id;
  if (cid) uni.redirectTo({ url: `/pages/reading/collection-detail?id=${cid}` });
}
</script>

<style scoped>
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8rpx;
  font-size: 24rpx;
  color: var(--ink-4);
  margin-bottom: 16rpx;
  padding: 8rpx 0;
}
.crumb-link {
  color: var(--brand);
}
.crumb-sep {
  color: var(--line);
}
.crumb-current {
  color: var(--ink);
  font-weight: 600;
}
</style>

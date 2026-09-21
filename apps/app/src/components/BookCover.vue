<template>
  <view class="book-cover" :class="{ lg: size === 'lg' }">
    <image v-if="coverUrl" :src="coverUrl" mode="aspectFill" class="cover-img" />
    <text v-else class="cover-fallback">{{ fallback }}</text>
  </view>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    coverUrl?: string | null;
    // 无封面图时显示的文字（一般取标题前两字）
    fallback: string;
    size?: "sm" | "lg";
  }>(),
  { size: "sm" },
);
</script>

<style scoped>
/* 默认尺寸：阅读列表书籍卡 100 × 134 */
.book-cover {
  flex-shrink: 0;
  width: 100rpx;
  height: 134rpx;
  border-radius: 10rpx;
  overflow: hidden;
  background: linear-gradient(135deg, var(--brand) 0%, #6c5ce7 100%);
  display: flex;
  align-items: center;
  justify-content: center;
}
.cover-img {
  width: 100%;
  height: 100%;
}
.cover-fallback {
  font-size: 40rpx;
  font-weight: 800;
  color: #fff;
}
/* 大尺寸：书籍详情头卡 180 × 240 */
.book-cover.lg {
  width: 180rpx;
  height: 240rpx;
  border-radius: 12rpx;
}
.book-cover.lg .cover-fallback {
  font-size: 60rpx;
}
</style>

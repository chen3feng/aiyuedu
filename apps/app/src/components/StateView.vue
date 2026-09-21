<template>
  <!-- 列表 / 详情页通用状态：loading / error / empty；无 message 时走默认插槽 -->
  <view class="state" :class="type">
    <slot>{{ message }}</slot>
  </view>
</template>

<script setup lang="ts">
// 视觉微调通过组件上的 class 透传到根节点（与 .state 组合）：
//   compact —— padding 40rpx、字号 26rpx（章节内空态）
//   pad60   —— padding 60rpx、字号 26rpx
//   mt16/mt24 —— 行内错误：带上边距、无上下 padding、字号 26rpx
defineProps<{
  type: "loading" | "error" | "empty";
  message?: string;
}>();
</script>

<style scoped>
.state {
  text-align: center;
  font-size: 28rpx;
  padding: 80rpx 0;
}
.state.loading {
  color: var(--ink-4);
}
.state.error {
  color: var(--danger);
}
.state.empty {
  color: var(--ink-4);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16rpx;
}
.state.compact {
  padding: 40rpx 0;
  font-size: 26rpx;
}
.state.empty-lg {
  padding: 120rpx 40rpx;
}
.state.f26 {
  font-size: 26rpx;
}
.state.pad60 {
  padding: 60rpx 0;
  font-size: 26rpx;
}
.state.mt16 {
  margin-top: 16rpx;
  padding: 0;
  font-size: 26rpx;
}
.state.mt24 {
  margin-top: 24rpx;
  padding: 0;
  font-size: 26rpx;
}
</style>

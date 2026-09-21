<template>
  <!-- 通用白卡：默认 20rpx 圆角 + 轻阴影；padding / 大卡变体用类名微调。
       class 从父组件透传合并到根节点（如 p28 / lg p40 / mb / praise-card）。 -->
  <view class="card">
    <slot />
  </view>
</template>

<script setup lang="ts">
// 无 props：所有变体走类名（与根节点 .card 在同一作用域，覆盖顺序确定）
</script>

<style scoped>
.card {
  background: #fff;
  border-radius: 20rpx;
  padding: 32rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
/* padding 变体（与此前各页面手写值一一对应） */
.card.p28 {
  padding: 28rpx 32rpx;
}
.card.p24 {
  padding: 24rpx 28rpx;
}
.card.p40 {
  padding: 40rpx 32rpx;
}
.card.p48 {
  padding: 48rpx 40rpx;
}
.card.mb {
  margin-bottom: 20rpx;
}
/* 大卡：更大圆角 + 更柔的扩散阴影（settings / assessment） */
.card.lg {
  border-radius: 24rpx;
  box-shadow: 0 8rpx 32rpx rgba(31, 45, 80, 0.06);
}
/* 按压反馈（原先只在 list / compose 的卡片上手写） */
.card:active {
  transform: scale(0.99);
}
</style>

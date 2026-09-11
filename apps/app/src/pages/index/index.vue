<template>
  <view class="home">
    <view class="hero">
      <text class="app-name">英语学习</text>
      <text class="slogan">从词汇量开始</text>
    </view>
    <button class="start-btn" @click="goAssessment">开始词汇量评测</button>
    <button class="reading-btn" @click="goReading">分级阅读</button>
  </view>
</template>

<script setup lang="ts">
function goAssessment() {
  uni.navigateTo({ url: "/pages/assessment/assessment" });
}
function goReading() {
  uni.navigateTo({ url: "/pages/reading/list" });
}
</script>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #f4f6fb;
  padding: 40rpx;
  box-sizing: border-box;
}
.hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 80rpx;
}
.app-name {
  font-size: 64rpx;
  font-weight: 800;
  color: #1f2d50;
}
.slogan {
  margin-top: 16rpx;
  font-size: 28rpx;
  color: #8a94ad;
}
.start-btn {
  width: 100%;
  background: #4f7cff;
  color: #fff;
  border-radius: 16rpx;
  font-size: 34rpx;
  font-weight: 600;
}
.reading-btn {
  width: 100%;
  margin-top: 24rpx;
  background: #fff;
  color: #4f7cff;
  border-radius: 16rpx;
  font-size: 34rpx;
  font-weight: 600;
}
</style>

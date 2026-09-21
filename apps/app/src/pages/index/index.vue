<template>
  <view class="home">
    <view class="hero">
      <text class="app-name">{{ t("appName") }}</text>
      <text class="slogan">{{ t("slogan") }}</text>
    </view>
    <button class="start-btn" @click="goAssessment">{{ t("home.start") }}</button>
    <button class="reading-btn" @click="goReading">{{ t("home.reading") }}</button>
    <button class="writing-btn" @click="goWriting">{{ t("nav.writing") }}</button>
    <view class="settings-link" @click="goSettings">{{ t("home.settings") }}</view>
  </view>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { onShow } from "@dcloudio/uni-app";

const { t } = useI18n();

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.home") });
});

function goAssessment() {
  uni.navigateTo({ url: "/pages/assessment/assessment" });
}
function goReading() {
  uni.navigateTo({ url: "/pages/reading/list" });
}
function goWriting() {
  uni.navigateTo({ url: "/pages/writing/index" });
}
function goSettings() {
  uni.navigateTo({ url: "/pages/settings/settings" });
}
</script>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--bg);
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
  color: var(--ink);
}
.slogan {
  margin-top: 16rpx;
  font-size: 28rpx;
  color: var(--ink-4);
}
.start-btn {
  width: 100%;
  background: var(--brand);
  color: #fff;
  border-radius: 16rpx;
  font-size: 34rpx;
  font-weight: 600;
}
.reading-btn,
.writing-btn {
  width: 100%;
  margin-top: 24rpx;
  background: #fff;
  color: var(--brand);
  border-radius: 16rpx;
  font-size: 34rpx;
  font-weight: 600;
}
.settings-link {
  margin-top: 36rpx;
  font-size: 26rpx;
  color: var(--ink-4);
}
</style>

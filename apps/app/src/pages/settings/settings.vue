<template>
  <view class="page">
    <view class="card">
      <view class="section-title">{{ t("settings.language") }}</view>
      <view
        v-for="opt in options"
        :key="opt.value"
        class="option"
        :class="{ active: langSetting === opt.value }"
        @click="choose(opt.value)"
      >
        <text class="label">{{ t(opt.key) }}</text>
        <text v-if="langSetting === opt.value" class="check">✓</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { onShow } from "@dcloudio/uni-app";
import { langSetting, setLanguage, type LangSetting } from "../../locale";

const { t } = useI18n();

const options: { value: LangSetting; key: string }[] = [
  { value: "auto", key: "settings.followSystem" },
  { value: "zh-CN", key: "settings.chinese" },
  { value: "en", key: "settings.english" },
];

onShow(() => {
  uni.setNavigationBarTitle({ title: t("settings.title") });
});

function choose(value: LangSetting) {
  setLanguage(value);
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f4f6fb;
  padding: 40rpx;
  box-sizing: border-box;
}
.card {
  background: #fff;
  border-radius: 24rpx;
  padding: 40rpx 32rpx;
  box-shadow: 0 8rpx 32rpx rgba(31, 45, 80, 0.06);
}
.section-title {
  font-size: 26rpx;
  color: #8a94ad;
  margin-bottom: 16rpx;
}
.option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 28rpx 20rpx;
  border-bottom: 2rpx solid #f0f2f8;
}
.option:last-child {
  border-bottom: none;
}
.label {
  font-size: 30rpx;
  color: #33405f;
}
.option.active .label {
  color: #4f7cff;
  font-weight: 700;
}
.check {
  font-size: 34rpx;
  color: #4f7cff;
  font-weight: 700;
}
</style>

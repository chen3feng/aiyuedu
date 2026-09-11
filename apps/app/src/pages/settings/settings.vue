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

    <view class="card">
      <view class="section-title">{{ t("settings.topicPref") }}</view>
      <view
        v-for="tp in TOPICS"
        :key="tp.key"
        class="option"
        :class="{ active: prefs.includes(tp.key) }"
        @click="toggleTopic(tp.key)"
      >
        <text class="label">{{ t(tp.labelKey) }}</text>
        <text v-if="prefs.includes(tp.key)" class="check">✓</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { onShow } from "@dcloudio/uni-app";
import { langSetting, setLanguage, type LangSetting } from "../../locale";
import { getProfile, saveProfile } from "../../api/users";

const { t } = useI18n();

const options: { value: LangSetting; key: string }[] = [
  { value: "auto", key: "settings.followSystem" },
  { value: "zh-CN", key: "settings.chinese" },
  { value: "en", key: "settings.english" },
];

const TOPICS = [
  { key: "science", labelKey: "topic.science" },
  { key: "sports", labelKey: "topic.sports" },
  { key: "history", labelKey: "topic.history" },
  { key: "adventure", labelKey: "topic.adventure" },
];

const prefs = ref<string[]>([]);

onShow(() => {
  uni.setNavigationBarTitle({ title: t("settings.title") });
  loadPrefs();
});

function choose(value: LangSetting) {
  setLanguage(value);
}

async function loadPrefs() {
  try {
    const p = await getProfile();
    prefs.value = p.topic_preferences || [];
  } catch {
    /* 后端不可用时保持现状 */
  }
}

function toggleTopic(key: string) {
  const idx = prefs.value.indexOf(key);
  if (idx >= 0) prefs.value.splice(idx, 1);
  else prefs.value.push(key);
  saveProfile({ topic_preferences: prefs.value }).catch(() => {});
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

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

    <view class="card">
      <view class="section-title">{{ t("settings.vocab") }}</view>
      <view class="option">
        <text class="label">{{ t("settings.vocabLabel") }}</text>
        <input
          class="vocab-input"
          type="number"
          v-model="vocabInput"
          placeholder="3600"
          @confirm="saveVocab"
          @blur="saveVocab"
        />
      </view>
      <view class="hint">{{ t("settings.vocabHint") }}</view>
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
const vocab = ref<number | null>(null);
const vocabInput = ref("");

onShow(() => {
  uni.setNavigationBarTitle({ title: t("settings.title") });
  loadProfile();
});

function choose(value: LangSetting) {
  setLanguage(value);
}

async function loadProfile() {
  try {
    const p = await getProfile();
    prefs.value = p.topic_preferences || [];
    vocab.value = p.vocab_size;
    vocabInput.value = p.vocab_size != null ? String(p.vocab_size) : "";
  } catch {
    // 后端不可用：回退本地缓存
    const local = Number(uni.getStorageSync("vocab_size"));
    vocab.value = local || null;
    vocabInput.value = local ? String(local) : "";
  }
}

function toggleTopic(key: string) {
  const idx = prefs.value.indexOf(key);
  if (idx >= 0) prefs.value.splice(idx, 1);
  else prefs.value.push(key);
  saveProfile({ topic_preferences: prefs.value }).catch(() => {});
}

function saveVocab() {
  const raw = vocabInput.value.trim();
  if (raw === "") {
    // 清空视为放弃修改，回退显示当前值
    vocabInput.value = vocab.value != null ? String(vocab.value) : "";
    return;
  }
  const v = Number(raw);
  if (!Number.isInteger(v) || v < 0) {
    vocabInput.value = vocab.value != null ? String(vocab.value) : "";
    return;
  }
  vocab.value = v;
  vocabInput.value = String(v);
  uni.setStorageSync("vocab_size", v);
  saveProfile({ vocab_size: v }).catch(() => {});
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
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
  color: var(--ink-4);
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
  color: var(--ink-2);
}
.option.active .label {
  color: var(--brand);
  font-weight: 700;
}
.check {
  font-size: 34rpx;
  color: var(--brand);
  font-weight: 700;
}
.vocab-input {
  width: 220rpx;
  text-align: right;
  font-size: 30rpx;
  color: var(--ink-2);
  background: var(--bg);
  border-radius: 12rpx;
  padding: 8rpx 16rpx;
}
.hint {
  margin-top: 12rpx;
  font-size: 24rpx;
  color: var(--ink-4);
  line-height: 1.5;
  padding: 0 20rpx 12rpx;
}
</style>

<template>
  <view class="page">
    <CheckList
      :title="t('settings.language')"
      :options="langOptions"
      :selected="[langSetting]"
      @select="(v) => choose(v as LangSetting)"
    />

    <CheckList
      multiple
      :title="t('settings.topicPref')"
      :options="topicOptions"
      :selected="prefs"
      @toggle="toggleTopic"
    />

    <Card class="lg p40" >
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
    </Card>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { onShow } from "@dcloudio/uni-app";
import { langSetting, setLanguage, type LangSetting } from "../../locale";
import { getProfile, saveProfile } from "../../api/users";
import Card from "../../components/Card.vue";
import CheckList from "../../components/CheckList.vue";
import { TOPICS } from "../../utils/topics";

const { t } = useI18n();

const langOptions: { value: LangSetting; labelKey: string }[] = [
  { value: "auto", labelKey: "settings.followSystem" },
  { value: "zh-CN", labelKey: "settings.chinese" },
  { value: "en", labelKey: "settings.english" },
];

const topicOptions = TOPICS.map((tp) => ({ value: tp.key, labelKey: tp.labelKey }));

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

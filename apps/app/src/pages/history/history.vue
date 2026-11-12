<template>
  <view class="page">
    <view class="tabs">
      <view
        v-for="tab in tabs"
        :key="tab.key"
        class="tab"
        :class="{ active: active === tab.key }"
        @click="switchTab(tab.key)"
      >
        {{ t(tab.labelKey) }}
      </view>
    </view>

    <StateView v-if="loading" type="loading" :message="t('common.loading')" />
    <StateView v-else-if="error" type="error" :message="error" />

    <template v-else>
      <!-- 词汇测试历史 -->
      <view v-if="active === 'vocab'" class="list">
        <Card v-for="(r, i) in vocabTests" :key="i" class="p24">
          <view class="row">
            <view class="row-main">
              <text class="main-title">{{ r.vocab_size }}</text>
              <text class="main-sub">{{ t("history.vocabSize") }} · {{ algoLabel(r.algo) }}</text>
            </view>
            <text class="time">{{ fmt(r.ts) }}</text>
          </view>
          <view class="detail">
            {{ t("history.vocabDetail", { total: r.total, correct: r.correct, unknown: r.unknown }) }}
          </view>
        </Card>
        <StateView v-if="!vocabTests.length" type="empty" :message="t('history.emptyVocab')" />
      </view>

      <!-- 阅读进度 -->
      <view v-else-if="active === 'reading'" class="list">
        <Card v-for="r in progress" :key="r.reading_id" class="p24" @click="openReading(r)">
          <view class="row">
            <view class="row-main">
              <text class="main-title">{{ r.title_zh || r.title }}</text>
              <text v-if="r.collection_title" class="main-sub">{{ r.collection_title }}</text>
            </view>
            <text class="time">{{ fmt(r.ts) }}</text>
          </view>
          <view class="progress-row">
            <view class="progress-track">
              <view class="progress-fill" :style="{ width: pct(r.completed_ratio) }" />
            </view>
            <text class="progress-text">{{ pct(r.completed_ratio) }}</text>
          </view>
        </Card>
        <StateView v-if="!progress.length" type="empty" :message="t('history.emptyReading')" />
      </view>

      <!-- 生词本 -->
      <view v-else class="list">
        <Card v-for="it in notebook" :key="it.word" class="p24">
          <view class="row">
            <view class="row-main">
              <view class="word-line">
                <text class="main-title">{{ it.word }}</text>
                <text v-if="it.phonetic" class="phonetic">{{ it.phonetic }}</text>
              </view>
              <text class="main-sub">{{ it.gloss || t("reading.reader.noGloss") }}</text>
            </view>
            <text class="remove" @click="removeWord(it.word)">×</text>
          </view>
        </Card>
        <StateView v-if="!notebook.length" type="empty" :message="t('history.emptyNotebook')" />
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { listReadingProgress, listVocabTests, type ReadingProgress, type VocabTestRecord } from "../../api/history";
import { listNotebook, removeNotebookItem, type NotebookItem } from "../../api/notebook";
import Card from "../../components/Card.vue";
import StateView from "../../components/StateView.vue";

type TabKey = "vocab" | "reading" | "notebook";

const { t } = useI18n();

const tabs: { key: TabKey; labelKey: string }[] = [
  { key: "vocab", labelKey: "history.tabVocab" },
  { key: "reading", labelKey: "history.tabReading" },
  { key: "notebook", labelKey: "history.tabNotebook" },
];

const active = ref<TabKey>("vocab");
const loading = ref(false);
const error = ref("");
const vocabTests = ref<VocabTestRecord[]>([]);
const progress = ref<ReadingProgress[]>([]);
const notebook = ref<NotebookItem[]>([]);

onShow(() => {
  uni.setNavigationBarTitle({ title: t("history.title") });
  load();
});

function switchTab(key: TabKey) {
  active.value = key;
  load();
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    if (active.value === "vocab") {
      vocabTests.value = (await listVocabTests()).items;
    } else if (active.value === "reading") {
      progress.value = (await listReadingProgress()).items;
    } else {
      const remote = (await listNotebook()).items;
      // 未登录时后端只看到匿名数据；再合并本机兜底生词本
      const local = (uni.getStorageSync("notebook") || []) as NotebookItem[];
      const seen = new Set(remote.map((it) => it.word));
      notebook.value = [...remote, ...(Array.isArray(local) ? local.filter((it) => !seen.has(it.word)) : [])];
    }
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

async function removeWord(word: string) {
  try {
    await removeNotebookItem(word);
  } catch {
    // 匿名本地兜底也要能删
  }
  const local = (uni.getStorageSync("notebook") || []) as NotebookItem[];
  if (Array.isArray(local)) {
    uni.setStorageSync("notebook", local.filter((it) => it.word !== word));
  }
  notebook.value = notebook.value.filter((it) => it.word !== word);
}

function openReading(r: ReadingProgress) {
  const level = r.level || Number(uni.getStorageSync("vocab_size")) || 3600;
  uni.navigateTo({ url: `/pages/reading/reader?id=${encodeURIComponent(r.reading_id)}&level=${level}` });
}

function pct(ratio: number) {
  return `${Math.round(Math.min(1, Math.max(0, ratio || 0)) * 100)}%`;
}

function fmt(ts: number) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function algoLabel(algo: string) {
  return algo === "eudic" ? t("assessment.algoEudic") : t("assessment.algoClassic");
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 24rpx 32rpx;
  box-sizing: border-box;
}
.tabs {
  display: flex;
  gap: 16rpx;
  margin-bottom: 24rpx;
}
.tab {
  flex: 1;
  text-align: center;
  padding: 14rpx 0;
  border-radius: 999rpx;
  background: #fff;
  color: var(--ink-3);
  font-size: 26rpx;
}
.tab.active {
  background: var(--brand);
  color: #fff;
  font-weight: 600;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 18rpx;
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16rpx;
}
.row-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}
.word-line {
  display: flex;
  align-items: baseline;
  gap: 12rpx;
}
.main-title {
  font-size: 32rpx;
  font-weight: 700;
  color: var(--ink);
}
.main-sub {
  font-size: 24rpx;
  color: var(--ink-4);
}
.phonetic {
  font-size: 24rpx;
  color: var(--ink-3);
}
.time {
  flex-shrink: 0;
  font-size: 22rpx;
  color: var(--ink-4);
}
.detail {
  margin-top: 12rpx;
  font-size: 24rpx;
  color: var(--ink-3);
}
.progress-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-top: 16rpx;
}
.progress-track {
  flex: 1;
  height: 10rpx;
  border-radius: 999rpx;
  background: var(--soft);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 999rpx;
  background: var(--brand);
}
.progress-text {
  font-size: 22rpx;
  color: var(--ink-4);
}
.remove {
  flex-shrink: 0;
  font-size: 36rpx;
  color: var(--ink-4);
  padding: 0 8rpx;
}
</style>

<template>
  <view class="page">
    <StateView v-if="loading" type="loading" :message="t('common.loading')" />
    <StateView v-else-if="error" type="error" :message="error" />
    <view v-else-if="essay">
      <!-- 顶部：题目标题 + 字数 -->
      <view class="header">
        <text class="title">{{ promptTitle(essay) }}</text>
        <view class="meta-row">
          <text class="meta-item">{{ t("writing.wordCount", { n: essay.word_count }) }}</text>
          <text v-if="essay.target_words" class="meta-item">·</text>
          <text v-if="essay.target_words" class="meta-item">{{ t("writing.target", { n: essay.target_words }) }}</text>
        </view>
      </view>

      <!-- AI 失败横幅 -->
      <view v-if="essay.reason" class="banner">
        <text class="banner-title">⚠️ {{ t("writing.aiFailed") }}</text>
        <text class="banner-body">{{ essay.reason }}</text>
      </view>

      <!-- 阶段一：逐句分屏 -->
      <SentenceReview
        v-if="sentences.length && phase === 'sentences'"
        :sentences="sentences"
        :start-index="reviewStart"
        @done="goSummary"
      />

      <!-- 阶段二：总结 + 全文朗读 -->
      <view v-else-if="sentences.length && phase === 'summary'" class="summary-screen">
        <Card class="p28 mb" >
          <text class="card-label">{{ t("writing.yourOriginal") }}</text>
          <text class="polished-full original">{{ essay.original }}</text>
        </Card>

        <Card class="p28 mb" >
          <text class="card-label">{{ t("writing.fullPolishedTitle") }}</text>
          <text class="polished-full">{{ fullPolishedText }}</text>
          <button
            class="speak-btn-big"
            :class="{ playing: speakingAll }"
            @click="onSpeakAll"
          >
            {{ speakingAll ? "■ 停止朗读" : "🔊 " + t("writing.listenFull") }}
          </button>
        </Card>

        <Card class="p28 mb" v-if="essay.report?.summary_table?.length" >
          <text class="card-label">{{ t("writing.summaryTable") }}</text>
          <view class="table">
            <view class="thead">
              <text class="th col-cat">类别</text>
              <text class="th col-ex">学生实例</text>
              <text class="th col-rule">应掌握</text>
            </view>
            <view v-for="(r, i) in essay.report.summary_table" :key="i" class="tr">
              <text class="td col-cat">{{ r.category }}</text>
              <text class="td col-ex">{{ (r.examples || []).join("；") }}</text>
              <text class="td col-rule">{{ r.rule }}</text>
            </view>
          </view>
        </Card>

        <Card class="p28 mb praise-card" v-if="essay.report?.praise" >
          <text class="praise-label">{{ t("writing.praise") }}</text>
          <text class="praise-text">{{ essay.report.praise }}</text>
        </Card>

        <view class="nav-row">
          <button class="btn-secondary" @click="goSentence(sentences.length - 1)">
            ← {{ t("writing.reviewSentences") }}
          </button>
          <button class="btn-primary" @click="goList">{{ t("writing.backToList") }}</button>
        </view>
      </view>

      <!-- 没有任何句子的报告（AI 整体失败）：直接展示原文 + 横幅，不进入逐句 -->
      <Card class="p28 mb" v-else >
        <text class="card-label">{{ t("writing.composeTitle") }}</text>
        <text class="original">{{ essay.original }}</text>
      </Card>

      <view v-if="phase === 'summary'" class="spacer"></view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, onBeforeUnmount } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { getEssay } from "../../api/writing";
import type { Essay, EssaySentenceReport } from "../../api/writing";
import { speakLines, stopSpeak } from "../../utils/tts";
import StateView from "../../components/StateView.vue";
import Card from "../../components/Card.vue";
import SentenceReview from "../../components/SentenceReview.vue";

const { t, locale } = useI18n();

const essay = ref<Essay | null>(null);
const loading = ref(false);
const error = ref("");

const phase = ref<"sentences" | "summary">("sentences");
// 逐句页重新挂载时的起始句下标（从总结页返回时定位到最后一句）
const reviewStart = ref(0);
const speakingIdx = ref(-1);
const speakingAll = ref(false);

function promptTitle(e: Essay): string {
  if (locale.value === "en" && e.prompt_title_en) return e.prompt_title_en;
  return e.prompt_title_zh || "（自由写作）";
}

const sentences = computed<EssaySentenceReport[]>(
  () => essay.value?.report?.sentences ?? [],
);
const fullPolishedText = computed(() =>
  sentences.value
    .map((s) => s.polished || s.corrected || s.original)
    .filter(Boolean)
    .join(" "),
);

async function fetchEssay(id: string) {
  loading.value = true;
  error.value = "";
  try {
    essay.value = await getEssay(id);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function goSentence(i: number) {
  // 逐句页随 v-if 重新挂载：停掉全文朗读，并把起始句传进去
  stopSpeak();
  speakingAll.value = false;
  speakingIdx.value = -1;
  reviewStart.value = i;
  phase.value = "sentences";
}

function goSummary() {
  if (speakingIdx.value !== -1) {
    stopSpeak();
    speakingIdx.value = -1;
  }
  phase.value = "summary";
}

function onSpeakAll() {
  if (speakingAll.value) {
    stopSpeak();
    speakingAll.value = false;
    speakingIdx.value = -1;
    return;
  }
  if (speakingIdx.value !== -1) stopSpeak();
  speakingIdx.value = -1;
  const lines = sentences.value
    .map((s) => s.polished || s.corrected || s.original)
    .filter(Boolean);
  if (!lines.length) return;
  const setAllEnd = () => {
    speakingAll.value = false;
    speakingIdx.value = -1;
  };
  const setLine = (i: number) => {
    speakingIdx.value = i;
  };
  const ok = speakLines(lines, "en-US", setLine, setAllEnd);
  if (ok) {
    speakingAll.value = true;
    speakingIdx.value = 0;
  }
}

function goList() {
  stopSpeak();
  uni.navigateBack({ delta: 1, fail: () => uni.redirectTo({ url: "/pages/writing/index" }) });
}

onLoad((query) => {
  if (query?.id) fetchEssay(String(query.id));
});

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.writing") });
});

onBeforeUnmount(() => {
  stopSpeak();
});
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 24rpx 32rpx 60rpx;
  box-sizing: border-box;
}
.header {
  margin-bottom: 20rpx;
}
.title {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 8rpx;
}
.meta-row {
  display: flex;
  gap: 12rpx;
  font-size: 24rpx;
  color: var(--ink-4);
}
.meta-item {
  font-size: 24rpx;
  color: var(--ink-4);
}
.banner {
  background: var(--danger-bg);
  border-left: 6rpx solid var(--danger);
  border-radius: 12rpx;
  padding: 20rpx 24rpx;
  margin-bottom: 20rpx;
}
.banner-title {
  display: block;
  font-size: 26rpx;
  font-weight: 700;
  color: var(--danger);
  margin-bottom: 8rpx;
}
.banner-body {
  display: block;
  font-size: 24rpx;
  color: var(--ink-3);
  line-height: 1.5;
}

.card-label {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 16rpx;
}

.nav-row {
  display: flex;
  gap: 16rpx;
  margin-top: 16rpx;
}
.btn-secondary,
.btn-primary {
  flex: 1;
  font-size: 28rpx;
  padding: 16rpx 0;
  border-radius: 999rpx;
  border: none;
}
.btn-secondary {
  background: #fff;
  color: var(--brand);
  border: 1rpx solid var(--soft);
}
.btn-secondary[disabled] {
  color: var(--line);
}
.btn-primary {
  background: var(--brand);
  color: #fff;
}

.polished-full {
  display: block;
  font-size: 28rpx;
  line-height: 1.8;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
  margin-bottom: 20rpx;
  background: var(--bg);
  padding: 20rpx 24rpx;
  border-radius: 12rpx;
}
.polished-full.original {
  color: var(--ink-3);
  text-decoration: line-through;
  text-decoration-color: var(--line);
}
.speak-btn-big {
  width: 100%;
  background: var(--brand);
  color: #fff;
  font-size: 28rpx;
  padding: 18rpx 0;
  border-radius: 999rpx;
  border: none;
}
.speak-btn-big.playing {
  background: var(--danger);
}

.table {
  border: 1rpx solid #f0f2f8;
  border-radius: 8rpx;
  overflow: hidden;
}
.thead,
.tr {
  display: flex;
  border-bottom: 1rpx solid #f0f2f8;
}
.tr:last-child {
  border-bottom: none;
}
.th,
.td {
  padding: 14rpx 16rpx;
  font-size: 24rpx;
  line-height: 1.5;
  word-break: break-word;
}
.th {
  font-weight: 700;
  color: var(--ink);
  background: var(--bg);
}
.col-cat {
  flex: 0 0 28%;
}
.col-ex {
  flex: 0 0 32%;
}
.col-rule {
  flex: 1;
}

.original {
  display: block;
  font-size: 28rpx;
  line-height: 1.7;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}

.praise-card {
  background: linear-gradient(135deg, #fff7e0 0%, #ffeac2 100%);
  border-left: 6rpx solid #ffb84d;
}
.praise-label {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #b35a00;
  margin-bottom: 8rpx;
}
.praise-text {
  display: block;
  font-size: 28rpx;
  line-height: 1.7;
  color: #5d4400;
}

.spacer {
  height: 60rpx;
}
</style>
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
      <ReportSummary
        v-else-if="sentences.length && phase === 'summary'"
        :essay="essay"
        :sentences="sentences"
        @review-sentences="goSentence(sentences.length - 1)"
        @back-list="goList"
      />

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
import { stopSpeak } from "../../utils/tts";
import StateView from "../../components/StateView.vue";
import Card from "../../components/Card.vue";
import SentenceReview from "../../components/SentenceReview.vue";
import ReportSummary from "../../components/ReportSummary.vue";

const { t, locale } = useI18n();

const essay = ref<Essay | null>(null);
const loading = ref(false);
const error = ref("");

const phase = ref<"sentences" | "summary">("sentences");
// 逐句页重新挂载时的起始句下标（从总结页返回时定位到最后一句）
const reviewStart = ref(0);

function promptTitle(e: Essay): string {
  if (locale.value === "en" && e.prompt_title_en) return e.prompt_title_en;
  return e.prompt_title_zh || "（自由写作）";
}

const sentences = computed<EssaySentenceReport[]>(
  () => essay.value?.report?.sentences ?? [],
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
  // 总结组件卸载时自行 stopSpeak；这里只传起始句并切阶段
  reviewStart.value = i;
  phase.value = "sentences";
}

// SentenceReview 完成前自行停掉单句朗读，再 emit done
function goSummary() {
  phase.value = "summary";
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
.original {
  display: block;
  font-size: 28rpx;
  line-height: 1.7;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}

.spacer {
  height: 60rpx;
}
</style>
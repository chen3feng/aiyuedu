<template>
  <view class="page">
    <view v-if="loading" class="loading">{{ t("common.loading") }}</view>
    <view v-else-if="error" class="error">{{ error }}</view>
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
      <view v-if="sentences.length && phase === 'sentences'" class="sentence-screen">
        <view class="progress">
          <view class="dots">
            <view
              v-for="(s, i) in sentences"
              :key="s.index"
              class="dot"
              :class="{ active: i === currentIdx, done: i < currentIdx, has_err: (s.errors?.length || 0) > 0 }"
              @click="goTo(i)"
            ></view>
          </view>
          <text class="progress-text">{{ currentIdx + 1 }} / {{ sentences.length }}</text>
        </view>

        <view class="card">
          <view class="s-header">
            <text class="s-index">#{{ currentSentence.index }}</text>
            <text class="s-original">{{ currentSentence.original }}</text>
          </view>

          <view v-if="currentSentence.errors?.length" class="errors">
            <view v-for="(e, i) in currentSentence.errors" :key="i" class="error-row">
              <text class="cb">{{ categoryLabel(e.category) }}</text>
              <text class="ce">{{ e.explanation }}</text>
              <text v-if="e.fix" class="cf">→ {{ e.fix }}</text>
            </view>
          </view>
          <view v-else class="ok-row">
            <text class="ok-icon">✓</text>
            <text class="ok-text">{{ noErrorText }}</text>
          </view>

          <view v-if="currentSentence.corrected" class="alt-row">
            <text class="alt-label">{{ t("writing.corrected") }}：</text>
            <text class="alt-text corrected">{{ currentSentence.corrected }}</text>
          </view>
          <view v-if="currentSentence.polished" class="alt-row">
            <text class="alt-label">{{ t("writing.polished") }}：</text>
            <text class="alt-text polished">{{ currentSentence.polished }}</text>
            <button
              class="speak-btn"
              :class="{ playing: speakingIdx === currentIdx }"
              @click="onSpeakSentence(currentIdx)"
            >
              {{ speakingIdx === currentIdx ? "■ 停止" : "🔊 朗读" }}
            </button>
          </view>
          <view v-if="currentSentence.polished_reason" class="reason-row">
            <text class="reason-label">💡 {{ t("writing.polishedReason") }}</text>
            <text class="reason-text">{{ currentSentence.polished_reason }}</text>
          </view>
        </view>

        <view class="nav-row">
          <button class="btn-secondary" :disabled="currentIdx === 0" @click="prev">
            ← {{ t("writing.prevSentence") }}
          </button>
          <button v-if="currentIdx < sentences.length - 1" class="btn-primary" @click="next">
            {{ t("writing.nextSentence") }} →
          </button>
          <button v-else class="btn-primary" @click="goSummary">
            {{ t("writing.viewSummary") }} →
          </button>
        </view>
      </view>

      <!-- 阶段二：总结 + 全文朗读 -->
      <view v-else-if="sentences.length && phase === 'summary'" class="summary-screen">
        <view class="card">
          <text class="card-label">{{ t("writing.yourOriginal") }}</text>
          <text class="polished-full original">{{ essay.original }}</text>
        </view>

        <view class="card">
          <text class="card-label">{{ t("writing.fullPolishedTitle") }}</text>
          <text class="polished-full">{{ fullPolishedText }}</text>
          <button
            class="speak-btn-big"
            :class="{ playing: speakingAll }"
            @click="onSpeakAll"
          >
            {{ speakingAll ? "■ 停止朗读" : "🔊 " + t("writing.listenFull") }}
          </button>
        </view>

        <view v-if="essay.report?.summary_table?.length" class="card">
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
        </view>

        <view v-if="essay.report?.praise" class="card praise-card">
          <text class="praise-label">{{ t("writing.praise") }}</text>
          <text class="praise-text">{{ essay.report.praise }}</text>
        </view>

        <view class="nav-row">
          <button class="btn-secondary" @click="goSentence(sentences.length - 1)">
            ← {{ t("writing.reviewSentences") }}
          </button>
          <button class="btn-primary" @click="goList">{{ t("writing.backToList") }}</button>
        </view>
      </view>

      <!-- 没有任何句子的报告（AI 整体失败）：直接展示原文 + 横幅，不进入逐句 -->
      <view v-else class="card">
        <text class="card-label">{{ t("writing.composeTitle") }}</text>
        <text class="original">{{ essay.original }}</text>
      </view>

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
import { speak, speakLines, stopSpeak } from "../../utils/tts";

const { t, locale } = useI18n();

const essay = ref<Essay | null>(null);
const loading = ref(false);
const error = ref("");

const phase = ref<"sentences" | "summary">("sentences");
const currentIdx = ref(0);
const speakingIdx = ref(-1);
const speakingAll = ref(false);

const CATEGORY_KEYS: Record<string, string> = {
  spell: "writing.categories.spell",
  plural: "writing.categories.plural",
  tense: "writing.categories.tense",
  sv_agree: "writing.categories.sv_agree",
  no_subject: "writing.categories.no_subject",
  literal: "writing.categories.literal",
  verb: "writing.categories.verb",
  prep: "writing.categories.prep",
  other: "writing.categories.other",
};

function categoryLabel(cat: string): string {
  const key = CATEGORY_KEYS[cat] || "writing.categories.other";
  return t(key);
}

function promptTitle(e: Essay): string {
  if (locale.value === "en" && e.prompt_title_en) return e.prompt_title_en;
  return e.prompt_title_zh || "（自由写作）";
}

const sentences = computed<EssaySentenceReport[]>(
  () => essay.value?.report?.sentences ?? [],
);
const currentSentence = computed<EssaySentenceReport>(
  () =>
      sentences.value[currentIdx.value] || { index: 0, original: "", errors: [], corrected: "", polished: "" },
);
const fullPolishedText = computed(() =>
  sentences.value
    .map((s) => s.polished || s.corrected || s.original)
    .filter(Boolean)
    .join(" "),
);
const noErrorText = computed(() =>
  locale.value === "en" ? "No errors in this sentence. Nice!" : "这句没问题，很棒！",
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

function goTo(i: number) {
  if (i < 0 || i >= sentences.value.length) return;
  // 切句前停掉上一句的朗读
  if (speakingIdx.value !== -1) {
    stopSpeak();
    speakingIdx.value = -1;
  }
  currentIdx.value = i;
  phase.value = "sentences";
}

function prev() {
  goTo(currentIdx.value - 1);
}

function next() {
  goTo(currentIdx.value + 1);
}

function goSentence(i: number) {
  currentIdx.value = i;
  phase.value = "sentences";
}

function goSummary() {
  if (speakingIdx.value !== -1) {
    stopSpeak();
    speakingIdx.value = -1;
  }
  phase.value = "summary";
}

function onSpeakSentence(i: number) {
  // 切换播放：点同一句 → 停；点不同句 → 切到新句
  if (speakingIdx.value === i) {
    stopSpeak();
    speakingIdx.value = -1;
    return;
  }
  if (speakingIdx.value !== -1 || speakingAll) {
    stopSpeak();
  }
  const s = sentences.value[i];
  const text = s.polished || s.corrected || s.original;
  if (!text) return;
  const ok = speak(text, "en-US", () => {
    // 自然播完（或回退浏览器 TTS 结束）→ 清除高亮；手动 stopSpeak 不走这里
    if (speakingIdx.value === i) speakingIdx.value = -1;
  });
  if (ok) speakingIdx.value = i;
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
.error {
  color: var(--danger);
  text-align: center;
  padding: 80rpx 0;
  font-size: 28rpx;
}
.loading {
  text-align: center;
  color: var(--ink-4);
  font-size: 28rpx;
  padding: 80rpx 0;
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

/* 进度条 */
.progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 20rpx;
}
.dots {
  display: flex;
  gap: 12rpx;
  flex-wrap: wrap;
  justify-content: center;
}
.dot {
  width: 20rpx;
  height: 20rpx;
  border-radius: 50%;
  background: #e0e6f0;
  transition: background 0.2s;
}
.dot.active {
  background: var(--brand);
  transform: scale(1.3);
}
.dot.done {
  background: #b8c5e0;
}
.dot.has_err {
  background: #ffb84d;
}
.dot.done.has_err {
  background: #ff9d2e;
}
.progress-text {
  font-size: 26rpx;
  color: var(--ink-3);
  font-weight: 600;
}

.card {
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx 32rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.card-label {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 16rpx;
}

.s-index {
  flex-shrink: 0;
  font-size: 22rpx;
  color: var(--ink-4);
  background: var(--soft);
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
}
.s-header {
  display: flex;
  gap: 12rpx;
  margin-bottom: 16rpx;
  align-items: flex-start;
}
.s-original {
  font-size: 30rpx;
  line-height: 1.6;
  color: var(--ink);
  flex: 1;
}

.errors {
  margin-bottom: 12rpx;
}
.error-row {
  background: #fff8e1;
  border-left: 4rpx solid #ffb84d;
  padding: 14rpx 18rpx;
  margin-bottom: 8rpx;
  border-radius: 6rpx;
}
.cb {
  display: inline-block;
  font-size: 22rpx;
  color: #b35a00;
  background: #fff;
  padding: 2rpx 10rpx;
  border-radius: 4rpx;
  margin-right: 12rpx;
}
.ce {
  font-size: 26rpx;
  color: #5d4400;
  line-height: 1.5;
}
.cf {
  display: block;
  font-size: 24rpx;
  color: var(--brand);
  margin-top: 6rpx;
}
.ok-row {
  background: #e7faf0;
  border-left: 4rpx solid var(--success);
  padding: 14rpx 18rpx;
  border-radius: 6rpx;
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.ok-icon {
  color: var(--success);
  font-size: 32rpx;
  font-weight: 700;
}
.ok-text {
  font-size: 26rpx;
  color: #1f7a3e;
}

.alt-row {
  margin-top: 12rpx;
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
  flex-wrap: wrap;
}
.alt-label {
  font-size: 22rpx;
  color: var(--ink-4);
  flex-shrink: 0;
  padding-top: 4rpx;
}
.alt-text {
  font-size: 26rpx;
  line-height: 1.6;
  flex: 1;
  min-width: 0;
}
.corrected {
  color: var(--ink);
}
.polished {
  color: var(--success);
}

.speak-btn {
  flex-shrink: 0;
  background: var(--soft);
  color: var(--brand);
  font-size: 22rpx;
  padding: 8rpx 18rpx;
  border-radius: 999rpx;
  border: none;
  margin-left: auto;
}
.speak-btn.playing {
  background: var(--brand);
  color: #fff;
}

.reason-row {
  margin-top: 12rpx;
  background: var(--bg);
  border-left: 4rpx solid var(--brand);
  padding: 12rpx 16rpx;
  border-radius: 6rpx;
}
.reason-label {
  display: block;
  font-size: 22rpx;
  font-weight: 600;
  color: var(--brand);
  margin-bottom: 4rpx;
}
.reason-text {
  font-size: 24rpx;
  line-height: 1.5;
  color: var(--ink);
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
<template>
  <view class="page">
    <!-- 介绍页 -->
    <view v-if="phase === 'intro'" class="intro">
      <view class="card">
        <view class="title">{{ t("assessment.title") }}</view>
        <view class="subtitle">{{ t("assessment.subtitle") }}</view>
        <view class="rules">
          <view class="rule-title">{{ t("assessment.howTo") }}</view>
          <view class="rule-row">
            <text class="dot ok"></text>
            <text class="rule-text">{{ t("assessment.knowRule") }}</text>
            <text class="score plus">{{ t("assessment.scoreUp") }}</text>
          </view>
          <view class="rule-row">
            <text class="dot neutral"></text>
            <text class="rule-text">{{ t("assessment.unknownRule") }}</text>
            <text class="score zero">{{ t("assessment.scoreLess") }}</text>
          </view>
          <view class="rule-row">
            <text class="dot bad"></text>
            <text class="rule-text">{{ t("assessment.guessWrong") }}</text>
            <text class="score minus">{{ t("assessment.extraPenalty") }}</text>
          </view>
        </view>
        <view class="hint">{{ t("assessment.honestHint") }}</view>
        <button class="btn primary" :loading="loading" @click="start">{{ t("assessment.start") }}</button>
        <view v-if="error" class="error">{{ error }}</view>
      </view>
    </view>

    <!-- 答题页 -->
    <view v-else-if="phase === 'quiz'" class="quiz">
      <view class="scorebar">
        <view class="score-main">
          <text class="score-label">{{ t("assessment.score") }}</text>
          <text class="score-value">{{ progress.score }}</text>
        </view>
        <view class="score-stats">
          <text class="stat">{{ t("assessment.questionN", { n: progress.total + 1 }) }}</text>
          <text class="stat ok">{{ t("assessment.correctN", { n: progress.correct }) }}</text>
          <text class="stat neutral">{{ t("assessment.unknownN", { n: progress.unknown }) }}</text>
          <text class="stat bad">{{ t("assessment.wrongN", { n: progress.wrong }) }}</text>
        </view>
      </view>

      <view class="word">{{ question.word }}</view>
      <view class="options">
        <view
          v-for="(opt, i) in question.options"
          :key="i"
          class="option"
          :class="optionClass(i)"
          @click="choose(i)"
        >
          <text class="opt-letter">{{ letters[i] }}</text>
          <text class="opt-text">{{ opt }}</text>
        </view>
      </view>
      <view
        class="unknown-btn"
        :class="{ active: selectedIndex === -1 }"
        @click="chooseUnknown"
      >
        {{ t("assessment.unknownWord") }}
      </view>
      <view v-if="progress.converged" class="converged-hint">
        {{ t("assessment.converged") }}
      </view>
      <view class="finish-btn" :class="{ disabled: loading }" @click="finish">
        {{ t("assessment.finish") }}
      </view>
      <view v-if="feedback" class="feedback" :class="feedback.response">
        <text class="fb-icon">{{ fbIcon }}</text>
        <text class="fb-text">{{ fbText }}</text>
      </view>
    </view>

    <!-- 结果页 -->
    <view v-else class="result">
      <view class="card">
        <view class="big-label">{{ t("assessment.yourVocab") }}</view>
        <view class="big-number">{{ result?.vocab_size }}</view>
        <view class="score-line">
          <text class="muted">{{ t("assessment.summary", { correct: result?.correct, unknown: result?.unknown, wrong: result?.wrong, total: result?.total }) }}</text>
        </view>
        <view class="message">{{ result?.message }}</view>
        <button class="btn primary" @click="again">{{ t("assessment.again") }}</button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { startTest, answer, finishTest } from "../../api/vocab";
import type { Question, Feedback, Progress, Result } from "../../api/vocab";

const { t } = useI18n();

type Phase = "intro" | "quiz" | "result";

const phase = ref<Phase>("intro");
const loading = ref(false);
const error = ref("");
const sessionId = ref("");
const question = ref<Question>({ word: "", options: [] });
const progress = ref<Progress>({ score: 0, total: 0, correct: 0, unknown: 0, wrong: 0, converged: false });
const feedback = ref<Feedback | null>(null);
const selectedIndex = ref<number | null>(null); // 0..3 选项下标，-1 表示「不认识」
const result = ref<Result | null>(null);

const letters = ["A", "B", "C", "D"];

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.assessment") });
});

const correctIndex = computed(() =>
  feedback.value ? question.value.options.indexOf(feedback.value.correct_gloss) : -1
);

const fbIcon = computed(() =>
  feedback.value?.response === "correct" ? "✓" : feedback.value?.response === "unknown" ? "⊙" : "✗"
);

const fbText = computed(() => {
  if (!feedback.value) return "";
  const g = feedback.value.correct_gloss;
  if (feedback.value.response === "correct") return t("assessment.correct") + g;
  if (feedback.value.response === "unknown") return t("assessment.unknownMarked") + g;
  return t("assessment.wrongAnswer") + g;
});

function optionClass(i: number): string {
  if (!feedback.value) return "";
  if (i === correctIndex.value) return "correct";
  if (i === selectedIndex.value) return "wrong";
  return "dim";
}

async function start() {
  error.value = "";
  loading.value = true;
  try {
    const resp = await startTest();
    sessionId.value = resp.session_id;
    question.value = resp.question;
    progress.value = {
      score: resp.score,
      total: resp.total,
      correct: resp.correct,
      unknown: resp.unknown,
      wrong: resp.wrong,
      converged: resp.converged ?? false,
    };
    feedback.value = null;
    selectedIndex.value = null;
    phase.value = "quiz";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function choose(i: number) {
  submit(i, false);
}

function chooseUnknown() {
  submit(null, true);
}

async function finish() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    const resp = await finishTest(sessionId.value);
    result.value = resp.result;
    feedback.value = null;
    selectedIndex.value = null;
    phase.value = "result";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

async function submit(choice: number | null, unknown: boolean) {
  if (loading.value || feedback.value) return;
  loading.value = true;
  selectedIndex.value = unknown ? -1 : choice;
  try {
    const resp = await answer(sessionId.value, choice, unknown);
    feedback.value = resp.feedback;
    progress.value = {
      score: resp.score,
      total: resp.total,
      correct: resp.correct,
      unknown: resp.unknown,
      wrong: resp.wrong,
      converged: resp.converged ?? false,
    };
    if (resp.finished && resp.result) {
      result.value = resp.result;
      setTimeout(() => {
        phase.value = "result";
      }, 900);
    } else if (resp.question) {
      const next = resp.question;
      setTimeout(() => {
        question.value = next;
        feedback.value = null;
        selectedIndex.value = null;
      }, 900);
    }
  } catch (e) {
    error.value = (e as Error).message;
    feedback.value = null;
  } finally {
    loading.value = false;
  }
}

function again() {
  phase.value = "intro";
  result.value = null;
  feedback.value = null;
  selectedIndex.value = null;
  error.value = "";
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
  padding: 48rpx 40rpx;
  box-shadow: 0 8rpx 32rpx rgba(31, 45, 80, 0.06);
}

/* 介绍页 */
.title {
  font-size: 48rpx;
  font-weight: 700;
  color: #1f2d50;
  text-align: center;
}
.subtitle {
  display: block;
  text-align: center;
  color: #8a94ad;
  font-size: 26rpx;
  margin-top: 12rpx;
}
.rules {
  margin-top: 40rpx;
}
.rule-title {
  font-size: 28rpx;
  font-weight: 600;
  color: #1f2d50;
  margin-bottom: 20rpx;
}
.rule-row {
  display: flex;
  align-items: center;
  padding: 16rpx 0;
}
.dot {
  width: 20rpx;
  height: 20rpx;
  border-radius: 50%;
  margin-right: 20rpx;
}
.dot.ok { background: #07c160; }
.dot.neutral { background: #b7c0d4; }
.dot.bad { background: #fa5151; }
.rule-text {
  flex: 1;
  font-size: 30rpx;
  color: #33405f;
}
.score {
  font-size: 26rpx;
  font-weight: 600;
}
.score.plus { color: #07c160; }
.score.zero { color: #8a94ad; }
.score.minus { color: #fa5151; }
.hint {
  margin-top: 32rpx;
  font-size: 26rpx;
  color: #e68a00;
  background: #fff7e8;
  border-radius: 12rpx;
  padding: 20rpx;
  line-height: 1.6;
}
.btn {
  margin-top: 40rpx;
  border-radius: 16rpx;
  font-size: 32rpx;
  font-weight: 600;
}
.btn.primary {
  background: #4f7cff;
  color: #fff;
}
.error {
  margin-top: 24rpx;
  color: #fa5151;
  font-size: 26rpx;
  text-align: center;
}

/* 实时得分条 */
.scorebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx 32rpx;
  margin-bottom: 40rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.score-main {
  display: flex;
  flex-direction: column;
}
.score-label {
  font-size: 24rpx;
  color: #8a94ad;
}
.score-value {
  font-size: 56rpx;
  font-weight: 800;
  color: #4f7cff;
  line-height: 1.1;
}
.score-stats {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6rpx;
}
.stat {
  font-size: 24rpx;
  color: #6a7591;
}
.stat.ok { color: #07c160; }
.stat.neutral { color: #8a94ad; }
.stat.bad { color: #fa5151; }

.word {
  font-size: 72rpx;
  font-weight: 700;
  color: #1f2d50;
  text-align: center;
  margin-bottom: 56rpx;
}
.options {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
}
.option {
  display: flex;
  align-items: center;
  background: #fff;
  border-radius: 16rpx;
  padding: 28rpx 32rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
  transition: all 0.15s;
}
.option:active {
  transform: scale(0.98);
}
.opt-letter {
  width: 56rpx;
  height: 56rpx;
  line-height: 56rpx;
  text-align: center;
  border-radius: 50%;
  background: #eef2fb;
  color: #4f7cff;
  font-weight: 700;
  margin-right: 24rpx;
  font-size: 28rpx;
  flex-shrink: 0;
}
.opt-text {
  font-size: 34rpx;
  color: #33405f;
}
.option.correct {
  background: #e8f8ef;
}
.option.correct .opt-letter {
  background: #07c160;
  color: #fff;
}
.option.wrong {
  background: #fdecec;
}
.option.wrong .opt-letter {
  background: #fa5151;
  color: #fff;
}
.option.dim {
  opacity: 0.5;
}
.unknown-btn {
  margin-top: 32rpx;
  text-align: center;
  padding: 28rpx;
  border-radius: 16rpx;
  border: 2rpx dashed #b7c0d4;
  color: #6a7591;
  font-size: 30rpx;
  background: #fff;
}
.unknown-btn.active {
  background: #eef2fb;
  border-color: #4f7cff;
  color: #4f7cff;
}
.converged-hint {
  margin-top: 28rpx;
  text-align: center;
  font-size: 24rpx;
  color: #07c160;
}
.finish-btn {
  margin-top: 32rpx;
  text-align: center;
  padding: 28rpx;
  border-radius: 16rpx;
  background: #4f7cff;
  color: #fff;
  font-size: 32rpx;
  font-weight: 600;
}
.finish-btn.disabled {
  opacity: 0.5;
}
.feedback {
  margin-top: 32rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30rpx;
  padding: 20rpx;
  border-radius: 12rpx;
}
.feedback .fb-icon {
  font-size: 36rpx;
  margin-right: 12rpx;
  font-weight: 700;
}
.feedback.correct { color: #07c160; background: #e8f8ef; }
.feedback.unknown { color: #6a7591; background: #eef2fb; }
.feedback.wrong { color: #fa5151; background: #fdecec; }

/* 结果页 */
.big-label {
  text-align: center;
  color: #8a94ad;
  font-size: 28rpx;
}
.big-number {
  text-align: center;
  font-size: 120rpx;
  font-weight: 800;
  color: #4f7cff;
  line-height: 1.2;
}
.score-line {
  display: flex;
  justify-content: center;
  margin-top: 16rpx;
}
.muted {
  font-size: 26rpx;
  color: #8a94ad;
}
.message {
  margin-top: 40rpx;
  font-size: 26rpx;
  color: #6a7591;
  line-height: 1.6;
}
</style>

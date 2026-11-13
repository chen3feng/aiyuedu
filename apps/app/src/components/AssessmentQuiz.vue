<template>
  <view class="quiz">
    <view class="scorebar">
      <view class="score-main">
        <view class="score-head">
          <text class="score-label">{{ t("assessment.score") }}</text>
          <text class="algo-tag">{{ algoLabel }}</text>
        </view>
        <text class="score-value">{{ progress.score }}</text>
        <text v-if="progress.score !== null && progress.score_interval" class="score-range">
          {{ t("assessment.interval") }} {{ progress.score_interval[0] }}–{{ progress.score_interval[1] }}
        </text>
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
        v-for="(opt, i) in displayOptions"
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

    <StateView v-if="error" type="error" class="mt24" :message="error" />
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { answer, finishTest } from "../api/vocab";
import type { Question, Feedback, Progress, Result, VocabAlgo } from "../api/vocab";
import StateView from "./StateView.vue";

const props = defineProps<{
  sessionId: string;
  algo?: VocabAlgo;
  initialQuestion: Question;
  initialProgress: Progress;
}>();
const emit = defineEmits<{ finished: [result: Result] }>();

const { t } = useI18n();

const algoLabel = computed(() =>
  props.algo === "cat"
    ? t("assessment.algoCat")
    : props.algo === "adaptive"
      ? t("assessment.algoAdaptive")
      : t("assessment.algoClassic"),
);

const letters = ["A", "B", "C", "D"];

const loading = ref(false);
const error = ref("");
const question = ref<Question>({ ...props.initialQuestion, options: [...props.initialQuestion.options] });
const progress = ref<Progress>({ ...props.initialProgress });
const feedback = ref<Feedback | null>(null);
const selectedIndex = ref<number | null>(null); // 0..3 选项下标，-1 表示「不认识」

const correctIndex = computed(() =>
  feedback.value ? question.value.options.indexOf(feedback.value.correct_gloss) : -1,
);

// 答完后：若正确选项是「以上都不对」，把该选项的文字换成词的真实含义。
// 用 word_gloss !== correct_gloss 判断，避免在前端硬编码中文文案。
const displayOptions = computed(() => {
  const opts = question.value.options;
  const fb = feedback.value;
  if (!fb || !fb.word_gloss || fb.word_gloss === fb.correct_gloss) return opts;
  const idx = opts.indexOf(fb.correct_gloss);
  if (idx < 0) return opts;
  const out = [...opts];
  out[idx] = fb.word_gloss;
  return out;
});

function optionClass(i: number): string {
  if (!feedback.value) return "";
  if (i === correctIndex.value) return "correct";
  if (i === selectedIndex.value) return "wrong";
  return "dim";
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
    const resp = await finishTest(props.sessionId);
    emit("finished", resp.result);
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
    const resp = await answer(props.sessionId, choice, unknown);
    feedback.value = resp.feedback;
    progress.value = {
      score: resp.score,
      total: resp.total,
      correct: resp.correct,
      unknown: resp.unknown,
      wrong: resp.wrong,
      converged: resp.converged ?? false,
      score_interval: resp.score_interval,
      level: resp.level,
    };
    if (resp.finished && resp.result) {
      setTimeout(() => {
        emit("finished", resp.result as Result);
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
</script>

<style scoped>
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
.score-head {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.algo-tag {
  font-size: 20rpx;
  color: var(--brand);
  background: var(--soft);
  border-radius: 6rpx;
  padding: 2rpx 10rpx;
}
.score-label {
  font-size: 24rpx;
  color: var(--ink-4);
}
.score-value {
  font-size: 56rpx;
  font-weight: 800;
  color: var(--brand);
  line-height: 1.1;
}
.score-range {
  font-size: 22rpx;
  color: var(--ink-4);
  margin-top: 4rpx;
}
.score-stats {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6rpx;
}
.stat {
  font-size: 24rpx;
  color: var(--ink-3);
}
.stat.ok { color: var(--success); }
.stat.neutral { color: var(--ink-4); }
.stat.bad { color: var(--danger); }

.word {
  font-size: 72rpx;
  font-weight: 700;
  color: var(--ink);
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
  background: var(--soft);
  color: var(--brand);
  font-weight: 700;
  margin-right: 24rpx;
  font-size: 28rpx;
  flex-shrink: 0;
}
.opt-text {
  font-size: 34rpx;
  color: var(--ink-2);
}
.option.correct {
  background: #e8f8ef;
}
.option.correct .opt-letter {
  background: var(--success);
  color: #fff;
}
.option.wrong {
  background: var(--danger-bg);
}
.option.wrong .opt-letter {
  background: var(--danger);
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
  color: var(--ink-3);
  font-size: 30rpx;
  background: #fff;
}
.unknown-btn.active {
  background: var(--soft);
  border-color: var(--brand);
  color: var(--brand);
}
.converged-hint {
  margin-top: 28rpx;
  text-align: center;
  font-size: 24rpx;
  color: var(--success);
}
.finish-btn {
  margin-top: 32rpx;
  text-align: center;
  padding: 28rpx;
  border-radius: 16rpx;
  background: var(--brand);
  color: #fff;
  font-size: 32rpx;
  font-weight: 600;
}
.finish-btn.disabled {
  opacity: 0.5;
}
</style>

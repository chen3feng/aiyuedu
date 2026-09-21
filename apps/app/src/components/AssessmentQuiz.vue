<template>
  <view class="quiz">
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

    <StateView v-if="error" type="error" class="mt24" :message="error" />
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { answer, finishTest } from "../api/vocab";
import type { Question, Feedback, Progress, Result } from "../api/vocab";
import StateView from "./StateView.vue";

const props = defineProps<{
  sessionId: string;
  initialQuestion: Question;
  initialProgress: Progress;
}>();
const emit = defineEmits<{ finished: [result: Result] }>();

const { t } = useI18n();

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

const fbIcon = computed(() =>
  feedback.value?.response === "correct" ? "✓" : feedback.value?.response === "unknown" ? "⊙" : "✗",
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
.feedback.correct { color: var(--success); background: #e8f8ef; }
.feedback.unknown { color: var(--ink-3); background: var(--soft); }
.feedback.wrong { color: var(--danger); background: var(--danger-bg); }
</style>

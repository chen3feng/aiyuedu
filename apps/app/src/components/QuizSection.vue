<template>
  <!-- 课后选择题：作答后锁定选项，展示英文解答，可展开中文 -->
  <view v-if="quizzes.length" class="quiz">
    <view class="quiz-title">{{ t("reading.reader.quizTitle", { n: quizzes.length }) }}</view>
    <view v-for="(item, qi) in quizzes" :key="qi" class="quiz-item">
      <view class="q-question">{{ qi + 1 }}. {{ item.question }}</view>
      <view
        v-for="(opt, oi) in item.options"
        :key="oi"
        class="q-opt"
        :class="optClass(qi, oi)"
        @click="chooseQuiz(qi, oi)"
      >
        <text class="q-letter">{{ LETTERS[oi] }}</text>
        <text class="q-opt-text">{{ opt.text }}</text>
      </view>
      <view
        v-if="answers[qi] >= 0"
        class="q-explain"
        :class="chosenIsCorrect(qi) ? 'right' : 'wrong'"
      >
        <text class="q-result">{{ chosenIsCorrect(qi) ? "✅ " + t("reading.reader.correct") : "❌ " + t("reading.reader.wrong") }}</text>
        <view class="q-explanation" @click="toggleZh(qi)">
          <text class="q-explanation-text">{{ item.explanation_en }}</text>
          <text class="q-explanation-hint">{{ zhShown[qi] ? t("reading.reader.hideZh") : t("reading.reader.showZh") }}</text>
        </view>
        <text v-if="zhShown[qi]" class="q-explanation-zh">{{ item.explanation_zh }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { ChoiceQuiz } from "../api/reading";

const props = defineProps<{ quizzes: ChoiceQuiz[] }>();
const emit = defineEmits<{
  (e: "update:modelValue", answers: number[]): void;
}>();

const { t } = useI18n();

const LETTERS = ["A", "B", "C", "D"];

// answers[qi] = 所选项下标（-1 未作答）。题目列表变化（打开新章节）时重置，
// 并通过 v-model 把初始数组同步给父页面（完成按钮的禁用态依赖它）
const answers = ref<number[]>([]);
const zhShown = ref<Record<number, boolean>>({});

watch(
  () => props.quizzes,
  (qs) => {
    answers.value = qs.map(() => -1);
    zhShown.value = {};
    emit("update:modelValue", answers.value);
  },
  { immediate: true },
);

function chooseQuiz(qi: number, oi: number) {
  if (answers.value[qi] >= 0) return; // 已作答，锁定不再改
  answers.value[qi] = oi;
  emit("update:modelValue", answers.value);
}

function chosenIsCorrect(qi: number): boolean {
  const oi = answers.value[qi];
  return oi >= 0 && !!props.quizzes[qi].options[oi]?.correct;
}

function optClass(qi: number, oi: number): string {
  const chosen = answers.value[qi];
  if (chosen < 0) return "";
  if (props.quizzes[qi].options[oi]?.correct) return "opt-correct";
  if (oi === chosen) return "opt-wrong";
  return "opt-dim";
}

function toggleZh(qi: number) {
  zhShown.value[qi] = !zhShown.value[qi];
}
</script>

<style scoped>
.quiz {
  margin-top: 32rpx;
  border-top: 2rpx solid #eef0f6;
  padding-top: 24rpx;
}
.quiz-title {
  font-size: 30rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 16rpx;
}
.quiz-item {
  padding: 20rpx 16rpx;
  border-radius: 12rpx;
  background: #fafbfe;
  margin-bottom: 16rpx;
}
.q-question {
  font-size: 30rpx;
  color: var(--ink-2);
  font-weight: 600;
  line-height: 1.5;
  margin-bottom: 16rpx;
}
.q-opt {
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
  padding: 14rpx 16rpx;
  border-radius: 10rpx;
  background: #fff;
  border: 2rpx solid #eef0f6;
  margin-bottom: 12rpx;
}
.q-letter {
  flex-shrink: 0;
  width: 40rpx;
  height: 40rpx;
  line-height: 40rpx;
  text-align: center;
  font-size: 26rpx;
  font-weight: 700;
  color: var(--brand);
  background: var(--soft);
  border-radius: 8rpx;
}
.q-opt-text {
  flex: 1;
  font-size: 28rpx;
  color: var(--ink-2);
  line-height: 1.5;
}
.q-opt.opt-correct {
  border-color: var(--success);
  background: #f0faf3;
}
.q-opt.opt-correct .q-letter {
  background: var(--success);
  color: #fff;
}
.q-opt.opt-wrong {
  border-color: var(--danger);
  background: var(--danger-bg);
}
.q-opt.opt-wrong .q-letter {
  background: var(--danger);
  color: #fff;
}
.q-opt.opt-dim {
  opacity: 0.55;
}
.q-explain {
  margin-top: 8rpx;
  padding: 16rpx;
  border-radius: 10rpx;
  font-size: 26rpx;
  line-height: 1.6;
}
.q-explain.right {
  background: #f0faf3;
  color: #1a7a3d;
}
.q-explain.wrong {
  background: var(--danger-bg);
  color: #c0392b;
}
.q-result {
  display: block;
  font-weight: 700;
  margin-bottom: 4rpx;
}
.q-explanation {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 12rpx;
}
.q-explanation-text {
  font-size: 26rpx;
  line-height: 1.6;
}
.q-explanation-hint {
  flex-shrink: 0;
  font-size: 22rpx;
  color: var(--brand);
  border-bottom: 2rpx dashed var(--brand);
}
.q-explanation-zh {
  display: block;
  margin-top: 8rpx;
  font-size: 24rpx;
  color: var(--ink-3);
}
</style>

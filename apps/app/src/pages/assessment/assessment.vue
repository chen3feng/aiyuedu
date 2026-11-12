<template>
  <view class="page">
    <!-- 介绍页 -->
    <view v-if="phase === 'intro'" class="intro">
      <Card class="lg p48" >
        <view class="title">{{ t("assessment.title") }}</view>
        <view class="subtitle">{{ t("assessment.subtitle") }}</view>
        <view class="algo-switch">
          <view class="algo-head">
            <text class="algo-label">{{ t("assessment.algoLabel") }}</text>
            <view class="algo-chips">
              <text
                class="algo-chip"
                :class="{ active: algo === 'classic' }"
                @click="setAlgo('classic')"
              >{{ t("assessment.algoClassic") }}</text>
              <text
                class="algo-chip"
                :class="{ active: algo === 'eudic' }"
                @click="setAlgo('eudic')"
              >{{ t("assessment.algoEudic") }}</text>
            </view>
          </view>
          <text class="algo-hint">
            {{ algo === "eudic" ? t("assessment.algoEudicHint") : t("assessment.algoClassicHint") }}
          </text>
        </view>
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
        <StateView v-if="error" type="error" class="mt24" :message="error" />
      </Card>
    </view>

    <!-- 答题页 -->
    <AssessmentQuiz
      v-else-if="phase === 'quiz'"
      :session-id="sessionId"
      :algo="algo"
      :initial-question="question"
      :initial-progress="progress"
      @finished="onFinished"
    />

    <!-- 结果页 -->
    <view v-else class="result">
      <Card class="lg p48" >
        <view class="big-label">{{ t("assessment.yourVocab") }}</view>
        <view class="big-number">{{ result?.vocab_size }}</view>
        <view class="score-line">
          <text class="muted">{{ t("assessment.summary", { correct: result?.correct, unknown: result?.unknown, wrong: result?.wrong, total: result?.total }) }}</text>
        </view>
        <view class="message">{{ result?.message }}</view>
        <button class="btn primary" @click="again">{{ t("assessment.again") }}</button>
      </Card>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { startTest } from "../../api/vocab";
import type { Question, Progress, Result, VocabAlgo } from "../../api/vocab";
import { saveProfile } from "../../api/users";
import StateView from "../../components/StateView.vue";
import Card from "../../components/Card.vue";
import AssessmentQuiz from "../../components/AssessmentQuiz.vue";

const { t } = useI18n();

type Phase = "intro" | "quiz" | "result";

const phase = ref<Phase>("intro");
const loading = ref(false);
const error = ref("");
const sessionId = ref("");
// 算法开关：classic = 固定分层抽样，eudic = 自适应 Elo/IRT。记住上次选择。
// 首次进入默认用欧路自适应，方便先测新算法；可随时切回经典。
const ALGO_KEY = "vocab_algo";
const algo = ref<VocabAlgo>(
  (uni.getStorageSync(ALGO_KEY) as VocabAlgo) || "eudic",
);
function setAlgo(v: VocabAlgo) {
  algo.value = v;
  uni.setStorageSync(ALGO_KEY, v);
}
// 作为 AssessmentQuiz 的初始数据（start 返回），之后状态由组件自管
const question = ref<Question>({ word: "", options: [] });
const progress = ref<Progress>({ score: 0, total: 0, correct: 0, unknown: 0, wrong: 0, converged: false });
const result = ref<Result | null>(null);

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.assessment") });
});

async function start() {
  error.value = "";
  loading.value = true;
  try {
    const resp = await startTest(algo.value);
    algo.value = resp.algo; // 以服务端实际使用的算法为准（答题页会显示）
    sessionId.value = resp.session_id;
    question.value = resp.question;
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
    phase.value = "quiz";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

// 答题组件结束（点完成或收敛自动结束）：存词汇量、展示结果页
function onFinished(r: Result) {
  result.value = r;
  persistVocabSize(r.vocab_size);
  phase.value = "result";
}

function persistVocabSize(v: number) {
  uni.setStorageSync("vocab_size", v);
  saveProfile({ vocab_size: v }).catch(() => {
    /* 网络失败不影响本地 */
  });
}

function again() {
  phase.value = "intro";
  result.value = null;
  error.value = "";
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 40rpx;
  box-sizing: border-box;
}

/* 介绍页 */
.title {
  font-size: 48rpx;
  font-weight: 700;
  color: var(--ink);
  text-align: center;
}
.subtitle {
  display: block;
  text-align: center;
  color: var(--ink-4);
  font-size: 26rpx;
  margin-top: 12rpx;
}
.rules {
  margin-top: 40rpx;
}
.rule-title {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--ink);
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
.dot.ok { background: var(--success); }
.dot.neutral { background: #b7c0d4; }
.dot.bad { background: var(--danger); }
.rule-text {
  flex: 1;
  font-size: 30rpx;
  color: var(--ink-2);
}
.score {
  font-size: 26rpx;
  font-weight: 600;
}
.score.plus { color: var(--success); }
.score.zero { color: var(--ink-4); }
.score.minus { color: var(--danger); }
.hint {
  margin-top: 32rpx;
  font-size: 26rpx;
  color: #e68a00;
  background: #fff7e8;
  border-radius: 12rpx;
  padding: 20rpx;
  line-height: 1.6;
}
.algo-switch {
  margin-top: 32rpx;
  padding: 24rpx;
  border-radius: 12rpx;
  background: var(--soft);
}
.algo-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.algo-label {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--ink);
}
.algo-chips {
  display: flex;
  gap: 12rpx;
}
.algo-chip {
  padding: 10rpx 24rpx;
  border-radius: 999rpx;
  font-size: 26rpx;
  color: var(--ink-3);
  background: #fff;
  border: 2rpx solid transparent;
}
.algo-chip.active {
  color: var(--brand);
  border-color: var(--brand);
  font-weight: 600;
}
.algo-hint {
  display: block;
  margin-top: 14rpx;
  font-size: 24rpx;
  color: var(--ink-4);
  line-height: 1.5;
}
.btn {
  margin-top: 40rpx;
  border-radius: 16rpx;
  font-size: 32rpx;
  font-weight: 600;
}
.btn.primary {
  background: var(--brand);
  color: #fff;
}

/* 结果页 */
.big-label {
  text-align: center;
  color: var(--ink-4);
  font-size: 28rpx;
}
.big-number {
  text-align: center;
  font-size: 120rpx;
  font-weight: 800;
  color: var(--brand);
  line-height: 1.2;
}
.score-line {
  display: flex;
  justify-content: center;
  margin-top: 16rpx;
}
.muted {
  font-size: 26rpx;
  color: var(--ink-4);
}
.message {
  margin-top: 40rpx;
  font-size: 26rpx;
  color: var(--ink-3);
  line-height: 1.6;
}
</style>

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
                :class="{ active: algo === 'adaptive' }"
                @click="setAlgo('adaptive')"
              >{{ t("assessment.algoAdaptive") }}</text>
              <text
                class="algo-chip"
                :class="{ active: algo === 'cat' }"
                @click="setAlgo('cat')"
              >{{ t("assessment.algoCat") }}</text>
            </view>
          </view>
          <text class="algo-hint">{{ algoHint }}</text>
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
        <view v-if="history.length" class="last-test" @click="goHistory">
          <text>{{ t("assessment.lastTest", { n: history[0].vocab_size, date: fmtDate(history[0].ts) }) }} · {{ algoLabel(history[0].algo) }}</text>
          <text class="last-test-arrow">›</text>
        </view>
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
        <view v-if="delta !== null" class="delta" :class="{ up: delta >= 0, down: delta < 0 }">
          {{ t("assessment.vsLast", { delta: (delta >= 0 ? "+" : "") + delta }) }}
        </view>
        <view v-if="resultInterval" class="range">
          <text class="range-value">{{ t("assessment.scoreRange", { low: resultInterval[0], high: resultInterval[1] }) }}</text>
          <text class="range-hint">{{ t("assessment.scoreRangeHint") }}</text>
        </view>
        <view v-if="result?.alpha" class="algo-used">
          {{ t("assessment.alphaValue", { alpha: result.alpha.toFixed(2) }) }}
        </view>
        <view class="score-line">
          <text class="muted">{{ t("assessment.summary", { correct: result?.correct, unknown: result?.unknown, wrong: result?.wrong, total: result?.total }) }}</text>
        </view>
        <view class="algo-used">{{ t("assessment.algoUsed", { algo: algoName }) }}</view>
        <view class="message">{{ result?.message }}</view>
        <button class="btn primary" @click="again">{{ t("assessment.again") }}</button>
        <button class="btn ghost" @click="goHistory">{{ t("assessment.viewHistory") }}</button>
      </Card>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { normalizeAlgo, startTest } from "../../api/vocab";
import type { Question, Progress, Result, VocabAlgo } from "../../api/vocab";
import { listVocabTests, type VocabTestRecord } from "../../api/history";
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
// 算法开关：classic = 固定分层抽样，adaptive = 双参数自适应（θ+α），
// cat = 词频 CAT。adaptive2 已并入 adaptive，旧缓存/旧历史由 normalizeAlgo 归一化。
const ALGO_KEY = "vocab_algo";
const algo = ref<VocabAlgo>(normalizeAlgo(uni.getStorageSync(ALGO_KEY) as string));
function setAlgo(v: VocabAlgo) {
  algo.value = v;
  uni.setStorageSync(ALGO_KEY, v);
}
// 文案与选项共用同一套算法名称，历史记录和结果页也能显示算法。
const algoName = computed(() => algoLabel(algo.value));
const algoHint = computed(() => {
  const v = normalizeAlgo(algo.value);
  return t(
    v === "cat"
      ? "assessment.algoCatHint"
      : v === "adaptive"
        ? "assessment.algoAdaptiveHint"
        : "assessment.algoClassicHint",
  );
});
function algoLabel(v: string) {
  const a = normalizeAlgo(v);
  return a === "cat"
    ? t("assessment.algoCat")
    : a === "adaptive"
      ? t("assessment.algoAdaptive")
      : t("assessment.algoClassic");
}
// 作为 AssessmentQuiz 的初始数据（start 返回），之后状态由组件自管
const question = ref<Question>({ word: "", options: [] });
const progress = ref<Progress>({ score: 0, total: 0, correct: 0, unknown: 0, wrong: 0, converged: false });
const result = ref<Result | null>(null);
// 双参数算法给出的是词汇量（面积）区间；其余算法给分位区间。
const resultInterval = computed<[number, number] | null>(
  () => result.value?.vocab_interval ?? result.value?.score_interval ?? null,
);
// 历史记录（最新在前）；用于介绍页「上次测试」和结果页「比上次」
const history = ref<VocabTestRecord[]>([]);
const previous = ref<VocabTestRecord | null>(null);
const delta = ref<number | null>(null);

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.assessment") });
  loadHistory();
});

async function loadHistory() {
  try {
    history.value = (await listVocabTests()).items;
  } catch {
    /* 后端不可用时不影响测试 */
  }
}

function goHistory() {
  uni.navigateTo({ url: "/pages/history/history" });
}

function fmtDate(ts: number) {
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function start() {
  error.value = "";
  loading.value = true;
  // 本次测试开始前的最新一条，作为结果页「比上次」的基准
  previous.value = history.value[0] || null;
  delta.value = null;
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
  delta.value = previous.value ? r.vocab_size - previous.value.vocab_size : null;
  persistVocabSize(r.vocab_size);
  phase.value = "result";
  loadHistory(); // 本次记录已由后端写入，刷新供下次「比上次」使用
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
  flex-wrap: wrap;
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
.btn.ghost {
  margin-top: 16rpx;
  background: #fff;
  color: var(--brand);
  border: 1rpx solid var(--brand);
}
.last-test {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--soft);
  border-radius: 14rpx;
  padding: 18rpx 24rpx;
  margin-top: 24rpx;
  font-size: 26rpx;
  color: var(--ink-2);
}
.last-test-arrow {
  color: var(--brand);
  font-size: 34rpx;
}
.delta {
  text-align: center;
  font-size: 30rpx;
  font-weight: 700;
  margin-top: 8rpx;
}
.delta.up {
  color: var(--success);
}
.delta.down {
  color: var(--danger);
}
.range {
  margin-top: 16rpx;
  text-align: center;
}
.range-value {
  display: block;
  font-size: 26rpx;
  color: var(--ink-3);
  font-weight: 600;
}
.range-hint {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: var(--ink-4);
}
.algo-used {
  text-align: center;
  margin-top: 12rpx;
  font-size: 24rpx;
  color: var(--ink-4);
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

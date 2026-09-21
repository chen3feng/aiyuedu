<template>
  <view class="sentence-screen">
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

    <Card class="p28 mb">
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
    </Card>

    <view class="nav-row">
      <button class="btn-secondary" :disabled="currentIdx === 0" @click="prev">
        ← {{ t("writing.prevSentence") }}
      </button>
      <button v-if="currentIdx < sentences.length - 1" class="btn-primary" @click="next">
        {{ t("writing.nextSentence") }} →
      </button>
      <button v-else class="btn-primary" @click="finish">
        {{ t("writing.viewSummary") }} →
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { EssaySentenceReport } from "../api/writing";
import { speak, stopSpeak } from "../utils/tts";
import Card from "./Card.vue";

const props = defineProps<{ sentences: EssaySentenceReport[]; startIndex?: number }>();
const emit = defineEmits<{ done: [] }>();

const { t, locale } = useI18n();

// 从总结页返回时直接定位到最后一句；组件随 phase 重新挂载，故只在初始化读取
const currentIdx = ref(props.startIndex || 0);
const speakingIdx = ref(-1);

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

const currentSentence = computed<EssaySentenceReport>(
  () =>
    props.sentences[currentIdx.value] || {
      index: 0,
      original: "",
      errors: [],
      corrected: "",
      polished: "",
    },
);
const noErrorText = computed(() =>
  locale.value === "en" ? "No errors in this sentence. Nice!" : "这句没问题，很棒！",
);

function goTo(i: number) {
  if (i < 0 || i >= props.sentences.length) return;
  // 切句前停掉上一句的朗读
  if (speakingIdx.value !== -1) {
    stopSpeak();
    speakingIdx.value = -1;
  }
  currentIdx.value = i;
}

function prev() {
  goTo(currentIdx.value - 1);
}

function next() {
  goTo(currentIdx.value + 1);
}

function onSpeakSentence(i: number) {
  // 切换播放：点同一句 → 停；点不同句 → 切到新句
  if (speakingIdx.value === i) {
    stopSpeak();
    speakingIdx.value = -1;
    return;
  }
  if (speakingIdx.value !== -1) {
    stopSpeak();
  }
  const s = props.sentences[i];
  const text = s.polished || s.corrected || s.original;
  if (!text) return;
  const ok = speak(text, "en-US", () => {
    // 自然播完（或回退浏览器 TTS 结束）→ 清除高亮；手动 stopSpeak 不走这里
    if (speakingIdx.value === i) speakingIdx.value = -1;
  });
  if (ok) speakingIdx.value = i;
}

function finish() {
  if (speakingIdx.value !== -1) {
    stopSpeak();
    speakingIdx.value = -1;
  }
  emit("done");
}
</script>

<style scoped>
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
</style>

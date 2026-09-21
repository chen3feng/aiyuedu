<template>
  <view class="summary-screen">
    <Card class="p28 mb">
      <text class="card-label">{{ t("writing.yourOriginal") }}</text>
      <text class="polished-full original">{{ essay.original }}</text>
    </Card>

    <Card class="p28 mb">
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

    <Card class="p28 mb" v-if="essay.report?.summary_table?.length">
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

    <Card class="p28 mb praise-card" v-if="essay.report?.praise">
      <text class="praise-label">{{ t("writing.praise") }}</text>
      <text class="praise-text">{{ essay.report.praise }}</text>
    </Card>

    <view class="nav-row">
      <button class="btn-secondary" @click="emit('review-sentences')">
        ← {{ t("writing.reviewSentences") }}
      </button>
      <button class="btn-primary" @click="emit('back-list')">{{ t("writing.backToList") }}</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { Essay, EssaySentenceReport } from "../api/writing";
import { speakLines, stopSpeak } from "../utils/tts";
import Card from "./Card.vue";

const props = defineProps<{ essay: Essay; sentences: EssaySentenceReport[] }>();
const emit = defineEmits<{ "review-sentences": []; "back-list": [] }>();

const { t } = useI18n();

const speakingAll = ref(false);
// speakingIdx 仅用于与外部朗读状态对齐；本组件内全文朗读的逐句进度暂不渲染高亮
const speakingIdx = ref(-1);

const fullPolishedText = computed(() =>
  props.sentences
    .map((s) => s.polished || s.corrected || s.original)
    .filter(Boolean)
    .join(" "),
);

function onSpeakAll() {
  if (speakingAll.value) {
    stopSpeak();
    speakingAll.value = false;
    speakingIdx.value = -1;
    return;
  }
  if (speakingIdx.value !== -1) stopSpeak();
  speakingIdx.value = -1;
  const lines = props.sentences
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

onBeforeUnmount(() => {
  // 离开总结阶段（复习逐句 / 返回列表）前停掉全文朗读
  if (speakingAll.value || speakingIdx.value !== -1) stopSpeak();
  speakingAll.value = false;
  speakingIdx.value = -1;
});
</script>

<style scoped>
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
</style>

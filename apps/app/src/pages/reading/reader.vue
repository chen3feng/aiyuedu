<template>
  <view class="page">
    <!-- 顶部信息 -->
    <view v-if="detail" class="header">
      <view class="head-top">
        <text class="title">{{ detail.title }}</text>
        <text class="tag">{{ detail.topic_label }}</text>
      </view>
      <view class="meta">
        <text class="meta-item">{{ detail.word_count }} 词</text>
        <text class="meta-item">生词 {{ detail.new_word_count }} 个</text>
        <text class="meta-item">生词率 {{ (detail.new_word_rate * 100).toFixed(1) }}%</text>
      </view>
      <view class="toolbar">
        <view class="mode-switch">
          <view class="mode" :class="{ active: mode === 'ruby' }" @click="mode = 'ruby'">
            生词标注
          </view>
          <view class="mode" :class="{ active: mode === 'original' }" @click="mode = 'original'">
            原文
          </view>
        </view>
        <view class="speak-all" :class="{ playing }" @click="toggleSpeakAll">
          {{ playing ? "停止朗读" : "全文朗读" }}
        </view>
      </view>
    </view>

    <view v-if="loading" class="loading">加载中…</view>
    <view v-else-if="error" class="error">{{ error }}</view>

    <!-- 正文 -->
    <view v-else-if="detail" class="body">
      <!-- 生词标注：ruby 内联释义 -->
      <view v-if="mode === 'ruby'" class="ruby-body">
        <view v-for="(line, li) in detail.lines" :key="li" :id="'para-' + li" :class="['para', { current: li === currentLine }]">
          <view class="en-line ruby" v-html="line.html"></view>
        </view>
      </view>
      <!-- 原文：逐词可点 -->
      <view v-else class="plain-body">
        <view v-for="(line, li) in detail.lines" :key="li" :id="'para-' + li" :class="['para', { current: li === currentLine }]">
          <view class="en-line">
            <text
              v-for="(wd, i) in line.words"
              :key="i"
              class="tok"
              :class="tokClass(wd)"
              @click="onTok(wd)"
            >{{ wd.w }}</text>
          </view>
        </view>
      </view>

      <!-- 文末生词表 -->
      <view v-if="detail.vocabulary.length" class="vocab">
        <view class="vocab-title">生词表（{{ detail.vocabulary.length }} 个）</view>
        <view v-for="(v, i) in detail.vocabulary" :key="i" class="vocab-item" @click="onVocab(v)">
          <view class="v-row">
            <text class="v-word">{{ v.word }}</text>
            <text v-if="v.phonetic" class="v-phonetic">{{ v.phonetic }}</text>
            <text class="v-speak" @click.stop="speakVocab(v)">🔊</text>
          </view>
          <text class="v-gloss">{{ v.gloss }}</text>
          <text v-if="v.full_gloss && v.full_gloss !== v.gloss" class="v-full">{{ v.full_gloss }}</text>
        </view>
      </view>

      <button class="finish-btn" @click="finish">完成阅读</button>
    </view>

    <!-- 生词弹窗 -->
    <view v-if="activeWord" class="mask" @click="closePopup">
      <view class="popup" @click.stop>
        <view class="popup-word">{{ activeWord.w }}</view>
        <view v-if="activeWord.lemma && activeWord.lemma !== activeWord.w.toLowerCase()" class="popup-lemma">
          原形：{{ activeWord.lemma }}
        </view>
        <view v-if="activeWord.phonetic" class="popup-phonetic">{{ activeWord.phonetic }}</view>
        <view class="popup-gloss">{{ activeWord.gloss || "（暂无释义）" }}</view>
        <view v-if="activeWord.full_gloss && activeWord.full_gloss !== activeWord.gloss" class="popup-full">
          {{ activeWord.full_gloss }}
        </view>
        <view class="popup-actions">
          <button class="act speak" @click="speakWord">发音</button>
          <button class="act save" @click="addToNotebook">加入生词本</button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { getCurrentInstance, nextTick, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { getReading, recordReading } from "../../api/reading";
import type { ReadingDetail, ReadingWord, VocabItem } from "../../api/reading";
import { speak, speakLines, stopSpeak } from "../../utils/tts";

interface ActiveWord {
  w: string;
  lemma: string;
  phonetic: string;
  gloss: string;
  full_gloss: string;
}

const id = ref("");
const level = ref(3600);
const mode = ref<"ruby" | "original">("ruby");
const detail = ref<ReadingDetail | null>(null);
const loading = ref(false);
const error = ref("");
const activeWord = ref<ActiveWord | null>(null);
const playing = ref(false);
const currentLine = ref(-1); // 朗读时高亮的当前句下标
const instance = getCurrentInstance();

const startTs = Date.now();
const clickedLemmas = new Set<string>();

onLoad((query) => {
  id.value = (query?.id as string) || "";
  level.value = Number((query?.level as string) || 3600) || 3600;
  fetchDetail();
});

async function fetchDetail() {
  loading.value = true;
  error.value = "";
  try {
    detail.value = await getReading(id.value, level.value);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function isNew(wd: ReadingWord): boolean {
  return !wd.punct && !wd.num && wd.known === false;
}

function tokClass(wd: ReadingWord): string {
  if (wd.punct) return "punct";
  if (isNew(wd)) return "new";
  return "";
}

function onTok(wd: ReadingWord) {
  if (!isNew(wd)) return;
  activeWord.value = {
    w: wd.w,
    lemma: wd.lemma || wd.w.toLowerCase(),
    phonetic: wd.phonetic || "",
    gloss: wd.gloss || "",
    full_gloss: wd.full_gloss || "",
  };
  clickedLemmas.add(wd.lemma || wd.w.toLowerCase());
}

function onVocab(v: VocabItem) {
  activeWord.value = {
    w: v.word,
    lemma: v.word, // 展示词已是原型，不再标「原形」；生词本以原型为键
    phonetic: v.phonetic,
    gloss: v.gloss,
    full_gloss: v.full_gloss,
  };
  clickedLemmas.add(v.word.toLowerCase());
}

function closePopup() {
  activeWord.value = null;
}

function speakWord() {
  if (activeWord.value) speak(activeWord.value.w);
}

function speakVocab(v: VocabItem) {
  speak(v.word);
}

// 朗读时保持当前句可见：即将滚出视口才滚动，避免每句都跳
function scrollToLine(i: number) {
  nextTick(() => {
    const q = uni.createSelectorQuery();
    if (instance?.proxy) q.in(instance.proxy);
    q.select(`#para-${i}`).boundingClientRect();
    // @ts-ignore uni-app 类型定义把 scrollOffset 的 callback 误标为必填；无参用法是文档推荐写法（结果交给 exec 数组）
    q.selectViewport().scrollOffset();
    q.exec((res) => {
      const rect = res?.[0] as { top: number; bottom: number } | null;
      const scroll = res?.[1] as { scrollTop: number } | null;
      if (!rect || !scroll) return;
      const winH = uni.getSystemInfoSync().windowHeight || 667;
      const margin = 120; // 上下安全区
      const top = scroll.scrollTop || 0;
      if (rect.bottom > winH - margin) {
        // 太靠下：下滚，让当前句停在视口上方 ~30% 处
        uni.pageScrollTo({ scrollTop: top + (rect.top - winH * 0.3), duration: 300 });
      } else if (rect.top < margin) {
        // 太靠上：上滚回安全区
        uni.pageScrollTo({ scrollTop: top + (rect.top - margin), duration: 300 });
      }
    });
  });
}

function toggleSpeakAll() {
  if (!detail.value) return;
  if (playing.value) {
    stopSpeak();
    playing.value = false;
    currentLine.value = -1;
    return;
  }
  const sentences = detail.value.lines.map((l) => l.words.map((w) => w.w).join(""));
  playing.value = true;
  const ok = speakLines(
    sentences,
    "en-US",
    (i) => {
      currentLine.value = i;
      scrollToLine(i);
    },
    () => {
      playing.value = false;
      currentLine.value = -1;
    },
  );
  if (!ok) playing.value = false;
}

function addToNotebook() {
  const w = activeWord.value;
  if (!w) return;
  const word = w.lemma || w.w.toLowerCase();
  const list = (uni.getStorageSync("notebook") || []) as Array<{
    word: string;
    gloss: string;
    phonetic?: string;
    ts: number;
  }>;
  if (!list.some((it) => it.word === word)) {
    list.push({ word, gloss: w.gloss || "", phonetic: w.phonetic, ts: Date.now() });
    uni.setStorageSync("notebook", list);
  }
  uni.showToast({ title: "已加入生词本", icon: "success" });
  closePopup();
}

function finish() {
  if (!detail.value) return;
  const seconds = Math.round((Date.now() - startTs) / 1000);
  recordReading(id.value, {
    level: level.value,
    completed_ratio: 1.0,
    seconds,
    new_word_clicks: Array.from(clickedLemmas),
  }).catch(() => {
    /* 记录失败不打断阅读 */
  });
  uni.showToast({ title: "已完成阅读", icon: "success" });
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f4f6fb;
  padding: 32rpx;
  box-sizing: border-box;
}
.header {
  background: #fff;
  border-radius: 20rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.head-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}
.title {
  font-size: 40rpx;
  font-weight: 800;
  color: #1f2d50;
  flex: 1;
  margin-right: 20rpx;
}
.tag {
  flex-shrink: 0;
  font-size: 22rpx;
  color: #4f7cff;
  background: #eef2fb;
  padding: 6rpx 16rpx;
  border-radius: 8rpx;
}
.meta {
  display: flex;
  gap: 28rpx;
}
.meta-item {
  font-size: 24rpx;
  color: #8a94ad;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 20rpx;
  margin-top: 24rpx;
}
.mode-switch {
  flex: 1;
  display: flex;
  background: #eef2fb;
  border-radius: 12rpx;
  padding: 6rpx;
}
.mode {
  flex: 1;
  text-align: center;
  padding: 14rpx 0;
  font-size: 26rpx;
  color: #6a7591;
  border-radius: 8rpx;
}
.mode.active {
  background: #fff;
  color: #4f7cff;
  font-weight: 600;
}
.speak-all {
  flex-shrink: 0;
  padding: 14rpx 28rpx;
  font-size: 26rpx;
  font-weight: 600;
  color: #4f7cff;
  background: #eef2fb;
  border-radius: 12rpx;
}
.speak-all.playing {
  color: #fa5151;
  background: #fdecec;
}
.loading,
.error {
  text-align: center;
  color: #8a94ad;
  font-size: 28rpx;
  padding: 80rpx 0;
}
.error {
  color: #fa5151;
}
.body {
  background: #fff;
  border-radius: 20rpx;
  padding: 32rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.para {
  margin-bottom: 28rpx;
}
.para.current {
  background: #fff7e6;
  border-radius: 10rpx;
  /* 左侧竖条画在文字外侧（负 x 偏移的 outset 阴影），不遮挡正文 */
  box-shadow: -10rpx 0 0 0 #4f7cff;
  transition: background 0.2s;
}
.en-line {
  font-size: 34rpx;
  line-height: 1.9;
  color: #33405f;
}
/* ruby 内联释义（v-html 内容不受 scoped 属性约束，故用 :deep 穿透） */
.ruby-body :deep(ruby) {
  color: #e68a00;
  font-weight: 700;
}
.ruby-body :deep(rt) {
  font-size: 0.62em;
  line-height: 1.1;
  color: #b06a00;
  font-weight: 400;
}
.tok.punct {
  color: #33405f;
}
.tok.new {
  color: #e68a00;
  font-weight: 700;
  border-bottom: 2rpx dashed #e6a94d;
}
.vocab {
  margin-top: 32rpx;
  border-top: 2rpx solid #eef0f6;
  padding-top: 24rpx;
}
.vocab-title {
  font-size: 30rpx;
  font-weight: 700;
  color: #1f2d50;
  margin-bottom: 16rpx;
}
.vocab-item {
  padding: 20rpx 16rpx;
  border-radius: 12rpx;
  background: #fafbfe;
  margin-bottom: 12rpx;
}
.v-row {
  display: flex;
  align-items: baseline;
  gap: 16rpx;
}
.v-word {
  font-size: 32rpx;
  font-weight: 700;
  color: #e68a00;
}
.v-phonetic {
  font-size: 24rpx;
  color: #8a94ad;
}
.v-speak {
  margin-left: auto;
  font-size: 28rpx;
}
.v-gloss {
  display: block;
  margin-top: 6rpx;
  font-size: 28rpx;
  color: #33405f;
}
.v-full {
  display: block;
  margin-top: 4rpx;
  font-size: 24rpx;
  color: #8a94ad;
  line-height: 1.5;
}
.finish-btn {
  margin-top: 24rpx;
  background: #4f7cff;
  color: #fff;
  border-radius: 16rpx;
  font-size: 32rpx;
  font-weight: 600;
}
.mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}
.popup {
  width: 560rpx;
  background: #fff;
  border-radius: 24rpx;
  padding: 48rpx 40rpx;
}
.popup-word {
  font-size: 56rpx;
  font-weight: 800;
  color: #1f2d50;
  text-align: center;
}
.popup-lemma {
  margin-top: 12rpx;
  text-align: center;
  font-size: 26rpx;
  color: #8a94ad;
}
.popup-phonetic {
  margin-top: 8rpx;
  text-align: center;
  font-size: 28rpx;
  color: #6a7591;
}
.popup-gloss {
  margin-top: 24rpx;
  text-align: center;
  font-size: 32rpx;
  color: #33405f;
  line-height: 1.6;
}
.popup-full {
  margin-top: 12rpx;
  text-align: center;
  font-size: 24rpx;
  color: #8a94ad;
  line-height: 1.5;
}
.popup-actions {
  margin-top: 40rpx;
  display: flex;
  gap: 24rpx;
}
.act {
  flex: 1;
  border-radius: 16rpx;
  font-size: 30rpx;
  font-weight: 600;
}
.act.speak {
  background: #eef2fb;
  color: #4f7cff;
}
.act.save {
  background: #4f7cff;
  color: #fff;
}
</style>

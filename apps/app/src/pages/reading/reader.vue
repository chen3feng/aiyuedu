<template>
  <view class="page">
    <!-- collection 章节面包屑 -->
    <view v-if="detail?.collection" class="breadcrumb">
      <text class="crumb-link" @click="goCollection">{{ detail.collection.title_zh || detail.collection.title }}</text>
      <text class="crumb-sep">›</text>
      <text class="crumb-current">{{ detail.chapter_title || detail.title }}</text>
    </view>
    <!-- 顶部信息 -->
    <view v-if="detail" class="header">
      <view class="head-top">
        <view class="title-block">
          <text v-if="detail.title_zh" class="title-zh">{{ detail.title_zh }}</text>
          <text class="title">{{ detail.title }}</text>
        </view>
        <view class="tags">
          <text v-for="(label, i) in topicTags(detail)" :key="i" class="tag">{{ label }}</text>
        </view>
      </view>
      <view class="meta">
        <text class="meta-item">{{ t("reading.reader.words", { n: detail.word_count }) }}</text>
        <text class="meta-item">{{ t("reading.reader.newWords", { n: detail.new_word_count }) }}</text>
        <text class="meta-item">{{ t("reading.reader.newWordRate", { n: (detail.new_word_rate * 100).toFixed(1) }) }}</text>
      </view>
      <view class="toolbar">
        <view class="mode-switch">
          <view class="mode" :class="{ active: mode === 'ruby' }" @click="mode = 'ruby'">
            {{ t("reading.reader.rubyMode") }}
          </view>
          <view class="mode" :class="{ active: mode === 'original' }" @click="mode = 'original'">
            {{ t("reading.reader.originalMode") }}
          </view>
        </view>
        <view class="speak-all" :class="{ playing }" @click="toggleSpeakAll">
          {{ playing ? t("reading.reader.stopSpeak") : t("reading.reader.speakAll") }}
        </view>
      </view>
    </view>

    <view v-if="loading" class="loading">{{ t("common.loading") }}</view>
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
        <view class="vocab-head">
          <view class="vocab-title">{{ t("reading.reader.vocabList", { n: detail.vocabulary.length }) }}</view>
          <view class="vocab-sort" @click="toggleVocabSort">
            {{ vocabSort === "alpha" ? t("reading.reader.sortAppearance") : t("reading.reader.sortAlpha") }}
          </view>
        </view>
        <view v-for="(v, i) in sortedVocabulary" :key="i" class="vocab-item" @click="onVocab(v)">
          <view class="v-row">
            <text class="v-word">{{ v.word }}</text>
            <text v-if="v.phonetic" class="v-phonetic">{{ v.phonetic }}</text>
            <text class="v-speak" @click.stop="speakVocab(v)">🔊</text>
          </view>
          <text class="v-gloss">{{ v.gloss }}</text>
          <text v-if="v.full_gloss && v.full_gloss !== v.gloss" class="v-full">{{ v.full_gloss }}</text>
        </view>
      </view>

      <!-- 课后小测：答完所有选择题后才能「完成」 -->
      <view v-if="choiceQuizzes.length" class="quiz">
        <view class="quiz-title">{{ t("reading.reader.quizTitle", { n: choiceQuizzes.length }) }}</view>
        <view v-for="item in choiceQuizzes" :key="item.i" class="quiz-item">
          <view class="q-question">{{ item.i + 1 }}. {{ item.q.question }}</view>
          <view
            v-for="(opt, oi) in item.q.options"
            :key="oi"
            class="q-opt"
            :class="optClass(item.q, item.i, oi)"
            @click="chooseQuiz(item.i, oi)"
          >
            <text class="q-letter">{{ LETTERS[oi] }}</text>
            <text class="q-opt-text">{{ opt.text }}</text>
          </view>
          <view
            v-if="answers[item.i] >= 0"
            class="q-explain"
            :class="chosenIsCorrect(item.q, item.i) ? 'right' : 'wrong'"
          >
            <text class="q-result">{{ chosenIsCorrect(item.q, item.i) ? "✅ " + t("reading.reader.correct") : "❌ " + t("reading.reader.wrong") }}</text>
            <view class="q-explanation" @click="toggleZh(item.i)">
              <text class="q-explanation-text">{{ item.q.explanation_en }}</text>
              <text class="q-explanation-hint">{{ zhShown[item.i] ? t("reading.reader.hideZh") : t("reading.reader.showZh") }}</text>
            </view>
            <text v-if="zhShown[item.i]" class="q-explanation-zh">{{ item.q.explanation_zh }}</text>
          </view>
        </view>
      </view>

      <!-- 章节导航（仅 collection 章节显示） -->
      <view v-if="detail?.collection && detail.chapters" class="chapter-nav">
        <button
          class="nav-btn"
          :disabled="!prevChapter"
          @click="goPrevChapter"
        >
          ← {{ prevChapter ? t("reading.reader.prevChapter", { title: prevChapter.title || '' }) : t("reading.reader.firstChapter") }}
        </button>
        <text class="chapter-pos">
          {{ t("reading.reader.chapterPos", { n: detail.chapter_index ?? 1, total: detail.collection.total_chapters }) }}
        </text>
        <button
          class="nav-btn"
          :disabled="!nextChapter"
          @click="goNextChapter"
        >
          {{ nextChapter ? t("reading.reader.nextChapter", { title: nextChapter.title || '' }) : t("reading.reader.lastChapter") }} →
        </button>
      </view>

      <button
        class="finish-btn"
        :class="{ disabled: !allAnswered }"
        :disabled="!allAnswered"
        @click="finish"
      >
        {{ allAnswered ? t("reading.reader.finish") : t("reading.reader.finishRemain", { n: remaining }) }}
      </button>
    </view>

    <!-- 生词弹窗 -->
    <WordPopup
      :word="activeWord"
      @close="closePopup"
      @speak="speakWord"
      @add="addToNotebook"
    />
  </view>
</template>

<script setup lang="ts">
import { computed, getCurrentInstance, nextTick, ref } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { getReading, recordReading } from "../../api/reading";
import type { ActiveWord, ChoiceQuiz, ReadingDetail, ReadingWord, VocabItem } from "../../api/reading";
import { speak, speakLines, stopSpeak } from "../../utils/tts";
import WordPopup from "../../components/WordPopup.vue";

const { t, locale } = useI18n();

// 多主题中文名直接来自后端 topic_labels；标签缺失回退主题 key
function topicTags(d: ReadingDetail): string[] {
  const labels = d.topic_labels || [];
  return (d.topics || []).map((k, i) => labels[i] || k);
}

// 课后小测解答：默认只出英文，点击英文解答后额外展示中文（与 UI 语言无关）
const zhShown = ref<Record<number, boolean>>({});
function toggleZh(qi: number) {
  zhShown.value[qi] = !zhShown.value[qi];
}

const id = ref("");
const level = ref(3600);
const mode = ref<"ruby" | "original">("ruby");
const detail = ref<ReadingDetail | null>(null);
const loading = ref(false);
const error = ref("");
const activeWord = ref<ActiveWord | null>(null);
// 生词表排序：appearance=文中出现顺序（默认），alpha=字母顺序，方便快速定位单词
const vocabSort = ref<"appearance" | "alpha">("appearance");
const sortedVocabulary = computed(() => {
  const list = detail.value?.vocabulary || [];
  if (vocabSort.value !== "alpha") return list;
  return [...list].sort((a, b) =>
    (a.word || a.lemma || "").toLowerCase().localeCompare((b.word || b.lemma || "").toLowerCase()),
  );
});
function toggleVocabSort() {
  vocabSort.value = vocabSort.value === "alpha" ? "appearance" : "alpha";
}
const playing = ref(false);
const currentLine = ref(-1); // 朗读时高亮的当前句下标
const instance = getCurrentInstance();

const startTs = Date.now();
const clickedLemmas = new Set<string>();

// 课后小测：answers[i] = 所选项下标（-1 未作答），与 detail.quizzes 下标对齐
const answers = ref<number[]>([]);
const LETTERS = ["A", "B", "C", "D"];

// 只渲染选择题；`type` 字段为判断题等未来题型预留（暂不渲染）
const choiceQuizzes = computed(() =>
  (detail.value?.quizzes || [])
    .map((q, i) => ({ q, i }))
    .filter((x): x is { q: ChoiceQuiz; i: number } => x.q.type === "choice"),
);
const remaining = computed(() => choiceQuizzes.value.filter((x) => answers.value[x.i] < 0).length);
// 没有题目时视为已满足完成条件（remaining 本来就是 0）
const allAnswered = computed(() => remaining.value === 0);

function chooseQuiz(qi: number, oi: number) {
  if (answers.value[qi] >= 0) return; // 已作答，锁定不再改
  answers.value[qi] = oi;
}

function chosenIsCorrect(q: ChoiceQuiz, qi: number): boolean {
  const oi = answers.value[qi];
  return oi >= 0 && !!q.options[oi]?.correct;
}

function optClass(q: ChoiceQuiz, qi: number, oi: number): string {
  const chosen = answers.value[qi];
  if (chosen < 0) return "";
  if (q.options[oi]?.correct) return "opt-correct";
  if (oi === chosen) return "opt-wrong";
  return "opt-dim";
}

// 章节导航（仅 collection 章节）
const prevChapter = computed(() => {
  const d = detail.value;
  if (!d?.chapters || d.chapter_index == null) return null;
  return d.chapters.find((c) => c.index === d.chapter_index! - 1) ?? null;
});
const nextChapter = computed(() => {
  const d = detail.value;
  if (!d?.chapters || d.chapter_index == null) return null;
  return d.chapters.find((c) => c.index === d.chapter_index! + 1) ?? null;
});
function goChapter(ch: { id: string }) {
  uni.redirectTo({ url: `/pages/reading/reader?id=${ch.id}` });
}
function goPrevChapter() {
  if (prevChapter.value) goChapter(prevChapter.value);
}
function goNextChapter() {
  if (nextChapter.value) goChapter(nextChapter.value);
}
function goCollection() {
  const d = detail.value;
  if (!d?.collection) return;
  uni.redirectTo({ url: `/pages/reading/collection-detail?id=${d.collection.id}` });
}

onLoad((query) => {
  id.value = (query?.id as string) || "";
  level.value = Number((query?.level as string) || 3600) || 3600;
  fetchDetail();
});

onShow(() => {
  // 中文 locale 时优先用 title_zh 显示在导航栏；en / 其他回退英文 title
  const navTitle = (locale.value === "zh-CN" && detail.value?.title_zh)
    || detail.value?.title
    || t("nav.reader");
  uni.setNavigationBarTitle({ title: navTitle });
});

async function fetchDetail() {
  loading.value = true;
  error.value = "";
  try {
    detail.value = await getReading(id.value, level.value);
    answers.value = (detail.value.quizzes || []).map(() => -1);
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
  const cls = isNew(wd) ? "new" : "";
  return wd.em ? `${cls} em`.trim() : cls;
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
  uni.showToast({ title: t("reading.reader.addedNotebook"), icon: "success" });
  closePopup();
}

function finish() {
  if (!detail.value) return;
  if (!allAnswered.value) return; // 未答完全部题目，不能完成
  const seconds = Math.round((Date.now() - startTs) / 1000);
  recordReading(id.value, {
    level: level.value,
    completed_ratio: 1.0,
    seconds,
    new_word_clicks: Array.from(clickedLemmas),
  }).catch(() => {
    /* 记录失败不打断阅读 */
  });
  uni.showToast({ title: t("reading.reader.finished"), icon: "success" });
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 32rpx;
  box-sizing: border-box;
}
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8rpx;
  font-size: 24rpx;
  color: var(--ink-4);
  margin-bottom: 16rpx;
  padding: 8rpx 0;
}
.crumb-link {
  color: var(--brand);
}
.crumb-sep {
  color: var(--line);
}
.crumb-current {
  color: var(--ink);
  font-weight: 600;
}

.chapter-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16rpx;
  margin-top: 28rpx;
  padding: 16rpx;
  background: var(--bg);
  border-radius: 12rpx;
}
.nav-btn {
  flex: 1;
  background: #fff;
  color: var(--brand);
  font-size: 24rpx;
  padding: 14rpx 16rpx;
  border-radius: 999rpx;
  border: 1rpx solid var(--soft);
}
.nav-btn[disabled] {
  color: var(--line);
  background: #f9fafe;
}
.chapter-pos {
  font-size: 24rpx;
  color: var(--ink-3);
  font-weight: 600;
  flex-shrink: 0;
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
  align-items: flex-start;
  margin-bottom: 16rpx;
}
.title-block {
  flex: 1;
  margin-right: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}
.title-zh {
  font-size: 40rpx;
  font-weight: 800;
  color: var(--ink);
  line-height: 1.3;
}
.title {
  font-size: 28rpx;
  font-weight: 500;
  color: var(--ink-4);
  line-height: 1.4;
}
.tags {
  display: flex;
  gap: 8rpx;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.tag {
  flex-shrink: 0;
  font-size: 22rpx;
  color: var(--brand);
  background: var(--soft);
  padding: 6rpx 16rpx;
  border-radius: 8rpx;
}
.meta {
  display: flex;
  gap: 28rpx;
}
.meta-item {
  font-size: 24rpx;
  color: var(--ink-4);
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
  background: var(--soft);
  border-radius: 12rpx;
  padding: 6rpx;
}
.mode {
  flex: 1;
  text-align: center;
  padding: 14rpx 0;
  font-size: 26rpx;
  color: var(--ink-3);
  border-radius: 8rpx;
}
.mode.active {
  background: #fff;
  color: var(--brand);
  font-weight: 600;
}
.speak-all {
  flex-shrink: 0;
  padding: 14rpx 28rpx;
  font-size: 26rpx;
  font-weight: 600;
  color: var(--brand);
  background: var(--soft);
  border-radius: 12rpx;
}
.speak-all.playing {
  color: var(--danger);
  background: var(--danger-bg);
}
.loading,
.error {
  text-align: center;
  color: var(--ink-4);
  font-size: 28rpx;
  padding: 80rpx 0;
}
.error {
  color: var(--danger);
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
  box-shadow: -10rpx 0 0 0 var(--brand);
  transition: background 0.2s;
}
.en-line {
  font-size: 34rpx;
  line-height: 1.9;
  color: var(--ink-2);
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
/* 斜体强调（正文 _text_ → <em>） */
.ruby-body :deep(em) {
  font-style: italic;
}
.tok.punct {
  color: var(--ink-2);
}
.tok.em {
  font-style: italic;
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
.vocab-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}
.vocab-title {
  font-size: 30rpx;
  font-weight: 700;
  color: var(--ink);
}
.vocab-sort {
  flex-shrink: 0;
  font-size: 24rpx;
  color: var(--brand);
  background: var(--soft);
  padding: 8rpx 20rpx;
  border-radius: 999rpx;
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
  color: var(--ink-4);
}
.v-speak {
  margin-left: auto;
  font-size: 28rpx;
}
.v-gloss {
  display: block;
  margin-top: 6rpx;
  font-size: 28rpx;
  color: var(--ink-2);
}
.v-full {
  display: block;
  margin-top: 4rpx;
  font-size: 24rpx;
  color: var(--ink-4);
  line-height: 1.5;
}
.finish-btn {
  margin-top: 24rpx;
  background: var(--brand);
  color: #fff;
  border-radius: 16rpx;
  font-size: 32rpx;
  font-weight: 600;
}
.finish-btn.disabled {
  background: #c3cbe0;
  color: #fff;
}
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

<template>
  <view class="page">
    <!-- collection 章节面包屑 -->
    <ChapterBreadcrumb :detail="detail" />
    <!-- 顶部信息：标题 / 标签 / 统计 / 模式切换 / 朗读工具条 -->
    <ReaderHeader
      v-if="detail"
      :detail="detail"
      v-model:mode="mode"
      :playing="playing"
      @toggle-speak-all="toggleSpeakAll"
    />

    <StateView v-if="loading" type="loading" :message="t('common.loading')" />
    <StateView v-else-if="error" type="error" :message="error" />

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
      <QuizSection :quizzes="choiceQuizList" v-model="answers" />

      <!-- 章节导航（仅 collection 章节显示） -->
      <ChapterNav :detail="detail" />

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
import QuizSection from "../../components/QuizSection.vue";
import ChapterBreadcrumb from "../../components/ChapterBreadcrumb.vue";
import ChapterNav from "../../components/ChapterNav.vue";
import StateView from "../../components/StateView.vue";
import ReaderHeader from "../../components/ReaderHeader.vue";

const { t, locale } = useI18n();

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

// 课后小测：answers[i] = 所选项下标（-1 未作答），由 QuizSection 通过 v-model 回写，
// 下标与 choiceQuizList 对齐
const answers = ref<number[]>([]);

// 只渲染选择题；`type` 字段为判断题等未来题型预留（暂不渲染）
const choiceQuizList = computed(() =>
  (detail.value?.quizzes || []).filter((q): q is ChoiceQuiz => q.type === "choice"),
);
const remaining = computed(() => answers.value.filter((a) => a < 0).length);
// 没有题目时视为已满足完成条件（remaining 本来就是 0）
const allAnswered = computed(() => remaining.value === 0);

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
</style>

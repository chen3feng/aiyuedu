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
      <!-- 正文：ruby 内联释义 / 原文逐词可点 -->
      <ChapterBody
        :lines="detail.lines"
        :mode="mode"
        :current-line="currentLine"
        @token-click="onTok"
      />

      <!-- 文末生词表 -->
      <VocabList :items="detail.vocabulary" @select="onVocab" />

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
import { addNotebookItem } from "../../api/notebook";
import type { ActiveWord, ChoiceQuiz, ReadingDetail, ReadingWord, VocabItem } from "../../api/reading";
import { speak, speakLines, stopSpeak } from "../../utils/tts";
import WordPopup from "../../components/WordPopup.vue";
import QuizSection from "../../components/QuizSection.vue";
import ChapterBreadcrumb from "../../components/ChapterBreadcrumb.vue";
import ChapterNav from "../../components/ChapterNav.vue";
import StateView from "../../components/StateView.vue";
import ReaderHeader from "../../components/ReaderHeader.vue";
import VocabList from "../../components/VocabList.vue";
import ChapterBody from "../../components/ChapterBody.vue";

const { t, locale } = useI18n();

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

function onTok(wd: ReadingWord) {
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

async function addToNotebook() {
  const w = activeWord.value;
  if (!w) return;
  const word = w.lemma || w.w.toLowerCase();
  try {
    // 登录后写服务端，跨设备同步
    await addNotebookItem({
      word,
      gloss: w.gloss || "",
      phonetic: w.phonetic || "",
      reading_id: id.value,
    });
  } catch {
    // 离线 / 未登录且服务不可用：回退本机存储，注册后自动同步
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

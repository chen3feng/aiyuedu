<template>
  <view class="page">
    <view v-if="loading" class="loading">{{ t("common.loading") }}</view>
    <view v-else-if="error" class="error">{{ error }}</view>
    <view v-else-if="essay">
      <!-- 题目 / 字数 -->
      <view class="header">
        <text class="title">{{ promptTitle(essay) }}</text>
        <view class="meta-row">
          <text class="meta-item">{{ t("writing.wordCount", { n: essay.word_count }) }}</text>
          <text v-if="essay.target_words" class="meta-item">·</text>
          <text v-if="essay.target_words" class="meta-item">{{ t("writing.target", { n: essay.target_words }) }}</text>
        </view>
      </view>

      <!-- AI 失败横幅 -->
      <view v-if="essay.reason" class="banner">
        <text class="banner-title">⚠️ {{ t("writing.aiFailed") }}</text>
        <text class="banner-body">{{ essay.reason }}</text>
      </view>

      <!-- 原文 -->
      <view class="card">
        <text class="card-label">{{ t("writing.composeTitle") }}</text>
        <text class="original">{{ essay.original }}</text>
      </view>

      <!-- 逐句批改 -->
      <view v-if="essay.report?.sentences?.length" class="card">
        <text class="card-label">{{ t("writing.reportTitle") }}</text>
        <view
          v-for="s in essay.report.sentences"
          :key="s.index"
          class="sentence-block"
        >
          <view class="s-header">
            <text class="s-index">#{{ s.index }}</text>
            <text class="s-original">{{ s.original }}</text>
          </view>
          <view v-if="s.errors?.length" class="errors">
            <view v-for="(e, i) in s.errors" :key="i" class="error-row">
              <text class="cb">{{ categoryLabel(e.category) }}</text>
              <text class="ce">{{ e.explanation }}</text>
              <text v-if="e.fix" class="cf">→ {{ e.fix }}</text>
            </view>
          </view>
          <view v-if="s.corrected" class="alt-row">
            <text class="alt-label">{{ t("writing.corrected") }}：</text>
            <text class="alt-text corrected">{{ s.corrected }}</text>
          </view>
          <view v-if="s.polished" class="alt-row">
            <text class="alt-label">{{ t("writing.polished") }}：</text>
            <text class="alt-text polished">{{ s.polished }}</text>
          </view>
        </view>
      </view>

      <!-- 常见错误类型表 -->
      <view v-if="essay.report?.summary_table?.length" class="card">
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
      </view>

      <!-- 表扬 -->
      <view v-if="essay.report?.praise" class="card praise-card">
        <text class="praise-label">{{ t("writing.praise") }}</text>
        <text class="praise-text">{{ essay.report.praise }}</text>
      </view>

      <view class="actions">
        <button class="btn-secondary" @click="goList">{{ t("writing.backToList") }}</button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { getEssay } from "../../api/writing";
import type { Essay } from "../../api/writing";

const { t, locale } = useI18n();

const essay = ref<Essay | null>(null);
const loading = ref(false);
const error = ref("");

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

function promptTitle(e: Essay): string {
  if (locale.value === "en" && e.prompt_title_en) return e.prompt_title_en;
  return e.prompt_title_zh || "（自由写作）";
}

async function fetchEssay(id: string) {
  loading.value = true;
  error.value = "";
  try {
    essay.value = await getEssay(id);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function goList() {
  uni.navigateBack({ delta: 1, fail: () => uni.redirectTo({ url: "/pages/writing/index" }) });
}

onLoad((query) => {
  if (query?.id) fetchEssay(String(query.id));
});

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.writing") });
});
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f4f6fb;
  padding: 24rpx 32rpx 60rpx;
  box-sizing: border-box;
}
.error {
  color: #fa5151;
  text-align: center;
  padding: 80rpx 0;
  font-size: 28rpx;
}
.loading {
  text-align: center;
  color: #8a94ad;
  font-size: 28rpx;
  padding: 80rpx 0;
}
.header {
  margin-bottom: 20rpx;
}
.title {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: #1f2d50;
  margin-bottom: 8rpx;
}
.meta-row {
  display: flex;
  gap: 12rpx;
  font-size: 24rpx;
  color: #8a94ad;
}
.meta-item {
  font-size: 24rpx;
  color: #8a94ad;
}
.banner {
  background: #fdecec;
  border-left: 6rpx solid #fa5151;
  border-radius: 12rpx;
  padding: 20rpx 24rpx;
  margin-bottom: 20rpx;
}
.banner-title {
  display: block;
  font-size: 26rpx;
  font-weight: 700;
  color: #fa5151;
  margin-bottom: 8rpx;
}
.banner-body {
  display: block;
  font-size: 24rpx;
  color: #6a7591;
  line-height: 1.5;
}
.card {
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx 32rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.card-label {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1f2d50;
  margin-bottom: 16rpx;
}
.original {
  display: block;
  font-size: 28rpx;
  line-height: 1.7;
  color: #1f2d50;
  white-space: pre-wrap;
  word-break: break-word;
}
.sentence-block {
  padding: 16rpx 0;
  border-top: 1rpx solid #f0f2f8;
}
.sentence-block:first-of-type {
  border-top: none;
}
.s-header {
  display: flex;
  gap: 12rpx;
  margin-bottom: 12rpx;
}
.s-index {
  flex-shrink: 0;
  font-size: 22rpx;
  color: #8a94ad;
  background: #eef2fb;
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
  height: 36rpx;
  line-height: 36rpx;
}
.s-original {
  font-size: 28rpx;
  line-height: 1.6;
  color: #1f2d50;
}
.errors {
  margin-bottom: 12rpx;
}
.error-row {
  background: #fff8e1;
  border-left: 4rpx solid #ffb84d;
  padding: 12rpx 16rpx;
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
  color: #4f7cff;
  margin-top: 6rpx;
}
.alt-row {
  margin-top: 8rpx;
}
.alt-label {
  font-size: 22rpx;
  color: #8a94ad;
  margin-right: 8rpx;
}
.alt-text {
  font-size: 26rpx;
  line-height: 1.6;
}
.corrected {
  color: #1f2d50;
}
.polished {
  color: #07c160;
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
  color: #1f2d50;
  background: #f4f6fb;
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
.actions {
  display: flex;
  gap: 16rpx;
  margin-top: 32rpx;
}
.btn-secondary {
  flex: 1;
  background: #fff;
  color: #4f7cff;
  font-size: 28rpx;
  padding: 18rpx 0;
  border-radius: 999rpx;
  border: 1rpx solid #eef2fb;
}
</style>
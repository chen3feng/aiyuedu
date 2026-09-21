<template>
  <!-- 生词标注：ruby 内联释义 -->
  <view v-if="mode === 'ruby'" class="ruby-body">
    <view v-for="(line, li) in lines" :key="li" :id="'para-' + li" :class="['para', { current: li === currentLine }]">
      <view class="en-line ruby" v-html="line.html"></view>
    </view>
  </view>
  <!-- 原文：逐词可点 -->
  <view v-else class="plain-body">
    <view v-for="(line, li) in lines" :key="li" :id="'para-' + li" :class="['para', { current: li === currentLine }]">
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
</template>

<script setup lang="ts">
import type { ReadingDetail, ReadingWord } from "../api/reading";

defineProps<{
  lines: ReadingDetail["lines"];
  mode: "ruby" | "original";
  currentLine: number;
}>();
const emit = defineEmits<{ "token-click": [wd: ReadingWord] }>();

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
  emit("token-click", wd);
}
</script>

<style scoped>
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
</style>

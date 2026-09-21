<template>
  <view v-if="items.length" class="vocab">
    <view class="vocab-head">
      <view class="vocab-title">{{ t("reading.reader.vocabList", { n: items.length }) }}</view>
      <view class="vocab-sort" @click="toggleVocabSort">
        {{ vocabSort === "alpha" ? t("reading.reader.sortAppearance") : t("reading.reader.sortAlpha") }}
      </view>
    </view>
    <view v-for="(v, i) in sortedItems" :key="i" class="vocab-item" @click="emit('select', v)">
      <view class="v-row">
        <text class="v-word">{{ v.word }}</text>
        <text v-if="v.phonetic" class="v-phonetic">{{ v.phonetic }}</text>
        <text class="v-speak" @click.stop="speak(v.word)">🔊</text>
      </view>
      <text class="v-gloss">{{ v.gloss }}</text>
      <text v-if="v.full_gloss && v.full_gloss !== v.gloss" class="v-full">{{ v.full_gloss }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { VocabItem } from "../api/reading";
import { speak } from "../utils/tts";

const props = defineProps<{ items: VocabItem[] }>();
const emit = defineEmits<{ select: [v: VocabItem] }>();

const { t } = useI18n();

// 排序：appearance=文中出现顺序（默认），alpha=字母顺序，方便快速定位单词
const vocabSort = ref<"appearance" | "alpha">("appearance");
const sortedItems = computed(() => {
  if (vocabSort.value !== "alpha") return props.items;
  return [...props.items].sort((a, b) =>
    (a.word || a.lemma || "").toLowerCase().localeCompare((b.word || b.lemma || "").toLowerCase()),
  );
});
function toggleVocabSort() {
  vocabSort.value = vocabSort.value === "alpha" ? "appearance" : "alpha";
}
</script>

<style scoped>
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
</style>

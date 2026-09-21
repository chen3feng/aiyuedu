<template>
  <Card v-if="count" class="p24 mb">
    <text class="card-label">{{ label }}（{{ count }}）</text>
    <view class="glossary-grid">
      <view v-for="(gloss, word) in glossary" :key="word" class="gl-item">
        <text class="gl-word">{{ word }}</text>
        <text class="gloss">{{ gloss }}</text>
      </view>
    </view>
  </Card>
</template>

<script setup lang="ts">
import { computed } from "vue";
import Card from "./Card.vue";

const props = withDefaults(
  defineProps<{
    glossary: Record<string, string>;
    label?: string;
  }>(),
  { label: "全书词汇表" },
);
// 空表整块不渲染（父页面原本用 v-if="glossaryCount" 控制）
const count = computed(() => Object.keys(props.glossary).length);
</script>

<style scoped>
.card-label {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 16rpx;
}
.glossary-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12rpx 16rpx;
}
.gl-item {
  display: flex;
  flex-direction: column;
  padding: 8rpx 0;
}
.gl-word {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--ink);
}
.gloss {
  font-size: 22rpx;
  color: var(--ink-3);
}
</style>

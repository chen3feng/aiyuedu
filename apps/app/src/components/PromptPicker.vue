<template>
  <view class="phase">
    <text class="title">{{ t("writing.pickPrompt") }}</text>
    <StateView v-if="loading" type="loading" class="f26" :message="t('common.loading')" />
    <view v-else class="cards">
      <Card class="p28" v-for="p in prompts" :key="p.key" @click="emit('pick', p)">
        <text class="prompt-title">{{ titleOf(p) }}</text>
        <text class="prompt-body">{{ p.body_zh }}</text>
        <view class="prompt-meta">
          <text class="meta-item">{{ t("writing.target", { n: p.target_words }) }}</text>
        </view>
      </Card>
      <StateView v-if="!prompts.length" type="empty" class="pad60" :message="t('common.loading')" />
    </view>
    <view class="prompt-free" @click="emit('pick', null)">
      <text class="free-title">自由写作</text>
      <text class="free-hint">不选题目，自由发挥</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { listPrompts } from "../api/writing";
import type { Prompt } from "../api/writing";
import StateView from "./StateView.vue";
import Card from "./Card.vue";

const emit = defineEmits<{ pick: [p: Prompt | null] }>();

const { t, locale } = useI18n();

const prompts = ref<Prompt[]>([]);
const loading = ref(false);

function titleOf(p: Prompt): string {
  return locale.value === "en" && p.title_en ? p.title_en : p.title_zh;
}

onLoad(() => {
  loading.value = true;
  listPrompts()
    .then((r) => {
      prompts.value = r.items;
    })
    .finally(() => {
      loading.value = false;
    });
});
</script>

<style scoped>
.title {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 24rpx;
}
.cards {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}
.prompt-free {
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx 32rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.prompt-free:active {
  transform: scale(0.99);
}
.prompt-title {
  display: block;
  font-size: 32rpx;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 8rpx;
}
.prompt-body {
  display: block;
  font-size: 26rpx;
  color: var(--ink-3);
  line-height: 1.5;
  margin-bottom: 12rpx;
}
.prompt-meta {
  display: flex;
  gap: 16rpx;
}
.meta-item {
  font-size: 24rpx;
  color: var(--ink-4);
}
.prompt-free {
  margin-top: 32rpx;
  text-align: center;
}
.free-title {
  display: block;
  font-size: 30rpx;
  font-weight: 600;
  color: var(--brand);
}
.free-hint {
  display: block;
  font-size: 24rpx;
  color: var(--ink-4);
  margin-top: 6rpx;
}
</style>

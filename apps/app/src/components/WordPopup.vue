<template>
  <!-- 生词弹窗：点击遮罩关闭，内容区阻止冒泡 -->
  <view v-if="word" class="mask" @click="emit('close')">
    <view class="popup" @click.stop>
      <view class="popup-word">{{ word.w }}</view>
      <view v-if="word.lemma && word.lemma !== word.w.toLowerCase()" class="popup-lemma">
        {{ t("reading.reader.lemma") }}{{ word.lemma }}
      </view>
      <view v-if="word.phonetic" class="popup-phonetic">{{ word.phonetic }}</view>
      <view class="popup-gloss">{{ word.gloss || t("reading.reader.noGloss") }}</view>
      <view v-if="word.full_gloss && word.full_gloss !== word.gloss" class="popup-full">
        {{ word.full_gloss }}
      </view>
      <view class="popup-actions">
        <button class="act speak" @click="emit('speak')">{{ t("reading.reader.speak") }}</button>
        <button class="act save" @click="emit('add')">{{ t("reading.reader.addNotebook") }}</button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";
import type { ActiveWord } from "../api/reading";

defineProps<{ word: ActiveWord | null }>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "speak"): void;
  (e: "add"): void;
}>();

const { t } = useI18n();
</script>

<style scoped>
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
  color: var(--ink);
  text-align: center;
}
.popup-lemma {
  margin-top: 12rpx;
  text-align: center;
  font-size: 26rpx;
  color: var(--ink-4);
}
.popup-phonetic {
  margin-top: 8rpx;
  text-align: center;
  font-size: 28rpx;
  color: var(--ink-3);
}
.popup-gloss {
  margin-top: 24rpx;
  text-align: center;
  font-size: 32rpx;
  color: var(--ink-2);
  line-height: 1.6;
}
.popup-full {
  margin-top: 12rpx;
  text-align: center;
  font-size: 24rpx;
  color: var(--ink-4);
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
  background: var(--soft);
  color: var(--brand);
}
.act.save {
  background: var(--brand);
  color: #fff;
}
</style>

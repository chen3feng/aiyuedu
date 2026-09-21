<template>
  <Card class="lg p40">
    <view class="section-title">{{ title }}</view>
    <view
      v-for="opt in options"
      :key="opt.value"
      class="option"
      :class="{ active: selected.includes(opt.value) }"
      @click="onPick(opt.value)"
    >
      <text class="label">{{ t(opt.labelKey) }}</text>
      <text v-if="selected.includes(opt.value)" class="check">✓</text>
    </view>
  </Card>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";
import Card from "./Card.vue";

const props = withDefaults(
  defineProps<{
    title: string;
    options: { value: string; labelKey: string }[];
    // 当前选中项；单选也用单元素数组传入
    selected: string[];
    // true = 多选（点选切换），false = 单选（点选即生效）
    multiple?: boolean;
  }>(),
  { multiple: false },
);
const emit = defineEmits<{
  select: [value: string];
  toggle: [value: string];
}>();

const { t } = useI18n();

function onPick(value: string) {
  if (props.multiple) emit("toggle", value);
  else emit("select", value);
}
</script>

<style scoped>
.section-title {
  font-size: 26rpx;
  color: var(--ink-4);
  margin-bottom: 16rpx;
}
.option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 28rpx 20rpx;
  border-bottom: 2rpx solid #f0f2f8;
}
.option:last-child {
  border-bottom: none;
}
.label {
  font-size: 30rpx;
  color: var(--ink-2);
}
.option.active .label {
  color: var(--brand);
  font-weight: 700;
}
.check {
  font-size: 34rpx;
  color: var(--brand);
  font-weight: 700;
}
</style>

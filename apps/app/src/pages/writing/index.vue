<template>
  <view class="page">
    <view class="topbar">
      <text class="title">{{ t("writing.listTitle") }}</text>
      <button class="btn-primary" @click="goPickPrompt">+ {{ t("writing.start") }}</button>
    </view>

    <StateView v-if="loading" type="loading" :message="t('common.loading')" />
    <StateView v-else-if="error" type="error" :message="error" />
    <StateView v-else-if="!items.length" type="empty" class="empty-lg">
      <view class="empty-icon">📝</view>
      <text>{{ t("writing.empty") }}</text>
      <text class="empty-hint">{{ t("writing.emptyHint") }}</text>
    </StateView>
    <view v-else class="cards">
      <EssayCard
        v-for="e in items"
        :key="e.id"
        :essay="e"
        @open="openReport(e.id)"
        @delete="onDelete(e.id)"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { listEssays, deleteEssay } from "../../api/writing";
import type { Essay } from "../../api/writing";
import StateView from "../../components/StateView.vue";
import EssayCard from "../../components/EssayCard.vue";

const { t } = useI18n();

const items = ref<Essay[]>([]);
const loading = ref(false);
const error = ref("");

async function fetchList() {
  loading.value = true;
  error.value = "";
  try {
    const resp = await listEssays();
    items.value = resp.items;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function goPickPrompt() {
  uni.navigateTo({ url: "/pages/writing/compose?pick=1" });
}

function openReport(id: string) {
  uni.navigateTo({ url: `/pages/writing/report?id=${id}` });
}

async function onDelete(id: string) {
  const ok = await new Promise<boolean>((resolve) => {
    uni.showModal({
      title: t("writing.deleteConfirm"),
      success: (r) => resolve(!!r.confirm),
      fail: () => resolve(false),
    });
  });
  if (!ok) return;
  try {
    await deleteEssay(id);
    items.value = items.value.filter((e) => e.id !== id);
  } catch (err) {
    error.value = (err as Error).message;
  }
}

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.writing") });
  fetchList();
});
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 24rpx 32rpx 60rpx;
  box-sizing: border-box;
}
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
}
.title {
  font-size: 38rpx;
  font-weight: 700;
  color: var(--ink);
}
.btn-primary {
  background: var(--brand);
  color: #fff;
  font-size: 26rpx;
  padding: 12rpx 28rpx;
  border-radius: 999rpx;
  border: none;
}
.empty-icon {
  font-size: 80rpx;
}
.empty-hint {
  color: var(--ink-4);
  font-size: 24rpx;
}
.cards {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}
</style>
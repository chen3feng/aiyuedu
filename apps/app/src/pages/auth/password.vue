<template>
  <view class="page">
    <view class="hero">
      <text class="title">{{ t("auth.passwordTitle") }}</text>
      <text class="subtitle">{{ t("auth.passwordHint") }}</text>
    </view>

    <Card class="lg p40">
      <view class="field">
        <text class="label">{{ t("auth.oldPassword") }}</text>
        <input class="input" v-model="oldPassword" password :placeholder="t('auth.oldPassword')" />
      </view>
      <view class="field">
        <text class="label">{{ t("auth.newPassword") }}</text>
        <input class="input" v-model="newPassword" password :placeholder="t('auth.passwordRule')" />
      </view>
      <view class="field">
        <text class="label">{{ t("auth.confirmPassword") }}</text>
        <input
          class="input"
          v-model="confirm"
          password
          :placeholder="t('auth.confirmPlaceholder')"
          @confirm="submit"
        />
      </view>

      <StateView v-if="error" type="error" class="mt16" :message="error" />

      <button class="primary-btn" :disabled="loading" @click="submit">
        {{ loading ? t("common.loading") : t("auth.savePassword") }}
      </button>
    </Card>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { changePassword } from "../../api/auth";
import Card from "../../components/Card.vue";
import StateView from "../../components/StateView.vue";

const { t } = useI18n();

const oldPassword = ref("");
const newPassword = ref("");
const confirm = ref("");
const error = ref("");
const loading = ref(false);

async function submit() {
  if (loading.value) return;
  if (!oldPassword.value || !newPassword.value) {
    error.value = t("auth.fillAll");
    return;
  }
  if (newPassword.value !== confirm.value) {
    error.value = t("auth.passwordMismatch");
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    await changePassword(oldPassword.value, newPassword.value);
    uni.showToast({ title: t("auth.passwordSaved"), icon: "success" });
    setTimeout(() => uni.navigateBack(), 500);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 60rpx 40rpx;
  box-sizing: border-box;
}
.hero {
  margin-bottom: 40rpx;
  text-align: center;
}
.title {
  font-size: 40rpx;
  font-weight: 800;
  color: var(--ink);
}
.subtitle {
  display: block;
  margin-top: 12rpx;
  font-size: 26rpx;
  color: var(--ink-4);
}
.field {
  margin-bottom: 28rpx;
}
.label {
  display: block;
  font-size: 26rpx;
  color: var(--ink-3);
  margin-bottom: 12rpx;
}
.input {
  background: var(--bg);
  border-radius: 14rpx;
  padding: 20rpx 24rpx;
  font-size: 30rpx;
  color: var(--ink-2);
}
.primary-btn {
  margin-top: 16rpx;
  background: var(--brand);
  color: #fff;
  border-radius: 16rpx;
  font-size: 32rpx;
  font-weight: 600;
}
</style>

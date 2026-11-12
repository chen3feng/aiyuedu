<template>
  <view class="page">
    <view class="hero">
      <text class="app-name">{{ t("appName") }}</text>
      <text class="slogan">{{ first ? t("auth.welcome") : t("auth.loginTitle") }}</text>
      <text v-if="first" class="intro">{{ t("auth.welcomeHint") }}</text>
    </view>

    <Card class="lg p40">
      <view class="field">
        <text class="label">{{ t("auth.username") }}</text>
        <input
          class="input"
          v-model="username"
          :placeholder="t('auth.usernamePlaceholder')"
          maxlength="20"
        />
      </view>
      <view class="field">
        <text class="label">{{ t("auth.password") }}</text>
        <input
          class="input"
          v-model="password"
          password
          :placeholder="t('auth.passwordPlaceholder')"
          @confirm="submit"
        />
      </view>

      <StateView v-if="error" type="error" class="mt16" :message="error" />

      <button class="primary-btn" :disabled="loading" @click="submit">
        {{ loading ? t("common.loading") : t("auth.login") }}
      </button>
      <view class="link-row">
        <text class="link" @click="goRegister">{{ t("auth.noAccount") }}</text>
        <text class="link" @click="useAnonymous">{{ t("auth.anonymous") }}</text>
      </view>
    </Card>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { login } from "../../api/auth";
import { markOnboarded, setAuth } from "../../utils/user";
import Card from "../../components/Card.vue";
import StateView from "../../components/StateView.vue";

const { t } = useI18n();

const first = ref(false);
const username = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);

onLoad((query) => {
  first.value = query?.first === "1";
  uni.setNavigationBarTitle({ title: t("auth.loginTitle") });
});

function leave() {
  markOnboarded();
  const pages = getCurrentPages();
  if (pages.length > 1) uni.navigateBack();
  else uni.reLaunch({ url: "/pages/index/index" });
}

async function submit() {
  if (loading.value) return;
  const name = username.value.trim();
  if (!name || !password.value) {
    error.value = t("auth.fillAll");
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const resp = await login(name, password.value);
    setAuth(resp.token, resp.user);
    markOnboarded();
    uni.showToast({ title: t("auth.loginSuccess"), icon: "success" });
    leave();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function goRegister() {
  uni.navigateTo({ url: `/pages/auth/register${first.value ? "?first=1" : ""}` });
}

function useAnonymous() {
  leave();
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 80rpx 40rpx;
  box-sizing: border-box;
}
.hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 60rpx;
  text-align: center;
}
.app-name {
  font-size: 56rpx;
  font-weight: 800;
  color: var(--ink);
}
.slogan {
  margin-top: 16rpx;
  font-size: 30rpx;
  color: var(--ink-3);
}
.intro {
  margin-top: 20rpx;
  font-size: 26rpx;
  color: var(--ink-4);
  line-height: 1.6;
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
.link-row {
  display: flex;
  justify-content: space-between;
  margin-top: 28rpx;
}
.link {
  font-size: 26rpx;
  color: var(--brand);
}
</style>

<template>
  <view class="page">
    <view class="hero">
      <text class="title">{{ t("auth.registerTitle") }}</text>
      <text class="subtitle">{{ t("auth.registerHint") }}</text>
    </view>

    <Card class="lg p40">
      <view class="field">
        <text class="label">{{ t("auth.username") }}</text>
        <input
          class="input"
          v-model="username"
          :placeholder="t('auth.usernameRule')"
          maxlength="20"
        />
      </view>
      <view class="field">
        <text class="label">{{ t("auth.password") }}</text>
        <input
          class="input"
          v-model="password"
          password
          :placeholder="t('auth.passwordRule')"
        />
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
        {{ loading ? t("common.loading") : t("auth.register") }}
      </button>
      <view class="link-row">
        <text class="link" @click="goLogin">{{ t("auth.haveAccount") }}</text>
      </view>
    </Card>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { register } from "../../api/auth";
import { addNotebookItem } from "../../api/notebook";
import { getUserId, markOnboarded, setAuth } from "../../utils/user";
import Card from "../../components/Card.vue";
import StateView from "../../components/StateView.vue";

const { t } = useI18n();

const username = ref("");
const password = ref("");
const confirm = ref("");
const error = ref("");
const loading = ref(false);

async function syncLocalNotebook() {
  // 未登录时生词本存在本机；注册后推送到服务端并清空本地兜底。
  const local = (uni.getStorageSync("notebook") || []) as Array<{
    word: string;
    gloss?: string;
    phonetic?: string;
    reading_id?: string;
  }>;
  if (!Array.isArray(local) || !local.length) return;
  for (const it of local) {
    try {
      await addNotebookItem({
        word: it.word,
        gloss: it.gloss || "",
        phonetic: it.phonetic || "",
        reading_id: it.reading_id || "",
      });
    } catch {
      // 单条失败不阻断注册流程
    }
  }
  uni.removeStorageSync("notebook");
}

async function submit() {
  if (loading.value) return;
  const name = username.value.trim();
  if (!name || !password.value) {
    error.value = t("auth.fillAll");
    return;
  }
  if (password.value !== confirm.value) {
    error.value = t("auth.passwordMismatch");
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const deviceUserId = getUserId();
    const resp = await register(name, password.value, deviceUserId);
    setAuth(resp.token, resp.user);
    markOnboarded();
    await syncLocalNotebook();
    const imported = Object.values(resp.imported || {}).reduce((a, b) => a + b, 0);
    uni.showToast({
      title: imported
        ? t("auth.imported", { n: imported })
        : t("auth.registerSuccess"),
      icon: "success",
    });
    uni.reLaunch({ url: "/pages/index/index" });
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function goLogin() {
  const pages = getCurrentPages();
  if (pages.length > 1) uni.navigateBack();
  else uni.redirectTo({ url: "/pages/auth/login" });
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
  margin-bottom: 50rpx;
  text-align: center;
}
.title {
  font-size: 44rpx;
  font-weight: 800;
  color: var(--ink);
}
.subtitle {
  margin-top: 14rpx;
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
  justify-content: center;
  margin-top: 28rpx;
}
.link {
  font-size: 26rpx;
  color: var(--brand);
}
</style>

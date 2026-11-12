<template>
  <view class="page">
    <Card class="lg p40 account-card">
      <template v-if="authUser">
        <view class="account-row">
          <view class="avatar">{{ initial }}</view>
          <view class="account-info">
            <text class="account-name">{{ authUser.username }}</text>
            <text class="account-sub">{{ t("settings.loggedInHint") }}</text>
          </view>
        </view>
        <view class="account-actions">
          <view class="account-btn" @click="goHistory">{{ t("settings.history") }}</view>
          <view class="account-btn" @click="goPassword">{{ t("settings.changePassword") }}</view>
          <view class="account-btn" @click="doLogout">{{ t("settings.logout") }}</view>
          <view class="account-btn danger" @click="doDelete">{{ t("settings.deleteAccount") }}</view>
        </view>
      </template>
      <template v-else>
        <view class="account-info">
          <text class="account-name">{{ t("settings.notLoggedIn") }}</text>
          <text class="account-sub">{{ t("settings.loginHint") }}</text>
        </view>
        <view class="account-actions">
          <view class="account-btn primary" @click="goLogin">{{ t("settings.login") }}</view>
          <view class="account-btn" @click="goRegister">{{ t("settings.register") }}</view>
          <view class="account-btn" @click="goHistory">{{ t("settings.history") }}</view>
        </view>
      </template>
    </Card>

    <CheckList
      :title="t('settings.language')"
      :options="langOptions"
      :selected="[langSetting]"
      @select="(v) => choose(v as LangSetting)"
    />

    <CheckList
      multiple
      :title="t('settings.topicPref')"
      :options="topicOptions"
      :selected="prefs"
      @toggle="toggleTopic"
    />

    <Card class="lg p40" >
      <view class="section-title">{{ t("settings.vocab") }}</view>
      <view class="option">
        <text class="label">{{ t("settings.vocabLabel") }}</text>
        <input
          class="vocab-input"
          type="number"
          v-model="vocabInput"
          placeholder="3600"
          @confirm="saveVocab"
          @blur="saveVocab"
        />
      </view>
      <view class="hint">{{ t("settings.vocabHint") }}</view>
    </Card>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { onShow } from "@dcloudio/uni-app";
import { langSetting, setLanguage, type LangSetting } from "../../locale";
import { getProfile, saveProfile } from "../../api/users";
import { deleteAccount, logout } from "../../api/auth";
import { clearAuth, getAuthUser, type AuthUser } from "../../utils/user";
import Card from "../../components/Card.vue";
import CheckList from "../../components/CheckList.vue";
import { TOPICS } from "../../utils/topics";

const { t } = useI18n();

const langOptions: { value: LangSetting; labelKey: string }[] = [
  { value: "auto", labelKey: "settings.followSystem" },
  { value: "zh-CN", labelKey: "settings.chinese" },
  { value: "en", labelKey: "settings.english" },
];

const topicOptions = TOPICS.map((tp) => ({ value: tp.key, labelKey: tp.labelKey }));

const prefs = ref<string[]>([]);
const vocab = ref<number | null>(null);
const vocabInput = ref("");
const authUser = ref<AuthUser | null>(null);
const initial = ref("");

onShow(() => {
  uni.setNavigationBarTitle({ title: t("settings.title") });
  authUser.value = getAuthUser();
  initial.value = (authUser.value?.username || "?").slice(0, 1).toUpperCase();
  loadProfile();
});

function goLogin() {
  uni.navigateTo({ url: "/pages/auth/login" });
}

function goRegister() {
  uni.navigateTo({ url: "/pages/auth/register" });
}

function goPassword() {
  uni.navigateTo({ url: "/pages/auth/password" });
}

function goHistory() {
  uni.navigateTo({ url: "/pages/history/history" });
}

function doLogout() {
  uni.showModal({
    title: t("settings.logout"),
    content: t("settings.logoutConfirm"),
    success: async (res) => {
      if (!res.confirm) return;
      try {
        await logout();
      } catch {
        // token 已失效也照常清理本地
      }
      clearAuth();
      authUser.value = null;
      uni.showToast({ title: t("settings.loggedOut"), icon: "success" });
    },
  });
}

function doDelete() {
  uni.showModal({
    title: t("settings.deleteAccount"),
    content: t("settings.deleteConfirm"),
    confirmColor: "#fa5151",
    success: (res) => {
      if (!res.confirm) return;
      uni.showModal({
        title: t("settings.deleteAccount"),
        editable: true,
        placeholderText: t("settings.deletePasswordHint"),
        confirmColor: "#fa5151",
        success: async (input) => {
          if (!input.confirm) return;
          try {
            await deleteAccount(input.content || "");
            clearAuth();
            authUser.value = null;
            uni.showToast({ title: t("settings.deleted"), icon: "success" });
            setTimeout(() => uni.reLaunch({ url: "/pages/index/index" }), 500);
          } catch (e) {
            uni.showToast({ title: (e as Error).message, icon: "none" });
          }
        },
      });
    },
  });
}

function choose(value: LangSetting) {
  setLanguage(value);
}

async function loadProfile() {
  try {
    const p = await getProfile();
    prefs.value = p.topic_preferences || [];
    vocab.value = p.vocab_size;
    vocabInput.value = p.vocab_size != null ? String(p.vocab_size) : "";
  } catch {
    // 后端不可用：回退本地缓存
    const local = Number(uni.getStorageSync("vocab_size"));
    vocab.value = local || null;
    vocabInput.value = local ? String(local) : "";
  }
}

function toggleTopic(key: string) {
  const idx = prefs.value.indexOf(key);
  if (idx >= 0) prefs.value.splice(idx, 1);
  else prefs.value.push(key);
  saveProfile({ topic_preferences: prefs.value }).catch(() => {});
}

function saveVocab() {
  const raw = vocabInput.value.trim();
  if (raw === "") {
    // 清空视为放弃修改，回退显示当前值
    vocabInput.value = vocab.value != null ? String(vocab.value) : "";
    return;
  }
  const v = Number(raw);
  if (!Number.isInteger(v) || v < 0) {
    vocabInput.value = vocab.value != null ? String(vocab.value) : "";
    return;
  }
  vocab.value = v;
  vocabInput.value = String(v);
  uni.setStorageSync("vocab_size", v);
  saveProfile({ vocab_size: v }).catch(() => {});
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
  padding: 40rpx;
  box-sizing: border-box;
}
.account-card {
  margin-bottom: 24rpx;
}
.account-row {
  display: flex;
  align-items: center;
  gap: 20rpx;
}
.avatar {
  width: 88rpx;
  height: 88rpx;
  border-radius: 50%;
  background: var(--brand);
  color: #fff;
  font-size: 38rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.account-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}
.account-name {
  font-size: 32rpx;
  font-weight: 700;
  color: var(--ink);
}
.account-sub {
  font-size: 24rpx;
  color: var(--ink-4);
}
.account-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
  margin-top: 24rpx;
}
.account-btn {
  padding: 12rpx 24rpx;
  border-radius: 999rpx;
  background: var(--soft);
  color: var(--brand);
  font-size: 26rpx;
}
.account-btn.primary {
  background: var(--brand);
  color: #fff;
}
.account-btn.danger {
  color: var(--danger);
}
.vocab-input {
  width: 220rpx;
  text-align: right;
  font-size: 30rpx;
  color: var(--ink-2);
  background: var(--bg);
  border-radius: 12rpx;
  padding: 8rpx 16rpx;
}
.hint {
  margin-top: 12rpx;
  font-size: 24rpx;
  color: var(--ink-4);
  line-height: 1.5;
  padding: 0 20rpx 12rpx;
}
</style>

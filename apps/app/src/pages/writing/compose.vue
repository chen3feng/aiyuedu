<template>
  <view class="page">
    <!-- 选题页（pick=1） -->
    <view v-if="phase === 'pick'" class="phase">
      <text class="title">{{ t("writing.pickPrompt") }}</text>
      <view v-if="loadingPrompts" class="loading">{{ t("common.loading") }}</view>
      <view v-else class="cards">
        <view v-for="p in prompts" :key="p.key" class="card" @click="onPick(p)">
          <text class="prompt-title">{{ promptTitle(p) }}</text>
          <text class="prompt-body">{{ p.body_zh }}</text>
          <view class="prompt-meta">
            <text class="meta-item">{{ t("writing.target", { n: p.target_words }) }}</text>
          </view>
        </view>
        <view v-if="!prompts.length" class="empty">{{ t("common.loading") }}</view>
      </view>
      <view class="prompt-free" @click="onPick(null)">
        <text class="free-title">自由写作</text>
        <text class="free-hint">不选题目，自由发挥</text>
      </view>
    </view>

    <!-- 写作页 -->
    <view v-else class="phase">
      <view class="prompt-card">
        <text class="prompt-title">{{ selectedPromptTitle }}</text>
        <text v-if="selectedPromptBody" class="prompt-body">{{ selectedPromptBody }}</text>
      </view>

      <view class="editor-wrap">
        <textarea
          class="editor"
          v-model="body"
          :placeholder="t('writing.writeHere')"
          :maxlength="-1"
          @input="onInput"
        ></textarea>
      </view>

      <view class="footer">
        <view class="word-count">
          <text :class="{ reach: wordCount >= target }">
            {{ t("writing.wordCount", { n: wordCount }) }} / {{ target }}
          </text>
        </view>
        <view class="autosave">
          <text class="autosave-dot">●</text>
          <text>{{ t("writing.autosaveOn") }}</text>
        </view>
      </view>

      <view class="actions">
        <button class="btn-secondary" @click="onBack">{{ t("writing.backToList") }}</button>
        <button class="btn-primary" :disabled="submitting || !body.trim()" @click="onSubmit">
          {{ submitting ? t("writing.submitting") : t("writing.submit") }}
        </button>
      </view>
      <view v-if="error" class="error">{{ error }}</view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useI18n } from "vue-i18n";
import { listPrompts, submitEssay } from "../../api/writing";
import type { Prompt } from "../../api/writing";

const { t, locale } = useI18n();

const phase = ref<"pick" | "compose">("pick");
const prompts = ref<Prompt[]>([]);
const loadingPrompts = ref(false);

const promptKey = ref<string | null>(null);
const body = ref("");
const submitting = ref(false);
const error = ref("");

const target = computed(() => {
  const p = prompts.value.find((x) => x.key === promptKey.value);
  return p?.target_words ?? 100;
});

const wordCount = computed(() => {
  // 简单按空白拆（与 backend 一致口径够用了）
  const s = body.value.trim();
  if (!s) return 0;
  return s.split(/\s+/).length;
});

const selectedPromptTitle = computed(() => {
  const p = prompts.value.find((x) => x.key === promptKey.value);
  if (!p) return locale.value === "en" ? "Free Writing" : "自由写作";
  return locale.value === "en" && p.title_en ? p.title_en : p.title_zh;
});

const selectedPromptBody = computed(() => {
  const p = prompts.value.find((x) => x.key === promptKey.value);
  return p?.body_zh ?? "";
});

function promptTitle(p: Prompt): string {
  return locale.value === "en" && p.title_en ? p.title_en : p.title_zh;
}

const DRAFT_KEY = "writing_draft";
let saveTimer: ReturnType<typeof setTimeout> | null = null;

function persistDraft() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      uni.setStorageSync(DRAFT_KEY, {
        prompt_key: promptKey.value,
        body: body.value,
        ts: Date.now(),
      });
    } catch {
      /* ignore quota errors */
    }
  }, 800);
}

function restoreDraft(): boolean {
  try {
    const raw = uni.getStorageSync(DRAFT_KEY);
    if (raw && typeof raw === "object" && raw.body) {
      body.value = raw.body;
      if (raw.prompt_key) promptKey.value = raw.prompt_key;
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

function onInput() {
  persistDraft();
}

async function loadPrompts() {
  loadingPrompts.value = true;
  try {
    const r = await listPrompts();
    prompts.value = r.items;
  } finally {
    loadingPrompts.value = false;
  }
}

function onPick(p: Prompt | null) {
  if (p) {
    promptKey.value = p.key;
  } else {
    promptKey.value = null;
  }
  // 选题时不主动恢复草稿，避免干扰用户重新选题
  body.value = "";
  phase.value = "compose";
}

async function onSubmit() {
  if (!body.value.trim()) return;
  submitting.value = true;
  error.value = "";
  try {
    const essay = await submitEssay({
      prompt_key: promptKey.value ?? undefined,
      original: body.value,
      target_words: target.value,
    });
    // 成功后清空草稿
    try {
      uni.removeStorageSync(DRAFT_KEY);
    } catch {
      /* ignore */
    }
    uni.redirectTo({ url: `/pages/writing/report?id=${essay.id}` });
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    submitting.value = false;
  }
}

function onBack() {
  uni.navigateBack();
}

onLoad((query) => {
  // ?pick=1 显示选题页；?key=xxx 直接进写作页
  if (query?.key) {
    promptKey.value = String(query.key);
    phase.value = "compose";
  } else {
    phase.value = "pick";
  }
  loadPrompts().then(() => {
    if (phase.value === "compose") {
      restoreDraft();
    }
  });
});

onShow(() => {
  uni.setNavigationBarTitle({ title: t("nav.writing") });
});

onBeforeUnmount(() => {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
});
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f4f6fb;
  padding: 24rpx 32rpx 60rpx;
  box-sizing: border-box;
}
.title {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: #1f2d50;
  margin-bottom: 24rpx;
}
.loading {
  text-align: center;
  color: #8a94ad;
  font-size: 26rpx;
  padding: 80rpx 0;
}
.empty {
  text-align: center;
  color: #8a94ad;
  font-size: 26rpx;
  padding: 60rpx 0;
}
.cards {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}
.card,
.prompt-free {
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx 32rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
}
.card:active,
.prompt-free:active {
  transform: scale(0.99);
}
.prompt-title {
  display: block;
  font-size: 32rpx;
  font-weight: 700;
  color: #1f2d50;
  margin-bottom: 8rpx;
}
.prompt-body {
  display: block;
  font-size: 26rpx;
  color: #6a7591;
  line-height: 1.5;
  margin-bottom: 12rpx;
}
.prompt-meta {
  display: flex;
  gap: 16rpx;
}
.meta-item {
  font-size: 24rpx;
  color: #8a94ad;
}
.prompt-free {
  margin-top: 32rpx;
  text-align: center;
}
.free-title {
  display: block;
  font-size: 30rpx;
  font-weight: 600;
  color: #4f7cff;
}
.free-hint {
  display: block;
  font-size: 24rpx;
  color: #8a94ad;
  margin-top: 6rpx;
}

/* compose */
.prompt-card {
  background: #eef2fb;
  border-radius: 16rpx;
  padding: 24rpx 28rpx;
  margin-bottom: 20rpx;
}
.editor-wrap {
  background: #fff;
  border-radius: 20rpx;
  padding: 8rpx;
  box-shadow: 0 4rpx 16rpx rgba(31, 45, 80, 0.05);
  margin-bottom: 16rpx;
}
.editor {
  width: 100%;
  min-height: 480rpx;
  font-size: 30rpx;
  line-height: 1.7;
  color: #1f2d50;
  padding: 24rpx;
  box-sizing: border-box;
  background: transparent;
  border: none;
}
.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
  padding: 0 8rpx;
}
.word-count {
  font-size: 24rpx;
  color: #8a94ad;
}
.word-count .reach {
  color: #07c160;
  font-weight: 600;
}
.autosave {
  display: flex;
  align-items: center;
  gap: 8rpx;
  font-size: 22rpx;
  color: #8a94ad;
}
.autosave-dot {
  color: #07c160;
  font-size: 18rpx;
}
.actions {
  display: flex;
  gap: 16rpx;
}
.btn-secondary,
.btn-primary {
  flex: 1;
  font-size: 28rpx;
  padding: 18rpx 0;
  border-radius: 999rpx;
  border: none;
}
.btn-secondary {
  background: #fff;
  color: #4f7cff;
  border: 1rpx solid #eef2fb;
}
.btn-primary {
  background: #4f7cff;
  color: #fff;
}
.btn-primary[disabled] {
  background: #c5cee0;
  color: #fff;
}
.error {
  margin-top: 16rpx;
  color: #fa5151;
  font-size: 26rpx;
  text-align: center;
}
</style>
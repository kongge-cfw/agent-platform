<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  UI_CARD_FRAME_SOURCE,
  UI_CARD_HOST_SOURCE,
  clampUiCardHeight,
  resolveUiCardOrigin,
  type UiCardState,
} from "@/utils/uiCard";

const props = defineProps<{
  payload: UiCardState;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (
    event: "submit",
    payload: { action: string; payload: Record<string, unknown> },
  ): void;
}>();

const iframeRef = ref<HTMLIFrameElement | null>(null);
const expanded = ref(props.payload.status === "pending");
const frameHeight = ref(clampUiCardHeight(props.payload.render.height));
const submittedOnce = ref(false);
const frameError = ref("");

const locked = computed(
  () =>
    Boolean(props.disabled) ||
    props.payload.status !== "pending" ||
    submittedOnce.value,
);

const targetOrigin = computed(() => resolveUiCardOrigin(props.payload.render));

const statusLabel = computed(() => {
  if (props.payload.status === "submitted") {
    return props.payload.action === "reject" ? "已驳回" : "已提交";
  }
  if (props.payload.status === "stale") return "已失效";
  if (props.payload.status === "expired") return "已过期";
  return "等待提交";
});

const submittedPreview = computed(() => {
  if (!props.payload.payload) return "";
  return JSON.stringify(props.payload.payload, null, 2);
});

function currentTheme(): "light" | "dark" {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function postToFrame(type: string, extra: Record<string, unknown> = {}) {
  const win = iframeRef.value?.contentWindow;
  if (!win) return;
  win.postMessage(
    {
      source: UI_CARD_HOST_SOURCE,
      type,
      card_id: props.payload.card_id,
      card_key: props.payload.card_key,
      title: props.payload.title,
      data: props.payload.data || {},
      actions: props.payload.actions || [],
      locale: "zh-CN",
      theme: currentTheme(),
      ...extra,
    },
    targetOrigin.value,
  );
}

function sendInit() {
  if (props.payload.status !== "pending") return;
  postToFrame("NANZI_CARD_INIT");
}

function onIframeLoad() {
  sendInit();
  window.setTimeout(sendInit, 50);
  window.setTimeout(sendInit, 200);
}

function sendDisable(reason: string) {
  postToFrame("NANZI_CARD_DISABLE", { reason });
}

function isTrustedMessage(event: MessageEvent): boolean {
  if (event.origin.replace(/\/$/, "") !== targetOrigin.value) return false;
  const data = event.data;
  if (!data || typeof data !== "object") return false;
  if (data.source !== UI_CARD_FRAME_SOURCE) return false;
  const incomingId = String(data.card_id || "");
  if (String(data.type || "") === "NANZI_CARD_READY" && !incomingId) return true;
  if (incomingId !== props.payload.card_id) return false;
  return true;
}

function onMessage(event: MessageEvent) {
  if (!isTrustedMessage(event)) return;
  const type = String(event.data.type || "");
  if (type === "NANZI_CARD_READY") {
    sendInit();
    return;
  }
  if (type === "NANZI_CARD_RESIZE") {
    frameHeight.value = clampUiCardHeight(event.data.height, frameHeight.value);
    return;
  }
  if (type === "NANZI_CARD_ERROR") {
    frameError.value = String(event.data.message || "业务页报错");
    return;
  }
  if (type !== "NANZI_CARD_SUBMIT" || locked.value) return;
  const action = String(event.data.action || "").trim();
  if (!action || !props.payload.actions.includes(action)) {
    frameError.value = "非法 action";
    return;
  }
  const payload =
    event.data.payload && typeof event.data.payload === "object" && !Array.isArray(event.data.payload)
      ? (event.data.payload as Record<string, unknown>)
      : {};
  submittedOnce.value = true;
  emit("submit", { action, payload });
}

watch(
  () => props.payload.card_id,
  () => {
    submittedOnce.value = false;
    frameError.value = "";
    frameHeight.value = clampUiCardHeight(props.payload.render.height);
    expanded.value = props.payload.status === "pending";
  },
);

watch(
  () => props.payload.status,
  (nextStatus, prevStatus) => {
    if (nextStatus !== "pending" && prevStatus === "pending") {
      expanded.value = false;
      sendDisable(nextStatus);
    } else if (nextStatus === "pending" && prevStatus !== "pending") {
      expanded.value = true;
    }
  },
);

onMounted(() => {
  window.addEventListener("message", onMessage);
});

onUnmounted(() => {
  window.removeEventListener("message", onMessage);
});
</script>

<template>
  <div
    class="mt-3 rounded-lg border border-sky-200 bg-sky-50/80 p-3 text-xs dark:border-sky-900/50 dark:bg-sky-900/20"
  >
    <button
      type="button"
      class="flex w-full items-center justify-between gap-2 text-left"
      @click="expanded = !expanded"
    >
      <div class="min-w-0">
        <div class="truncate font-bold text-sky-900 dark:text-sky-100">{{ payload.title }}</div>
        <div class="mt-0.5 truncate text-[11px] text-sky-800/70 dark:text-sky-200/70">
          {{ payload.card_key }}
        </div>
      </div>
      <span
        class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold"
        :class="payload.status === 'pending'
          ? 'bg-sky-100 text-sky-700 dark:bg-sky-900/50 dark:text-sky-200'
          : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'"
      >
        {{ statusLabel }}
      </span>
    </button>

    <div v-show="expanded" class="mt-3">
      <p v-if="payload.status === 'submitted'" class="mb-2 text-[11px] text-sky-800 dark:text-sky-200">
        动作：{{ payload.action || "—" }}
      </p>
      <p v-if="frameError || payload.error" class="mb-2 text-[11px] text-red-600 dark:text-red-300">
        {{ frameError || payload.error }}
      </p>
      <iframe
        v-if="payload.status === 'pending'"
        ref="iframeRef"
        class="w-full rounded-md border border-sky-100 bg-white dark:border-sky-900/40 dark:bg-slate-950"
        :src="payload.render.url"
        :style="{ height: `${frameHeight}px` }"
        sandbox="allow-scripts allow-forms allow-same-origin"
        referrerpolicy="no-referrer"
        title="业务对话卡片"
        @load="onIframeLoad"
      />
      <pre
        v-else-if="payload.status === 'submitted' && submittedPreview"
        class="max-h-40 overflow-auto rounded-md bg-white/80 p-2 text-[11px] text-slate-600 dark:bg-slate-950/40 dark:text-slate-300"
      >{{ submittedPreview }}</pre>
      <p v-else class="text-[11px] text-slate-500">该卡片已不再可交互。</p>
    </div>
  </div>
</template>

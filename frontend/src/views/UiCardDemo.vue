<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  UI_CARD_FRAME_SOURCE,
  UI_CARD_HOST_SOURCE,
} from "@/utils/uiCard";

interface InitPayload {
  card_id: string;
  card_key: string;
  title: string;
  data: Record<string, unknown>;
  actions: string[];
  theme?: string;
}

const route = useRoute();
const card = ref<InitPayload | null>(null);
const error = ref("");
const submitting = ref(false);
const note = ref("");

const actions = computed(() => card.value?.actions || ["confirm", "reject"]);
const dataPreview = computed(() => JSON.stringify(card.value?.data || {}, null, 2));

function postToParent(type: string, extra: Record<string, unknown> = {}) {
  if (!window.parent || window.parent === window) return;
  window.parent.postMessage(
    {
      source: UI_CARD_FRAME_SOURCE,
      type,
      card_id: card.value?.card_id,
      ...extra,
    },
    window.location.origin,
  );
}

function applyInit(data: Record<string, unknown>) {
  const cardId = String(data.card_id || "").trim();
  if (!cardId) return;
  card.value = {
    card_id: cardId,
    card_key: String(data.card_key || ""),
    title: String(data.title || "请确认"),
    data: data.data && typeof data.data === "object" && !Array.isArray(data.data)
      ? (data.data as Record<string, unknown>)
      : {},
    actions: Array.isArray(data.actions)
      ? data.actions.map((item) => String(item)).filter(Boolean)
      : ["confirm", "reject"],
    theme: data.theme ? String(data.theme) : undefined,
  };
  error.value = "";
  postToParent("NANZI_CARD_RESIZE", { height: Math.min(720, document.body.scrollHeight + 24) });
}

async function loadSessionFallback() {
  const token = String(route.query.card_token || "").trim();
  if (!token || card.value) return;
  try {
    const response = await fetch(`/api/portal/ui-cards/session?card_token=${encodeURIComponent(token)}`);
    if (!response.ok) throw new Error("card_token 无效或已过期");
    const data = await response.json();
    applyInit({
      card_id: data.card_id,
      card_key: data.card_key,
      title: data.title,
      data: data.data,
      actions: data.actions,
    });
  } catch (exc: any) {
    error.value = String(exc?.message || "无法加载卡片会话");
  }
}

function onMessage(event: MessageEvent) {
  if (event.origin !== window.location.origin) return;
  const data = event.data;
  if (!data || typeof data !== "object" || data.source !== UI_CARD_HOST_SOURCE) return;
  if (data.type === "NANZI_CARD_INIT") {
    applyInit(data);
    return;
  }
  if (data.type === "NANZI_CARD_DISABLE") {
    submitting.value = true;
  }
}

function actionLabel(action: string) {
  if (action === "confirm") return "确认";
  if (action === "reject") return "驳回";
  return action;
}

function submit(action: string) {
  if (!card.value || submitting.value) return;
  submitting.value = true;
  postToParent("NANZI_CARD_SUBMIT", {
    action,
    payload: {
      ...(card.value.data || {}),
      note: note.value.trim(),
    },
  });
}

onMounted(() => {
  window.addEventListener("message", onMessage);
  postToParent("NANZI_CARD_READY", { card_id: String(route.query.card_id || "") });
  void loadSessionFallback();
});

onUnmounted(() => {
  window.removeEventListener("message", onMessage);
});
</script>

<template>
  <div class="flex h-full w-full items-stretch justify-center bg-slate-50 p-4 text-slate-800">
    <div class="flex w-full max-w-xl flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div class="text-sm font-bold">{{ card?.title || "平台演示确认卡" }}</div>
      <p class="mt-1 text-xs text-slate-500">
        同域演示页，仅用于验收 <code>show_ui_card</code>。业务系统应实现相同的 postMessage 协议。
      </p>
      <p v-if="error" class="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-600">{{ error }}</p>
      <pre class="mt-3 max-h-48 overflow-auto rounded-md bg-slate-50 p-3 text-[11px] leading-5 text-slate-700">{{ dataPreview }}</pre>
      <label class="mt-3 block text-xs font-medium text-slate-600">
        备注（会写入回执 payload）
        <input
          v-model="note"
          class="mt-1 w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm outline-none focus:border-sky-400"
          :disabled="submitting || !card"
          placeholder="可选"
        />
      </label>
      <div class="mt-4 flex gap-2">
        <button
          v-for="action in actions"
          :key="action"
          type="button"
          class="rounded-md px-3 py-1.5 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
          :class="action === 'reject' ? 'bg-slate-500 hover:bg-slate-600' : 'bg-sky-600 hover:bg-sky-700'"
          :disabled="submitting || !card"
          @click="submit(action)"
        >
          {{ actionLabel(action) }}
        </button>
      </div>
    </div>
  </div>
</template>

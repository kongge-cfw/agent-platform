<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import type { BusinessConfirmationOption } from "@/utils/businessConfirmation";

const props = defineProps<{
  modelValue?: unknown;
  options?: BusinessConfirmationOption[];
  disabled?: boolean;
  placeholder?: string;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
}>();

const open = ref(false);
const triggerRef = ref<HTMLButtonElement | null>(null);
const panelRef = ref<HTMLDivElement | null>(null);
const panelStyle = ref<Record<string, string>>({});
const activeIndex = ref(0);

const items = computed(() => props.options ?? []);

const currentValue = computed(() => {
  if (props.modelValue === null || props.modelValue === undefined) return "";
  return String(props.modelValue);
});

const selected = computed(
  () => items.value.find((item) => item.value === currentValue.value) ?? null,
);

const displayText = computed(() => selected.value?.label || currentValue.value);

const placeholder = computed(() => props.placeholder || "请选择");

function closePanel() {
  open.value = false;
}

function updatePanelPosition() {
  const trigger = triggerRef.value;
  if (!trigger) return;
  const rect = trigger.getBoundingClientRect();
  const width = Math.max(rect.width, 160);
  const estimatedHeight = Math.min(240, 8 + items.value.length * 32);
  const gap = 4;
  let top = rect.bottom + gap;
  if (top + estimatedHeight > window.innerHeight - 8) {
    top = Math.max(8, rect.top - estimatedHeight - gap);
  }
  let left = rect.left;
  if (left + width > window.innerWidth - 8) {
    left = Math.max(8, window.innerWidth - width - 8);
  }
  panelStyle.value = {
    top: `${Math.round(top)}px`,
    left: `${Math.round(left)}px`,
    width: `${Math.round(width)}px`,
  };
}

function syncActiveIndex() {
  const index = items.value.findIndex((item) => item.value === currentValue.value);
  activeIndex.value = index >= 0 ? index : 0;
}

function scrollActiveIntoView() {
  const panel = panelRef.value;
  if (!panel) return;
  const active = panel.querySelector<HTMLButtonElement>("[data-option-active='true']");
  active?.scrollIntoView({ block: "nearest" });
}

function openPanel() {
  if (props.disabled || !items.value.length) return;
  syncActiveIndex();
  open.value = true;
  nextTick(() => {
    updatePanelPosition();
    scrollActiveIntoView();
  });
}

function togglePanel() {
  if (open.value) closePanel();
  else openPanel();
}

function pick(value: string) {
  if (props.disabled) return;
  emit("update:modelValue", value);
  closePanel();
}

function moveActive(delta: number) {
  if (!items.value.length) return;
  const next = (activeIndex.value + delta + items.value.length) % items.value.length;
  activeIndex.value = next;
  nextTick(scrollActiveIntoView);
}

function onDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Node | null;
  if (!target) return;
  if (triggerRef.value?.contains(target) || panelRef.value?.contains(target)) return;
  closePanel();
}

function onKeydown(event: KeyboardEvent) {
  if (!open.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closePanel();
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveActive(1);
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    moveActive(-1);
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    const item = items.value[activeIndex.value];
    if (item) pick(item.value);
  }
}

watch(open, (next) => {
  if (next) {
    document.addEventListener("pointerdown", onDocumentPointerDown, true);
    document.addEventListener("keydown", onKeydown, true);
    window.addEventListener("resize", updatePanelPosition);
    window.addEventListener("scroll", updatePanelPosition, true);
  } else {
    document.removeEventListener("pointerdown", onDocumentPointerDown, true);
    document.removeEventListener("keydown", onKeydown, true);
    window.removeEventListener("resize", updatePanelPosition);
    window.removeEventListener("scroll", updatePanelPosition, true);
  }
});

watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) closePanel();
  },
);

onBeforeUnmount(() => {
  closePanel();
  document.removeEventListener("pointerdown", onDocumentPointerDown, true);
  document.removeEventListener("keydown", onKeydown, true);
  window.removeEventListener("resize", updatePanelPosition);
  window.removeEventListener("scroll", updatePanelPosition, true);
});
</script>

<template>
  <div class="relative w-full">
    <button
      ref="triggerRef"
      type="button"
      class="bc-select-trigger"
      :class="{ 'is-open': open, 'is-disabled': disabled }"
      :disabled="disabled"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :aria-label="placeholder"
      @click="togglePanel"
    >
      <span
        class="min-w-0 flex-1 truncate text-left"
        :class="displayText ? 'text-[rgba(0,0,0,0.88)] dark:text-gray-100' : 'text-[rgba(0,0,0,0.25)] dark:text-gray-500'"
      >
        {{ displayText || placeholder }}
      </span>
      <svg
        class="h-3 w-3 shrink-0 text-[rgba(0,0,0,0.45)] transition-transform duration-200 dark:text-gray-400"
        :class="{ 'rotate-180': open }"
        viewBox="0 0 12 12"
        fill="none"
        aria-hidden="true"
      >
        <path d="M2.2 4.2 6 8l3.8-3.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="panelRef"
        class="bc-select-panel"
        :style="panelStyle"
        role="listbox"
        :aria-label="placeholder"
        @click.stop
      >
        <button
          v-for="(item, index) in items"
          :key="item.value"
          type="button"
          class="bc-select-option"
          :class="{
            'is-active': index === activeIndex,
            'is-selected': item.value === currentValue,
          }"
          role="option"
          :aria-selected="item.value === currentValue"
          :data-option-active="index === activeIndex"
          @mouseenter="activeIndex = index"
          @click="pick(item.value)"
        >
          <span class="min-w-0 flex-1 truncate text-left">{{ item.label }}</span>
          <svg
            v-if="item.value === currentValue"
            class="h-3.5 w-3.5 shrink-0 text-primary"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 12l4 4 10-10" />
          </svg>
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.bc-select-trigger {
  display: flex;
  width: 100%;
  min-height: 32px;
  align-items: center;
  gap: 8px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background-color: #fff;
  padding: 4px 11px;
  font-size: 12px;
  line-height: 1.5714285714;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.bc-select-trigger:hover:not(:disabled) {
  border-color: #1677ff;
}
.bc-select-trigger.is-open,
.bc-select-trigger:focus-visible {
  border-color: #1677ff;
  box-shadow: 0 0 0 2px rgba(5, 145, 255, 0.1);
}
.bc-select-trigger.is-disabled {
  cursor: default;
  background-color: #fff;
  color: rgba(0, 0, 0, 0.88);
  opacity: 1;
}
.bc-select-panel {
  position: fixed;
  z-index: 1080;
  max-height: 240px;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  background-color: #fff;
  box-shadow: 0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 9px 28px 8px rgba(0, 0, 0, 0.05);
}
.bc-select-option {
  display: flex;
  width: 100%;
  min-height: 32px;
  align-items: center;
  gap: 8px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  padding: 5px 12px;
  font-size: 12px;
  line-height: 1.5714285714;
  color: rgba(0, 0, 0, 0.88);
  text-align: left;
}
.bc-select-option.is-active {
  background-color: #e6f4ff;
}
.bc-select-option.is-selected {
  font-weight: 600;
}
:global(.dark) .bc-select-trigger,
:global(.dark) .bc-select-trigger.is-disabled,
:global(.dark) .bc-select-panel {
  background-color: rgb(31 41 55);
  border-color: rgb(75 85 99);
  color: rgb(243 244 246);
}
:global(.dark) .bc-select-option {
  color: rgb(243 244 246);
}
:global(.dark) .bc-select-option.is-active {
  background-color: rgb(30 58 138 / 0.45);
}
</style>

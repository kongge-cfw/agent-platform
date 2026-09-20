<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import {
  addMonths,
  addYears,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import {
  confirmationDateFromValue,
  confirmationDateInputValue,
  confirmationDateTimeDisplayValue,
} from "@/utils/businessConfirmation";

const props = defineProps<{
  modelValue?: unknown;
  disabled?: boolean;
  showTime?: boolean;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
}>();

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, "0"));

const open = ref(false);
const triggerRef = ref<HTMLButtonElement | null>(null);
const panelRef = ref<HTMLDivElement | null>(null);
const panelStyle = ref<Record<string, string>>({});
const viewDate = ref(startOfMonth(new Date()));
const draftHour = ref("00");
const draftMinute = ref("00");

const selectedDate = computed(() => confirmationDateFromValue(props.modelValue));

const displayText = computed(() => {
  if (props.showTime) return confirmationDateTimeDisplayValue(props.modelValue);
  return confirmationDateInputValue(props.modelValue);
});

const placeholder = computed(() => (props.showTime ? "请选择日期时间" : "请选择日期"));

const calendarDays = computed(() => {
  const monthStart = startOfMonth(viewDate.value);
  const start = startOfWeek(monthStart, { weekStartsOn: 1 });
  const end = endOfWeek(endOfMonth(monthStart), { weekStartsOn: 1 });
  return eachDayOfInterval({ start, end });
});

function syncDraftFromValue() {
  const current = selectedDate.value ?? new Date();
  viewDate.value = startOfMonth(current);
  draftHour.value = String(current.getHours()).padStart(2, "0");
  draftMinute.value = String(current.getMinutes()).padStart(2, "0");
}

function updatePanelPosition() {
  const trigger = triggerRef.value;
  if (!trigger) return;
  const rect = trigger.getBoundingClientRect();
  const panelWidth = props.showTime ? 392 : 280;
  const estimatedHeight = props.showTime ? 380 : 332;
  const gap = 4;
  let top = rect.bottom + gap;
  if (top + estimatedHeight > window.innerHeight - 8) {
    top = Math.max(8, rect.top - estimatedHeight - gap);
  }
  let left = rect.left;
  if (left + panelWidth > window.innerWidth - 8) {
    left = Math.max(8, window.innerWidth - panelWidth - 8);
  }
  panelStyle.value = {
    top: `${Math.round(top)}px`,
    left: `${Math.round(left)}px`,
    width: `${panelWidth}px`,
  };
}

function emitValue(date: Date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  if (!props.showTime) {
    emit("update:modelValue", `${y}-${m}-${d}`);
    return;
  }
  emit("update:modelValue", `${y}-${m}-${d} ${draftHour.value}:${draftMinute.value}`);
}

function closePanel() {
  open.value = false;
}

function openPanel() {
  if (props.disabled) return;
  syncDraftFromValue();
  open.value = true;
  nextTick(() => {
    updatePanelPosition();
    scrollTimeColumns();
  });
}

function togglePanel() {
  if (open.value) closePanel();
  else openPanel();
}

function onPickDay(day: Date) {
  if (props.disabled) return;
  emitValue(day);
  if (!props.showTime) closePanel();
}

function onPickNow() {
  const now = new Date();
  draftHour.value = String(now.getHours()).padStart(2, "0");
  draftMinute.value = String(now.getMinutes()).padStart(2, "0");
  emitValue(now);
  closePanel();
}

function onConfirmTime() {
  emitValue(selectedDate.value ?? new Date());
  closePanel();
}

function onTimeChange() {
  if (!selectedDate.value) return;
  emitValue(selectedDate.value);
}

function scrollTimeColumns() {
  const panel = panelRef.value;
  if (!panel) return;
  panel.querySelectorAll<HTMLButtonElement>("[data-time-active='true']").forEach((el) => {
    el.scrollIntoView({ block: "center" });
  });
}

function onDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Node | null;
  if (!target) return;
  if (triggerRef.value?.contains(target) || panelRef.value?.contains(target)) return;
  closePanel();
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") closePanel();
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
      class="bc-date-trigger"
      :class="{ 'is-open': open, 'is-disabled': disabled }"
      :disabled="disabled"
      :aria-expanded="open"
      :aria-haspopup="true"
      :aria-label="placeholder"
      @click="togglePanel"
    >
      <span class="min-w-0 flex-1 truncate text-left" :class="displayText ? 'text-[rgba(0,0,0,0.88)] dark:text-gray-100' : 'text-[rgba(0,0,0,0.25)] dark:text-gray-500'">
        {{ displayText || placeholder }}
      </span>
      <svg class="h-3.5 w-3.5 shrink-0 text-[rgba(0,0,0,0.45)] dark:text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
        <rect x="3" y="5" width="18" height="16" rx="2" stroke-width="1.75" />
        <path stroke-width="1.75" stroke-linecap="round" d="M8 3v4M16 3v4M3 10h18" />
      </svg>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="panelRef"
        class="bc-date-panel"
        :style="panelStyle"
        role="dialog"
        :aria-label="placeholder"
        @click.stop
      >
        <div class="flex">
          <div class="min-w-0 flex-1 px-2 pb-2 pt-2">
            <div class="mb-1 flex items-center justify-between px-1">
              <div class="flex items-center gap-0.5">
                <button type="button" class="bc-date-nav" aria-label="上一年" @click="viewDate = addYears(viewDate, -1)">«</button>
                <button type="button" class="bc-date-nav" aria-label="上一月" @click="viewDate = addMonths(viewDate, -1)">‹</button>
              </div>
              <div class="text-sm font-medium text-[rgba(0,0,0,0.88)] dark:text-gray-100">
                {{ format(viewDate, "yyyy年 M月") }}
              </div>
              <div class="flex items-center gap-0.5">
                <button type="button" class="bc-date-nav" aria-label="下一月" @click="viewDate = addMonths(viewDate, 1)">›</button>
                <button type="button" class="bc-date-nav" aria-label="下一年" @click="viewDate = addYears(viewDate, 1)">»</button>
              </div>
            </div>
            <div class="grid grid-cols-7">
              <span v-for="day in WEEKDAYS" :key="day" class="h-8 text-center text-xs leading-8 text-[rgba(0,0,0,0.45)] dark:text-gray-400">
                {{ day }}
              </span>
              <button
                v-for="day in calendarDays"
                :key="day.toISOString()"
                type="button"
                class="bc-date-cell"
                :class="{
                  'is-outside': !isSameMonth(day, viewDate),
                  'is-today': isSameDay(day, new Date()),
                  'is-selected': selectedDate && isSameDay(day, selectedDate),
                }"
                @click="onPickDay(day)"
              >
                {{ day.getDate() }}
              </button>
            </div>
          </div>
          <div v-if="showTime" class="flex border-l border-[#f0f0f0] dark:border-gray-700">
            <div class="bc-time-col">
              <button
                v-for="hour in HOURS"
                :key="`h-${hour}`"
                type="button"
                class="bc-time-item"
                :class="{ 'is-active': hour === draftHour }"
                :data-time-active="hour === draftHour"
                @click="draftHour = hour; onTimeChange()"
              >
                {{ hour }}
              </button>
            </div>
            <div class="bc-time-col border-l border-[#f0f0f0] dark:border-gray-700">
              <button
                v-for="minute in MINUTES"
                :key="`m-${minute}`"
                type="button"
                class="bc-time-item"
                :class="{ 'is-active': minute === draftMinute }"
                :data-time-active="minute === draftMinute"
                @click="draftMinute = minute; onTimeChange()"
              >
                {{ minute }}
              </button>
            </div>
          </div>
        </div>
        <div class="flex items-center justify-between border-t border-[#f0f0f0] px-3 py-2 dark:border-gray-700">
          <button type="button" class="text-sm text-primary hover:text-primary-hover" @click="onPickNow">
            {{ showTime ? "此刻" : "今天" }}
          </button>
          <button
            v-if="showTime"
            type="button"
            class="inline-flex h-6 items-center rounded-md bg-primary px-2 text-xs text-white hover:bg-primary-hover"
            @click="onConfirmTime"
          >
            确定
          </button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.bc-date-trigger {
  display: flex;
  width: 100%;
  min-height: 32px;
  align-items: center;
  gap: 8px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #fff;
  padding: 4px 11px;
  font-size: 12px;
  line-height: 1.5714285714;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.bc-date-trigger:hover:not(:disabled) {
  border-color: #1677ff;
}
.bc-date-trigger.is-open,
.bc-date-trigger:focus-visible {
  border-color: #1677ff;
  box-shadow: 0 0 0 2px rgba(5, 145, 255, 0.1);
}
.bc-date-trigger.is-disabled {
  cursor: default;
  background: #fff;
  color: rgba(0, 0, 0, 0.88);
  opacity: 1;
}
.bc-date-panel {
  position: fixed;
  z-index: 1080;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 9px 28px 8px rgba(0, 0, 0, 0.05);
}
.bc-date-nav {
  display: inline-flex;
  height: 24px;
  width: 24px;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: rgba(0, 0, 0, 0.45);
}
.bc-date-nav:hover {
  background: #f5f5f5;
  color: rgba(0, 0, 0, 0.88);
}
.bc-date-cell {
  height: 32px;
  border-radius: 4px;
  font-size: 14px;
  color: rgba(0, 0, 0, 0.88);
}
.bc-date-cell:hover {
  background: #f5f5f5;
}
.bc-date-cell.is-outside {
  color: rgba(0, 0, 0, 0.25);
}
.bc-date-cell.is-today {
  border: 1px solid #1677ff;
  color: #1677ff;
}
.bc-date-cell.is-selected,
.bc-date-cell.is-selected.is-today {
  background: #1677ff;
  border-color: #1677ff;
  color: #fff;
}
.bc-time-col {
  height: 256px;
  width: 56px;
  overflow-y: auto;
  padding: 4px 0;
}
.bc-time-item {
  display: block;
  width: 100%;
  height: 28px;
  text-align: center;
  font-size: 14px;
  line-height: 28px;
  color: rgba(0, 0, 0, 0.88);
}
.bc-time-item:hover {
  background: #f5f5f5;
}
.bc-time-item.is-active {
  background: #e6f4ff;
  font-weight: 600;
  color: #1677ff;
}
:global(.dark) .bc-date-trigger {
  background: rgb(31 41 55);
  border-color: rgb(107 114 128);
  color: rgb(243 244 246);
}
:global(.dark) .bc-date-panel {
  background: rgb(31 41 55);
  border-color: rgb(75 85 99);
}
:global(.dark) .bc-date-nav {
  color: rgb(156 163 175);
}
:global(.dark) .bc-date-nav:hover,
:global(.dark) .bc-date-cell:hover,
:global(.dark) .bc-time-item:hover {
  background: rgb(55 65 81);
  color: rgb(243 244 246);
}
:global(.dark) .bc-date-cell {
  color: rgb(243 244 246);
}
:global(.dark) .bc-date-cell.is-outside {
  color: rgb(107 114 128);
}
:global(.dark) .bc-time-item {
  color: rgb(243 244 246);
}
:global(.dark) .bc-time-item.is-active {
  background: rgb(12 74 110 / 0.4);
  color: rgb(125 211 252);
}
</style>

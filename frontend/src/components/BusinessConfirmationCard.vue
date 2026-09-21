<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import ConfirmationDatePicker from '@/components/ConfirmationDatePicker.vue';
import ConfirmationSelect from '@/components/ConfirmationSelect.vue';
import {
  confirmationDateInputValue,
  confirmationDateTimeDisplayValue,
  inferConfirmationValueType,
  normalizeConfirmationOptions,
  type BusinessConfirmationField,
  type BusinessConfirmationOption,
  type BusinessConfirmationState,
} from '@/utils/businessConfirmation';

const props = defineProps<{
  payload: BusinessConfirmationState;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (
    event: 'submit',
    payload: { confirmed: boolean; fields: BusinessConfirmationField[] },
  ): void;
}>();

const draftFields = reactive<BusinessConfirmationField[]>([]);
const expanded = ref(props.payload.status === 'pending');

function syncDraft(fields: BusinessConfirmationField[]) {
  draftFields.splice(
    0,
    draftFields.length,
    ...fields.map((field) => ({
      key: field.key,
      label: field.label,
      value: field.value ?? '',
      editable: field.editable !== false,
      value_type: inferConfirmationValueType(field),
      options: normalizeConfirmationOptions(field.options),
    })),
  );
}

watch(
  () => props.payload,
  (next) => {
    syncDraft(next?.fields || []);
    expanded.value = next?.status === 'pending';
  },
  { immediate: true, deep: true },
);

watch(
  () => props.payload.status,
  (nextStatus, prevStatus) => {
    if (nextStatus !== 'pending' && prevStatus === 'pending') {
      expanded.value = false;
    } else if (nextStatus === 'pending' && prevStatus !== 'pending') {
      expanded.value = true;
    }
  },
);

const locked = computed(
  () =>
    props.disabled ||
    props.payload.status === 'submitted' ||
    props.payload.status === 'stale',
);

function isDateTimeField(field: BusinessConfirmationField): boolean {
  return inferConfirmationValueType(field) === 'datetime';
}

function isDateField(field: BusinessConfirmationField): boolean {
  return inferConfirmationValueType(field) === 'date';
}

function isEnumField(field: BusinessConfirmationField): boolean {
  return inferConfirmationValueType(field) === 'enum';
}

function fieldOptions(field: BusinessConfirmationField): BusinessConfirmationOption[] {
  const options = normalizeConfirmationOptions(field.options);
  const current = field.value === null || field.value === undefined ? '' : String(field.value);
  if (current && !options.some((item) => item.value === current)) {
    return [{ value: current, label: current }, ...options];
  }
  return options;
}

function onEnumChange(field: BusinessConfirmationField, value: string) {
  field.value = value;
}

function isReadonlyField(field: BusinessConfirmationField): boolean {
  return field.editable === false;
}

function isDisplayOnlyField(field: BusinessConfirmationField): boolean {
  return locked.value || isReadonlyField(field);
}

function isMultilineField(field: BusinessConfirmationField): boolean {
  if (isDateField(field) || isDateTimeField(field) || isEnumField(field)) return false;
  if (field.value_type === 'text') return true;
  const value = field.value === null || field.value === undefined ? '' : String(field.value);
  return value.includes('\n') || value.length > 80;
}

function isTextRow(field: BusinessConfirmationField): boolean {
  return isDisplayOnlyField(field);
}

function isMultilineRow(field: BusinessConfirmationField): boolean {
  if (isTextRow(field)) {
    const text = displayFieldValue(field);
    return text.includes('\n') || text.length > 40;
  }
  return isMultilineField(field);
}

function rowClass(field: BusinessConfirmationField): string {
  if (isMultilineRow(field)) return 'is-multiline';
  if (isTextRow(field)) return 'is-text';
  return 'is-control';
}

function displayFieldValue(field: BusinessConfirmationField): string {
  let text = '';
  if (field.value_type === 'boolean') {
    text = Boolean(field.value) ? '是' : '否';
  } else if (isEnumField(field)) {
    const current = field.value === null || field.value === undefined ? '' : String(field.value);
    const match = fieldOptions(field).find((item) => item.value === current);
    text = match?.label || current;
  } else if (isDateTimeField(field)) {
    text = confirmationDateTimeDisplayValue(field.value) || String(field.value ?? '');
  } else if (isDateField(field)) {
    text = confirmationDateInputValue(field.value) || String(field.value ?? '');
  } else if (field.value !== null && field.value !== undefined) {
    text = String(field.value);
  }
  const trimmed = text.trim();
  if (!trimmed || trimmed === '请选择日期' || trimmed === '请选择日期时间') return '--';
  return trimmed;
}

function onDateChange(field: BusinessConfirmationField, raw: string) {
  field.value = raw;
}

const statusLabel = computed(() => {
  if (props.payload.status === 'submitted') {
    return props.payload.decision === 'cancelled' ? '已取消' : '已确定';
  }
  if (props.payload.status === 'stale') return '已失效';
  return '待确认';
});

function toggleExpand() {
  expanded.value = !expanded.value;
}

function onBooleanChange(field: BusinessConfirmationField, checked: boolean) {
  field.value = checked;
}

function submit(confirmed: boolean) {
  if (locked.value) return;
  emit('submit', {
    confirmed,
    fields: draftFields.map((field) => ({ ...field })),
  });
}
</script>

<template>
  <section
    class="bc-antd-card mt-2.5 w-full min-w-0 max-w-[42rem] lg:max-w-[48rem] 2xl:max-w-[52rem] overflow-hidden rounded-lg border border-[#d9d9d9] bg-white text-xs text-[rgba(0,0,0,0.88)] dark:border-gray-500 dark:bg-gray-800 dark:text-gray-100"
    role="group"
    :aria-label="payload.title || '业务数据确认'"
  >
    <div
      class="flex cursor-pointer select-none items-center justify-between gap-3 border-b border-[#d9d9d9] px-4 py-3 dark:border-gray-500"
      :title="expanded ? '点击收起' : '点击展开'"
      @click="toggleExpand"
    >
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <span class="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-primary text-white" aria-hidden="true">
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 12l2 2 4-4" />
          </svg>
        </span>
        <div class="min-w-0 truncate text-sm font-semibold leading-5">
          {{ payload.title || '请确认以下信息' }}
        </div>
        <span
          v-if="!expanded && payload.summary"
          class="min-w-0 flex-1 truncate text-xs font-normal text-[rgba(0,0,0,0.45)] dark:text-gray-400"
        >
          {{ payload.summary }}
        </span>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <span
          class="inline-flex h-5 items-center rounded-sm border px-2 text-xs leading-5"
          :class="{
            'border-[#91caff] bg-[#e6f4ff] text-[#1677ff] dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-300': payload.status === 'pending',
            'border-[#b7eb8f] bg-[#f6ffed] text-[#389e0d] dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300': payload.status === 'submitted' && payload.decision !== 'cancelled',
            'border-[#d9d9d9] bg-[#fafafa] text-[rgba(0,0,0,0.65)] dark:border-gray-600 dark:bg-gray-700 dark:text-gray-300': payload.status === 'submitted' && payload.decision === 'cancelled',
            'border-[#ffe58f] bg-[#fffbe6] text-[#d48806] dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300': payload.status === 'stale',
          }"
        >
          {{ statusLabel }}
        </span>
        <button
          type="button"
          class="flex h-6 w-6 items-center justify-center rounded-md text-[rgba(0,0,0,0.45)] hover:bg-[#f5f5f5] hover:text-[rgba(0,0,0,0.88)] dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-100"
          :aria-label="expanded ? '收起确认' : '展开确认'"
          @click.stop="toggleExpand"
        >
          <svg
            class="h-3.5 w-3.5 transition-transform duration-200"
            :class="{ 'rotate-180': !expanded }"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m19 15-7-7-7 7" />
          </svg>
        </button>
      </div>
    </div>

    <div v-show="expanded" class="px-4 pb-4 pt-3">
      <p
        v-if="payload.summary"
        class="break-words text-xs leading-5 text-[rgba(0,0,0,0.65)] dark:text-gray-300"
      >
        {{ payload.summary }}
      </p>

      <div class="bc-antd-form mt-3">
        <template v-for="field in draftFields" :key="field.key || field.label">
          <div class="bc-form-label" :class="rowClass(field)">
            {{ field.label }}<span>:</span>
          </div>
          <div class="bc-form-value" :class="rowClass(field)">
            <div
              v-if="isDisplayOnlyField(field)"
              class="bc-antd-readonly"
            >{{ displayFieldValue(field) }}</div>
            <label
              v-else-if="field.value_type === 'boolean'"
              class="bc-form-check"
            >
              <input
                type="checkbox"
                class="h-4 w-4 rounded-sm border-[#d9d9d9] text-primary accent-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed"
                :checked="Boolean(field.value)"
                :disabled="locked || field.editable === false"
                @change="onBooleanChange(field, ($event.target as HTMLInputElement).checked)"
              />
            </label>
            <ConfirmationDatePicker
              v-else-if="isDateTimeField(field)"
              :model-value="field.value"
              show-time
              :disabled="locked || field.editable === false"
              @update:model-value="onDateChange(field, $event)"
            />
            <ConfirmationDatePicker
              v-else-if="isDateField(field)"
              :model-value="field.value"
              :disabled="locked || field.editable === false"
              @update:model-value="onDateChange(field, $event)"
            />
            <ConfirmationSelect
              v-else-if="isEnumField(field)"
              :model-value="field.value"
              :options="fieldOptions(field)"
              :disabled="locked || field.editable === false"
              @update:model-value="onEnumChange(field, $event)"
            />
            <textarea
              v-else-if="isMultilineField(field)"
              v-model="field.value as string"
              :rows="String(field.value || '').split('\n').length > 3 ? 6 : 3"
              class="bc-antd-control bc-antd-textarea"
              :disabled="locked || field.editable === false"
            />
            <input
              v-else
              v-model="field.value as string | number"
              :type="field.value_type === 'number' ? 'number' : 'text'"
              class="bc-antd-control"
              :disabled="locked || field.editable === false"
            />
          </div>
        </template>
      </div>

      <div
        v-if="payload.risk_note"
        class="mt-2 flex items-start gap-2 rounded-md border border-[#ffe58f] bg-[#fffbe6] px-3 py-2 text-xs leading-5 text-[rgba(0,0,0,0.88)] dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100"
      >
        <span class="mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-[#faad14] text-white" aria-hidden="true">
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 9v4m0 4h.01" />
          </svg>
        </span>
        <p>风险提示：{{ payload.risk_note }}</p>
      </div>

      <div v-if="payload.status === 'pending'" class="mt-4 flex items-center justify-end gap-2">
        <button
          type="button"
          class="inline-flex h-7 items-center justify-center rounded-md border border-[#d9d9d9] bg-white px-3 text-xs text-[rgba(0,0,0,0.88)] transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
          :disabled="locked"
          @click="submit(false)"
        >
          {{ payload.cancel_label || '取消' }}
        </button>
        <button
          type="button"
          class="inline-flex h-7 items-center justify-center rounded-md bg-primary px-3 text-xs text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="locked"
          @click="submit(true)"
        >
          {{ payload.confirm_label || '确定' }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.bc-antd-card {
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.06), 0 1px 6px -1px rgba(0, 0, 0, 0.08), 0 2px 4px 0 rgba(0, 0, 0, 0.05);
}
.bc-antd-form {
  --bc-control-h: 32px;
  --bc-text-lh: 22px;
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  column-gap: 12px;
  row-gap: 8px;
  align-items: start;
}
.bc-form-label {
  margin: 0;
  text-align: right;
  white-space: nowrap;
  font-size: 12px;
  color: rgba(0, 0, 0, 0.88);
}
.bc-form-label.is-control {
  line-height: var(--bc-control-h);
}
.bc-form-label.is-text,
.bc-form-label.is-multiline {
  line-height: var(--bc-text-lh);
}
.bc-form-value {
  min-width: 0;
  font-size: 12px;
  color: rgba(0, 0, 0, 0.88);
}
.bc-form-value.is-control {
  min-height: var(--bc-control-h);
  line-height: var(--bc-control-h);
}
.bc-form-value.is-text,
.bc-form-value.is-multiline {
  min-height: var(--bc-text-lh);
  line-height: var(--bc-text-lh);
}
.bc-form-check {
  display: inline-flex;
  height: var(--bc-control-h);
  align-items: center;
}
.bc-antd-control {
  display: block;
  box-sizing: border-box;
  width: 100%;
  height: var(--bc-control-h);
  min-height: var(--bc-control-h);
  margin: 0;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background-color: #fff;
  padding: 0 11px;
  font-size: 12px;
  line-height: calc(var(--bc-control-h) - 2px);
  color: rgba(0, 0, 0, 0.88);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.bc-antd-control:hover:not(:disabled) {
  border-color: #1677ff;
}
.bc-antd-control:focus {
  border-color: #1677ff;
  box-shadow: 0 0 0 2px rgba(5, 145, 255, 0.1);
}
.bc-antd-control:disabled {
  cursor: default;
  background-color: #fff;
  color: rgba(0, 0, 0, 0.88);
  border-color: #d9d9d9;
  opacity: 1;
  -webkit-text-fill-color: rgba(0, 0, 0, 0.88);
}
.bc-antd-textarea {
  height: auto;
  min-height: 76px;
  padding: 5px 11px;
  line-height: var(--bc-text-lh);
  resize: vertical;
  white-space: pre-wrap;
}
.bc-antd-readonly {
  display: block;
  box-sizing: border-box;
  width: 100%;
  margin: 0;
  border: none;
  background-color: transparent;
  padding: 0;
  font-size: inherit;
  line-height: inherit;
  color: inherit;
  white-space: pre-wrap;
  word-break: break-word;
}
.bc-antd-form :deep(.bc-select-trigger),
.bc-antd-form :deep(.bc-date-trigger) {
  height: var(--bc-control-h);
  min-height: var(--bc-control-h);
  margin: 0;
}
:global(.dark) .bc-form-label,
:global(.dark) .bc-form-value {
  color: rgb(243 244 246);
}
:global(.dark) .bc-antd-control {
  background-color: rgb(17 24 39);
  border-color: rgb(75 85 99);
  color: rgb(243 244 246);
}
:global(.dark) .bc-antd-control:disabled {
  background-color: rgb(31 41 55);
  color: rgb(243 244 246);
  -webkit-text-fill-color: rgb(243 244 246);
}
</style>

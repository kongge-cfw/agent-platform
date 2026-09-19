<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

interface Props {
  title: string
  message?: string
  confirmText?: string
  cancelText?: string
  type?: 'danger' | 'primary' | 'warning'
  loading?: boolean
  details?: string[]
  detailsLabel?: string
  detailsLimit?: number
  showCancel?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  confirmText: '确认',
  cancelText: '取消',
  type: 'danger',
  loading: false,
  details: () => [],
  detailsLabel: '影响配置',
  detailsLimit: 5,
  showCancel: true,
})

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

const confirmButtonRef = ref<HTMLButtonElement | null>(null)
const showAllDetails = ref(false)
const visibleDetails = computed(() => props.details?.slice(0, props.detailsLimit) || [])
const hasHiddenDetails = computed(() => (props.details?.length || 0) > props.detailsLimit)

const toggleDetails = () => {
  showAllDetails.value = !showAllDetails.value
}

const handleKeydown = (e: KeyboardEvent) => {
  if (props.loading) return
  if (e.key === 'Enter') {
    e.preventDefault()
    e.stopPropagation()
    emit('confirm')
  } else if (e.key === 'Escape') {
    e.preventDefault()
    e.stopPropagation()
    emit('cancel')
  }
}

onMounted(() => {
  confirmButtonRef.value?.focus()
  document.addEventListener('keydown', handleKeydown, true)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown, true)
})
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-[13000] flex items-center justify-center p-4 bg-black/[0.45]"
      role="dialog"
      aria-modal="true"
      @click.self="!loading && $emit('cancel')"
    >
      <!-- 视觉对齐 Ant Design Modal.warning / Modal.confirm：416 宽、左图标、右标题正文、底栏右对齐 -->
      <div
        class="w-[416px] max-w-[calc(100vw-32px)] overflow-hidden rounded-lg bg-white dark:bg-gray-800"
        style="box-shadow: 0 6px 16px 0 rgba(0,0,0,0.08), 0 3px 6px -4px rgba(0,0,0,0.12), 0 9px 28px 8px rgba(0,0,0,0.05);"
      >
        <div class="flex gap-3 px-6 pt-5">
          <div
            class="mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-white"
            :class="{
              'bg-[#ff4d4f]': type === 'danger',
              'bg-primary': type === 'primary',
              'bg-[#faad14]': type === 'warning',
            }"
            aria-hidden="true"
          >
            <svg v-if="type === 'primary'" class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 16h-1v-4h-1m1-4h.01" />
            </svg>
            <svg v-else class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 9v4m0 4h.01" />
            </svg>
          </div>
          <div class="min-w-0 flex-1 pb-2">
            <h3 class="text-base font-semibold leading-6 text-[rgba(0,0,0,0.88)] dark:text-gray-100">{{ title }}</h3>
            <div v-if="$slots.default" class="mt-2">
              <slot />
            </div>
            <p
              v-else-if="message"
              class="mt-2 text-sm leading-6 text-[rgba(0,0,0,0.65)] dark:text-gray-400 whitespace-pre-line"
            >
              {{ message }}
            </p>
            <div v-if="details?.length" class="mt-3">
              <p class="mb-1 text-xs font-medium text-[rgba(0,0,0,0.45)] dark:text-gray-400">
                {{ detailsLabel }}（{{ details.length }}）
              </p>
              <ul class="max-h-36 space-y-1 overflow-y-auto rounded-md bg-[#fafafa] p-2 text-xs text-[rgba(0,0,0,0.65)] dark:bg-gray-900/40 dark:text-gray-300">
                <li v-for="(detail, index) in (showAllDetails ? details : visibleDetails)" :key="`${index}-${detail}`" class="truncate" :title="detail">
                  {{ detail }}
                </li>
              </ul>
              <button
                v-if="hasHiddenDetails"
                type="button"
                class="mt-1 text-xs font-medium text-primary hover:text-primary-hover"
                @click="toggleDetails"
              >
                {{ showAllDetails ? '收起列表' : `还有 ${details.length - detailsLimit} 个，展开查看` }}
              </button>
            </div>
          </div>
        </div>
        <div class="flex justify-end gap-2 px-4 py-3">
          <button
            v-if="showCancel"
            @click="!loading && $emit('cancel')"
            type="button"
            class="inline-flex h-8 items-center justify-center rounded-md border border-[#d9d9d9] bg-white px-[15px] text-sm text-[rgba(0,0,0,0.88)] transition-colors hover:border-primary hover:text-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:border-primary dark:hover:text-primary"
            :disabled="loading"
          >
            {{ cancelText }}
          </button>
          <button
            ref="confirmButtonRef"
            @click="!loading && $emit('confirm')"
            type="button"
            class="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-transparent px-[15px] text-sm text-white shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-60"
            :class="{
              'bg-[#ff4d4f] hover:bg-[#ff7875] focus:ring-[#ff4d4f]/30': type === 'danger',
              'bg-primary hover:bg-primary-hover focus:ring-primary/30': type !== 'danger',
            }"
            :disabled="loading"
          >
            <svg v-if="loading" class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span>{{ loading ? '处理中...' : confirmText }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

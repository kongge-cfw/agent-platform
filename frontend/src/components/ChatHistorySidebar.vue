<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed } from "vue";
import {
  readHistoryCollapsedGroups,
  writeHistoryCollapsedGroups,
} from "@/utils/chatHistorySidebarPref";

const props = withDefaults(
  defineProps<{
    visible: boolean;
    loading: boolean;
    loadingMore?: boolean;
    hasMore?: boolean;
    historyList: any[];
    activeTraceId?: string;
    activeConversationId?: string;
    processingConversationIds?: string[];
    settledConversationIds?: string[];
    modelValue: string; // keyword
  }>(),
  {
    loadingMore: false,
    hasMore: false,
    activeTraceId: "",
    activeConversationId: "",
    processingConversationIds: () => [],
    settledConversationIds: () => [],
  }
);

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "update:modelValue", value: string): void;
  (e: "fetch-history"): void;
  (e: "load-more"): void;
  (e: "load-chat", item: any): void;
  (e: "delete-history", item: any): void;
  (e: "delete-group", group: any): void;
  (e: "new-chat"): void;
}>();

const windowWidth = ref(window.innerWidth);
const isMobile = computed(() => windowWidth.value < 640);

const handleResize = () => {
  windowWidth.value = window.innerWidth;
};

onMounted(() => {
  window.addEventListener("resize", handleResize);
});

onUnmounted(() => {
  window.removeEventListener("resize", handleResize);
});

// Search keyword with Debounce
const keyword = ref(props.modelValue);
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

watch(
  () => props.modelValue,
  (val) => {
    keyword.value = val;
  }
);

const handleSearchInput = () => {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    emit("update:modelValue", keyword.value);
  }, 300);
};

const clearSearch = () => {
  keyword.value = "";
  if (debounceTimer) clearTimeout(debounceTimer);
  emit("update:modelValue", "");
};

// Date Formatter
const formatDate = (dateStr: string) => {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();

  if (diff < 60000) {
    return "刚刚";
  }
  if (diff < 3600000) {
    return `${Math.floor(diff / 60000)} 分钟前`;
  }
  if (diff < 86400000) {
    return `${Math.floor(diff / 3600000)} 小时前`;
  }
  if (diff < 604800000) {
    return `${Math.floor(diff / 86400000)} 天前`;
  }

  return date.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

// Infinite Scroll
const handleScroll = (e: Event) => {
  const target = e.target as HTMLElement;
  if (!target) return;
  if (target.scrollHeight - target.scrollTop <= target.clientHeight + 15) {
    if (props.hasMore && !props.loading && !props.loadingMore) {
      emit("load-more");
    }
  }
};

// Check if Item is Active
const isItemActive = (item: any) => {
  if (props.activeConversationId && item.conversation_id) {
    return props.activeConversationId === item.conversation_id;
  }
  if (props.activeTraceId && item.trace_id) {
    return props.activeTraceId === item.trace_id;
  }
  return false;
};

const isItemRunning = (item: any) => {
  const cid = String(item?.conversation_id || "");
  if (cid && props.processingConversationIds.includes(cid)) return true;
  if (item?.status !== "running") return false;
  if (cid && props.settledConversationIds.includes(cid)) return false;
  return true;
};

// 日期分组默认全部展开；用户收起后再写入本地，刷新后保持。
const collapsedGroups = ref<Record<string, boolean>>(readHistoryCollapsedGroups());

const toggleGroupCollapse = (groupId: string) => {
  const next = { ...collapsedGroups.value };
  if (next[groupId]) delete next[groupId];
  else next[groupId] = true;
  collapsedGroups.value = next;
  writeHistoryCollapsedGroups(next);
};

// Single Delete Inline Confirmation State
const deletingItemId = ref<string | null>(null);

const triggerDelete = (item: any) => {
  const id = item.conversation_id || item.trace_id;
  deletingItemId.value = id;
};

const cancelDelete = () => {
  deletingItemId.value = null;
};

const confirmDelete = (item: any) => {
  deletingItemId.value = null;
  emit("delete-history", item);
};
</script>

<template>
  <!-- Mobile Backdrop -->
  <div
    v-if="visible && isMobile"
    class="fixed inset-0 bg-black/40 backdrop-blur-sm z-40 transition-opacity"
    @click="emit('update:visible', false)"
  ></div>

  <transition :name="isMobile ? 'slide-up' : 'slide-fade-left'">
    <div
      v-if="visible"
      class="bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col flex-shrink-0 shadow-xl transition-all duration-300"
      :class="[
        isMobile
          ? 'fixed inset-x-0 bottom-0 top-0 w-full z-50 rounded-none h-full'
          : 'relative w-72 h-full z-10'
      ]"
    >
      <!-- Header -->
      <div
        class="h-12 px-3.5 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between bg-white/80 dark:bg-gray-900/80 backdrop-blur-md flex-shrink-0"
      >
        <div class="flex min-w-0 items-center gap-1.5">
          <svg class="w-4 h-4 shrink-0 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <h3 class="truncate font-bold text-gray-800 dark:text-gray-100 text-xs tracking-wider uppercase">
            会话历史
          </h3>
        </div>

        <div class="flex items-center gap-0.5">
          <button
            @click="emit('fetch-history')"
            class="inline-flex h-7 shrink-0 items-center gap-0.5 rounded-lg px-1 text-[11px] font-medium text-gray-700 transition-colors hover:bg-gray-100 hover:text-primary dark:text-gray-200 dark:hover:bg-gray-800"
            title="刷新会话历史"
          >
            <svg
              class="h-4 w-4 shrink-0"
              :class="{ 'animate-spin text-primary': loading }"
              fill="none"
              stroke="currentColor"
              stroke-width="1.75"
              stroke-linecap="round"
              stroke-linejoin="round"
              viewBox="0 0 24 24"
            >
              <path d="M20 12a8 8 0 0 1-13.7 5.6L4 16" />
              <path d="M4 20v-4h4" />
              <path d="M4 12a8 8 0 0 1 13.7-5.6L20 8" />
              <path d="M20 4v4h-4" />
            </svg>
            刷新
          </button>
          <button
            type="button"
            @click="emit('new-chat')"
            class="inline-flex h-7 shrink-0 items-center gap-0.5 rounded-lg px-1 text-[11px] font-medium text-gray-700 transition-colors hover:bg-gray-100 hover:text-primary dark:text-gray-200 dark:hover:bg-gray-800"
            title="新会话"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24">
              <path d="M5.2 16.8 3.5 20l2.6-1.2A8.2 8.2 0 1 0 8 19.2" />
              <path d="M12 9v6M9 12h6" />
            </svg>
            新会话
          </button>
          <button
            @click="emit('update:visible', false)"
            class="inline-flex h-7 shrink-0 items-center gap-0.5 rounded-lg px-1 text-[11px] font-medium text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-200 dark:hover:bg-gray-800 dark:hover:text-white"
            title="收起侧边栏"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24">
              <rect x="4" y="4" width="16" height="16" rx="2.5" />
              <path d="M9.5 4v16" />
              <path d="M14.6 9.2 11.8 12l2.8 2.8" />
            </svg>
            收起
          </button>
        </div>
      </div>

      <!-- Search Bar with Debounce & Clear -->
      <div class="px-3 py-2.5 border-b border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 flex-shrink-0">
        <div class="relative flex items-center">
          <svg
            class="w-3.5 h-3.5 text-gray-400 absolute left-3 pointer-events-none"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            v-model="keyword"
            @input="handleSearchInput"
            type="text"
            placeholder="搜索历史记录..."
            class="w-full pl-8 pr-7 py-1.5 text-xs bg-gray-50/80 dark:bg-gray-800/80 border border-gray-200/80 dark:border-gray-700/80 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all placeholder-gray-400 text-gray-700 dark:text-gray-200"
          />
          <button
            v-if="keyword"
            @click="clearSearch"
            type="button"
            class="absolute right-2.5 p-0.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 rounded-full transition-colors"
            title="清空搜索"
          >
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <!-- History List -->
      <div class="flex-1 overflow-y-auto custom-scrollbar bg-gray-50/40 dark:bg-gray-900/40" @scroll="handleScroll">
        <!-- Skeleton Loading (Shimmer) -->
        <div v-if="loading && !historyList.length" class="p-3 space-y-3">
          <div
            v-for="n in 4"
            :key="n"
            class="p-3.5 rounded-2xl bg-white dark:bg-gray-800/70 border border-gray-100 dark:border-gray-800 space-y-2.5 animate-pulse"
          >
            <div class="flex items-center justify-between">
              <div class="h-3 w-16 bg-gray-200 dark:bg-gray-700 rounded-md"></div>
              <div class="h-3 w-10 bg-gray-100 dark:bg-gray-700/60 rounded-md"></div>
            </div>
            <div class="h-3.5 w-4/5 bg-gray-200 dark:bg-gray-700 rounded-md"></div>
            <div class="h-2.5 w-full bg-gray-100 dark:bg-gray-700/50 rounded-md"></div>
          </div>
        </div>

        <!-- Empty State -->
        <div v-else-if="!historyList.length" class="p-8 text-center flex flex-col items-center justify-center h-4/5">
          <div class="w-14 h-14 bg-primary/5 dark:bg-primary/10 rounded-2xl flex items-center justify-center mx-auto mb-3 border border-primary/10">
            <svg
              class="w-7 h-7 text-primary/60"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="1.8"
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          </div>
          <p class="text-xs font-bold text-gray-600 dark:text-gray-300 mb-1">暂无会话历史</p>
          <p class="text-[11px] text-gray-400 dark:text-gray-500 mb-4 max-w-[180px]">
            开启新对话，即可记录您的灵感与工作流
          </p>
          <button
            @click="emit('new-chat')"
            class="px-3.5 py-1.5 rounded-lg border border-primary/30 text-primary text-xs font-semibold hover:bg-primary/5 transition-colors"
          >
            开启新对话
          </button>
        </div>

        <!-- Grouped History -->
        <div v-else class="space-y-3 p-2.5">
          <div v-for="group in historyList" :key="group.id" class="mb-2">
            <!-- Accordion Group Header -->
            <div
              @click="toggleGroupCollapse(group.id)"
              class="px-2.5 py-1.5 flex items-center justify-between rounded-xl cursor-pointer select-none hover:bg-gray-100/80 dark:hover:bg-gray-800/60 transition-colors mb-1.5 group/header"
            >
              <div class="flex items-center gap-1.5 min-w-0">
                <svg
                  class="w-3.5 h-3.5 text-gray-400 group-hover/header:text-gray-600 dark:group-hover/header:text-gray-300 transition-transform duration-200"
                  :class="{ '-rotate-90': collapsedGroups[group.id] }"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                </svg>
                <span class="text-[11px] font-bold text-gray-500 dark:text-gray-400 tracking-wider">
                  {{ group.title }}
                </span>
                <span class="text-[10px] text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.2 rounded-full">
                  {{ group.items.length }}
                </span>
              </div>

              <!-- Delete Entire Group Action -->
              <button
                @click.stop="emit('delete-group', group)"
                class="p-1 opacity-0 group-hover/header:opacity-100 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/40 rounded-lg text-gray-400 transition-all"
                title="清空此组全部会话"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>

            <!-- Group Items List (Collapsible) -->
            <div v-show="!collapsedGroups[group.id]" class="space-y-1.5">
              <div
                v-for="item in group.items"
                :key="item.conversation_id || item.trace_id"
                @click="emit('load-chat', item)"
                class="p-3 rounded-xl transition-all border group relative overflow-hidden"
                :class="[
                  isItemActive(item)
                    ? 'bg-primary/[0.06] dark:bg-primary/[0.12] border-primary/30 shadow-sm ring-1 ring-primary/20'
                    : 'bg-white dark:bg-gray-800/80 border-gray-100 dark:border-gray-800/60 hover:border-primary/30 hover:bg-white dark:hover:bg-gray-800 hover:shadow-sm cursor-pointer'
                ]"
              >
                <!-- Active Indicator Bar -->
                <div
                  v-if="isItemActive(item)"
                  class="absolute left-0 top-2 bottom-2 w-1 bg-primary rounded-r-full"
                ></div>

                <!-- Top Row: Date & Actions -->
                <div class="flex items-center justify-between mb-1.5">
                  <div class="flex items-center gap-1.5 min-w-0">
                    <span
                      v-if="item.project_name"
                      class="px-1.5 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 border border-indigo-100 dark:border-indigo-900/50 text-[9px] font-bold truncate max-w-[90px]"
                      :title="item.project_name"
                    >
                      📁 {{ item.project_name }}
                    </span>
                    <span class="text-[10px] font-medium text-gray-400">
                      {{ formatDate(item.created_at) }}
                    </span>
                  </div>

                  <!-- Hover Action Buttons -->
                  <div class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <!-- Delete Single -->
                    <button
                      @click.stop="triggerDelete(item)"
                      class="p-1 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/40 rounded-md text-gray-400 transition-colors"
                      title="删除此会话"
                    >
                      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>

                <!-- Query / Title -->
                <p
                  class="text-xs font-bold text-gray-800 dark:text-gray-100 truncate mb-1 transition-colors"
                  :class="{ 'text-primary dark:text-primary': isItemActive(item) }"
                  :title="item.query"
                >
                  {{ item.query || '未命名对话' }}
                </p>

                <!-- Summary Preview -->
                <p
                  v-if="item.summary"
                  class="text-[11px] text-gray-500 dark:text-gray-400 line-clamp-2 leading-relaxed"
                  :title="item.summary"
                >
                  {{ item.summary }}
                </p>

                <!-- Footer: Turn Count & Active Tag -->
                <div class="mt-2 flex items-center justify-between text-[10px] text-gray-400">
                  <div class="flex items-center gap-1.5">
                    <span v-if="isItemRunning(item)" class="relative flex h-1.5 w-1.5 shrink-0">
                      <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75"></span>
                      <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500"></span>
                    </span>
                    <span
                      v-else
                      class="w-1.5 h-1.5 rounded-full"
                      :class="item.status === 'failed' || item.status === 'error'
                        ? 'bg-rose-500'
                        : item.status === 'interrupted'
                          ? 'bg-gray-400'
                          : 'bg-emerald-500'"
                    ></span>
                    <span v-if="isItemRunning(item)" class="font-bold text-amber-600 dark:text-amber-400">
                      进行中
                    </span>
                    <span v-else-if="item.status === 'interrupted'" class="font-bold text-gray-500 dark:text-gray-400">
                      已中断
                    </span>
                    <span v-if="item.turn_count !== undefined">
                      {{ item.turn_count }} 轮交互
                    </span>
                  </div>

                  <span
                    v-if="isItemActive(item)"
                    class="px-1.5 py-0.5 rounded-md bg-primary/10 text-primary font-bold text-[9px] uppercase tracking-wider"
                  >
                    当前会话
                  </span>
                </div>

                <!-- Inline Delete Confirmation Overlay -->
                <div
                  v-if="deletingItemId === (item.conversation_id || item.trace_id)"
                  @click.stop
                  class="absolute inset-0 bg-white/95 dark:bg-gray-900/95 backdrop-blur-xs flex items-center justify-between px-3.5 z-20 transition-all"
                >
                  <span class="text-xs text-red-600 dark:text-red-400 font-bold">确认删除该会话？</span>
                  <div class="flex items-center gap-2">
                    <button
                      @click.stop="cancelDelete"
                      class="px-2 py-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 rounded-md"
                    >
                      取消
                    </button>
                    <button
                      @click.stop="confirmDelete(item)"
                      class="px-2 py-1 text-xs bg-red-600 hover:bg-red-700 text-white font-bold rounded-md shadow-xs transition-colors"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Loading More Indicator -->
          <div v-if="loadingMore" class="py-3 flex justify-center items-center text-gray-400">
            <svg class="w-4 h-4 animate-spin text-primary" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span class="ml-2 text-xs font-medium">加载更多...</span>
          </div>

          <!-- No More Records -->
          <div v-if="!hasMore && historyList.length > 0" class="py-3 text-center text-[10px] text-gray-400 uppercase tracking-wider opacity-60">
            - 已加载全部历史 -
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.slide-fade-left-enter-active,
.slide-fade-left-leave-active {
  transition: all 0.28s cubic-bezier(0.16, 1, 0.3, 1);
}

.slide-fade-left-enter-from,
.slide-fade-left-leave-to {
  transform: translateX(-16px);
  opacity: 0;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.32s cubic-bezier(0.16, 1, 0.3, 1);
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
}
</style>

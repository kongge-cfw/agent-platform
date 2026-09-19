<template>
  <div
    v-if="files.length || uploading"
    class="user-message-file-wrap"
  >
    <div
      v-if="showClearAll && files.length"
      class="user-message-file-toolbar"
    >
      <span class="user-message-file-count">已添加 {{ files.length }} 个附件</span>
      <button
        type="button"
        class="user-message-file-clear"
        title="清空附件"
        @click="emit('clear')"
      >
        <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
        <span>清空附件</span>
      </button>
    </div>
    <div
      class="user-message-file-list"
      :class="align === 'start' ? 'is-start' : 'is-end'"
      :style="{ '--file-card-columns': String(columns) }"
    >
      <component
        :is="removable ? 'div' : 'button'"
        v-for="(file, index) in files"
        :key="`${file.filename || 'file'}-${index}`"
        :type="removable ? undefined : 'button'"
        class="user-message-file-card group min-w-0 text-left"
        :class="{ 'is-plain': plain }"
        :title="file.filename"
        @click="onClick(file)"
      >
        <AttachmentImageThumb
          v-if="isImageAttachment(file)"
          :file="file"
          clickable
          size-class="w-8 h-8"
          class="flex-shrink-0 border border-[#f0f0f0] dark:border-gray-700"
          @click.stop="(url) => emit('preview-image', url, file.filename || '图片预览')"
        />
        <span
          v-else
          class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md border border-[#f0f0f0] text-sm dark:border-gray-700"
          :class="iconClass(file)"
        >
          {{ iconText(file) }}
        </span>
        <span class="min-w-0 flex-1">
          <span class="block truncate text-xs font-medium leading-5 text-[rgba(0,0,0,0.88)] dark:text-gray-100">
            {{ file.filename }}
          </span>
          <span class="block truncate text-[11px] leading-4 text-[rgba(0,0,0,0.45)] dark:text-gray-400">
            {{ subtitle(file) }}
          </span>
        </span>
        <button
          v-if="removable"
          type="button"
          class="user-message-file-remove"
          title="移除附件"
          @click.stop="emit('remove', file, index)"
        >
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </component>
      <div
        v-if="uploading"
        class="user-message-file-card is-uploading"
        :class="{ 'is-plain': plain }"
      >
        <span class="h-3.5 w-3.5 flex-shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span class="truncate text-xs text-[rgba(0,0,0,0.45)] dark:text-gray-400">正在上传...</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import AttachmentImageThumb from "@/components/embed/AttachmentImageThumb.vue";
import { isImageAttachment } from "@/utils/attachmentImages";
import { resolveFileTypeVisual } from "@/utils/fileTypeVisual";

export type UserMessageAttachment = {
  url?: string;
  type?: string;
  ext?: string;
  filename?: string;
  size?: number;
};

const RESOURCE_META: Record<string, { icon: string; label: string; iconClass: string }> = {
  skill: {
    icon: "⚙️",
    label: "生态技能",
    iconClass: "bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300",
  },
  knowledge_base: {
    icon: "📚",
    label: "知识库",
    iconClass: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300",
  },
  metadata_dataset: {
    icon: "📊",
    label: "数据集",
    iconClass: "bg-purple-50 text-purple-600 dark:bg-purple-500/15 dark:text-purple-300",
  },
  memory: {
    icon: "🧠",
    label: "记忆记录",
    iconClass: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300",
  },
  local_file: {
    icon: "💻",
    label: "服务器文件",
    iconClass: "bg-blue-50 text-blue-600 dark:bg-blue-500/15 dark:text-blue-300",
  },
  local_dir: {
    icon: "📁",
    label: "服务器目录",
    iconClass: "bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300",
  },
};

withDefaults(defineProps<{
  files: UserMessageAttachment[];
  columns?: number;
  align?: "start" | "end";
  removable?: boolean;
  showClearAll?: boolean;
  uploading?: boolean;
  plain?: boolean;
}>(), {
  columns: 4,
  align: "end",
  removable: false,
  showClearAll: false,
  uploading: false,
  plain: false,
});

const emit = defineEmits<{
  (e: "open-file", file: UserMessageAttachment): void;
  (e: "preview-image", url: string, filename: string): void;
  (e: "remove", file: UserMessageAttachment, index: number): void;
  (e: "clear"): void;
}>();

const formatBytes = (bytes?: number) => {
  const value = Number(bytes || 0);
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${Number((value / 1024 ** index).toFixed(1))} ${units[index]}`;
};

const resourceMeta = (file: UserMessageAttachment) => RESOURCE_META[String(file.type || "")];

const iconText = (file: UserMessageAttachment) =>
  resourceMeta(file)?.icon || resolveFileTypeVisual(file.filename || "", file.type === "local_dir").icon;

const iconClass = (file: UserMessageAttachment) =>
  resourceMeta(file)?.iconClass ||
  resolveFileTypeVisual(file.filename || "", file.type === "local_dir").iconBg;

const subtitle = (file: UserMessageAttachment) => {
  const resource = resourceMeta(file);
  if (resource) {
    if (file.type === "local_file" && isImageAttachment(file)) return "服务器图片";
    return resource.label;
  }
  return formatBytes(file.size);
};

const onClick = (file: UserMessageAttachment) => {
  if (isImageAttachment(file)) {
    const url = String(file.url || "").trim();
    if (url) emit("preview-image", url, file.filename || "图片预览");
    return;
  }
  if (resourceMeta(file) && file.type !== "local_file" && file.type !== "local_dir") {
    return;
  }
  emit("open-file", file);
};
</script>

<style scoped>
.user-message-file-wrap {
  width: 100%;
}

.user-message-file-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
  padding: 0 2px;
}

.user-message-file-count {
  font-size: 12px;
  line-height: 20px;
  color: rgba(0, 0, 0, 0.45);
}

.user-message-file-clear {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  line-height: 20px;
  color: rgba(0, 0, 0, 0.45);
  background: transparent;
  border: 0;
  padding: 0;
  cursor: pointer;
}

.user-message-file-clear:hover {
  color: #ff4d4f;
}

.user-message-file-list {
  --file-card-columns: 4;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  width: 100%;
}

.user-message-file-list.is-start {
  justify-content: flex-start;
}

.user-message-file-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  width: calc((100% - (var(--file-card-columns) - 1) * 8px) / var(--file-card-columns));
  min-height: 56px;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 8px;
  box-shadow: none;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.user-message-file-card.is-uploading {
  cursor: default;
}

.user-message-file-card.is-plain {
  background: transparent;
  box-shadow: none;
}

.user-message-file-card:hover {
  border-color: var(--primary-color, #1677ff);
}

.user-message-file-card.is-uploading:hover {
  border-color: #d9d9d9;
}

.user-message-file-remove {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 0;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.04);
  color: rgba(0, 0, 0, 0.45);
  opacity: 0;
  cursor: pointer;
}

.user-message-file-card:hover .user-message-file-remove,
.user-message-file-remove:focus-visible {
  opacity: 1;
}

.user-message-file-remove:hover {
  background: #ff4d4f;
  color: #fff;
}

.dark .user-message-file-count,
.dark .user-message-file-clear {
  color: rgb(156 163 175);
}

.dark .user-message-file-clear:hover {
  color: rgb(248 113 113);
}

.dark .user-message-file-card {
  background: rgb(31 41 55);
  border-color: rgb(75 85 99);
}

.dark .user-message-file-card.is-plain {
  background: transparent;
}

.dark .user-message-file-card.is-uploading:hover {
  border-color: rgb(75 85 99);
}

.dark .user-message-file-remove {
  background: rgb(55 65 81);
  color: rgb(156 163 175);
}
</style>

export const CHAT_FILE_MAX_COUNT = 10;
export const CHAT_FILE_MAX_BYTES = 20 * 1024 * 1024;

const FORBIDDEN_EXTS = new Set([
  ".exe",
  ".bat",
  ".sh",
  ".cmd",
  ".msi",
  ".php",
  ".js",
  ".html",
]);

export type ChatAttachmentLike = {
  type?: string;
};

export type ChatFileIntakePlan = {
  accepted: File[];
  overflowCount: number;
  oversizeNames: string[];
  forbiddenNames: string[];
  notice: string;
};

function fileKey(file: File): string {
  return `${file.name}\0${file.size}\0${file.lastModified}\0${file.type}`;
}

function displayName(file: File): string {
  return String(file.name || "").trim() || "未命名文件";
}

export function fileExt(name: string): string {
  const idx = String(name || "").lastIndexOf(".");
  return idx >= 0 ? name.slice(idx).toLowerCase() : "";
}

export function collectFilesFromList(list: ArrayLike<File> | null | undefined): File[] {
  if (!list) return [];
  const seen = new Set<string>();
  const files: File[] = [];
  for (let i = 0; i < list.length; i += 1) {
    const file = list[i];
    if (!file) continue;
    const key = fileKey(file);
    if (seen.has(key)) continue;
    seen.add(key);
    files.push(file);
  }
  return files;
}

export function collectClipboardFiles(data: DataTransfer | null | undefined): File[] {
  if (!data) return [];
  const seen = new Set<string>();
  const files: File[] = [];
  const add = (file: File | null | undefined) => {
    if (!file) return;
    const key = fileKey(file);
    if (seen.has(key)) return;
    seen.add(key);
    files.push(file);
  };
  // 访达 / 资源管理器一次复制多个文件时，完整列表在 files，items 往往只有第一项。
  for (const file of collectFilesFromList(data.files)) add(file);
  if (data.items) {
    for (const item of Array.from(data.items)) {
      if (item.kind === "file") add(item.getAsFile());
    }
  }
  return files;
}

export function isPhysicalChatAttachment(item: ChatAttachmentLike | null | undefined): boolean {
  const type = String(item?.type || "").trim();
  return !type || type === "local_file";
}

export function countPhysicalChatAttachments(
  items: ChatAttachmentLike[] | null | undefined,
): number {
  return (items || []).filter(isPhysicalChatAttachment).length;
}

export function planChatFileIntake(
  files: File[],
  options?: {
    existingCount?: number;
    maxCount?: number;
    maxBytes?: number;
  },
): ChatFileIntakePlan {
  const maxCount = options?.maxCount ?? CHAT_FILE_MAX_COUNT;
  const maxBytes = options?.maxBytes ?? CHAT_FILE_MAX_BYTES;
  const existing = Math.max(0, options?.existingCount ?? 0);
  const remaining = Math.max(0, maxCount - existing);

  const oversizeNames: string[] = [];
  const forbiddenNames: string[] = [];
  const eligible: File[] = [];

  for (const file of files) {
    if (file.size > maxBytes) {
      oversizeNames.push(displayName(file));
      continue;
    }
    if (FORBIDDEN_EXTS.has(fileExt(file.name))) {
      forbiddenNames.push(displayName(file));
      continue;
    }
    eligible.push(file);
  }

  const accepted = eligible.slice(0, remaining);
  const overflowCount = Math.max(0, eligible.length - accepted.length);

  const lines: string[] = [];
  if (oversizeNames.length) {
    lines.push(`每个文件不能超过 20MB，已跳过：${oversizeNames.join("、")}`);
  }
  if (forbiddenNames.length) {
    lines.push(`暂不支持该类型文件，已跳过：${forbiddenNames.join("、")}`);
  }
  if (overflowCount) {
    if (existing >= maxCount) {
      lines.push(`当前已有 ${maxCount} 个文件，单次最多 ${maxCount} 个，请先移除后再添加`);
    } else {
      lines.push(`单次最多上传 ${maxCount} 个文件，已忽略其余 ${overflowCount} 个`);
    }
  }

  return {
    accepted,
    overflowCount,
    oversizeNames,
    forbiddenNames,
    notice: lines.join("\n"),
  };
}

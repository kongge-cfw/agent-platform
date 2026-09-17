import { stripAppBase, withAppBase } from "./appBase";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "webp", "gif"]);

export function normalizeAttachmentExt(ext?: string, url?: string): string {
  let normalized = (ext || "").toLowerCase().replace(/^\./, "");
  if (!normalized && url) {
    const path = url.split("?")[0] || "";
    const segment = path.split("/").pop() || "";
    const dot = segment.lastIndexOf(".");
    normalized = dot >= 0 ? segment.slice(dot + 1).toLowerCase() : "";
  }
  return normalized;
}

export function isImageAttachment(file: {
  ext?: string;
  url?: string;
}): boolean {
  return IMAGE_EXTS.has(normalizeAttachmentExt(file.ext, file.url));
}

/** 输入框/气泡内图片缩略图 URL（本地上传 vs 服务器文件） */
export function getAttachmentPreviewUrl(file: {
  url?: string;
  type?: string;
  ext?: string;
}): string | null {
  if (!file.url || !isImageAttachment(file)) return null;
  if (/^https?:\/\//.test(file.url)) return file.url;
  const path = stripAppBase(file.url);
  if (path.startsWith("/static/uploads/")) return withAppBase(file.url);
  if (path.startsWith("/api/")) return withAppBase(file.url);
  return withAppBase(`/api/v1/chat/fs/preview?path=${encodeURIComponent(file.url)}`);
}

/** `/api/...` 预览需带鉴权头，不能直接塞进 <img src> */
export function attachmentPreviewNeedsAuthFetch(previewUrl: string | null | undefined): boolean {
  if (!previewUrl) return false;
  const path = stripAppBase(previewUrl);
  if (path.startsWith("/static/")) return false;
  if (/^https?:\/\//.test(previewUrl)) return false;
  if (previewUrl.startsWith("blob:") || previewUrl.startsWith("data:")) return false;
  return path.startsWith("/api/");
}

/** 附件在服务器上的绝对路径（供 AI 上下文与工具使用） */
export function getServerAttachmentPath(file: {
  type?: string;
  url?: string;
  filename?: string;
}): string {
  if (file.type === "skill") {
    return `/app/data/skills/${file.url}/SKILL.md`;
  }
  if (file.type === "local_file" || file.type === "local_dir") {
    return file.url || "";
  }
  const url = file.url || "";
  const path = stripAppBase(url);
  if (path.startsWith("/static/uploads/")) {
    const fileName = path.split("/").filter(Boolean).pop() || file.filename || "";
    return `/app/data/uploads/${fileName}`;
  }
  if (url && !url.startsWith("http")) {
    return url;
  }
  const fileName = url.split("/").filter(Boolean).pop() || file.filename || "";
  return `/app/data/uploads/${fileName}`;
}

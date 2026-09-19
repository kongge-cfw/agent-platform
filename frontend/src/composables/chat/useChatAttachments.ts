import { getServerAttachmentPath, isImageAttachment } from "@/utils/attachmentImages";
import { visibleUserMessageContent } from "@/utils/hitlReceiptDisplay";

export const USER_MESSAGE_CONTEXT_DIVIDER = "\n\n---\n\n";
const TRIMMED_CONTEXT_DIVIDER = "---\n\n";

/** 只认平台拼进用户消息的系统说明，避免把用户自己写的「---」或「用户本轮已…」当附件上下文。 */
const PLATFORM_CONTEXT_MARKERS = [
  "用户本轮已上传文件附件：",
  "用户本轮已上传图片：",
  "用户本轮已从服务器挂载图片：",
  "用户本轮已挂载服务器本地文件：",
  "用户本轮已挂载服务器本地目录：",
  "用户本轮已选择知识库",
  "用户本轮已选择数据集/数据源",
  "用户本轮已调用生态技能工作流：",
  "💡 以下引用的是历史记忆，供参考：",
  "【被点击的 AI 回复】",
  "本次为知识库查询，须优先",
  "本次为数据查询与分析，须优先",
];

export const isPlatformAttachmentContext = (text: string): boolean => {
  const head = String(text || "").trim().slice(0, 400);
  if (!head) return false;
  return PLATFORM_CONTEXT_MARKERS.some((marker) => head.startsWith(marker) || head.includes(`\n${marker}`));
};

interface AttachmentSkillMeta {
  name?: string;
  description?: string;
}

interface AttachmentMemoryMeta {
  last_active?: number;
  summary?: string;
}

export interface ChatAttachment {
  type?: string;
  url: string;
  filename: string;
  skillMeta?: AttachmentSkillMeta;
  memoryMeta?: AttachmentMemoryMeta[];
}

interface ChatAttachmentOptions {
  buildKnowledgeBaseAttachmentHint: (datasetIdLine: string) => string;
  buildDatasetAttachmentHint?: (datasetIdLine: string) => string;
}

const splitAtDivider = (raw: string, divider: string) => {
  const idx = raw.indexOf(divider);
  if (idx === -1) return null;
  return {
    hasContext: true,
    userPart: raw.slice(0, idx).trim(),
    contextPart: raw.slice(idx + divider.length).trim(),
  };
};

export const splitUserMessageContent = (text: string) => {
  const raw = text || "";
  const exact = splitAtDivider(raw, USER_MESSAGE_CONTEXT_DIVIDER);
  if (exact && isPlatformAttachmentContext(exact.contextPart)) {
    return exact;
  }

  // 无文字只发附件时，正文是 "\n\n---\n\n用户本轮已..."，落库/回显 trim 后变成 "---\n\n..."
  const trimmed = raw.trim();
  const trimmedSplit = splitAtDivider(trimmed, TRIMMED_CONTEXT_DIVIDER);
  if (trimmedSplit && isPlatformAttachmentContext(trimmedSplit.contextPart)) {
    return trimmedSplit;
  }
  if (!trimmedSplit?.userPart && PLATFORM_CONTEXT_MARKERS.some((marker) => trimmed.startsWith(marker))) {
    return { hasContext: true, userPart: "", contextPart: trimmed };
  }
  return { hasContext: false, userPart: raw, contextPart: "" };
};

export const visibleUserBubbleText = (content: string | undefined | null): string =>
  splitUserMessageContent(visibleUserMessageContent(content)).userPart;

export const useChatAttachments = ({
  buildKnowledgeBaseAttachmentHint,
  buildDatasetAttachmentHint,
}: ChatAttachmentOptions) => {
  const buildImageAttachmentHint = (file: ChatAttachment, path: string) => {
    if (file.type === "local_file") {
      return `用户本轮已从服务器挂载图片：${file.filename}，该图片已作为视觉多模态输入随消息一并发送（源路径：${path}）。`;
    }
    return `用户本轮已上传图片：${file.filename}，该图片已作为视觉多模态输入随消息一并发送（托管路径：${path}）。`;
  };

  const buildSkillAttachmentHint = (file: ChatAttachment) => {
    const skillName = file.filename.replace(" (技能)", "");
    const skillId = String(file.url || "").trim();
    const meta = file.skillMeta;
    const metaParts: string[] = [];
    if (meta?.name) metaParts.push(`name: ${meta.name}`);
    if (meta?.description) metaParts.push(`description: ${meta.description}`);
    const metaText = metaParts.length > 0 ? metaParts.join(", ") : "";
    let hint = `用户本轮已调用生态技能工作流：${skillName}，skill_id=\`${skillId}\`。\n请用 read_skill_instruction(skill_id="${skillId}") 读取 SKILL.md；同目录附属文件再传 file 相对路径，禁止用 Read 拼会话 skills/ 路径。`;
    if (metaText) {
      hint += `\nskills meta 为：${metaText}`;
    }
    return hint;
  };

  const appendAttachmentContext = (content: string, files: ChatAttachment[]) => {
    if (files.length === 0) return content;

    const contextLines = files.map((file) => {
      if (file.type === "knowledge_base") {
        const datasetLine = `用户本轮已选择知识库，dataset_id：${file.url}。你必须在本轮回复前调用 search_knowledge_base 工具检索后再作答，不得跳过。dataset_ids 请传纯 ID 或单引号列表，例如 ['${file.url}']；禁止使用双引号 JSON 如 ["${file.url}"]。`;
        return buildKnowledgeBaseAttachmentHint(datasetLine);
      }
      if (file.type === "metadata_dataset") {
        const datasetLine = `用户本轮已选择数据集/数据源，dataset_id：${file.url}。本次提问为数据查询与分析，须优先由具数据查询能力的专家处理，且查询只能在已选数据集限定范围内进行。`;
        return buildDatasetAttachmentHint ? buildDatasetAttachmentHint(datasetLine) : datasetLine;
      }
      if (file.type === "memory") {
        const meta = file.memoryMeta || [];
        const memoryContextLines = meta.map((memory, index) => {
          const dateStr = memory.last_active
            ? new Date(memory.last_active * 1000).toLocaleDateString("zh-CN")
            : "";
          const dateInfo = dateStr ? `【${dateStr}】` : "";
          return `${index + 1}. ${dateInfo}${memory.summary}`;
        });
        return `💡 以下引用的是历史记忆，供参考：\n\n${memoryContextLines.join("\n\n")}`;
      }
      if (file.type === "skill") {
        return buildSkillAttachmentHint(file);
      }
      const path = getServerAttachmentPath(file);
      if (isImageAttachment(file)) {
        return buildImageAttachmentHint(file, path);
      }
      if (file.type === "local_file") {
        return `用户本轮已挂载服务器本地文件：${file.filename}，其真实的绝对路径是：${path}。你可以直接通过系统级执行工具访问或读取此绝对路径的资料以解答用户的问题。`;
      }
      if (file.type === "local_dir") {
        return `用户本轮已挂载服务器本地目录：${file.filename}，其真实的绝对路径是：${path}。你可以直接通过系统级执行工具访问、遍历或检索此绝对路径目录下的资料以解答用户的问题。`;
      }
      return `用户本轮已上传文件附件：${file.filename}，其安全托管后的服务器绝对路径是：${path}。调用 excel_document_read / word_document_read / Read 时，path 必须原样使用该绝对路径；卡片上的文件名只是显示名，托管文件名可能带 _xxxx 后缀，禁止只传显示文件名。`;
    });

    const contextBlock = contextLines.filter(Boolean).join("\n\n");
    const userPart = (content || "").trim();
    if (!contextBlock) return userPart;
    // 无正文时仍带分隔符，模型能区分系统附件说明；展示层按分隔符丢掉后半段。
    if (!userPart) return `${USER_MESSAGE_CONTEXT_DIVIDER}${contextBlock}`;
    return `${userPart}${USER_MESSAGE_CONTEXT_DIVIDER}${contextBlock}`;
  };

  return {
    appendAttachmentContext,
    buildImageAttachmentHint,
    buildSkillAttachmentHint,
  };
};

/** 将 HITL 回执协议转成用户气泡可读摘要；发给模型的原文仍是协议文本。 */

import { BUSINESS_CONFIRMATION_MESSAGE_PREFIX } from "./businessConfirmation";
import { USER_QUESTION_MESSAGE_PREFIX } from "./userQuestion";

export type HitlReceiptKind = "user_question" | "business_confirmation";

export interface HitlReceiptDisplay {
  kind: HitlReceiptKind;
  summary: string;
}

function protocolLine(content: string, key: string): string {
  const prefix = `${key}:`;
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.startsWith(prefix)) {
      return trimmed.slice(prefix.length).trim();
    }
  }
  return "";
}

function formatUserQuestionSummary(content: string): string {
  if (/^cancelled:\s*true\b/im.test(content) || content.includes("用户取消了本次提问")) {
    return "已取消本次选择";
  }
  const selected = protocolLine(content, "所选选项");
  if (selected) {
    const labels = selected
      .split("、")
      .map((item) => item.replace(/\s*\([^)]*\)\s*$/, "").trim())
      .filter(Boolean);
    if (labels.length) return `已选择：${labels.join("、")}`;
  }
  const extra = protocolLine(content, "补充说明");
  if (extra) return `已补充：${extra}`;
  return "已提交选择";
}

function formatBusinessConfirmationSummary(content: string): string {
  if (content.includes("用户已取消")) return "已取消业务确认";
  return "已确认业务数据";
}

export function formatHitlReceiptDisplay(content: string | undefined | null): HitlReceiptDisplay | null {
  const text = String(content || "");
  if (text.includes(USER_QUESTION_MESSAGE_PREFIX)) {
    return { kind: "user_question", summary: formatUserQuestionSummary(text) };
  }
  if (text.includes(BUSINESS_CONFIRMATION_MESSAGE_PREFIX)) {
    return { kind: "business_confirmation", summary: formatBusinessConfirmationSummary(text) };
  }
  return null;
}

export function visibleUserMessageContent(content: string | undefined | null): string {
  return formatHitlReceiptDisplay(content)?.summary || String(content || "");
}

/** Restore pending HITL cards from persisted process_timeline after refresh. */

import type {
  GroundingBlockedAction,
  GroundingBlockedPayload,
  PendingExternalExecution,
  PendingToolPermission,
} from "./agentscopeSseHandlers";
import {
  BUSINESS_CONFIRMATION_MESSAGE_PREFIX,
  parseBusinessConfirmationEvent,
  type BusinessConfirmationState,
} from "./businessConfirmation";
import { USER_QUESTION_MESSAGE_PREFIX, parseUserQuestionEvent, type UserQuestionState } from "./userQuestion";
import { completeOpenTodos, type ProcessTimelineItem } from "./processTimeline";

export type HistoryHitlMessage = {
  role?: string;
  content?: string;
  status?: string;
  processTimeline?: ProcessTimelineItem[];
  businessConfirmation?: BusinessConfirmationState;
  userQuestion?: UserQuestionState;
  pendingPermission?: PendingToolPermission;
  pendingExternalExecution?: PendingExternalExecution;
  groundingBlocked?: GroundingBlockedPayload;
};

type StoredHitlItem = {
  kind?: string;
  id?: string;
  card_type?: string;
  status?: string;
  payload?: Record<string, unknown>;
};

function isUserRole(role?: string): boolean {
  const value = String(role || "").toLowerCase();
  return value === "user" || value === "human";
}

function isAssistantRole(role?: string): boolean {
  const value = String(role || "").toLowerCase();
  return value === "assistant" || value === "agent";
}

function continuationAssistantAfterReceipt<T extends HistoryHitlMessage>(
  messages: T[],
  receipt: T,
): T | undefined {
  const afterReceipt = messages.slice(messages.indexOf(receipt) + 1);
  const nextUserIndex = afterReceipt.findIndex((item) => isUserRole(item.role));
  const sameTurn = nextUserIndex >= 0
    ? afterReceipt.slice(0, nextUserIndex)
    : afterReceipt;
  return sameTurn.find((item) => isAssistantRole(item.role));
}

function protocolValue(content: string, key: string): string {
  const prefix = `${key}:`;
  for (const line of String(content || "").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.startsWith(prefix)) {
      return trimmed.slice(prefix.length).trim();
    }
  }
  return "";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function extractHitlItems(storedTimeline: unknown): StoredHitlItem[] {
  if (!Array.isArray(storedTimeline)) return [];
  return storedTimeline.filter((item): item is StoredHitlItem => {
    return Boolean(item && typeof item === "object" && (item as StoredHitlItem).kind === "hitl");
  });
}

function mapPermissionStatus(status: string): PendingToolPermission["status"] {
  if (status === "rejected") return "rejected";
  if (status === "approved" || status === "success") return "approved";
  if (status === "error") return "error";
  if (status === "expired") return "expired";
  return "pending";
}

function mapExternalStatus(status: string): PendingExternalExecution["status"] {
  if (status === "error") return "error";
  if (status === "completed" || status === "success") return "completed";
  return "pending";
}

function applyHitlItem(message: HistoryHitlMessage, item: StoredHitlItem): void {
  const payload = asRecord(item.payload);
  const cardType = String(item.card_type || payload.type || "");
  const status = String(item.status || payload.status || "pending");

  if (cardType === "business_confirmation") {
    const parsed = parseBusinessConfirmationEvent({
      type: "business_confirmation",
      ...payload,
    });
    if (!parsed) return;
    if (status === "submitted" || status === "stale") parsed.status = status;
    if (payload.decision === "confirmed" || payload.decision === "cancelled") {
      parsed.decision = payload.decision;
    }
    message.businessConfirmation = parsed;
    return;
  }

  if (cardType === "user_question") {
    const parsed = parseUserQuestionEvent({
      type: "user_question",
      ...payload,
    });
    if (!parsed) return;
    if (status === "submitted" || status === "cancelled" || status === "stale") {
      parsed.status = status;
    }
    message.userQuestion = parsed;
    return;
  }

  if (cardType === "permission_required") {
    const requestId = String(payload.permission_request_id || "").trim();
    if (!requestId) return;
    const mapped = mapPermissionStatus(status);
    message.pendingPermission = {
      permission_request_id: requestId,
      reply_id: payload.reply_id ? String(payload.reply_id) : undefined,
      id: payload.id ? String(payload.id) : undefined,
      title: String(payload.title || "工具调用确认"),
      details: String(payload.details || ""),
      tool_call: payload.tool_call as PendingToolPermission["tool_call"],
      status: mapped,
      expanded: mapped === "pending",
    };
    return;
  }

  if (cardType === "external_execution_required") {
    const requestId = String(
      payload.external_execution_request_id || payload.permission_request_id || "",
    ).trim();
    if (!requestId) return;
    const mapped = mapExternalStatus(status);
    message.pendingExternalExecution = {
      external_execution_request_id: requestId,
      reply_id: payload.reply_id ? String(payload.reply_id) : undefined,
      id: payload.id ? String(payload.id) : undefined,
      title: String(payload.title || "外部工具执行"),
      details: String(payload.details || ""),
      tool_call: payload.tool_call as PendingExternalExecution["tool_call"],
      status: mapped,
      outputDraft: "",
      expanded: mapped === "pending",
    };
    return;
  }

  if (cardType === "grounding_blocked") {
    message.groundingBlocked = {
      title: String(payload.title || "暂时无法验证事实"),
      message: String(payload.message || "本次回答缺少可验证的事实来源。"),
      details: payload.details ? String(payload.details) : undefined,
      required_evidence_types: Array.isArray(payload.required_evidence_types)
        ? payload.required_evidence_types.map(String)
        : [],
      retry_query: String(payload.retry_query || ""),
      actions: Array.isArray(payload.actions)
        ? (payload.actions as GroundingBlockedAction[])
        : [],
      fallback_content: payload.fallback_content
        ? String(payload.fallback_content)
        : undefined,
    };
  }
}

export function attachHitlCardsFromTimeline<T extends HistoryHitlMessage>(
  message: T,
  storedTimeline: unknown,
): T {
  for (const item of extractHitlItems(storedTimeline)) {
    applyHitlItem(message, item);
  }
  return message;
}

export function resolveHitlCardsInHistory<T extends HistoryHitlMessage>(messages: T[]): T[] {
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (!message || !isAssistantRole(message.role)) continue;
    if (message.status === "success") completeOpenTodos(message);
    const later = messages.slice(index + 1);
    const conversationMovedOn = later.some((item) => isUserRole(item.role) || isAssistantRole(item.role));

    const confirmation = message.businessConfirmation;
    if (confirmation?.status === "pending") {
      const receipt = later.find((item) => {
        if (!isUserRole(item.role)) return false;
        const content = String(item.content || "");
        if (!content.includes(BUSINESS_CONFIRMATION_MESSAGE_PREFIX)) return false;
        return protocolValue(content, "confirmation_id") === confirmation.confirmation_id;
      });
      if (receipt) {
        const cancelled = String(receipt.content || "").includes("用户已取消");
        confirmation.status = "submitted";
        confirmation.decision = cancelled ? "cancelled" : "confirmed";
        const continuation = continuationAssistantAfterReceipt(later, receipt);
        if (!cancelled && continuation?.status === "success") {
          completeOpenTodos(message);
        }
      } else if (conversationMovedOn) {
        confirmation.status = "stale";
      }
    }

    const question = message.userQuestion;
    if (question?.status === "pending") {
      const receipt = later.find((item) => {
        if (!isUserRole(item.role)) return false;
        const content = String(item.content || "");
        if (!content.includes(USER_QUESTION_MESSAGE_PREFIX)) return false;
        return protocolValue(content, "question_id") === question.question_id;
      });
      if (receipt) {
        const cancelled = /cancelled:\s*true/i.test(String(receipt.content || ""));
        question.status = cancelled ? "cancelled" : "submitted";
        const continuation = continuationAssistantAfterReceipt(later, receipt);
        if (!cancelled && continuation?.status === "success") {
          completeOpenTodos(message);
        }
      } else if (conversationMovedOn) {
        question.status = "stale";
      }
    }

    const permission = message.pendingPermission;
    if (permission?.status === "pending" && conversationMovedOn) {
      permission.status = "expired";
      permission.expanded = false;
    }

    const external = message.pendingExternalExecution;
    if (external?.status === "pending" && conversationMovedOn) {
      external.status = "error";
      external.expanded = false;
    }
  }
  return messages;
}

export function historyHasActionableResumeCard(messages: HistoryHitlMessage[]): boolean {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || !isAssistantRole(message.role)) continue;
    return (
      message.pendingPermission?.status === "pending"
      || message.pendingExternalExecution?.status === "pending"
    );
  }
  return false;
}

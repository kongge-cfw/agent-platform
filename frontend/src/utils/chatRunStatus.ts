import type {
  PendingExternalExecution,
  PendingToolPermission,
} from "./agentscopeSseHandlers";
import {
  resolveHitlCardsInHistory,
  type HistoryHitlMessage,
} from "./hitlHistory";
import { cancelOpenTodos, completeOpenTodos } from "./processTimeline";

export type RunStatusEvent = {
  type?: string;
  status?: string;
};

export type RunStatusMessage = HistoryHitlMessage & {
  isThinking?: boolean;
  pendingPermission?: PendingToolPermission;
  pendingExternalExecution?: PendingExternalExecution;
};

/** 归并普通对话流中的 run_status 终态。 */
export function applyRunStatusEvent<T extends RunStatusMessage>(
  message: T,
  event: RunStatusEvent,
  history: T[],
): boolean {
  if (event?.type !== "run_status") return false;

  message.isThinking = false;
  if (event.status === "success") {
    message.status = "success";
    completeOpenTodos(message);
    resolveHitlCardsInHistory(history);
  } else if (event.status === "cancelled") {
    message.status = "cancelled";
    cancelOpenTodos(message);
  }
  return true;
}

/** 归并权限确认与外部执行恢复流中的终态卡片状态。 */
export function applyResumeRunStatusEvent<T extends RunStatusMessage>(
  message: T,
  event: RunStatusEvent,
  history: T[],
): boolean {
  if (event?.type !== "run_status") return false;

  if (message.pendingPermission) {
    message.pendingPermission.status =
      event.status === "awaiting_permission"
        ? "pending"
        : event.status === "rejected" || event.status === "denied"
          ? "rejected"
          : event.status === "error" || event.status === "failed"
            ? "error"
            : "approved";
    if (event.status === "awaiting_permission") {
      message.pendingPermission.expanded = true;
    }
  }
  if (message.pendingExternalExecution) {
    message.pendingExternalExecution.status =
      event.status === "error" || event.status === "failed"
        ? "error"
        : "completed";
  }

  return applyRunStatusEvent(message, event, history);
}

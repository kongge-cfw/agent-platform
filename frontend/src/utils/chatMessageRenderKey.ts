type MessageRenderKeyInput = {
  id: string | number;
  status?: string;
  pendingPermission?: {
    permission_request_id?: string;
    status?: string;
  };
  pendingExternalExecution?: {
    external_execution_request_id?: string;
    status?: string;
  };
  businessConfirmation?: {
    confirmation_id?: string;
    status?: string;
    decision?: string;
  };
  userQuestion?: {
    question_id?: string;
    status?: string;
  };
  groundingBlocked?: unknown;
};

/**
 * 保持流式正文期间 key 稳定，仅在终态或 HITL 卡片身份/状态变化时切换渲染边界。
 */
export function chatMessageRenderKey(message: MessageRenderKeyInput): string {
  return [
    message.id,
    message.status || "",
    message.pendingPermission?.permission_request_id || "",
    message.pendingPermission?.status || "",
    message.pendingExternalExecution?.external_execution_request_id || "",
    message.pendingExternalExecution?.status || "",
    message.businessConfirmation?.confirmation_id || "",
    message.businessConfirmation?.status || "",
    message.businessConfirmation?.decision || "",
    message.userQuestion?.question_id || "",
    message.userQuestion?.status || "",
    message.groundingBlocked ? "grounding-blocked" : "",
  ].join("|");
}

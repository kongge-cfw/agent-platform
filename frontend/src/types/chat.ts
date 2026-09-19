import type { ProcessTimelineItem } from "@/utils/processTimeline";

export type ChatMessageRole = "user" | "agent" | "system";

/**
 * 两个聊天入口共同依赖的消息基础结构。
 * 页面专属的调试、HITL、附件及业务载荷继续由各自 Message 扩展。
 */
export interface ChatMessageBase {
  id: number;
  trace_id?: string;
  status?: string;
  role: ChatMessageRole;
  content: string;
  reasoningContent?: string;
  isReasoningExpanded?: boolean;
  isThinking?: boolean;
  processNarration?: string;
  processNarrationPending?: string;
  processTimeline?: ProcessTimelineItem[];
  isProcessNarrationExpanded?: boolean;
  citations?: any[];
  isCitationsExpanded?: boolean;
  isThoughtExpanded?: boolean;
  thoughtStartTime?: number;
  thoughtDuration?: string;
  thinkingText?: string;
  agentName?: string;
  agentDisplayName?: string;
  agentType?: string;
  isSavedReportResult?: boolean;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  feedback?: "up" | "down" | null;
  timestamp?: string;
}

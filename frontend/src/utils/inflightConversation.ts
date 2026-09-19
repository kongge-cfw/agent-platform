/** 切走会话时按 conversationId 缓存正在生成的消息，切回直接还原，避免被 Redis 旧历史覆盖。 */

export type InflightChatMessage = {
  role: string;
  content?: string;
  isThinking?: boolean;
  isHistory?: boolean;
  isGreeting?: boolean;
  trace_id?: string;
  thinkingText?: string;
  processTimeline?: unknown;
  [key: string]: any;
};

export type InflightSnapshot<T = InflightChatMessage> = {
  messages: T[];
  isProcessing: boolean;
  abortController: AbortController | null;
  historyOffset?: number;
  hasMoreHistory?: boolean;
};

const inflightByConversation = new Map<string, InflightSnapshot>();

const normalizeConversationId = (conversationId?: string | null): string =>
  String(conversationId || "").trim();

export const lastNonSystemMessage = <T extends InflightChatMessage>(
  messages: T[] | undefined | null,
): T | undefined => {
  const list = Array.isArray(messages) ? messages : [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (list[i]?.role !== "system") return list[i];
  }
  return undefined;
};

const isAgentMessage = (message?: InflightChatMessage | null): boolean =>
  message?.role === "agent" || message?.role === "assistant";

const timelineTodoState = (
  timeline: unknown,
): { hasTodo: boolean; hasOpen: boolean } => {
  if (!Array.isArray(timeline)) return { hasTodo: false, hasOpen: false };
  let hasTodo = false;
  let hasOpen = false;
  for (const item of timeline) {
    if (!item || typeof item !== "object" || (item as any).kind !== "todo") continue;
    hasTodo = true;
    const todos = Array.isArray((item as any).todos) ? (item as any).todos : [];
    if (todos.some((todo: any) => todo?.status === "pending" || todo?.status === "in_progress")) {
      hasOpen = true;
    }
  }
  return { hasTodo, hasOpen };
};

const mergedProcessTimeline = (
  localTimeline: unknown,
  serverTimeline: unknown,
): unknown => {
  const localState = timelineTodoState(localTimeline);
  const serverState = timelineTodoState(serverTimeline);
  if (
    serverState.hasTodo
    && !serverState.hasOpen
    && (!localState.hasTodo || localState.hasOpen)
  ) {
    if (!Array.isArray(localTimeline) || localTimeline.length === 0) {
      return serverTimeline;
    }
    const serverTodo = Array.isArray(serverTimeline)
      ? [...serverTimeline].reverse().find((item) => item?.kind === "todo")
      : undefined;
    if (!serverTodo) return localTimeline;
    const firstLocalTodoIndex = localTimeline.findIndex((item) => item?.kind === "todo");
    const withoutLocalTodos = localTimeline.filter((item) => item?.kind !== "todo");
    const insertAt = firstLocalTodoIndex >= 0
      ? Math.min(firstLocalTodoIndex, withoutLocalTodos.length)
      : withoutLocalTodos.length;
    return [
      ...withoutLocalTodos.slice(0, insertAt),
      serverTodo,
      ...withoutLocalTodos.slice(insertAt),
    ];
  }
  return Array.isArray(localTimeline) && localTimeline.length
    ? localTimeline
    : serverTimeline;
};

export const messageLooksIncomplete = (message?: InflightChatMessage | null): boolean => {
  if (!message) return true;
  if (message.role === "user") return true;
  if (isAgentMessage(message)) {
    return Boolean(message.isThinking || !String(message.content || "").trim());
  }
  return false;
};

export const stashInflightConversation = <T extends InflightChatMessage>(
  conversationId: string | null | undefined,
  snapshot: InflightSnapshot<T>,
): void => {
  const cid = normalizeConversationId(conversationId);
  if (!cid) return;
  inflightByConversation.set(cid, snapshot as InflightSnapshot);
};

export const peekInflightConversation = <T extends InflightChatMessage>(
  conversationId?: string | null,
): InflightSnapshot<T> | undefined => {
  const cid = normalizeConversationId(conversationId);
  if (!cid) return undefined;
  return inflightByConversation.get(cid) as InflightSnapshot<T> | undefined;
};

export const shouldSkipHistoryReplace = (conversationId?: string | null): boolean =>
  Boolean(peekInflightConversation(conversationId));

export const patchInflightConversation = (
  conversationId: string | null | undefined,
  patch: Partial<InflightSnapshot>,
): void => {
  const snap = peekInflightConversation(conversationId);
  if (!snap) return;
  Object.assign(snap, patch);
};

export const discardInflightConversation = (conversationId?: string | null): void => {
  const cid = normalizeConversationId(conversationId);
  if (!cid) return;
  inflightByConversation.delete(cid);
};

export const hasLiveGeneratingAgent = (
  messages: InflightChatMessage[] | undefined | null,
): boolean => {
  const last = lastNonSystemMessage(messages);
  return Boolean(isAgentMessage(last) && !last?.isHistory && !last?.isGreeting);
};

export const needsGeneratingPlaceholder = (
  messages: InflightChatMessage[] | undefined | null,
  remoteRunActive: boolean,
): boolean => {
  if (!remoteRunActive) return false;
  if (hasLiveGeneratingAgent(messages)) return false;
  return true;
};

export const mergeCompletedRunIntoMessages = <T extends InflightChatMessage>(
  local: T[],
  server: T[],
): { messages: T[]; usedServer: boolean } => {
  const lastServer = lastNonSystemMessage(server);
  if (!isAgentMessage(lastServer) || !String(lastServer?.content || "").trim()) {
    return { messages: local, usedServer: false };
  }
  const lastLocal = lastNonSystemMessage(local);
  if (!lastLocal) {
    return { messages: server, usedServer: true };
  }
  if (
    isAgentMessage(lastLocal)
    && lastLocal.isHistory
    && lastServer.trace_id
    && lastLocal.trace_id
    && lastLocal.trace_id !== lastServer.trace_id
  ) {
    return { messages: server, usedServer: true };
  }
  if (lastLocal.role === "user") {
    return { messages: [...local, lastServer as T], usedServer: true };
  }
  if (!isAgentMessage(lastLocal)) {
    return { messages: local, usedServer: false };
  }
  if (!lastLocal.isHistory && lastServer.trace_id && lastLocal.trace_id && lastLocal.trace_id !== lastServer.trace_id) {
    return { messages: local, usedServer: false };
  }
  if (
    !lastLocal.isHistory
    && messageLooksIncomplete(lastLocal)
    && lastServer.trace_id
    && local.some((item) => item !== lastLocal && isAgentMessage(item) && item.trace_id === lastServer.trace_id)
  ) {
    return { messages: local, usedServer: false };
  }
  const localText = String(lastLocal.content || "");
  const serverText = String(lastServer.content || "");
  const sameTrace = Boolean(lastLocal.trace_id && lastLocal.trace_id === lastServer.trace_id);
  const localIncomplete = messageLooksIncomplete(lastLocal);
  if (!localIncomplete && localText.length >= serverText.length && (sameTrace || !lastServer.trace_id || !lastLocal.trace_id)) {
    Object.assign(lastLocal, {
      isThinking: false,
      trace_id: lastLocal.trace_id || lastServer.trace_id,
      status: lastServer.status ?? lastLocal.status,
      reasoningContent: lastLocal.reasoningContent || lastServer.reasoningContent,
      processTimeline: mergedProcessTimeline(
        lastLocal.processTimeline,
        lastServer.processTimeline,
      ),
      prompt_tokens: lastServer.prompt_tokens ?? lastLocal.prompt_tokens,
      completion_tokens: lastServer.completion_tokens ?? lastLocal.completion_tokens,
      total_tokens: lastServer.total_tokens ?? lastLocal.total_tokens,
      agentName: lastLocal.agentName || lastServer.agentName,
      agentDisplayName: lastLocal.agentDisplayName || lastServer.agentDisplayName,
    });
    return { messages: local, usedServer: true };
  }
  if (localIncomplete || serverText.length > localText.length || sameTrace) {
    const next = local.slice();
    const idx = next.lastIndexOf(lastLocal);
    if (idx >= 0) {
      const localLogs = Array.isArray(lastLocal.logs) ? lastLocal.logs : [];
      const localCitations = Array.isArray(lastLocal.citations) ? lastLocal.citations : [];
      const localTimeline = Array.isArray(lastLocal.processTimeline) ? lastLocal.processTimeline : [];
      next[idx] = {
        ...lastLocal,
        ...lastServer,
        id: lastLocal.id,
        isHistory: lastLocal.isHistory,
        isThinking: false,
        content: serverText.length > localText.length ? lastServer.content : lastLocal.content,
        logs: localLogs.length > 0 ? localLogs : lastServer.logs,
        citations: localCitations.length > 0 ? localCitations : lastServer.citations,
        processTimeline: mergedProcessTimeline(
          localTimeline,
          lastServer.processTimeline,
        ),
      };
    }
    return { messages: next, usedServer: true };
  }
  return { messages: local, usedServer: false };
};

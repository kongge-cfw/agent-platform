import axios from "@/utils/axios";
import type { ReasoningEffort } from "@/api/model";

export const CHAT_RUNTIME_PREFS_PATH = "/api/portal/chat-runtime-prefs";

export type ChatRuntimePrefPayload = {
  override_model?: string | null;
  thinking_enable?: boolean | null;
  reasoning_effort?: ReasoningEffort | string | null;
  temperature?: number | null;
  persistable?: boolean;
  embed_app_key?: string;
};

function asPayload(data: unknown): ChatRuntimePrefPayload {
  if (!data || typeof data !== "object") {
    return { persistable: false };
  }
  return data as ChatRuntimePrefPayload;
}

export async function fetchChatRuntimePrefs(): Promise<ChatRuntimePrefPayload> {
  const res = await axios.get(CHAT_RUNTIME_PREFS_PATH);
  return asPayload(res.data?.data);
}

export async function saveChatRuntimePrefs(payload: {
  override_model?: string | null;
  thinking_enable?: boolean | null;
  reasoning_effort?: ReasoningEffort | string | null;
  temperature?: number | null;
}): Promise<ChatRuntimePrefPayload> {
  const body: Record<string, unknown> = {};
  if ("override_model" in payload) body.override_model = payload.override_model ?? null;
  if ("thinking_enable" in payload) body.thinking_enable = payload.thinking_enable ?? null;
  if ("reasoning_effort" in payload) body.reasoning_effort = payload.reasoning_effort ?? null;
  if ("temperature" in payload) body.temperature = payload.temperature ?? null;
  const res = await axios.put(CHAT_RUNTIME_PREFS_PATH, body);
  return asPayload(res.data?.data);
}

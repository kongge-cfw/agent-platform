/** Helpers for registered business UI cards in chat. */

export const UI_CARD_MESSAGE_PREFIX = "【UI卡片】";
export const UI_CARD_HOST_SOURCE = "nanzi-host";
export const UI_CARD_FRAME_SOURCE = "nanzi-card";

export interface UiCardRender {
  type?: string;
  url: string;
  origin?: string;
  height?: number;
  card_token?: string;
  token_ttl_seconds?: number;
}

export interface UiCardState {
  card_id: string;
  card_key: string;
  tool_call_id?: string;
  title: string;
  actions: string[];
  data: Record<string, unknown>;
  render: UiCardRender;
  status: "pending" | "submitted" | "stale" | "expired";
  action?: string;
  payload?: Record<string, unknown>;
  error?: string;
}

function asStringList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return [...new Set(raw.map((item) => String(item || "").trim()).filter(Boolean))];
}

function asRecord(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? { ...(raw as Record<string, unknown>) }
    : {};
}

export function parseUiCardEvent(data: Record<string, unknown>): UiCardState | null {
  if (String(data.type || "") !== "ui_card") return null;
  const cardId = String(data.card_id || "").trim();
  const cardKey = String(data.card_key || "").trim();
  const renderRaw = asRecord(data.render);
  const url = String(renderRaw.url || "").trim();
  const actions = asStringList(data.actions);
  if (!cardId || !cardKey || !url || actions.length === 0) return null;
  const height = Number(renderRaw.height);
  return {
    card_id: cardId,
    card_key: cardKey,
    tool_call_id: data.tool_call_id ? String(data.tool_call_id) : undefined,
    title: String(data.title || "请确认业务信息"),
    actions,
    data: asRecord(data.data),
    render: {
      type: String(renderRaw.type || "iframe"),
      url,
      origin: renderRaw.origin ? String(renderRaw.origin) : undefined,
      height: Number.isFinite(height) ? height : 480,
      card_token: renderRaw.card_token ? String(renderRaw.card_token) : undefined,
      token_ttl_seconds: Number(renderRaw.token_ttl_seconds) || undefined,
    },
    status: "pending",
  };
}

export function resolveUiCardOrigin(render: UiCardRender): string {
  const explicit = String(render.origin || "").trim().replace(/\/$/, "");
  if (explicit) return explicit;
  const url = String(render.url || "").trim();
  if (!url || url.startsWith("/")) return window.location.origin;
  try {
    return new URL(url, window.location.origin).origin;
  } catch {
    return window.location.origin;
  }
}

export function clampUiCardHeight(height: number | undefined, fallback = 480): number {
  const value = Number.isFinite(Number(height)) ? Number(height) : fallback;
  return Math.min(1200, Math.max(240, value));
}

export function buildUiCardUserMessage(
  cardId: string,
  cardKey: string,
  action: string,
  payload: Record<string, unknown> = {},
): string {
  return [
    UI_CARD_MESSAGE_PREFIX,
    "interaction_type: ui_card",
    `card_id: ${cardId.trim() || "unknown"}`,
    `card_key: ${cardKey.trim() || "unknown"}`,
    `action: ${action.trim() || "unknown"}`,
    `payload: ${JSON.stringify(payload || {})}`,
  ].join("\n");
}

export function markOtherUiCardsStale<T extends { uiCard?: UiCardState }>(
  messages: T[],
  activeCardId: string,
): void {
  for (const message of messages) {
    const card = message.uiCard;
    if (!card || card.status !== "pending") continue;
    if (card.card_id === activeCardId) continue;
    card.status = "stale";
  }
}

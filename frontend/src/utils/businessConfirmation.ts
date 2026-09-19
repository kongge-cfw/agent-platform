/** Business data confirmation card helpers (not tool-execution HITL). */

export type BusinessConfirmationValueType =
  | "string"
  | "number"
  | "boolean"
  | "text"
  | "date"
  | "datetime";

export interface BusinessConfirmationField {
  key: string;
  label: string;
  value: unknown;
  editable?: boolean;
  value_type?: BusinessConfirmationValueType;
}

const DATE_ONLY_RE = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/;
const CN_DATE_RE = /^(\d{4})年(\d{1,2})月(\d{1,2})日$/;
const DATETIME_RE =
  /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/;

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function parseConfirmationDateParts(value: unknown): {
  y: number;
  m: number;
  d: number;
  hh?: number;
  mm?: number;
} | null {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const datetime = text.match(DATETIME_RE);
  if (datetime) {
    return {
      y: Number(datetime[1]),
      m: Number(datetime[2]),
      d: Number(datetime[3]),
      hh: Number(datetime[4]),
      mm: Number(datetime[5]),
    };
  }
  const iso = text.match(DATE_ONLY_RE);
  if (iso) {
    return { y: Number(iso[1]), m: Number(iso[2]), d: Number(iso[3]) };
  }
  const cn = text.match(CN_DATE_RE);
  if (cn) {
    return { y: Number(cn[1]), m: Number(cn[2]), d: Number(cn[3]) };
  }
  return null;
}

export function confirmationDateInputValue(value: unknown): string {
  const parsed = parseConfirmationDateParts(value);
  if (!parsed) return "";
  return `${parsed.y}-${pad2(parsed.m)}-${pad2(parsed.d)}`;
}

export function confirmationDateTimeInputValue(value: unknown): string {
  const parsed = parseConfirmationDateParts(value);
  if (!parsed) return "";
  return `${parsed.y}-${pad2(parsed.m)}-${pad2(parsed.d)}T${pad2(parsed.hh ?? 0)}:${pad2(parsed.mm ?? 0)}`;
}

export function confirmationDateTimeDisplayValue(value: unknown): string {
  const input = confirmationDateTimeInputValue(value);
  return input ? input.replace("T", " ") : "";
}

export function confirmationDateFromValue(value: unknown): Date | null {
  const parsed = parseConfirmationDateParts(value);
  if (!parsed) return null;
  return new Date(parsed.y, parsed.m - 1, parsed.d, parsed.hh ?? 0, parsed.mm ?? 0);
}

export function inferConfirmationValueType(
  field: Pick<BusinessConfirmationField, "value" | "value_type">,
): BusinessConfirmationValueType {
  const declared = field.value_type;
  if (
    declared === "boolean" ||
    declared === "number" ||
    declared === "text" ||
    declared === "date" ||
    declared === "datetime"
  ) {
    return declared;
  }
  const text = field.value === null || field.value === undefined ? "" : String(field.value).trim();
  if (DATETIME_RE.test(text)) return "datetime";
  if (DATE_ONLY_RE.test(text) || CN_DATE_RE.test(text)) return "date";
  return "string";
}

export interface BusinessConfirmationState {
  confirmation_id: string;
  tool_call_id?: string;
  title: string;
  summary?: string;
  fields: BusinessConfirmationField[];
  confirm_label: string;
  cancel_label: string;
  risk_note?: string;
  status: "pending" | "submitted" | "stale";
  decision?: "confirmed" | "cancelled";
}

export const BUSINESS_CONFIRMATION_MESSAGE_PREFIX = "【业务确认】";
export const BUSINESS_CONFIRMATION_CANCEL_MARKER = `${BUSINESS_CONFIRMATION_MESSAGE_PREFIX}用户已取消`;

export function isBusinessConfirmationCancelMessage(content: string | undefined | null): boolean {
  return String(content || "").includes(BUSINESS_CONFIRMATION_CANCEL_MARKER);
}

export function shouldSuppressBusinessConfirmation(
  messages?: Array<{ role?: string; content?: string }>,
): boolean {
  if (!messages?.length) return false;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    const role = String(msg?.role || "").toLowerCase();
    if (role !== "user" && role !== "human") continue;
    return isBusinessConfirmationCancelMessage(msg?.content);
  }
  return false;
}

function asFields(raw: unknown): BusinessConfirmationField[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    .map((item) => {
      const field: BusinessConfirmationField = {
        key: String(item.key || "").trim(),
        label: String(item.label || item.key || "字段").trim(),
        value: item.value ?? "",
        editable: item.editable !== false,
        value_type: (item.value_type as BusinessConfirmationValueType) || "string",
      };
      field.value_type = inferConfirmationValueType(field);
      return field;
    })
    .filter((item) => item.key || item.label);
}

export function parseBusinessConfirmationEvent(
  data: Record<string, unknown>,
): BusinessConfirmationState | null {
  if (String(data.type || "") !== "business_confirmation") return null;
  const confirmationId = String(data.confirmation_id || "").trim();
  const fields = asFields(data.fields);
  if (!confirmationId || fields.length === 0) return null;
  return {
    confirmation_id: confirmationId,
    tool_call_id: data.tool_call_id ? String(data.tool_call_id) : undefined,
    title: String(data.title || "请确认以下信息"),
    summary: String(data.summary || ""),
    fields,
    confirm_label: String(data.confirm_label || "确定"),
    cancel_label: String(data.cancel_label || "取消"),
    risk_note: String(data.risk_note || ""),
    status: "pending",
  };
}

export function formatBusinessConfirmationSnapshot(
  fields: BusinessConfirmationField[],
): string {
  return fields
    .map((field) => {
      const label = field.label || field.key || "字段";
      const value =
        field.value === null || field.value === undefined ? "" : String(field.value);
      if (field.key) return `- ${label} (${field.key}): ${value}`;
      return `- ${label}: ${value}`;
    })
    .join("\n");
}

export function buildBusinessConfirmationUserMessage(
  confirmed: boolean,
  confirmationId: string,
  fields: BusinessConfirmationField[],
): string {
  const snapshot = formatBusinessConfirmationSnapshot(fields);
  const cid = confirmationId.trim() || "unknown";
  if (confirmed) {
    return [
      `${BUSINESS_CONFIRMATION_MESSAGE_PREFIX}用户已确定`,
      `confirmation_id: ${cid}`,
      "请根据以下已确认字段继续执行（如需写入请调用相应工具）：",
      snapshot,
    ].join("\n");
  }
  return [
    `${BUSINESS_CONFIRMATION_MESSAGE_PREFIX}用户已取消`,
    `confirmation_id: ${cid}`,
    "请立即终止本次录入/变更：不要调用写入类工具；禁止再次调用 request_user_confirmation（不要重新弹确认卡）。只用文字确认已取消，并询问用户是否修改后重试或放弃。仅当用户随后明确提供新的/修改后的数据并要求继续时，才可再次请求确认。",
    "当时字段快照：",
    snapshot,
  ].join("\n");
}

export function markOtherBusinessConfirmationsStale<
  T extends { businessConfirmation?: BusinessConfirmationState },
>(messages: T[], activeConfirmationId: string): void {
  for (const msg of messages) {
    const card = msg.businessConfirmation;
    if (!card || card.status !== "pending") continue;
    if (card.confirmation_id === activeConfirmationId) continue;
    card.status = "stale";
  }
}

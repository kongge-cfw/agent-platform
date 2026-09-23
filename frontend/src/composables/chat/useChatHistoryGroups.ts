export interface ChatHistoryItem {
  conversation_id?: string | null;
  query?: string | null;
  created_at?: string | null;
  [key: string]: unknown;
}

const HISTORY_RECEIPT_PREFIXES = ["【业务确认】", "【用户回答】"];

export const historyCardTitle = (text: unknown): string => {
  const raw = String(text ?? "").trim();
  if (!raw || HISTORY_RECEIPT_PREFIXES.some((prefix) => raw.startsWith(prefix))) return "";
  const head = raw.includes("---") ? (raw.split("---", 1)[0] || "").trim() : raw;
  return head;
};

export const upsertPendingHistoryCard = <T extends ChatHistoryItem>(list: T[], card: T): T[] => {
  const cid = String(card.conversation_id || "");
  const title = historyCardTitle(card.query);
  if (!cid || !title) return list;
  const index = list.findIndex((item) => item.conversation_id === cid);
  if (index === -1) return [{ ...card, query: title }, ...list];
  if (historyCardTitle(list[index]?.query)) return list;
  const next = list.slice();
  next[index] = { ...list[index], query: title };
  return next;
};

export const mergePendingHistoryCards = <T extends ChatHistoryItem>(
  serverItems: T[],
  pending: Record<string, T>,
): { items: T[]; pending: Record<string, T> } => {
  const nextPending = { ...pending };
  const items = serverItems.map((item) => {
    const cid = String(item.conversation_id || "");
    const pin = cid ? nextPending[cid] : undefined;
    if (!pin) return item;
    if (historyCardTitle(item.query)) {
      delete nextPending[cid];
      return item;
    }
    return { ...item, query: historyCardTitle(pin.query) || item.query };
  });
  Object.entries(nextPending).forEach(([cid, card]) => {
    if (!items.some((item) => item.conversation_id === cid)) {
      items.unshift(card);
    }
  });
  return { items, pending: nextPending };
};

export interface ChatHistoryDateGroup<T extends ChatHistoryItem> {
  id: string;
  title: string;
  items: T[];
  order: number;
}

export const groupChatHistoryByDate = <T extends ChatHistoryItem>(
  history: T[],
  now = new Date(),
): ChatHistoryDateGroup<T>[] => {
  if (!history.length) return [];

  const groupsMap = {
    today: { title: "今天", items: [] as T[], order: 1 },
    yesterday: { title: "昨天", items: [] as T[], order: 2 },
    threeDays: { title: "3天前", items: [] as T[], order: 3 },
    sevenDays: { title: "7天前", items: [] as T[], order: 4 },
    older: { title: "更早", items: [] as T[], order: 5 },
  };

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const oneDayMs = 24 * 60 * 60 * 1000;

  history.forEach((item) => {
    if (!item.created_at) {
      groupsMap.older.items.push(item);
      return;
    }
    const itemTime = new Date(item.created_at).getTime();
    const diffMs = startOfToday - itemTime;

    if (itemTime >= startOfToday) {
      groupsMap.today.items.push(item);
    } else if (diffMs < oneDayMs) {
      groupsMap.yesterday.items.push(item);
    } else if (diffMs < 3 * oneDayMs) {
      groupsMap.threeDays.items.push(item);
    } else if (diffMs < 7 * oneDayMs) {
      groupsMap.sevenDays.items.push(item);
    } else {
      groupsMap.older.items.push(item);
    }
  });

  return Object.entries(groupsMap)
    .map(([id, group]) => ({ id, ...group }))
    .filter((group) => group.items.length > 0)
    .sort((left, right) => left.order - right.order);
};

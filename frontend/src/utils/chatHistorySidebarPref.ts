const SIDEBAR_OPEN_KEY = "chat_history_sidebar_open";
const COLLAPSED_GROUPS_KEY = "chat_history_collapsed_groups";

export function readHistorySidebarOpen(): boolean {
  try {
    const saved = localStorage.getItem(SIDEBAR_OPEN_KEY);
    if (saved === "0") return false;
    if (saved === "1") return true;
  } catch {
    // 无痕模式或存储不可用时沿用默认展开。
  }
  return true;
}

export function writeHistorySidebarOpen(open: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_OPEN_KEY, open ? "1" : "0");
  } catch {
    // 写入失败时只影响下次刷新，不打断当前操作。
  }
}

export function readHistoryCollapsedGroups(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(COLLAPSED_GROUPS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const next: Record<string, boolean> = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (value === true && key) next[key] = true;
    }
    return next;
  } catch {
    return {};
  }
}

export function writeHistoryCollapsedGroups(groups: Record<string, boolean>): void {
  try {
    localStorage.setItem(COLLAPSED_GROUPS_KEY, JSON.stringify(groups));
  } catch {
    // 写入失败时只影响下次刷新，不打断当前操作。
  }
}

/** 平台主助手；嵌入应用可另指定替代宿主。站内空宿主仍认平台 Main，嵌入空宿主不委派。 */

export const PLATFORM_MAIN_AGENT_ID = "sys-agent-chat";
export const PLATFORM_MAIN_AGENT_NAMES = new Set(["main", "assistant", "general-chat"]);

export type DelegationHostMode = {
  /** 嵌入会话：空宿主=不能智能委派，不回落平台 Main。站内/调试省略此标志。 */
  strict?: boolean;
};

export function isPlatformMainAgent(agent: any): boolean {
  if (!agent) return false;
  if (typeof agent === "string") {
    const key = agent.trim();
    return key === PLATFORM_MAIN_AGENT_ID || PLATFORM_MAIN_AGENT_NAMES.has(key.toLowerCase());
  }
  const id = String(agent.id || "").trim();
  const name = String(agent.name || "").trim().toLowerCase();
  return id === PLATFORM_MAIN_AGENT_ID || PLATFORM_MAIN_AGENT_NAMES.has(name);
}

export function agentMatchesKey(agent: any, key: string): boolean {
  const wanted = String(key || "").trim();
  if (!wanted || !agent) return false;
  if (typeof agent === "string") return agent.trim() === wanted;
  return String(agent.id || "").trim() === wanted || String(agent.name || "").trim() === wanted;
}

/** 指定了宿主则只认它；站内未指定认平台主助手；嵌入 strict 且未指定则无人是宿主。 */
export function isDelegationHostAgent(
  agent: any,
  hostKey?: string | null,
  mode?: DelegationHostMode,
): boolean {
  const key = String(hostKey || "").trim();
  if (key) return agentMatchesKey(agent, key);
  if (mode?.strict) return false;
  return isPlatformMainAgent(agent);
}

export function catalogHasDelegationHost(
  agents: any[] | null | undefined,
  hostKey?: string | null,
  mode?: DelegationHostMode,
): boolean {
  const list = Array.isArray(agents) ? agents : [];
  return list.some((agent) => isDelegationHostAgent(agent, hostKey, mode));
}

export function resolveDelegationHostAgent(
  agents: any[] | null | undefined,
  hostKey?: string | null,
  mode?: DelegationHostMode,
): any | null {
  const list = Array.isArray(agents) ? agents : [];
  const key = String(hostKey || "").trim();
  if (key) {
    return list.find((agent) => agentMatchesKey(agent, key)) || null;
  }
  if (mode?.strict) return null;
  return list.find((agent) => isPlatformMainAgent(agent)) || null;
}

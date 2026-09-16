/** 业务系统 iframe 嵌套南孜对话组件时为 true；顶层打开 /embed/chat 为 false。 */
export function isEmbeddedInIframe(): boolean {
  if (typeof window === "undefined") return false
  try {
    return window.self !== window.top
  } catch {
    return true
  }
}

export interface ShortcutSkillRef {
  id: string;
  name: string;
}

const SHORTCUT_SKILL_RE = /^\[\[skill:([a-zA-Z0-9_-]+)\|([^\]]*)\]\]\n?/;

export function splitShortcutSkill(command: string): { text: string; skill: ShortcutSkillRef | null } {
  const raw = String(command || "");
  const match = raw.match(SHORTCUT_SKILL_RE);
  if (!match) return { text: raw, skill: null };
  const id = match[1] || "";
  const name = (match[2] || id).trim() || id;
  return { text: raw.slice(match[0].length), skill: id ? { id, name } : null };
}

export function packShortcutSkill(text: string, skill: ShortcutSkillRef | null): string {
  const body = String(text || "").trim();
  if (!skill?.id || !/^[a-zA-Z0-9_-]+$/.test(skill.id)) return body;
  const name = String(skill.name || skill.id).replace(/[\[\]|\r\n]/g, "").trim() || skill.id;
  return body ? `[[skill:${skill.id}|${name}]]\n${body}` : `[[skill:${skill.id}|${name}]]`;
}

export function shortcutCommandPreview(command: string): string {
  const parsed = splitShortcutSkill(command);
  const skill = parsed.skill ? `/${parsed.skill.name}` : "";
  const text = parsed.text.trim();
  return [skill, text].filter(Boolean).join(" ");
}

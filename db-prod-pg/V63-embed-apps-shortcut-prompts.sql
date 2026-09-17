-- V63: 嵌入应用常用提示词（按业务入口隔离，不跟全局快捷指令共享）

ALTER TABLE "sys_embed_apps"
    ADD COLUMN IF NOT EXISTS "shortcut_prompts" TEXT NOT NULL DEFAULT '[]';

COMMENT ON COLUMN "sys_embed_apps"."shortcut_prompts" IS '常用提示词 [{label, command}]，仅该嵌入应用 iframe 可见';

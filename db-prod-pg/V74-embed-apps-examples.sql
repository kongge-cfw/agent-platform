-- V74: 嵌入应用示例库，与应用绑定。示例含名称、指令、使用场景和附件

ALTER TABLE "sys_embed_apps"
    ADD COLUMN IF NOT EXISTS "examples" TEXT NOT NULL DEFAULT '[]';

COMMENT ON COLUMN "sys_embed_apps"."examples" IS '示例库 [{label, command, scenario, attachments}]，仅该嵌入应用对话可见';

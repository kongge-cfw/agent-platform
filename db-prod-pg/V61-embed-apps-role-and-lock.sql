-- V61: 嵌入应用改为关联角色，入口智能体锁定改为开关（PostgreSQL）

ALTER TABLE "sys_embed_apps"
    ADD COLUMN IF NOT EXISTS "role_id" BIGINT;

ALTER TABLE "sys_embed_apps"
    ADD COLUMN IF NOT EXISTS "lock_entry_agent" BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE "sys_embed_apps" DROP COLUMN IF EXISTS "allowed_agent_ids";

CREATE INDEX IF NOT EXISTS "idx_sys_embed_apps_role_id" ON "sys_embed_apps" ("role_id");

COMMENT ON COLUMN "sys_embed_apps"."role_id" IS '关联角色，智能体范围以角色资产为准';
COMMENT ON COLUMN "sys_embed_apps"."lock_entry_agent" IS '锁定入口智能体；关闭后 iframe 可切换/智能委派';

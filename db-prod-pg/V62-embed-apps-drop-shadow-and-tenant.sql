-- V62: 嵌入应用移除映射账号与租户隔离开关（PostgreSQL）

ALTER TABLE "sys_embed_apps" DROP COLUMN IF EXISTS "create_shadow_user";
ALTER TABLE "sys_embed_apps" DROP COLUMN IF EXISTS "isolate_datasets_by_tenant";

-- V57: 嵌入应用（平台化）+ 数据集/知识库租户隔离字段（PostgreSQL）

CREATE TABLE IF NOT EXISTS "sys_embed_apps" (
    "id" CHAR(36) PRIMARY KEY,
    "app_key" VARCHAR(64) NOT NULL,
    "name" VARCHAR(128) NOT NULL,
    "description" TEXT,
    "allowed_agent_ids" TEXT NOT NULL DEFAULT '[]',
    "allowed_origins" TEXT NOT NULL DEFAULT '[]',
    "require_identity" BOOLEAN NOT NULL DEFAULT TRUE,
    "claim_keys" TEXT NOT NULL DEFAULT '[]',
    "create_shadow_user" BOOLEAN NOT NULL DEFAULT TRUE,
    "data_permission_mode" VARCHAR(32) NOT NULL DEFAULT 'nanzi_sql_rewrite',
    "isolate_datasets_by_tenant" BOOLEAN NOT NULL DEFAULT FALSE,
    "is_active" BOOLEAN NOT NULL DEFAULT TRUE,
    "created_by" VARCHAR(64),
    "updated_by" VARCHAR(64),
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS "uk_sys_embed_apps_app_key" ON "sys_embed_apps" ("app_key");
CREATE INDEX IF NOT EXISTS "idx_sys_embed_apps_is_active" ON "sys_embed_apps" ("is_active");

COMMENT ON TABLE "sys_embed_apps" IS '嵌入应用（宿主系统注册）';
COMMENT ON COLUMN "sys_embed_apps"."app_key" IS '宿主 Ticket 引用键';
COMMENT ON COLUMN "sys_embed_apps"."allowed_agent_ids" IS '允许嵌入的智能体 ID JSON 数组';
COMMENT ON COLUMN "sys_embed_apps"."allowed_origins" IS '允许嵌入的宿主域名 JSON 数组';
COMMENT ON COLUMN "sys_embed_apps"."require_identity" IS '是否强制提交 identity claims';
COMMENT ON COLUMN "sys_embed_apps"."claim_keys" IS '允许的 claims 字段白名单 JSON 数组';
COMMENT ON COLUMN "sys_embed_apps"."create_shadow_user" IS '是否 JIT 影子账号';
COMMENT ON COLUMN "sys_embed_apps"."data_permission_mode" IS 'nanzi_sql_rewrite 或 mcp_only';
COMMENT ON COLUMN "sys_embed_apps"."isolate_datasets_by_tenant" IS '按 claims.tenant_id 隔离数据集/知识库';

INSERT INTO "ai_agent_resource_permissions"
    ("resource_type", "resource_id", "enabled", "created_at", "updated_at")
SELECT seed.resource_type, seed.resource_id, seed.enabled, NOW(), NOW()
FROM (VALUES
    ('menu', 'menu:embed_apps', TRUE),
    ('element', 'element:embed_apps:create', TRUE),
    ('element', 'element:embed_apps:edit', TRUE),
    ('element', 'element:embed_apps:delete', TRUE)
) AS seed(resource_type, resource_id, enabled)
WHERE NOT EXISTS (
    SELECT 1
    FROM "ai_agent_resource_permissions" existing
    WHERE existing."resource_type" = seed.resource_type
      AND existing."resource_id" = seed.resource_id
);

ALTER TABLE "meta_datasets"
    ADD COLUMN IF NOT EXISTS "tenant_id" VARCHAR(64);

ALTER TABLE "knowledge_base_metadata"
    ADD COLUMN IF NOT EXISTS "tenant_id" VARCHAR(64);

COMMENT ON COLUMN "meta_datasets"."tenant_id" IS '业务租户，空=所有租户可见';
COMMENT ON COLUMN "knowledge_base_metadata"."tenant_id" IS '业务租户，空=所有租户可见';

CREATE INDEX IF NOT EXISTS "idx_meta_datasets_tenant_id" ON "meta_datasets" ("tenant_id");
CREATE INDEX IF NOT EXISTS "idx_kb_metadata_tenant_id" ON "knowledge_base_metadata" ("tenant_id");

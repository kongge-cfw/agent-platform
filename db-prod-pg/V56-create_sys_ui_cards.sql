-- V56: 对话卡片登记表 + 菜单/按钮权限 + 平台 demo 卡（PostgreSQL）

CREATE TABLE IF NOT EXISTS "sys_ui_cards" (
    "id" CHAR(36) PRIMARY KEY,
    "card_key" VARCHAR(64) NOT NULL,
    "name" VARCHAR(128) NOT NULL,
    "description" TEXT,
    "render_type" VARCHAR(16) NOT NULL DEFAULT 'iframe',
    "url" VARCHAR(1024) NOT NULL,
    "allowed_origins" TEXT NOT NULL DEFAULT '[]',
    "allowed_actions" TEXT NOT NULL DEFAULT '[]',
    "allowed_agent_ids" TEXT NOT NULL DEFAULT '[]',
    "default_height" INTEGER NOT NULL DEFAULT 480,
    "token_ttl_seconds" INTEGER NOT NULL DEFAULT 600,
    "is_active" BOOLEAN NOT NULL DEFAULT TRUE,
    "created_by" VARCHAR(64),
    "updated_by" VARCHAR(64),
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS "uk_sys_ui_cards_card_key" ON "sys_ui_cards" ("card_key");
CREATE INDEX IF NOT EXISTS "idx_sys_ui_cards_is_active" ON "sys_ui_cards" ("is_active");

COMMENT ON TABLE "sys_ui_cards" IS '对话流业务卡片登记表（卡种，不是单据）';
COMMENT ON COLUMN "sys_ui_cards"."card_key" IS '模型唯一引用键';
COMMENT ON COLUMN "sys_ui_cards"."render_type" IS '渲染类型，首版仅 iframe';
COMMENT ON COLUMN "sys_ui_cards"."url" IS '业务卡页地址，查询串由平台追加';
COMMENT ON COLUMN "sys_ui_cards"."allowed_origins" IS 'iframe 源白名单 JSON 数组';
COMMENT ON COLUMN "sys_ui_cards"."allowed_actions" IS '允许动作 JSON 数组';
COMMENT ON COLUMN "sys_ui_cards"."allowed_agent_ids" IS '可选智能体 ID 白名单 JSON 数组';

INSERT INTO "ai_agent_resource_permissions"
    ("resource_type", "resource_id", "enabled", "created_at", "updated_at")
SELECT seed.resource_type, seed.resource_id, seed.enabled, NOW(), NOW()
FROM (VALUES
    ('menu', 'menu:ui_cards', TRUE),
    ('element', 'element:ui_cards:create', TRUE),
    ('element', 'element:ui_cards:edit', TRUE),
    ('element', 'element:ui_cards:delete', TRUE)
) AS seed(resource_type, resource_id, enabled)
WHERE NOT EXISTS (
    SELECT 1
    FROM "ai_agent_resource_permissions" existing
    WHERE existing."resource_type" = seed.resource_type
      AND existing."resource_id" = seed.resource_id
);

INSERT INTO "sys_ui_cards" (
    "id", "card_key", "name", "description", "render_type", "url",
    "allowed_origins", "allowed_actions", "allowed_agent_ids",
    "default_height", "token_ttl_seconds", "is_active", "created_at", "updated_at"
)
SELECT
    '00000000-0000-4000-8000-0000000000c1',
    'platform_demo_confirm',
    '平台演示确认卡',
    '同域演示页，用于验收 show_ui_card 闭环，不依赖外部业务系统。',
    'iframe',
    '/embed/ui-card-demo',
    '[]',
    '["confirm","reject"]',
    '[]',
    360,
    600,
    TRUE,
    NOW(),
    NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM "sys_ui_cards" WHERE "card_key" = 'platform_demo_confirm'
);

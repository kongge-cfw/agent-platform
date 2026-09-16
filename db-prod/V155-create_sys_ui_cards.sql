-- V155: 对话卡片登记表 + 菜单/按钮权限 + 平台 demo 卡（MySQL）

CREATE TABLE IF NOT EXISTS `sys_ui_cards` (
    `id` CHAR(36) NOT NULL,
    `card_key` VARCHAR(64) NOT NULL COMMENT '模型唯一引用键',
    `name` VARCHAR(128) NOT NULL COMMENT '管理端展示名',
    `description` TEXT NULL COMMENT '管理员/工具描述摘要',
    `render_type` VARCHAR(16) NOT NULL DEFAULT 'iframe' COMMENT '渲染类型，首版仅 iframe',
    `url` VARCHAR(1024) NOT NULL COMMENT '业务卡页地址，查询串由平台追加',
    `allowed_origins` TEXT NOT NULL COMMENT 'iframe 源白名单 JSON 数组',
    `allowed_actions` TEXT NOT NULL COMMENT '允许动作 JSON 数组',
    `allowed_agent_ids` TEXT NOT NULL COMMENT '可选智能体 ID 白名单 JSON 数组',
    `default_height` INT NOT NULL DEFAULT 480 COMMENT 'iframe 初始高度',
    `token_ttl_seconds` INT NOT NULL DEFAULT 600 COMMENT 'card_token TTL 秒',
    `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '停用后工具调用失败',
    `created_by` VARCHAR(64) NULL,
    `updated_by` VARCHAR(64) NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_sys_ui_cards_card_key` (`card_key`),
    KEY `idx_sys_ui_cards_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='对话流业务卡片登记表（卡种，不是单据）';

INSERT IGNORE INTO `ai_agent_resource_permissions`
    (`resource_type`, `resource_id`, `enabled`, `created_at`, `updated_at`)
VALUES
    ('menu', 'menu:ui_cards', 1, NOW(), NOW()),
    ('element', 'element:ui_cards:create', 1, NOW(), NOW()),
    ('element', 'element:ui_cards:edit', 1, NOW(), NOW()),
    ('element', 'element:ui_cards:delete', 1, NOW(), NOW());

INSERT INTO `sys_ui_cards` (
    `id`, `card_key`, `name`, `description`, `render_type`, `url`,
    `allowed_origins`, `allowed_actions`, `allowed_agent_ids`,
    `default_height`, `token_ttl_seconds`, `is_active`
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
    1
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM `sys_ui_cards` WHERE `card_key` = 'platform_demo_confirm'
);

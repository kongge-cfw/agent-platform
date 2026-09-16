-- V156: 嵌入应用（平台化）+ 数据集/知识库租户隔离字段（MySQL）

CREATE TABLE IF NOT EXISTS `sys_embed_apps` (
    `id` CHAR(36) NOT NULL,
    `app_key` VARCHAR(64) NOT NULL COMMENT '宿主 Ticket 引用键',
    `name` VARCHAR(128) NOT NULL COMMENT '管理端展示名',
    `description` TEXT NULL,
    `allowed_agent_ids` TEXT NOT NULL COMMENT '允许嵌入的智能体 ID JSON 数组，空=签发人权限内均可',
    `allowed_origins` TEXT NOT NULL COMMENT '允许嵌入的宿主域名 JSON 数组',
    `require_identity` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否强制提交 identity claims',
    `claim_keys` TEXT NOT NULL COMMENT '允许的 claims 字段白名单 JSON 数组，空=标准字段',
    `create_shadow_user` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否 JIT 影子账号；关闭后会话 owner 仅为外部 subject',
    `data_permission_mode` VARCHAR(32) NOT NULL DEFAULT 'nanzi_sql_rewrite' COMMENT 'nanzi_sql_rewrite | mcp_only',
    `isolate_datasets_by_tenant` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '按 claims.tenant_id 隔离数据集/知识库',
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_by` VARCHAR(64) NULL,
    `updated_by` VARCHAR(64) NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_sys_embed_apps_app_key` (`app_key`),
    KEY `idx_sys_embed_apps_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='嵌入应用（宿主系统注册）';

INSERT IGNORE INTO `ai_agent_resource_permissions`
    (`resource_type`, `resource_id`, `enabled`, `created_at`, `updated_at`)
VALUES
    ('menu', 'menu:embed_apps', 1, NOW(), NOW()),
    ('element', 'element:embed_apps:create', 1, NOW(), NOW()),
    ('element', 'element:embed_apps:edit', 1, NOW(), NOW()),
    ('element', 'element:embed_apps:delete', 1, NOW(), NOW());

ALTER TABLE `meta_datasets`
    ADD COLUMN `tenant_id` VARCHAR(64) NULL COMMENT '业务租户，空=所有租户可见' AFTER `status`;

ALTER TABLE `knowledge_base_metadata`
    ADD COLUMN `tenant_id` VARCHAR(64) NULL COMMENT '业务租户，空=所有租户可见' AFTER `status`;

CREATE INDEX `idx_meta_datasets_tenant_id` ON `meta_datasets` (`tenant_id`);
CREATE INDEX `idx_kb_metadata_tenant_id` ON `knowledge_base_metadata` (`tenant_id`);

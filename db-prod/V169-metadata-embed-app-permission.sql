-- V169: 数据集授权可授予嵌入应用

ALTER TABLE `ai_agent_resource_permissions`
    ADD COLUMN `embed_app_id` VARCHAR(36) NULL COMMENT '授权嵌入应用 ID' AFTER `role_id`,
    ADD INDEX `idx_resource_permission_embed_app` (`embed_app_id`, `resource_type`);

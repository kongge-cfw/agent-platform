-- V160: 嵌入应用改为关联角色，入口智能体锁定改为开关（MySQL）

ALTER TABLE `sys_embed_apps`
    ADD COLUMN `role_id` BIGINT NULL COMMENT '关联角色，智能体范围以角色资产为准' AFTER `description`,
    ADD COLUMN `lock_entry_agent` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '锁定入口智能体；关闭后 iframe 可切换/智能委派' AFTER `role_id`;

ALTER TABLE `sys_embed_apps` DROP COLUMN `allowed_agent_ids`;

CREATE INDEX `idx_sys_embed_apps_role_id` ON `sys_embed_apps` (`role_id`);

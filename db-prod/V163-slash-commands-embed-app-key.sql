-- V163: 个人快捷指令绑定嵌入应用，按业务入口隔离

ALTER TABLE `slash_commands`
    ADD COLUMN `embed_app_key` VARCHAR(64) NULL COMMENT '嵌入应用 Key；NULL 为站内全局' AFTER `created_by`;

CREATE INDEX `idx_slash_embed_app_creator` ON `slash_commands` (`embed_app_key`, `created_by`);

-- V168: 嵌入应用共享对话设置（同一应用内所有用户共用）

ALTER TABLE `sys_embed_apps`
    ADD COLUMN `chat_settings` TEXT NULL COMMENT '嵌入应用共享对话设置 JSON' AFTER `shortcut_prompts`;

UPDATE `sys_embed_apps` SET `chat_settings` = '{}' WHERE `chat_settings` IS NULL;

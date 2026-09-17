-- V162: 嵌入应用常用提示词（按业务入口隔离，不跟全局快捷指令共享）

ALTER TABLE `sys_embed_apps`
    ADD COLUMN `shortcut_prompts` TEXT NULL COMMENT '常用提示词 [{label, command}]' AFTER `data_permission_mode`;

UPDATE `sys_embed_apps` SET `shortcut_prompts` = '[]' WHERE `shortcut_prompts` IS NULL;

-- V173: 嵌入应用示例库，与应用绑定。示例含名称、指令、使用场景和附件

ALTER TABLE `sys_embed_apps`
    ADD COLUMN `examples` TEXT NULL COMMENT '示例库 [{label, command, scenario, attachments}]' AFTER `chat_settings`;

UPDATE `sys_embed_apps` SET `examples` = '[]' WHERE `examples` IS NULL;

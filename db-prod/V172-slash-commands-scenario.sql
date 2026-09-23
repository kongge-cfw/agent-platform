-- V172: 快捷指令增加使用场景，描述这条指令做什么

ALTER TABLE `slash_commands`
    ADD COLUMN `scenario` VARCHAR(200) NOT NULL DEFAULT '' COMMENT '使用场景，描述这条指令做什么' AFTER `command`;

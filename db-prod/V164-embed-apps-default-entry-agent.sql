-- V164: 嵌入应用默认入口智能体（未锁定时 iframe 默认进入该智能体）

ALTER TABLE `sys_embed_apps`
    ADD COLUMN `default_entry_agent_id` VARCHAR(64) NULL COMMENT '默认入口智能体 ID；空=角色含主助手则智能委派' AFTER `lock_entry_agent`;

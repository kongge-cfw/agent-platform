-- V167: 对话运行时个人偏好（模型 / 思考 / 温度），按嵌入应用 + 用户隔离（MySQL）

CREATE TABLE IF NOT EXISTS `user_chat_runtime_prefs` (
    `id` CHAR(36) NOT NULL,
    `embed_app_key` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '嵌入应用 Key；站内会话为空串',
    `owner_key` VARCHAR(128) NOT NULL COMMENT 'session_owner（嵌入 e:…）或站内 user_id',
    `override_model` VARCHAR(255) NULL COMMENT '覆盖模型 ID；空=跟随智能体默认',
    `thinking_enable` TINYINT(1) NULL COMMENT '思考开关；NULL=跟随平台默认（支持思考则开）',
    `reasoning_effort` VARCHAR(32) NULL COMMENT '思考强度；空=跟随模型默认',
    `temperature` FLOAT NULL COMMENT '采样温度；空=跟随模型默认',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_user_chat_runtime_prefs_app_owner` (`embed_app_key`, `owner_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='对话运行时个人偏好';

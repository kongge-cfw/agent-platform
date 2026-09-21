-- V68: 对话运行时个人偏好（模型 / 思考 / 温度），按嵌入应用 + 用户隔离（PostgreSQL）

CREATE TABLE IF NOT EXISTS "user_chat_runtime_prefs" (
    "id" CHAR(36) PRIMARY KEY,
    "embed_app_key" VARCHAR(64) NOT NULL DEFAULT '',
    "owner_key" VARCHAR(128) NOT NULL,
    "override_model" VARCHAR(255),
    "thinking_enable" BOOLEAN,
    "reasoning_effort" VARCHAR(32),
    "temperature" REAL,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS "uk_user_chat_runtime_prefs_app_owner"
    ON "user_chat_runtime_prefs" ("embed_app_key", "owner_key");

COMMENT ON TABLE "user_chat_runtime_prefs" IS '对话运行时个人偏好';
COMMENT ON COLUMN "user_chat_runtime_prefs"."embed_app_key" IS '嵌入应用 Key；站内会话为空串';
COMMENT ON COLUMN "user_chat_runtime_prefs"."owner_key" IS 'session_owner（嵌入 e:…）或站内 user_id';
COMMENT ON COLUMN "user_chat_runtime_prefs"."override_model" IS '覆盖模型 ID；空=跟随智能体默认';
COMMENT ON COLUMN "user_chat_runtime_prefs"."thinking_enable" IS '思考开关；NULL=跟随平台默认（支持思考则开）';
COMMENT ON COLUMN "user_chat_runtime_prefs"."reasoning_effort" IS '思考强度；空=跟随模型默认';
COMMENT ON COLUMN "user_chat_runtime_prefs"."temperature" IS '采样温度；空=跟随模型默认';

-- V69: 嵌入应用共享对话设置（同一应用内所有用户共用）

ALTER TABLE sys_embed_apps
  ADD COLUMN IF NOT EXISTS chat_settings TEXT NOT NULL DEFAULT '{}';

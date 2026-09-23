-- V70: 数据集授权可授予嵌入应用

ALTER TABLE ai_agent_resource_permissions
    ADD COLUMN IF NOT EXISTS embed_app_id VARCHAR(36);

CREATE INDEX IF NOT EXISTS idx_resource_permission_embed_app
    ON ai_agent_resource_permissions (embed_app_id, resource_type);

COMMENT ON COLUMN ai_agent_resource_permissions.embed_app_id IS '授权嵌入应用 ID';

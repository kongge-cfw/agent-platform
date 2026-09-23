-- 嵌入应用的数据集改由关联角色授权，移除数据集上的嵌入应用直授。

DELETE FROM ai_agent_resource_permissions
WHERE embed_app_id IS NOT NULL AND embed_app_id <> '';

DROP INDEX IF EXISTS idx_resource_permission_embed_app;

ALTER TABLE ai_agent_resource_permissions
    DROP COLUMN IF EXISTS embed_app_id;

-- 嵌入应用的数据集改由关联角色授权，移除数据集上的嵌入应用直授。

DELETE FROM `ai_agent_resource_permissions`
WHERE `embed_app_id` IS NOT NULL AND `embed_app_id` <> '';

ALTER TABLE `ai_agent_resource_permissions`
    DROP INDEX `idx_resource_permission_embed_app`,
    DROP COLUMN `embed_app_id`;

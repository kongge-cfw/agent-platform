-- V161: 嵌入应用移除映射账号与租户隔离开关（MySQL）

ALTER TABLE `sys_embed_apps` DROP COLUMN `create_shadow_user`;
ALTER TABLE `sys_embed_apps` DROP COLUMN `isolate_datasets_by_tenant`;

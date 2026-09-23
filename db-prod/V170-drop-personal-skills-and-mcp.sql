-- 取消个人技能与个人 MCP：删除已有个人 MCP 服务及其工具缓存、出站审计，
-- 并清空个人技能发布谱系。平台技能目录与平台 MCP 不受影响。

DELETE FROM skill_publication_versions;
DELETE FROM skill_publications;

DELETE FROM sys_mcp_tool_cache
WHERE server_id IN (SELECT id FROM sys_mcp_servers WHERE scope = 'personal');

DELETE FROM sys_mcp_outbound_audit_logs
WHERE server_id IN (SELECT id FROM sys_mcp_servers WHERE scope = 'personal');

DELETE FROM sys_mcp_servers WHERE scope = 'personal';

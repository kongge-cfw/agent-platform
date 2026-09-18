-- V66: 旧嵌入应用若角色已授权平台 Main 且未指定宿主，回填 sys-agent-chat。
-- 彻底方案下空宿主不再隐式回落 Main；要用平台主助手委派必须显式选中。

UPDATE "sys_embed_apps" AS a
SET "default_entry_agent_id" = 'sys-agent-chat'
FROM (
    SELECT DISTINCT p.role_id
    FROM "ai_agent_resource_permissions" p
    LEFT JOIN "ai_agents" ag
        ON ag.id = p.resource_id
        OR ag.name = p.resource_id
    WHERE p.enabled = TRUE
      AND p.resource_type = 'agent'
      AND p.role_id IS NOT NULL
      AND (
          p.resource_id IN ('sys-agent-chat', 'main', 'assistant', 'general-chat')
          OR ag.id = 'sys-agent-chat'
          OR LOWER(ag.name) IN ('main', 'assistant', 'general-chat')
      )
) AS role_main
WHERE a.role_id = role_main.role_id
  AND a.role_id IS NOT NULL
  AND (a.default_entry_agent_id IS NULL OR a.default_entry_agent_id = '');

COMMENT ON COLUMN "sys_embed_apps"."default_entry_agent_id" IS '智能委派宿主智能体 ID；空=不启用智能委派（不回落平台 Main）';

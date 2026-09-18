-- V166: 从智能体版本 skills 白名单摘掉已删除的公共技能 industry-dispatch-task。
-- 删除技能时的解绑只对之后的删除生效；已发布主智能体 v10、主智能体dev v4
-- 以及对应归档版本仍残留该幽灵 ID。白名单被摘空时关闭 skills_custom。
-- 本脚本幂等：不含该 ID 的行不会被更新。

UPDATE `ai_agent_versions`
SET `skills` = JSON_REMOVE(
        `skills`,
        JSON_UNQUOTE(JSON_SEARCH(`skills`, 'one', 'industry-dispatch-task', NULL, '$[*]'))
    )
WHERE `skills` IS NOT NULL
  AND JSON_CONTAINS(`skills`, JSON_QUOTE('industry-dispatch-task'), '$');

UPDATE `ai_agent_versions`
SET `skills_custom` = 0
WHERE `skills_custom` = 1
  AND (
      `skills` IS NULL
      OR JSON_TYPE(`skills`) <> 'ARRAY'
      OR JSON_LENGTH(`skills`) = 0
  );

-- V67: 从智能体版本 skills 白名单摘掉已删除的公共技能 industry-dispatch-task。
-- 删除技能时的解绑只对之后的删除生效；已发布主智能体 v10、主智能体dev v4
-- 以及对应归档版本仍残留该幽灵 ID。白名单被摘空时关闭 skills_custom。
-- 本脚本幂等：不含该 ID 的行不会被更新。

UPDATE "ai_agent_versions" AS v
SET
    "skills" = cleaned.skills,
    "skills_custom" = CASE
        WHEN cleaned.skills = '[]'::jsonb THEN FALSE
        ELSE v.skills_custom
    END
FROM (
    SELECT
        src.id,
        COALESCE(
            (
                SELECT jsonb_agg(to_jsonb(elem) ORDER BY ord)
                FROM jsonb_array_elements_text(src.skills)
                    WITH ORDINALITY AS t(elem, ord)
                WHERE elem IS DISTINCT FROM 'industry-dispatch-task'
            ),
            '[]'::jsonb
        ) AS skills
    FROM "ai_agent_versions" AS src
    WHERE src.skills IS NOT NULL
      AND jsonb_typeof(src.skills) = 'array'
      AND src.skills @> '["industry-dispatch-task"]'::jsonb
) AS cleaned
WHERE v.id = cleaned.id;

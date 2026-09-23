-- V73: 快捷指令增加使用场景，描述这条指令做什么

ALTER TABLE "slash_commands"
    ADD COLUMN IF NOT EXISTS "scenario" VARCHAR(200) NOT NULL DEFAULT '';

COMMENT ON COLUMN "slash_commands"."scenario" IS '使用场景，描述这条指令做什么';

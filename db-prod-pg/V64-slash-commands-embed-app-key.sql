-- V64: 个人快捷指令绑定嵌入应用，按业务入口隔离

ALTER TABLE "slash_commands"
    ADD COLUMN IF NOT EXISTS "embed_app_key" VARCHAR(64) NULL;

CREATE INDEX IF NOT EXISTS "idx_slash_embed_app_creator"
    ON "slash_commands" ("embed_app_key", "created_by");

COMMENT ON COLUMN "slash_commands"."embed_app_key" IS '嵌入应用 Key；NULL 为站内全局，非空则仅该业务入口的本人可见';

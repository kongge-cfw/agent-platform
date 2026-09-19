import assert from "node:assert/strict";
import { parseQuickButtons, promoteRecommendedQuestionLines } from "../src/utils/quickButtons.ts";

const sqlTarget = "改用 meta_changelog 表查询 2-7 月每月用户数 AS month, COUNT(DISTINCT user_id) AS monthly_users FROM meta_changelog";
const rendered = parseQuickButtons(`[⚡ 🧙 改用 meta_changelog 表查询 2-7 月每月用户数](quick:${sqlTarget})`);

assert.equal(rendered.includes("quick-action-btn"), true);
assert.equal(rendered.includes("AS monthly_users FROM meta_changelog"), false);
assert.equal(rendered.match(/quick-action-btn/g)?.length, 1);

const promoted = promoteRecommendedQuestionLines(
  "可前往任务跟踪查看办理进度。\n\n谁还没交\n催一下没交的企业\n查看无法匹配的企业名单",
);
assert.equal(promoted.includes("[🙋 谁还没交](quick:谁还没交)"), true);
const parsedPromoted = parseQuickButtons(promoted);
assert.equal(parsedPromoted.includes("quick-action-btn"), true);

const listed = parseQuickButtons(
  "### 💬 您可能还想了解\n---\n- [🙋 查看趋势图](quick:查看趋势图)\n- [🙋 对比季度](quick:对比季度)\n",
);
assert.equal(listed.includes('class="quick-action-row"'), true);
assert.equal((listed.match(/quick-action-btn/g) || []).length, 2);
assert.equal(listed.includes("\n- "), false);
assert.equal(
  promoteRecommendedQuestionLines("无法匹配企业：\n\n安达危运有限公司\n顺通物流有限公司"),
  "无法匹配企业：\n\n安达危运有限公司\n顺通物流有限公司",
);

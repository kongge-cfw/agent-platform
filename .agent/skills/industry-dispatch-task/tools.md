# 行业侧 MCP

下列接口**全部是 MCP**，不是技能或平台工具。必须通过 MCP 调用（`tools/call`）。本技能只说明怎么用，不提供这些接口本身。

运行时名称通常是 `mcp_<服务>_<短名>_<hash>`，例如 `mcp_mcp-public-admin-127-0-0-1_enterprise_resolve_e311844780`。按短名匹配：

| 短名 | 用途 |
|------|------|
| `enterprise_list` | 按地区/经营范围圈名录；`keyword` **仅口语**按名称或信用代码查找。空条件=权限内全部启用企业 |
| `enterprise_resolve` | 按企业全称批量精确匹配：判断是否存在，并取可下发企业的 ID |
| `dispatch_task_create` | 立即下发（必须 `publish=true`，必填 `taskType`） |
| `dispatch_task_set_type` | 改任务类型（已下发也可改） |
| `dispatch_task_search` / `dispatch_task_get` | 查**任务**，不查企业 |
| `dispatch_task_urge` / `approve` / `reject` | 催办与审核 |

**禁止调用**企业收件箱：`dispatch_inbox_search`、`dispatch_inbox_get`、`dispatch_inbox_submit`。文档/附件里的企业名称必须 `enterprise_resolve` 全称精确匹配，禁止对文档名称用 `enterprise_list(keyword)`。`keyword` 只用于口语对话查找。本技能只做行业下发，即使用户说「企业提交/办理」也只用行业侧 `dispatch_task_*`。点名全称走 `enterprise_resolve`。按危货/客运/地区圈选走 `enterprise_list`（不要 keyword）。口语简称走 `enterprise_list(keyword)`。

禁止：把 MCP 当成技能内置工具；因「未绑定」就跳过解析；先 `create` 无企业任务再补企业。本技能只立即下发，禁止保存草稿。MCP 列表里没有行业侧短名时，告诉用户检查 MCP 连接，不要改调 `dispatch_inbox_*`，不要继续写入。

`names`、`items`、`taskId` 等都必须放在 `tools/call` 的 `arguments` 对象里，不要拼到 URL。

文档解析/点名全称：出卡前 `enterprise_resolve`，仅唯一匹配且启用时取 ID 并冻结进 `create.json`。条件圈选：`enterprise_list`（不要 keyword），`enabled=true` 的 ID 冻结进 JSON；`truncated=true` 禁止当全集。口语检索：`enterprise_list(keyword=用户原词)`，唯一启用命中后 resolve 取 ID。确认后不再解析企业。不要把名称填进 `enterpriseId`。ID 必须是 JSON 字符串。

**写入类**（`dispatch_task_create` / `urge` / `approve` / `reject`）必须先走确认卡。下发卡必须含任务类型，且与 create 的 `taskType` 为同一中文值（见 [cards.md](cards.md)）。收到 `【业务确认】用户已确定` 后再调用。查询类不必出确认卡。禁止 `dispatch_task_issue`、`dispatch_task_delete_draft`。

当前账号无法匹配的企业：确认卡只在 `risk_note` 写总家数，不列名单、不增加字段。没有文件发布工具，不要生成 CSV、不要承诺下载；用户要求完整名单时按原始顺序每批最多展示 10 家。

## 企业

### enterprise_resolve

按**企业全称批量精确匹配**（去空格后与库中全称相等）。Excel/PDF/源表/用户粘贴的名单必须走本工具，禁止改用 `enterprise_list(keyword)` 模糊补全。一次调用同时判断能否下发并取得 `enterpriseId`，一次最多 1000 个。一家也放进 `names` 数组。出卡前调用一次并把 ID 冻结进 `create.json`；确认后不再调用。禁止凭简称、记忆或模糊命中推断存在。

必填：`names`（字符串数组，只填企业全称，不要填简称、关键词）。

返回每条：`found`、`enterpriseId`、`matchedName`、`creditCode`、`enabled`、`matchCount`；汇总 `total` / `found` / `missing`。

- `found=false`：不存在或本账号不可见，不得当下发对象
- `enabled=false`：存在但已停用，不得下发
- `matchCount!=1`：无法唯一确认，不得下发
- 仅 `found=true`、`enabled=true` 且 `matchCount=1` 才写入下发名单并使用 `enterpriseId`

重名时请用户提供可唯一匹配的企业全称，再把整份名单一次性 `enterprise_resolve`。文档里对不上的名称列入无法匹配，不要改走 list。仅当用户在对话里说简称、「查一下 XX」时才走 `enterprise_list(keyword)`。用户只说区划或经营范围、未点名企业且未上传名单时走圈选 `enterprise_list`，不要 resolve。

### enterprise_list

按地区、经营范围圈选名录；`keyword` **仅口语对话**按企业名称/统一社会信用代码查找。禁止用本工具解析 Excel/PDF/源表里的企业名称。

可选：`businessScopes`、`regionCode`、`keyword`、`enabled`（默认 true）、`current`、`size`（默认 100，最大 1000）。

- **圈选全市/危货/客运：** 传 `businessScopes` / `regionCode`，**不要传 `keyword`**。`enabled=true` 的 `enterpriseId` 可直接用于 create。
- **口语检索：** 用户当场说简称、「查一下 XX」时只传 `keyword=用户原词`。命中 1 家且启用：用返回的 `name` 作为全称。命中 0：请用户改全称。命中多家：列出全称请用户点名，再 `enterprise_resolve`。禁止把模糊命中多家当下发全集。禁止对文档抽出的名称使用 `keyword`。
- `truncated=true` 禁止当全集下发。

## 任务创建与下发

### dispatch_task_create

必填：`name`、`taskType`（与确认卡同一字段，传卡上中文原值：通知 / 工作部署 / 问题处置 / 材料报送）、`requirement`（Markdown、纯文本或 HTML；Markdown 原样入库，纯文本由后端转 HTML）。已下发任务改类型用 `dispatch_task_set_type`。

用户点「立即下发」：只调本工具一次，`publish=true`，同时带 `items`（至少 1 条）。成功后任务已是 `ISSUED`。禁止 `publish=false`，禁止 `dispatch_task_issue`。用户要求草稿时仍走立即下发。

**可下发企业为 0 时禁止调用本工具**。MCP 会报「未解析到可下发企业，禁止创建企业数为 0 的任务」。此时不要建空任务，去请用户改全称。

问题整改未特别说明时传 `needAudit=true`；其它任务默认 false。明确为重大事故隐患、立即整改、证照失效或不具备安全运营条件时必须传明确的 `deadlineDate`，不得省略为不限期。

冻结文件里问题处置写 `problems` 对象数组，不要手写 Markdown。确认后按 SKILL.md 模板拼成 `requirement` 再调用本工具。`items` 必填写法（推荐只传 `items`，不要再传一份 `enterpriseIds`）：

```json
{
  "name": "2026年6月货运超载问题整改",
  "taskType": "问题处置",
  "requirement": "请核查超载记录，落实车辆、驾驶人和装载管理整改，并提交整改凭证。",
  "publish": true,
  "needAudit": true,
  "deadlineDate": "2026-10-15",
  "items": [
    { "enterpriseId": "1987654321098765432", "requirement": "## 车辆问题\n\n| 发生时间 | 车牌号 | 问题类型 | 事实 |\n| --- | --- | --- | --- |\n| 2026-06-02 10:23 | A19251D | 超载 | 超载未达30%，实载32000kg，核定31000kg |" },
    { "enterpriseId": "1987654321098765433", "requirement": "## 车辆问题\n\n| 发生时间 | 车牌号 | 问题类型 | 事实 |\n| --- | --- | --- | --- |\n| 2026-06-02 10:25 | A05909D | 超载 | 超载未达30%，实载32000kg，核定31000kg |" }
  ]
}
```

每项：

- `enterpriseId`：必须是**刚完成的** `enterprise_resolve` 里对应全称的 `records[].enterpriseId` 字符串。把企业名填进来会报 `enterpriseId 不是有效 ID`
- `requirement`：提交给 MCP 时必须是拼好的 Markdown 表（`## 车辆问题` 等 + 表）。这就是企业端「任务说明」。问题整改有事实时必填，必须含 `##` 和 `|` 表，禁止一句话摘要，禁止建议句，禁止把 `problems` JSON 原样传进来。有车牌进车辆节，无车牌有人进驾驶员节，都无进企业节。有分车/分人禁止再写企业合计。不要分析/建议三节，不要 HTML。仅当与共性完全相同且无对象级事实时可空
- `attachments`：本企业附件 URL，最多 10 个

出确认卡前读全源明细并写入 `pending_write/create.json`。问题整改每个 item 冻结 `problems`（一车一条或一驾驶员一条），禁止概要/统计，禁止在冻结文件里手写 `requirement`。缺文件、缺家、检查不通过：禁止出卡、禁止调用本工具。确认后只 Read 这一份 JSON，剔除 `enterpriseNames`、`unmatchedCount`，把 `problems` 拼成 `requirement` 后提交；不得改写 facts。问题处置只传 `items`，不要传 `enterpriseIds`。会议通知用短 Markdown，不套整改三节。

立即下发时至少一家企业，否则报「请至少选择一家企业」。`sourceType` 由后端写成 `MCP`，不必传。

确认后写入失败：根据错误改 `items` 后**重试本工具**。禁止改调 `dispatch_task_issue`，禁止去掉 `items` 再建空任务。

## 查询

### dispatch_task_search

分页任务跟踪。可选：`keyword`、`status`（`DRAFT` / `ISSUED` / `DONE`）、`taskType`、`needAudit`、`current`、`size`。

### dispatch_task_get

任务详情及各企业进度。必填：`taskId`。返回的是 `requirementPlain`，不要据此编造或重建企业明细；明细里的 `itemId` 用于催办/审核/驳回。

## 催办与审核

### dispatch_task_urge

- 催一家：传 `itemId`
- 催该任务全部待办：传 `taskId`（不要同时依赖未解析的 item）

可选：`remark`（最多 500 字）。只催 `PENDING`。

### dispatch_task_approve

审核通过。必填：`itemId`。可选：`remark`。任务须开启审核，且明细为 `REVIEWING`。

### dispatch_task_reject

驳回，企业须重新办理。必填：`itemId`、`remark`（驳回原因）。条件同审核通过。

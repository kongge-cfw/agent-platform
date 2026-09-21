# 智云卡片交互

人机交互只用平台卡片。不要用口头「是否确认」或推荐问代替确认卡。出确认卡当轮禁止推荐问；写入成功后的回执末尾必须带 SKILL.md 规定的固定中文推荐问。

业务确认卡（内容对不对）与工具权限卡（允许不允许调 MCP）是两层：确认通过后再调写入工具；若平台再弹出权限卡，按用户点选执行，不要再叠一张同样内容的业务确认卡。不要调用 `show_ui_card`。

## 下发确认卡（必出）

解析企业之后、`dispatch_task_create` 之前必须调用 `request_user_confirmation`。只展示、不写库。等 `【业务确认】用户已确定` 再写入；`【业务确认】用户已取消` 则终止，禁止立刻再出确认卡。禁止保存草稿，禁止 `dispatch_task_issue`。

工具顶层入参必须是包含 `title, summary, confirm_label, cancel_label, risk_note, fields` 的 JSON 对象。禁止把字段数组直接作为顶层入参；`fields` 必须是真实数组，不能是 JSON 字符串。

出卡当轮不要写「汇总工具结果」、指标口径长文或 todo。允许出卡前一段「纳入核对」旁白。确认卡本身只展示任务级信息和企业范围。问题整改必须先有 `pending_write/problems.md`（每个可下发企业一个 `# 全称` 一级标题）。缺文件或缺家：禁止出卡。确认后只 Read 这一份 Markdown，按标题切成 `items[].requirement`。读不到则停止并重新出卡。

`title` 与主按钮只能是「确认立即下发」+「立即下发」。禁止「保存草稿」。

`summary` 只用 `将向N家企业立即下发，完成时限D。`。`N家` 不加空格，`D` 只能是 `yyyy-MM-dd` 或 `不限期`。无法匹配家数只写在 `risk_note`，不写进 summary 或字段。

字段必须让人看清**可下发**企业与时限（不要只把家数写在 summary 里）。缺 `enterpriseCount` / `enterprises` 禁止出卡。不符合条件的企业不进这两字段。

```json
{
  "title": "确认立即下发",
  "summary": "将向2家企业立即下发，完成时限2026-10-15。",
  "confirm_label": "立即下发",
  "cancel_label": "取消",
  "risk_note": "立即下发后不可修改、不可删除。另有23家企业当前无法匹配，本次不会下发。",
  "fields": [
    { "key": "name", "label": "任务名称", "value": "2026年6月货运超载问题整改", "value_type": "string", "editable": true },
    { "key": "taskType", "label": "任务类型", "value": "问题处置", "value_type": "enum", "editable": true, "options": ["通知", "工作部署", "问题处置", "材料报送"] },
    { "key": "deadlineDate", "label": "完成时限", "value": "2026-10-15", "value_type": "date", "editable": true },
    { "key": "needAudit", "label": "企业提交后需行业审核", "value": true, "value_type": "boolean", "editable": true },
    { "key": "enterpriseCount", "label": "可下发企业数", "value": "2家", "value_type": "string", "editable": false },
    { "key": "enterprises", "label": "可下发企业清单", "value": "安达危运有限公司、顺通物流有限公司", "value_type": "string", "editable": false }
  ]
}
```

约定：

- 字段恰好 6 个，顺序固定为：任务名称、任务类型、完成时限、企业提交后需行业审核、可下发企业数、可下发企业清单。禁止增加共性任务要求或任何第七字段。`taskType` 必须是中文下拉：`value_type=enum`，`options` 固定为 `["通知", "工作部署", "问题处置", "材料报送"]`，`value` 只能是其中一项。确认后 `dispatch_task_create.taskType` 必须等于卡上中文原值。任务级 `requirement` 用 SKILL.md 固定句，不进确认卡。
- 禁止增加 `itemPreview`、`skippedCount`、`skipped`、“各企业明细”“当前账号无法下发”“无法下发企业”或同类字段。企业问题 Markdown 写入 `pending_write/problems.md`，确认后按一级标题切分写入 `items[].requirement`。纳入核对写在出卡前旁白，不进确认卡字段。
- `enterprises` 只读且 `value_type=string`，必须用**可下发**企业全称数组 `join('、')` 生成，值中禁止 `\n`、编号和项目符号。无法匹配、停用、重名禁止写入。`enterpriseCount` 的 N 必须等于该名单家数。缺这两字段、N=0、名单为空或家数对不上：禁止出卡。
- 无法匹配家数只写入 `risk_note`，必须是准确数字，禁止写「若干」「部分」。有无法匹配时用「另有M家企业当前无法匹配，本次不会下发。」；为0时不要提。不要在确认卡列无法匹配企业名单，不要把名单做成用户可下载文件或承诺下载。写入 `pending_write/` 的待提交正文除外。
- 文档解析/点名全称：能否下发只看本次 `enterprise_resolve` 的 `found` / `enabled` / `matchCount`。条件圈选：看 `enterprise_list` 的 `enabled`（不要 keyword）；`truncated=true` 先补全再出卡。口语检索：`enterprise_list(keyword)` 仅对话使用，唯一启用命中后按点名处理。文档里的名称禁止走 keyword。用户主动要求看名单时，再按用户原始顺序每批最多展示 10 家。
- `deadlineDate` 的 `value_type` 必须始终为 `date`。无时限 `value` 为空字符串，禁止把「不限期」写入字段值。用户可在日期选择器中填写或修改；写入前有日期则规范为 `yyyy-MM-dd`，仍为空则不传 `deadlineDate`。
- 不要放 `publish` 勾选。确认后一律 `publish=true`。
- 卡上只展示企业名称，不展示 ID。文档解析、点名全称或口语唯一命中：确定后再 `enterprise_resolve` 取 ID；条件圈选用出卡前 list 的 ID。禁止把本卡名称填进 `items[].enterpriseId`。
- 反查 ID 后只调 `dispatch_task_create(publish=true)`，禁止 `publish=false`，禁止 `dispatch_task_issue`。
- **可下发企业数为 0 时不要出本卡、不要 create**。改用短问请用户改全称；无法下发清单按每批最多 10 家展示。
- 按任务类型选用结构，见 [item-requirement.md](item-requirement.md)。整改用问题清单 Markdown；会议通知等不要套整改三类表。

调用 `request_user_confirmation` 前强制校验：

- 顶层是非空 JSON 对象，不是数组
- `title` 是非空字符串
- 顶层 key 严格为 `title, summary, confirm_label, cancel_label, risk_note, fields`
- `fields` 是数组，不是字符串
- `fields.length` 必须为 6
- key 顺序必须为 `name, taskType, deadlineDate, needAudit, enterpriseCount, enterprises`
- `taskType` 的 `value_type` 必须是 `enum`，`options` 必须是 `["通知", "工作部署", "问题处置", "材料报送"]`，`value` 必须是其中一项
- 字段的 label、`value_type`、`editable` 必须与模板完全一致
- 标题、按钮、风险提示和 summary 必须匹配立即下发固定模板
- label 不得使用企业名称，不得包含企业 ID
- `enterprises` 不得包含换行
- `enterpriseCount`、`enterprises` 必须存在且只含可下发企业；家数必须与名单家数一致
- 不满足时重建参数，禁止调用确认工具

## 提问卡（少用）

`ask_user_question` 每轮一题，2–12 个互斥选项。只在确认卡解决不了时用：

- `matchCount>1` 或一家都匹配不到：短问请用户改成营业执照全称后，再一次性按全称 `enterprise_resolve`；禁止 `dispatch_task_create`，禁止保存 0 家任务
- 用户没说清是通过还是驳回

不要用提问卡问：要不要审核、要不要存草稿、部分企业不在库怎么办、催全部还是指定（用户说「没交的」就是全部待办）。这些要么已有默认，要么已写在确认卡上。本技能不保存草稿。

## 催办 / 审核确认卡

催办、通过、驳回同样必须先出确认卡。催办卡带上任务名、催办对象企业（逐家或「全部待办理：…」）、该任务完成时限。驳回卡 `remark` 必填；通过卡说明可空。

## todo_write

仅当用户一句话里要连续做多件写入（例如催办且驳回）时建清单。单纯下发、单纯查询不要建，也不要用 todo 复述「解析企业 → 出确认卡 → 下发」。

## 下发结果：固定 Markdown 回执

`dispatch_task_create(publish=true)` 成功后只输出 SKILL.md 规定的固定下发 Markdown 模板，只用 2 张表，不输出 HTML，不调用卡片、文件或图表工具：

- 下发结果：已下发、未下发、完成时限、行业审核、办理流程、问题构成、数据依据
- 企业清单：序号、企业名称、下发结果；超过30家只列前30家

禁止再拆概况、对象、构成、办理、未下发原因等表。禁止 HTML 标签、覆盖率、进度条、ASCII 图、外部图片、假按钮、任务 ID、车牌、人员身份信息和整改正文。回执末尾必须带固定中文推荐问，文案见 SKILL.md。

用户问「进度 / 谁还没交」才用 `dispatch_task_get`，也只出待办/已完成等数字，仍不要复制整改正文。

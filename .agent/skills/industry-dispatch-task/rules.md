# 业务硬约束

对应后端 `DispatchTaskService`、行业侧 MCP，以及智云 HITL 卡片。违反会直接报错或把错误操作打到企业。

## 交互

- **立即下发前必须** `request_user_confirmation`。卡上只确认任务名称、任务类型、完成时限、企业提交后需行业审核、可下发企业数、可下发企业清单，恰好 6 个字段。不展示各企业明细或摘要。禁止用纯文字「是否确认」代替。禁止保存草稿。
- `request_user_confirmation` 的顶层入参必须是 JSON 对象，顶层 key 严格为 `title, summary, confirm_label, cancel_label, risk_note, fields`，其中 `title` 非空、`fields` 为真实数组。禁止把字段数组直接作为顶层入参或把 `fields` 传成 JSON 字符串；Schema 校验前无法由工具内部兜底。
- 规程以 SKILL.md「规程裁定」为准：出卡前允许按表补读。问题整改只写一次 `pending_write/problems.md`（按企业一级标题切分的 Markdown）。禁止 records.json，禁止按家写 html。确认后只 Read 这一份文件，把各家 Markdown 写入 `items[].requirement`。企业合计页不是企业问题。禁止把企业明细或企业 ID 打进对话。
- 企业收到的整改说明是 **Markdown 问题清单**（`## 企业问题` / `## 车辆问题` / `## 驾驶员问题` + 表），写入 `items[].requirement`，这就是企业端「任务说明」。禁止一句话摘要，禁止建议句。**企业问题 = 源材料没有精确到具体车辆、也没有精确到具体驾驶员的事项**。有分车/分人不得再写企业合计。车辆行必须有真实车牌。事实须含次数/里程/完整率等源材料已有数值。禁止编造源附件中没有的车牌、人员、指标。源材料提到或要求整改的，不论大小一律下发；仅源材料明确标注无需处理的才可省略。
- 按证据来源定性：执法认定=违法事实，设备报警=监测预警，检查发现=隐患，证照有效期=资质异常。禁止把报警线索直接写成违法，禁止在无调查结论时编造根因。
- 任务级 `requirement` 用 SKILL.md 按类型固定句，不进确认卡。企业明细只下发问题清单 Markdown，不要分析/建议三节，不能用三句摘要代替表。问题整改默认 `needAudit=true`。身份证号、资格证号等敏感标识默认脱敏。
- 下发结果使用固定 Markdown 回执。企业明细为 Markdown，由任务系统展示。
- 确认卡取消后禁止调用任何写入 MCP，禁止立刻再弹确认卡。
- 确认卡字段恰好 6 个，顺序固定为：任务名称、任务类型、完成时限、企业提交后需行业审核、可下发企业数、可下发企业清单。缺 `enterpriseCount` 或 `enterprises` 禁止出卡。两字段只含可下发企业（点名：`found=true && enabled=true && matchCount=1`；圈选：`enabled=true`）。无法匹配、停用、重名不进家数、不进名单，总家数只写入 `risk_note`。`enterpriseCount` 必须为 `N家` 且 N 等于名单按 `、` 拆开的家数。`taskType` 必须是中文下拉：`value_type=enum`，`options=["通知", "工作部署", "问题处置", "材料报送"]`。确认后 create 必须带卡上中文原值。`enterprises` 用 `value_type=string`，值由可下发名称数组 `join('、')` 生成，禁止换行和编号。禁止增加 `skippedCount`、`skipped`、共性任务要求或无法下发企业名单字段。出卡前旁白纳入核对。确认后只 Read `pending_write/problems.md`，原样拷进 `items[].requirement`，禁止压成摘要。读不到文件则停止并重新出卡，禁止在确认轮读 PDF 后直接 create。
- 调用确认工具前校验 `fields.length=6` 且 key 顺序严格为 `name, taskType, deadlineDate, needAudit, enterpriseCount, enterprises`。字段 label、`value_type`、`editable` 及对应模式的标题、按钮、风险提示必须与 SKILL.md 完整模板一致；禁止企业名称充当 label，禁止 label 出现企业 ID，禁止动态生成每企业字段。
- summary 只允许使用 SKILL.md 的立即下发句式；risk_note 只允许使用两个立即下发固定句式；家数写 `N家`，日期写 `yyyy-MM-dd` 或 `不限期`。可下发企业名单按用户原始顺序去重后展示，禁止重新排序。
- 同时校验顶层不是数组、`title` 为非空字符串、`fields` 为真实数组；不满足时先重建完整对象，不得尝试调用。
- 部分名称匹配失败或非本账号企业：确认卡只在 `risk_note` 写**总家数**，不列名单。用户要求时再按每批最多 10 家展示。禁止把无法匹配名单做成用户可下载文件或调用不存在的文件发布工具。写入 `pending_write/` 的待提交正文除外。点「立即下发」=只发唯一匹配且启用的。
- 可下发为 0 家：禁止出下发确认卡，禁止 `dispatch_task_create`。
- 业务确认通过后才调 MCP；若平台另弹工具权限卡，不要再叠一张同样内容的业务确认卡。
- 不要调用 `show_ui_card`。
- 立即下发成功：只输出 SKILL.md 规定的固定 2 表 Markdown 回执（下发结果 + 企业清单），末尾带固定中文推荐问。确认卡当轮禁止推荐问。不输出 HTML，不调用卡片、文件或图表工具。不得再拆概况、对象、构成、办理、未下发原因等表。禁止任务 ID、车牌、人员身份信息和整改原文。禁止保存草稿回执。

## 身份与权限

- 仅**行业账号下发任务**。需要权限 `menu:/office/task-track:view`。
- **禁止** `dispatch_inbox_search` / `dispatch_inbox_get` / `dispatch_inbox_submit`（企业收件箱）。行业账号调用会报「仅企业账号可使用此工具」。MCP 里即使出现也不要用。
- 行业侧工具若被企业账号调用会报「仅行业账号可使用此工具」。本技能不要给企业账号用。
- 调用需要用户身份（租户/地区范围由登录用户决定）。无用户身份时不要重试编造企业。

## 企业

- 本文件所列接口均是 **MCP**，不是技能或平台工具。运行时按短名匹配（如名称中含 `enterprise_resolve`），不要报「未绑定」后跳过。
- **文档解析 / 点名全称**：Excel/PDF/源表/用户粘贴的企业名称必须 `enterprise_resolve` 全称精确匹配。`names` 一次提交全部全称，去空格后精确匹配。禁止凭简称、记忆推断存在，禁止对文档名称用 `enterprise_list(keyword)` 模糊补全。
- **条件圈选**：危货/客运/地区/全市走 `enterprise_list`（不要 keyword），用返回的 `enterpriseId`。禁止用 resolve 圈经营范围。`truncated=true` 禁止当全集下发。
- **口语检索**：仅用户当场说简称、「查一下 XX」时走 `enterprise_list(keyword=用户原词)`。命中 1 家且启用才可进名单；命中多家先让用户点名再 resolve。禁止用 `dispatch_task_search` 查企业。
- 一家点名也用 `names: ["全称"]`。禁止按家循环查询，禁止用相似名称替换。`found=false` 即全称对不上或不可见；`matchCount>1` 列入无法下发。请用户改成企业全称后再批量 `enterprise_resolve`。
- 文档名称对不上：列入无法下发或请用户补全称，禁止用相似名称替换，禁止改走 list。
- 只纳入 `found=true`、`enabled=true` 且 `matchCount=1`。
- 确认卡只展示名称。用户确定后，用卡上「可下发企业清单」全称再批量反查一次。第二次可下发企业集合必须与确认卡完全一致，否则重新确认；一致时才把本次返回的 ID 字符串写入 `items[].enterpriseId`。禁止把名称当 ID，禁止凭记忆填 ID（会报「enterpriseId 不是有效 ID」）。JSON 里 ID 必须加引号。
- 下发范围受登录用户地区权限限制；解析不到可能是无权限或全称不一致。

## 创建与下发

必填：

- 任务名称 `name`，最多 200 字
- 任务类型 `taskType`：`通知` / `工作部署` / `问题处置` / `材料报送`（与确认卡同一字段、同一中文值；英文码也可，禁止省略、禁止默认、禁止从名称猜测）
- 任务要求 `requirement`，不能为空（空 `<p></p>` / `<p><br></p>` 也不算有内容）

可选：

- `deadlineDate`：`yyyy-MM-dd`；到期日当天仍算时限内，列表用 `overdue` 判断逾期
- `needAudit`：问题整改默认 true；会议、培训、材料报送等默认 false；true 时企业提交后进入待审核
- 附件 URL、单家企业补充说明、`sourceId`

规则：

- 点「立即下发」= 一次 `dispatch_task_create` 且 `publish=true` 并带 `items`。成功即已下发。禁止 `publish=false`，禁止 `dispatch_task_issue`，禁止 `dispatch_task_delete_draft`
- 明确为重大事故隐患、立即整改、证照失效或不具备安全运营条件时必须有明确完成时限，不得使用“不限期”
- **可下发企业为 0：禁止 `dispatch_task_create`**，禁止出下发确认卡。MCP 会报「未解析到可下发企业，禁止创建企业数为 0 的任务」
- `items` 至少一家，否则不要调用 create
- 创建失败不要改调 `dispatch_task_issue`，不要建 0 家任务再下发
- 已下发（`ISSUED` / `DONE`）不可改、不可删
- 任务级要求可纯文本；企业明细用 Markdown 原样入库（不要包成 HTML）。不要塞脚本或超长正文（上限约 20 万字符）
- 单家正文预计超过 20 万字符时禁止截断，按时间段或问题类型拆成多个任务并分别确认

## 催办

- 仅催 `PENDING`（待办理）
- 已完成、待审核不催（分别报「已完成的任务无需催办」「待审核的任务无需催办」）
- 按任务催办时若没有待办企业，报「没有可催办的企业」
- 催办备注最多 500 字

## 审核与驳回

- 任务必须 `needAudit=true`，否则报「该任务无需审核」
- 明细必须是 `REVIEWING`
- 驳回必须写 `remark`
- 驳回后企业回到待办理，需重新提交

## 状态

任务：`DRAFT` → `ISSUED` →（全部企业明细 `DONE` 后）`DONE`。

企业明细：`PENDING` →（开启审核则）`REVIEWING` → `DONE`；或 `REVIEWING` → `REJECTED` → 再提交。

## 来源

MCP 创建的任务 `sourceType=MCP`（展示为「智能体」），由后端写入，skill 不要传 `sourceType`。

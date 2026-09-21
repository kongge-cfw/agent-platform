---
name: industry-dispatch-task
description: "行业监管账号向备案企业下发交通运输安全任务并跟踪办理。用户提到下发、发给企业、通知企业、整改、风险预警、事故隐患、超载、超速、疲劳驾驶、证照异常、车辆问题、人员问题、会议通知、培训、材料报送、催办、没交、审核、通过、驳回、任务进度或任务跟踪时使用；即使前一步是监测分析，只要下一步要对企业执行，也必须使用。"
---

# 行业任务下发

仅服务行业账号 `/office/task-track`。查企业只有两个 MCP：`enterprise_resolve`（营业执照全称精确反查）、`enterprise_list`（圈选名录；口语对话里才可用 `keyword` 查找）。只调用本文件列出的 MCP。`dispatch_task_search` 只查任务，不查企业。禁止 `dispatch_inbox_*`。禁止用 resolve 圈危货。禁止用 list 的 `keyword` 去圈全市/危货，也禁止用它解析文档里的企业名称。写入只走 `dispatch_task_create(publish=true)`。禁止 `publish=false`，禁止 `dispatch_task_issue`，禁止 `show_ui_card`，禁止 `todo_write` 串主路径。运行时名称带前缀时按短名匹配。

平台只注入本文件。禁止为读规则去打开附属 md。用户上传的 Excel/PDF 按主路径读写。源附件只 Read，不要另存 records.json 或按家 html。

## 规程裁定（后面章节不得写相反要求）

1. **准优先于快。** 出卡前允许按表补读源附件。确认后禁止再读源附件，禁止再生成正文。
2. **只写一份 Markdown。** 出卡前只 `Write` 一次 `pending_write/problems.md`。禁止 `records.json`，禁止按家写 html，禁止把同一份事实再写成第二份文件。
3. **企业合计页不是企业问题。** 有分车或分人明细时，合计不要写入问题清单。企业问题只收制度/台账/许可，或全文既无车牌也无驾驶员姓名的事项。
4. **确认轮只提交冻结结果。** 文档解析或点名全称：卡上全称再 `enterprise_resolve`。口语检索唯一命中后也按点名：卡上全称再 `enterprise_resolve`。条件圈选：用出卡前 `enterprise_list` 的 `enterpriseId`，禁止再 list、禁止再 resolve。然后一次 `Read pending_write/problems.md`（无该文件的通知可跳过 Read）→ 一次 `dispatch_task_create`。按一级标题切成各家 Markdown，**原样**填入 `items[].requirement`，一个字都不改。读不到该有的文件：停止，禁止 create，禁止在确认轮读 PDF 补写后直接下发。`truncated=true` 禁止当全集下发。
5. **禁止编造。** 车牌、姓名、次数、里程、完整率、时间必须在源材料原文中逐字出现。禁止连续重复数字号牌。找不到就省略该列，不准补号。
6. **文档提到即下发。** 源材料列出、点名或要求整改的问题，不论轻微、一般、提示、预警、次数少、已处理、完整率高，一律写入问题清单并下发给对应企业。禁止自行判断「太小不用发」。仅当该条在源材料中明确标注「无需处理 / 不纳入整改 / 仅供参考不下发」等，才可省略。
7. **企业端看到的就是 `items[].requirement`。** 任务跟踪「任务说明」直接展示该字段。写成摘要，企业端就只看到摘要。问题整改有车牌/人员/记录时，该字段**必须**含 `##` 节标题和 Markdown 表（含 `|` 行），禁止一句话、禁止「超速N次」这种合计句、禁止把多行表压成一段话。确认轮禁止为省 token 压缩、改写或补建议。
8. **禁止建议句和分析句。** 不要写「请核查…并加强教育」「请落实整改」这类套话进企业明细。不要「二、问题分析」「三、整改建议」。空类不要写对应 `##` 节。
9. **确认卡恰好 6 个字段，不能多也不能少。** 顺序与 label 必须是：任务名称、任务类型、完成时限、企业提交后需行业审核、可下发企业数、可下发企业清单。禁止增加共性任务要求或任何第七字段。缺一个、多一个、label 不一致、或 key 顺序不对：禁止出卡。
10. **无任务类型禁止出卡、禁止 create。** 第二字段必须是 `taskType`，`value_type=enum`，`options=["通知", "工作部署", "问题处置", "材料报送"]`。确认后 `dispatch_task_create.taskType` 必须等于卡上中文原值。
11. **无可下发企业数或可下发企业清单禁止出卡。** `enterpriseCount`、`enterprises` 只含可下发企业：文档解析/点名全称/口语唯一命中后 resolve=`found=true && enabled=true && matchCount=1`；条件圈选=`enabled=true`。无法匹配、停用、重名、不在权限内的不进家数、不进名单，其总家数只写 `risk_note`。`enterpriseCount` 必须是 `N家`（N 为正整数、无空格），且 N 等于 `enterprises` 按 `、` 拆开后的家数。`enterprises` 必须是可下发全称 `join('、')`，禁止空、禁止换行、禁止编号。缺字段、N=0、名单为空、家数与名单不一致、或把不符合条件的企业写进去：禁止出卡。
12. **文档用 resolve，口语才用 list.keyword。** Excel/PDF/附件/源表里的企业名称必须 `enterprise_resolve` 全称精确匹配，禁止对文档名称用 `enterprise_list(keyword)` 模糊补全。`enterprise_list` 的 `keyword` **仅**用于口语对话（用户当场说简称、「查一下 XX」）。圈选全市/危货不要 keyword。禁止用 `dispatch_task_search` 或 `dispatch_inbox_*` 查企业。

## 主路径（问题整改）

缺任务名时一句短问。未提时限通常不限期；重大事故隐患、立即整改、证照失效必须有明确时限。问题处置默认 `needAudit=true`。用户说「先存草稿」也只出立即下发卡。任务类型必填，确认卡与 create 都用中文：通知、工作部署、问题处置、材料报送。会议/培训/一般告知用通知，专项整治/贯彻文件用工作部署，整改/隐患/责令改正用问题处置，报表/台账/核查名单用材料报送。

文档解析与点名全称：可下发 = `found=true && enabled=true && matchCount=1`。条件圈选：可下发 = `enabled=true`。为 0：禁止出卡、禁止 create。

1. **认企业（三条路径互斥）。**
   - **文档解析 / 附件名单 / 用户给出全称：** Excel、PDF、源表、用户粘贴的企业名称一律一次 `enterprise_resolve`，`names` 提交文档中的营业执照全称（去空格后精确匹配）。禁止对文档里的名称用 `enterprise_list` 或 `keyword` 模糊补全。对不上的不进确认卡，总家数写入 `risk_note`；不要用相似名称替换。
   - **条件圈选：** 用户说危货/客运/某地/全市且未给名单、也没有上传企业名单 → 一次 `enterprise_list`（`businessScopes` 可用「危货」等口语，空条件=权限内全部启用）。**不要传 `keyword`。** `truncated=true` 先问是否扩大 `size`（最大 1000）或分页，禁止只拿一页当下发全集。班线/包车企业主档没有，先按客运圈并旁白说明。
   - **口语检索（仅对话，不是文档）：** 用户当场说简称、「查一下 XX」、没有上传名单也不是圈选全市 → 一次 `enterprise_list(keyword=用户原词)`。命中 1 家且 `enabled=true`：用返回的 `name` 全称进可下发名单，确认后再 `enterprise_resolve` 取 ID。命中 0：请用户改成营业执照全称。命中多家：列出返回的全称请用户点名，再 `enterprise_resolve`。禁止把模糊命中的多家直接当下发全集。
2. **认表并可补读。** 旁白列出源表。禁止因完整率 ≥95%、已处理、次数少、轻微或「看起来不大」丢掉某张表或某行。截断则再 `Read` 该表。仅源材料对该条写明无需处理时才跳过。
3. **一次写入 `pending_write/problems.md`。** 每个可下发企业一个一级标题，标题必须是营业执照全称。节名只用 `## 企业问题` / `## 车辆问题` / `## 驾驶员问题`。有车牌 → 车辆；无车牌有姓名 → 驾驶员；都无 → 企业。同一车牌多种问题分行。文档提到的问题全部入表，禁止因达标、已处理、次数少或程度轻删行。有分车/分人时禁止把「超速6次」这类合计写入企业问题。

```markdown
# 安达危运有限公司

## 车辆问题

| 发生时间 | 车牌号 | 问题类型 | 事实 |
| --- | --- | --- | --- |
| 2026-09-12 | 晋L68222 | 超速 | 超速7次，已处理7次 |
| 2026-09-12 | 晋LS0715 | 轨迹异常 | 总里程530.25km，完整率97.69% |

# 顺通物流有限公司

## 车辆问题

| 发生时间 | 车牌号 | 问题类型 | 事实 |
| --- | --- | --- | --- |
| 2026-09-12 | 晋A12345 | 超速 | 超速1次，已处理1次 |
```

**禁止写成：**

```text
9月12日存在问题：超速6次。请核查超速原因并加强驾驶员教育。
```

列：车辆用发生时间、车牌号、问题类型、事实；驾驶员用发生时间、姓名、问题类型、事实；企业用发生时间、问题类别、问题事项、事实。事实须含源材料已有的次数、已处理、里程、完整率。旁白：`已写入 pending_write/problems.md：可下发2家，超速18条，轨迹2条。` 行数对不上则补读后**覆盖写同一文件**，不要另存。写入后自检：每家必须有 `##` 和至少一行 `|` 表；缺表则覆盖重写，禁止出卡。
4. **旁白纳入核对后出卡。** 缺 `problems.md`、或缺卡上任一家的一级标题、或任一家没有 `##`+表：禁止出卡。确认卡不放各家问题明细。不出推荐问。
5. **用户已确定。** 文档解析、点名全称或口语唯一命中：卡上全称再 `enterprise_resolve`（集合必须与卡一致），`enterpriseId` 用本次反查字符串。条件圈选：用出卡前 list 的 ID，按卡上全称对齐。一次 `Read pending_write/problems.md`。一次 `create(publish=true)`：`taskType` 必须等于卡上中文原值；任务级 `requirement` 用下方固定句，不要另写；每家 `items[].requirement` 为该一级标题下的 Markdown **原文**（不含 `# 企业全称` 行）。调用前再检：任一家缺少 `##` 或 `|` → 停止，禁止 create。禁止再读附件，禁止再 `Write`，禁止凭记忆改表，禁止把表压成摘要。创建失败且内容不变时可重试 create。

任务级 `requirement`（不进确认卡，create 必填）按类型原样使用，不要改写：

- 问题处置：`请按本任务所列问题核查原因、落实整改，并在完成时限前提交整改材料。`
- 通知：`请按通知要求办理并按时反馈。`
- 工作部署：`请按部署要求贯彻执行并按时反馈。`
- 材料报送：`请按报送清单准备材料并按时提交。`

会议/培训/材料报送：未给名单则先 `enterprise_list` 圈企业。旁白一句类型，仍写入同一 `problems.md`（各家一级标题 + 对应 `##` 节，不要整改三类表），再出卡。催办/通过/驳回：查到对象后各出一张确认卡。查询进度不出确认卡。

## 确认卡

顶层必须是对象，key 仅为 `title, summary, confirm_label, cancel_label, risk_note, fields`。禁止把 `fields` 当顶层或做成 JSON 字符串。只许下面这一套。`fields.length` 必须为 **6**。只替换 `value`、`summary` 中的 N/D，以及 `risk_note` 里的无法匹配家数。`taskType` 的 `value_type`、`options` 不得改。字段 key、label、顺序、`value_type`、`editable` 不得改。

```json
{
  "title": "确认立即下发",
  "summary": "将向9家企业立即下发，完成时限2026-09-26。",
  "confirm_label": "立即下发",
  "cancel_label": "取消",
  "risk_note": "立即下发后不可修改、不可删除。另有22家企业当前无法匹配，本次不会下发。",
  "fields": [
    { "key": "name", "label": "任务名称", "value": "9月12日疲劳驾驶/超速/轨迹异常问题整改", "value_type": "string", "editable": true },
    { "key": "taskType", "label": "任务类型", "value": "问题处置", "value_type": "enum", "editable": true, "options": ["通知", "工作部署", "问题处置", "材料报送"] },
    { "key": "deadlineDate", "label": "完成时限", "value": "2026-09-26", "value_type": "date", "editable": true },
    { "key": "needAudit", "label": "企业提交后需行业审核", "value": true, "value_type": "boolean", "editable": true },
    { "key": "enterpriseCount", "label": "可下发企业数", "value": "9家", "value_type": "string", "editable": false },
    { "key": "enterprises", "label": "可下发企业清单", "value": "甲运输有限公司、乙物流有限公司、丙客运有限公司", "value_type": "string", "editable": false }
  ]
}
```

- `summary` 只能是 `将向N家企业立即下发，完成时限D。` 这里的 N 必须等于 `enterpriseCount` 的可下发家数。
- 有无法匹配：`立即下发后不可修改、不可删除。另有M家企业当前无法匹配，本次不会下发。`；无则去掉后半句。M 不计入 `enterpriseCount`，也不出现在 `enterprises`。
- `N家`/`M家` 无空格。有时限时 `D` 为 `yyyy-MM-dd`；无时限时 `D` 为 `不限期`。`deadlineDate` 的 `value_type` 必须始终为 `date`，禁止改成 `string`，以便确认卡用日期选择器且用户可改。无时限时 `value` 为空字符串，禁止填「不限期」。确认后：值为 `yyyy-MM-dd` 则传入 `deadlineDate`；仍为空则不传。
- `enterpriseCount`、`enterprises` 只读。`enterprises` 仅为可下发全称 `join('、')`。`needAudit` 为 JSON 布尔。
- 禁止第七字段，禁止 `requirement` 进确认卡，禁止企业 ID 出现在 key/label。可下发名单按用户原始顺序去重。
- 确认后无 `taskType`、无 `enterpriseCount`、无 `enterprises` 禁止调用 create。

## 下发回执

成功后只输出 Markdown 两张表，禁止输出企业问题原文、任务 ID、车牌。未下发 0 家标题 `## ✅ 任务下发完成`，否则 `## ⚠️ 任务已下发（部分成功）`。结果表行序：已下发、未下发、任务类型、完成时限、行业审核、办理流程、问题构成、数据依据。任务类型用中文：通知 / 工作部署 / 问题处置 / 材料报送。问题构成最多 3 类，如 `超速10条、疲劳驾驶4条，共16条`。企业清单按原始顺序，超过 30 家只列前 30。末尾三句推荐问：有未下发为「谁还没交 / 催一下没交的企业 / 查看无法匹配的企业名单」；未下发 0 家第三句改为「查看任务进度」。出卡、等待确认、取消、失败时禁止推荐问。

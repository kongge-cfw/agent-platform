---
name: industry-dispatch-task
description: "行业监管账号向备案企业下发交通运输安全任务并跟踪办理。用户提到下发、发给企业、通知企业、整改、风险预警、事故隐患、超载、超速、疲劳驾驶、证照异常、车辆问题、人员问题、会议通知、培训、材料报送、催办、没交、审核、通过、驳回、任务进度或任务跟踪时使用；即使前一步是监测分析，只要下一步要对企业执行，也必须使用。"
---

# 行业任务下发

仅服务行业账号 `/office/task-track`。查企业只有两个 MCP：`enterprise_resolve`（营业执照全称精确反查）、`enterprise_list`（圈选名录；口语对话里才可用 `keyword` 查找）。只调用本文件列出的 MCP。`dispatch_task_search` 只查任务，不查企业。禁止 `dispatch_inbox_*`。禁止用 resolve 圈危货。禁止用 list 的 `keyword` 去圈全市/危货，也禁止用它解析文档里的企业名称。写入只走 `dispatch_task_create(publish=true)`。禁止 `publish=false`，禁止 `dispatch_task_issue`，禁止 `show_ui_card`。运行时名称带前缀时按短名匹配。多步下发、催办、通过、驳回必须用 `todo_write` 更新任务清单，见下文「任务清单」。

平台只注入本文件。Java 把 `items[].requirement` 展示在企业页「任务说明」；「问题详述」是另一字段，MCP 创建时会被清空，不要指望表格出现在那里。四列表必须写进 `items[].requirement`。问题处置先冻结 `problems`，确认后必须用脚本 `render` 成四列表再提交。禁止手写合计句（如「疲劳驾驶1次未处理、超速17次、轨迹完整率低于100%」）。禁止 `dispatch_items.json`。禁止 Read `scripts/validate_create_json.py`（会被截成半截函数）。根目录短脚本 `render.py` 找不到 Bash 路径时，允许 `read_skill_instruction(file="render.py")` 后 Write 到 `pending_write/render.py` 再执行。JSON 可以 Read；改 `pending_write/` 只用 Write 整文件，禁止 Edit。

## 规程裁定

1. **准优先于快。** 准备写入 `problems` 的原文出卡前必须读全；确认后禁止再读附件、禁止改写 facts，只允许脚本把 `problems` 渲成 `requirement`。
2. **只维护 `pending_write/create.json` 与 `allowed_ids.json`。** 这两个文件和 `submit.json` 一律用 **Write 整文件覆盖**，禁止 `Edit`（Edit 未先 Read 会直接失败）。带「汇总、合计、小计、总计」的加总行由 `check` 删除，不要为此重写。没有 `problems` 的企业也由 `check` 从 `items` 和 `enterpriseNames` 去掉，不要为此再 Write，也不要写进确认卡。文件中仍有车辆、驾驶员或企业事项的企业保留。其他校验失败才 Write 完整 create.json，不要打补丁。禁止为了通过校验而删除仍有问题明细的企业、`enterpriseId` 或分车/分人行。禁止 `dispatch_items.json`、`issues`、`fatigue`/`speed`/`track_issue` 合计文件。
3. **JSON 冻结明细，脚本校验并拼表。** 问题处置只写 `items[].problems`。出卡前 `check` 必须退出码 0；确认后 `render` 生成 `pending_write/submit.json`，再 `check-submit`，禁止手写 `requirement` 表格。车辆/人员表头固定为截图四列。
4. **一对象一行。** `problems` 每条必须是一个车辆、一个驾驶员，或一条企业事项。禁止概况、列表、建议句。带「汇总、合计、小计、总计」的加总行不写入；文件里没有车牌、没有姓名的事项写成 `ENTERPRISE`，不要因为同一家已有分车/分人就整段不写。禁止把各车各人次数加总后新造一条企业问题。误写入的加总行由 `check` 删除，不要删掉该企业或其他企业问题。不打算写入的内容不要读。
5. **每个附件只采集一轮。** 每个附件最多一次 inspect（只看表名、表头、行数）。该附件要进 `problems` 时，接着 `read_range` / `filter`（PDF/Word 按截断续读），直到工具不再截断。禁止再 inspect、禁止 `profile`、禁止读完再读一遍。`profile` 的 `top_values` 不能当全集或企业名单。不写死列名。企业名只从即将写入 `problems` 的原文抽取；禁止为凑名单或核对再打开不打算写入的材料。
6. **文档提到即下发。** 可下发企业在源材料中出现的问题，不论轻微、已处理、次数少、完整率高，全部写入 `problems`；仅原文明示无需处理/不纳入整改/仅供参考时省略。没有车牌、没有姓名的事项写成企业问题。带「汇总、合计、小计、总计」的加总行不要写入。
7. **禁止编造。** 企业名、车牌、姓名、时间、次数、里程、完整率必须来自原文。
8. **确认卡恰好 6 字段。** 任务名称、任务类型、完成时限、企业提交后需行业审核、可下发企业数、可下发企业清单，不能多不能少。
9. **问题处置只提交 `items`。** 禁止使用 `enterpriseIds`，否则企业会沿用任务要求。冻结阶段每个 item 必须有字符串 ID 和非空 `problems`；调用 MCP 时每个 item 必须有字符串 ID 和非空 Markdown `requirement`，不要把 `problems` 传给接口。
10. **文档用 resolve，口语才用 list.keyword。** 文档、Excel、PDF、粘贴名单里的全称一次 `enterprise_resolve`；条件圈选用 `enterprise_list` 且不传 keyword；keyword 只用于用户口语简称。先认企业，再只为可下发企业 Write 一次 `create.json`。禁止先写未匹配企业再整文件重写。每做完一步按「任务清单」更新 `todo_write`。

## 任务清单

多步下发、催办、通过、驳回用 `todo_write` 对齐界面进度。只查任务或单次检索不要建清单。

每次调用发送完整清单。文案确定后不要改字。同一时刻只有一项 `in_progress`。做完一步、调用下一步工具之前更新：刚完成的改为 `completed`，下一项改为 `in_progress`。`todo_write` 返回后立刻继续下一步，禁止把清单当最终回复，禁止在正文里复述清单。

问题处置下发固定六项。开始时第一项 `in_progress`，其余 `pending`：

1. 采集附件原文
2. 认企业并写 allowed_ids.json
3. 写 create.json
4. 脚本校验 create.json
5. 出确认卡
6. 确认后渲染并下发

没有附件时去掉第 1 项。非问题处置去掉用不到的采集、`create.json`、校验项，保留认企业、出确认卡、确认后执行。催办、通过、驳回只用三项：查对象、出确认卡、确认后执行。

出确认卡之前把「出确认卡」标为 `in_progress`，不要提前点亮下一项。用户确定后，先把出卡标 `completed`、下一项标 `in_progress`，再 render 或执行。下发或执行成功后，最后一项标 `completed`。取消或失败时，不要把未做的步骤标完成。

## 主路径

缺任务名时一句短问。未提时限通常不限期；重大事故隐患、立即整改、证照失效必须有明确时限。问题处置默认 `needAudit=true`。任务类型使用中文：通知、工作部署、问题处置、材料报送。

1. **采集将写入的原文。** 每个附件只采集一轮（裁定 5）。可下发名单只从这份原文抽全称，不要另开一份材料。
2. **认企业。** 必须在 Write `create.json` 之前完成。
   - 文档/附件名单/点名全称：一次 `enterprise_resolve`。仅 `found=true && enabled=true && matchCount=1` 可下发。
   - 条件圈选：一次 `enterprise_list`（不要 keyword），补齐全部分页。
   - 口语简称：`enterprise_list(keyword=用户原词)`；唯一启用命中后再 resolve。
   - 可下发为 0：禁止出卡、禁止 create。
   - 立刻 Write `pending_write/allowed_ids.json`，值为可下发 `enterpriseId` 字符串数组，例如 `["1987654321098765432"]`。禁止把表格行号写成 ID。
3. **只为可下发企业 Write 一次 `pending_write/create.json`。** 禁止先写入未匹配企业再整文件重写。顶层只能是下列字段；无时限时省略 `deadlineDate`。`enterpriseNames` 只和 `items` 一起写入，供 `check` 使用，禁止拿它或 resolve 命中名单填确认卡。`unmatchedCount` 只供确认卡 `risk_note`。问题处置每个 item 只放 `enterpriseId` + `problems` 数组，不要写 `requirement`。

```json
{
  "name": "9月12日疲劳驾驶/超速/轨迹异常问题整改",
  "taskType": "问题处置",
  "requirement": "请按本任务所列问题核查原因、落实整改，并在完成时限前提交整改材料。",
  "publish": true,
  "needAudit": true,
  "deadlineDate": "2026-09-26",
  "enterpriseNames": ["侯马经济开发区盛达聚危货运输有限公司"],
  "unmatchedCount": 0,
  "items": [
    {
      "enterpriseId": "1987654321098765432",
      "problems": [
        {"kind": "ENTERPRISE", "occurredAt": "2026-09-12", "problemCategory": "安全", "problemType": "超速", "fact": "超速12次，已处理10次"},
        {"kind": "VEHICLE", "occurredAt": "2026-09-12", "vehiclePlate": "晋L68222", "problemType": "超速", "fact": "超速7次，已处理7次"},
        {"kind": "VEHICLE", "occurredAt": "2026-09-12", "vehiclePlate": "晋LB1516", "problemType": "超速", "fact": "超速1次，已处理1次"},
        {"kind": "VEHICLE", "occurredAt": "2026-09-12", "vehiclePlate": "晋LB1516", "problemType": "轨迹异常", "fact": "总里程163.21km，完整率74.99%"},
        {"kind": "DRIVER", "occurredAt": "2026-09-12", "driverName": "张三", "problemType": "疲劳驾驶", "fact": "疲劳驾驶1次，已处理1次"}
      ]
    }
  ]
}
```

问题处置 JSON 硬约束：

- `publish` 必须为 true；`items.length == enterpriseNames.length`，顺序一致；ID 必须是 resolve/list 返回的字符串。
- 每个 item 只能有 `enterpriseId`、`problems`；禁止 `issues`、`summary`、`name`、手写 `requirement`。
- `problems` 必须是对象数组，至少 1 条。`kind` 只能是 `VEHICLE` / `DRIVER` / `ENTERPRISE`。
- `VEHICLE`：`vehiclePlate` 必填且只能有一个车牌；不要填 `driverName`。
- `DRIVER`：`driverName` 必填且只能有一个姓名，必须是源行里的具体人名。源行没有姓名就不要写 `DRIVER`，禁止把企业级次数改写成驾驶员。`driverName` 禁止使用汇总、合计、小计、总计、企业、公司，也禁止填企业全称。不要填 `vehiclePlate`。
- `ENTERPRISE`：必须有 `problemCategory`、`problemType`、`fact`。文件里没有车牌、没有姓名的事项写成这里，即使同一家已有分车/分人。禁止把各车次数加总后新造一条。带「汇总、合计、小计、总计」的加总行不要写；若仍写入，`check` 会删掉这些行并写回，企业数、分车/分人和其他企业问题不变。不要为此再 Write `create.json`。
- `occurredAt` 无则填 `—`；`problemType`、`fact` 必填，事实保留原文次数、已处理、里程、完整率。
- 同一车牌或同一人的多种问题分成多条。禁止「超速17次」「疲劳驾驶1次（未处理）」这种无对象合计。

4. **脚本校验 `create.json`，禁止凭记忆检查。** 出卡前必须 Bash 跑 `check`，退出码必须为 0。通过时标准输出有两行：`可下发企业数=`、`可下发企业清单=`。这两行是确认卡家数和名单的唯一来源。`check` 可能已经删掉没有问题明细的企业并写回文件；禁止再 Read `create.json`，也禁止用写入前记住的 `enterpriseNames`、resolve 命中数、或按 `、` 重新计数。禁止 Read `scripts/validate_create_json.py`。会话里脚本常在 `skills/.seed/`，按顺序试，找到即停：

```text
python3 skills/.seed/industry-dispatch-task/validate.py check pending_write/create.json --allowed-ids pending_write/allowed_ids.json
python3 skills/industry-dispatch-task/validate.py check pending_write/create.json --allowed-ids pending_write/allowed_ids.json
```

都失败则 `find skills /workspace/skills . -name 'validate.py' -o -name 'render.py' | head -5`。仍没有：`read_skill_instruction(skill_id="industry-dispatch-task", file="render.py")`，Write 到 `pending_write/render.py`。退出码非 0：错误里出现「企业合计」时，再跑一次同一条 check，不要 Write。其他错误才 Write 完整 `create.json` 后重跑，重写时企业数、`enterpriseId`、分车/分人一条不许少。禁止 Edit，禁止出卡。
5. **出确认卡。** `enterpriseCount` 只能是 `可下发企业数=` 后面的整数加上「家」，例如输出 `可下发企业数=11` 就填 `11家`。`enterprises` 只能原样粘贴 `可下发企业清单=` 等号后面的整段，不增删企业、不重排。`summary` 里的 N 必须是同一个整数。三者有一处对不上就禁止出卡。禁止把 `check` 删掉的企业补回。`enterpriseNames` 比 `items` 长时 `check` 失败，禁止出卡。无法匹配数来自 `unmatchedCount`。确认卡不展示企业明细。
6. **用户已确定。** 禁止 Read `create.json`，禁止 Write `create.json`，禁止改 `problems`。一次 `render`，把卡上 `name`、`taskType`、`needAudit`、`deadlineDate` 传给脚本；脚本只覆盖这四项。`render` 退出码必须为 0（内部已含 `check` 与 `check-submit`），不要再单独跑 `check-submit`。有时限传 `yyyy-MM-dd`；无时限传空字符串。

```text
python3 skills/.seed/industry-dispatch-task/validate.py render pending_write/create.json pending_write/submit.json --allowed-ids pending_write/allowed_ids.json --name "卡上任务名称" --task-type "问题处置" --need-audit true --deadline "2026-09-26"
```

无时限时 `--deadline ""`。路径不存在则改 `skills/industry-dispatch-task/validate.py`。若 `validate.py` 不存在，改跑：

```text
python3 pending_write/render.py render pending_write/create.json pending_write/submit.json --name "卡上任务名称" --task-type "问题处置" --need-audit true --deadline "2026-09-26"
```

没有 `pending_write/render.py` 时先 `read_skill_instruction(file="render.py")` 再 Write 该短文件。`submit.json` 每个 `items[].requirement` 必须含 `##` 和 `| --- |` 四列表。禁止把「疲劳驾驶1次未处理、超速17次」或「【车辆问题】车牌：事实」写进 requirement。没有表格禁止 `dispatch_task_create`。

`render` 退出码为 0 后调用一次 `dispatch_task_create`。`items[].requirement` 必须原样使用 `submit.json` 里的四列表，必须含 `##` 和 `| --- |`。禁止改成「【车辆问题】车牌：事实」或任何一句话。企业数必须等于 `submit.json` 的 items 条数，禁止少传一家。未调用、工具报错、或参数里没有四列表时，只写「任务未创建」，禁止输出下发回执。禁止再 resolve、再读附件或改写 facts。取消则不调 MCP。

脚本按 kind 分组渲染（顺序：企业问题 → 车辆问题 → 驾驶员问题；空组不输出；组内保持原数组顺序）。车辆/人员必须是下面这种四列表，同一车牌或同一人多种问题分行：

```text
VEHICLE →
## 车辆问题

| 发生时间 | 车牌号 | 问题类型 | 事实 |
| --- | --- | --- | --- |
| {occurredAt} | {vehiclePlate} | {problemType} | {fact} |

DRIVER →
## 驾驶员问题

| 发生时间 | 姓名 | 问题类型 | 事实 |
| --- | --- | --- | --- |
| {occurredAt} | {driverName} | {problemType} | {fact} |

ENTERPRISE →
## 企业问题

| 发生时间 | 问题类别 | 问题事项 | 事实 |
| --- | --- | --- | --- |
| {occurredAt} | {problemCategory} | {problemType} | {fact} |
```

多组之间空一行。单元格里的 `|` 换成 `｜`。得到的字符串原样写入 `items[].requirement`。

任务级 `requirement`（不进确认卡，create 必填）按类型原样使用，不要改写：

- 问题处置：`请按本任务所列问题核查原因、落实整改，并在完成时限前提交整改材料。`
- 通知：`请按通知要求办理并按时反馈。`
- 工作部署：`请按部署要求贯彻执行并按时反馈。`
- 材料报送：`请按报送清单准备材料并按时提交。`

会议/培训/材料报送：未给名单则先 `enterprise_list` 圈企业，仍冻结在 `create.json`。非问题处置的 item 直接写短 Markdown 到 `requirement`，不要 `problems`，不套整改三类表。催办/通过/驳回：查到对象后各出一张确认卡。查询进度不出确认卡。

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

- `summary` 只能是 `将向N家企业立即下发，完成时限D。` 这里的 N 必须是 `可下发企业数=` 后面的整数，并与 `enterpriseCount` 的数字相同。禁止另数名单。
- 有无法匹配：`立即下发后不可修改、不可删除。另有M家企业当前无法匹配，本次不会下发。`；无则去掉后半句。M 不计入 `enterpriseCount`，也不出现在 `enterprises`。
- `N家`/`M家` 无空格。有时限时 `D` 为 `yyyy-MM-dd`；无时限时 `D` 为 `不限期`。`deadlineDate` 的 `value_type` 必须始终为 `date`，禁止改成 `string`，以便确认卡用日期选择器且用户可改。无时限时 `value` 为空字符串，禁止填「不限期」。确认后：值为 `yyyy-MM-dd` 则传入 `deadlineDate`；仍为空则不传。
- `enterpriseCount`、`enterprises` 只读。`enterpriseCount` 由 `可下发企业数=` 的整数加「家」得到；`enterprises` 原样粘贴 `可下发企业清单=` 等号后的整段。禁止按 resolve 结果、用户原始顺序或顿号重数。`needAudit` 为 JSON 布尔。
- 禁止第七字段，禁止 `requirement` 进确认卡，禁止企业 ID 出现在 key/label。
- 确认后无 `taskType`、无 `enterpriseCount`、无 `enterprises` 禁止调用 create。

## 下发回执

只有本轮 `dispatch_task_create` 成功返回后才输出回执。第一行写「任务编号：」加工具返回的 `taskId`，禁止编造。没有返回、工具报错或未调用时，只写「任务未创建」，禁止「任务下发完成」「任务已成功下发」「已下发企业数」。已下发家数以工具返回为准，禁止用确认卡上的企业数填写。

成功后只输出 Markdown 两张表，禁止输出企业问题原文、车牌。未下发 0 家标题 `## ✅ 任务下发完成`，否则 `## ⚠️ 任务已下发（部分成功）`。结果表行序：已下发、未下发、任务类型、完成时限、行业审核、办理流程、问题构成、数据依据。任务类型用中文：通知 / 工作部署 / 问题处置 / 材料报送。问题构成最多 3 类，如 `超速10条、疲劳驾驶4条，共16条`。企业清单按原始顺序，超过 30 家只列前 30。末尾三句推荐问：有未下发为「谁还没交 / 催一下没交的企业 / 查看无法匹配的企业名单」；未下发 0 家第三句改为「查看任务进度」。出卡、等待确认、取消、失败时禁止推荐问。

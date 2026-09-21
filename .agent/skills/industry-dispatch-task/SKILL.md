---
name: industry-dispatch-task
description: "行业监管账号向备案企业下发交通运输安全任务并跟踪办理。用户提到下发、发给企业、通知企业、整改、风险预警、事故隐患、超载、超速、疲劳驾驶、证照异常、车辆问题、人员问题、会议通知、培训、材料报送、催办、没交、审核、通过、驳回、任务进度或任务跟踪时使用；即使前一步是监测分析，只要下一步要对企业执行，也必须使用。"
---

# 行业任务下发

仅服务行业账号 `/office/task-track`。查企业只有两个 MCP：`enterprise_resolve`（营业执照全称精确反查）、`enterprise_list`（圈选名录；口语对话里才可用 `keyword` 查找）。只调用本文件列出的 MCP。`dispatch_task_search` 只查任务，不查企业。禁止 `dispatch_inbox_*`。禁止用 resolve 圈危货。禁止用 list 的 `keyword` 去圈全市/危货，也禁止用它解析文档里的企业名称。写入只走 `dispatch_task_create(publish=true)`。禁止 `publish=false`，禁止 `dispatch_task_issue`，禁止 `show_ui_card`，禁止 `todo_write` 串主路径。运行时名称带前缀时按短名匹配。

平台只注入本文件。Java 把 `items[].requirement` 展示在企业页「任务说明」；「问题详述」是另一字段，MCP 创建时会被清空，不要指望表格出现在那里。四列表必须写进 `items[].requirement`。问题处置先冻结 `problems`，确认后必须用脚本 `render` 成四列表再提交。禁止手写合计句（如「疲劳驾驶1次未处理、超速17次、轨迹完整率低于100%」）。禁止 `dispatch_items.json`。禁止 Read `scripts/validate_create_json.py`（会被截成半截函数）。根目录短脚本 `render.py` 找不到 Bash 路径时，允许 `read_skill_instruction(file="render.py")` 后 Write 到 `pending_write/render.py` 再执行。JSON 可以 Read；改 `pending_write/` 只用 Write 整文件，禁止 Edit。

## 规程裁定

1. **准优先于快。** 出卡前读全源明细；确认后禁止再读附件、禁止改写 facts，只允许脚本把 `problems` 渲成 `requirement`。
2. **只维护 `pending_write/create.json` 与 `allowed_ids.json`。** 这两个文件和 `submit.json` 一律用 **Write 整文件覆盖**，禁止 `Edit`（Edit 未先 Read 会直接失败）。检查失败也是 Write 完整 create.json，不要打补丁。禁止 `dispatch_items.json`、`issues`、`fatigue`/`speed`/`track_issue` 合计文件。
3. **JSON 冻结明细，脚本校验并拼表。** 问题处置只写 `items[].problems`。出卡前 `check` 必须退出码 0；确认后 `render` 生成 `pending_write/submit.json`，禁止手写 `requirement` 表格。车辆/人员表头固定为截图四列。
4. **一对象一行。** `problems` 每条必须是一个车辆或一个驾驶员（或一条企业事项）。禁止概况、合计、列表、建议句。
5. **企业合计页只用于核对，不得下发。** 源材料有分车/分人明细时，只写对象级明细。企业问题只收制度、台账、许可，或全文确实没有车牌和姓名的事项。
6. **文档提到即下发。** 可下发企业在源材料中出现的问题，不论轻微、已处理、次数少、完整率高，全部写入 `problems`；仅原文明示无需处理/不纳入整改/仅供参考时省略。
7. **禁止编造。** 企业名、车牌、姓名、时间、次数、里程、完整率必须来自原文。
8. **确认卡恰好 6 字段。** 任务名称、任务类型、完成时限、企业提交后需行业审核、可下发企业数、可下发企业清单，不能多不能少。
9. **问题处置只提交 `items`。** 禁止使用 `enterpriseIds`，否则企业会沿用任务要求。冻结阶段每个 item 必须有字符串 ID 和非空 `problems`；调用 MCP 时每个 item 必须有字符串 ID 和非空 Markdown `requirement`，不要把 `problems` 传给接口。
10. **文档用 resolve，口语才用 list.keyword。** 文档、Excel、PDF、粘贴名单里的全称一次 `enterprise_resolve`；条件圈选用 `enterprise_list` 且不传 keyword；keyword 只用于用户口语简称。

## 主路径

缺任务名时一句短问。未提时限通常不限期；重大事故隐患、立即整改、证照失效必须有明确时限。问题处置默认 `needAudit=true`。任务类型使用中文：通知、工作部署、问题处置、材料报送。

1. **认企业。**
   - 文档/附件名单/点名全称：一次 `enterprise_resolve`。仅 `found=true && enabled=true && matchCount=1` 可下发。
   - 条件圈选：一次 `enterprise_list`（不要 keyword），补齐全部分页。
   - 口语简称：`enterprise_list(keyword=用户原词)`；唯一启用命中后再 resolve。
   - 可下发为 0：禁止出卡、禁止 create。
   - 立刻 Write `pending_write/allowed_ids.json`，值为可下发 `enterpriseId` 字符串数组，例如 `["1987654321098765432"]`。禁止把合计表里的行号写成 ID。
2. **读全源明细。** Excel/PDF/Word 截断必须续读。先按企业，再按车辆/驾驶员切分。禁止从企业合计页生成正文。
3. **生成并写入 `pending_write/create.json`。** 顶层只能是下列字段；无时限时省略 `deadlineDate`。`enterpriseNames` 与 `unmatchedCount` 只供确认卡使用。问题处置每个 item 只放 `enterpriseId` + `problems` 数组，不要写 `requirement`。

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
- `DRIVER`：`driverName` 必填且只能有一个姓名；不要填 `vehiclePlate`。
- `ENTERPRISE`：必须有 `problemCategory`、`problemType`、`fact`；有分车/分人时不要把合计写进这里。
- `occurredAt` 无则填 `—`；`problemType`、`fact` 必填，事实保留原文次数、已处理、里程、完整率。
- 同一车牌或同一人的多种问题分成多条。禁止「超速17次」「疲劳驾驶1次（未处理）」这种无对象合计。

4. **脚本校验 `create.json`，禁止凭记忆检查。** 先 Read `pending_write/create.json` 核对 `problems` 与源明细行数；再用 Bash 执行。禁止 Read `scripts/validate_create_json.py`。会话里脚本常在 `skills/.seed/`，按顺序试，找到即停：

```text
python3 skills/.seed/industry-dispatch-task/validate.py check pending_write/create.json --allowed-ids pending_write/allowed_ids.json
python3 skills/industry-dispatch-task/validate.py check pending_write/create.json --allowed-ids pending_write/allowed_ids.json
```

都失败则 `find skills /workspace/skills . -name 'validate.py' -o -name 'render.py' | head -5`。仍没有：`read_skill_instruction(skill_id="industry-dispatch-task", file="render.py")`，Write 到 `pending_write/render.py`。出卡前至少要能跑 `check` 或确认 `create.json` 的 `problems` 为一车/一人一条。退出码非 0：Write 完整 `create.json` 后重跑，禁止 Edit，禁止出卡。没有四列表禁止 create。
5. **出确认卡。** `enterpriseCount=items.length`，`enterprises=enterpriseNames.join('、')`，无法匹配数来自 `unmatchedCount`。确认卡不展示企业明细。
6. **用户已确定。** 用卡上 name/taskType/deadlineDate/needAudit 更新后 **Write 完整** `create.json`（禁止 Edit）。然后：

```text
python3 skills/.seed/industry-dispatch-task/validate.py render pending_write/create.json pending_write/submit.json --allowed-ids pending_write/allowed_ids.json
python3 skills/.seed/industry-dispatch-task/validate.py check-submit pending_write/submit.json
```

若 `validate.py` 不存在，改跑：

```text
python3 pending_write/render.py render pending_write/create.json pending_write/submit.json
```

没有 `pending_write/render.py` 时先 `read_skill_instruction(file="render.py")` 再 Write 该短文件。`submit.json` 每个 `items[].requirement` 必须含 `##` 和 `| --- |` 四列表。禁止把「疲劳驾驶1次未处理、超速17次」这种合计句写入 requirement。没有表格禁止 `dispatch_task_create`。

Read `pending_write/submit.json` 一次 `dispatch_task_create`，只传其中字段，禁止传 `enterpriseIds`，禁止改 `items[].requirement`。禁止再 resolve、再读附件或改写 facts。取消则不调 MCP。

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

- `summary` 只能是 `将向N家企业立即下发，完成时限D。` 这里的 N 必须等于 `enterpriseCount` 的可下发家数。
- 有无法匹配：`立即下发后不可修改、不可删除。另有M家企业当前无法匹配，本次不会下发。`；无则去掉后半句。M 不计入 `enterpriseCount`，也不出现在 `enterprises`。
- `N家`/`M家` 无空格。有时限时 `D` 为 `yyyy-MM-dd`；无时限时 `D` 为 `不限期`。`deadlineDate` 的 `value_type` 必须始终为 `date`，禁止改成 `string`，以便确认卡用日期选择器且用户可改。无时限时 `value` 为空字符串，禁止填「不限期」。确认后：值为 `yyyy-MM-dd` 则传入 `deadlineDate`；仍为空则不传。
- `enterpriseCount`、`enterprises` 只读。`enterprises` 仅为可下发全称 `join('、')`。`needAudit` 为 JSON 布尔。
- 禁止第七字段，禁止 `requirement` 进确认卡，禁止企业 ID 出现在 key/label。可下发名单按用户原始顺序去重。
- 确认后无 `taskType`、无 `enterpriseCount`、无 `enterprises` 禁止调用 create。

## 下发回执

成功后只输出 Markdown 两张表，禁止输出企业问题原文、任务 ID、车牌。未下发 0 家标题 `## ✅ 任务下发完成`，否则 `## ⚠️ 任务已下发（部分成功）`。结果表行序：已下发、未下发、任务类型、完成时限、行业审核、办理流程、问题构成、数据依据。任务类型用中文：通知 / 工作部署 / 问题处置 / 材料报送。问题构成最多 3 类，如 `超速10条、疲劳驾驶4条，共16条`。企业清单按原始顺序，超过 30 家只列前 30。末尾三句推荐问：有未下发为「谁还没交 / 催一下没交的企业 / 查看无法匹配的企业名单」；未下发 0 家第三句改为「查看任务进度」。出卡、等待确认、取消、失败时禁止推荐问。

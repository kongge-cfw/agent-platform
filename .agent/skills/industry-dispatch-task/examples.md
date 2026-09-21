# 示例

规程以 SKILL.md 为准。所有下发内容只冻结在 `pending_write/create.json`。问题处置冻结结构化 `problems`；出卡前脚本 `check`，确认后脚本 `render` 成四列表，禁止手写 Markdown 表。

## 问题处置

用户上传超速、疲劳驾驶、轨迹异常明细，要求给可匹配企业下发整改：

1. 读全明细，一次 `enterprise_resolve` 全称匹配，并写入 `pending_write/allowed_ids.json`。
2. 每个可下发企业生成一个 item。只写 `enterpriseId` + `problems` 对象数组，一车/一人一条。同一车牌多种问题分成多条。
3. Write `pending_write/create.json`（禁止 Edit）。
4. Bash：`python3 skills/.seed/industry-dispatch-task/validate.py check pending_write/create.json --allowed-ids pending_write/allowed_ids.json`（路径不存在则改 `skills/industry-dispatch-task/validate.py`，或 `find skills /workspace/skills -name validate_create_json.py`）。禁止 Read `.py`。退出码必须为 0。
5. 出 6 字段确认卡。
6. 用户确定后 Write 完整 create.json 写入卡上字段（禁止 Edit），`render` 出 `pending_write/submit.json`，`check-submit` 通过后再提交。

```json
{
  "name": "9月12日运输安全问题整改",
  "taskType": "问题处置",
  "requirement": "请按本任务所列问题核查原因、落实整改，并在完成时限前提交整改材料。",
  "publish": true,
  "needAudit": true,
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

脚本渲染后的车辆/人员表必须是：

```text
## 车辆问题

| 发生时间 | 车牌号 | 问题类型 | 事实 |
| --- | --- | --- | --- |
| 2026-09-12 | 晋L68222 | 超速 | 超速7次，已处理7次 |
| 2026-09-12 | 晋LB1516 | 超速 | 超速1次，已处理1次 |
| 2026-09-12 | 晋LB1516 | 轨迹异常 | 总里程163.21km，完整率74.99% |

## 驾驶员问题

| 发生时间 | 姓名 | 问题类型 | 事实 |
| --- | --- | --- | --- |
| 2026-09-12 | 张三 | 疲劳驾驶 | 疲劳驾驶1次，已处理1次 |
```

## 多个问题维度

同一企业的 `problems` 可混放 `ENTERPRISE` / `VEHICLE` / `DRIVER`。拼表时按企业问题、车辆问题、驾驶员问题分组；空组不输出。同一车牌或同一人的多种问题分成多条对象。

## 禁止

以下都不能进入 `problems`，脚本 `check` 会失败：

```text
1. 疲劳驾驶1次（未处理）
2. 超速17次
3. 轨迹完整率低于100%
```

```json
[
  {"enterpriseId":"5","name":"某公司","fatigue":1,"speed":17,"track_issue":true}
]
```

```json
{"issues": ["疲劳驾驶1次（未处理）", "超速17次"]}
```

它们是企业合计概况，不是一车/一人一条的 `problems`。

## 部分企业无法匹配

25 家全称 resolve 后只有 2 家可下发：

- `enterpriseNames` 和 `items` 只放 2 家。
- `unmatchedCount=23`。
- 确认卡家数为 2 家，风险提示写另有 23 家无法匹配。
- 0 家可下发时不写 JSON、不出卡、不调用 create。

## 会议通知

仍使用 `create.json`，但 `taskType=通知`。每个 item 直接写短 Markdown 到 `requirement`，不要 `problems`，不套问题处置表格。

## 口语简称

用户口语说「安达危运」时才使用 `enterprise_list(keyword)`。唯一启用命中后 resolve 得到 ID，再冻结 JSON。名称来自附件时必须直接 `enterprise_resolve`。

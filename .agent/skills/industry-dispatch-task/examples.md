# 示例

规程以 SKILL.md 为准。所有下发内容只冻结在 `pending_write/create.json`。问题处置冻结结构化 `problems`，不要手写 Markdown 表；确认后按 SKILL.md 模板拼成 `requirement` 再提交。

## 问题处置

用户上传超速、疲劳驾驶、轨迹异常明细，要求给可匹配企业下发整改：

1. 读全明细，一次 `enterprise_resolve` 全称匹配。
2. 每个可下发企业生成一个 item。只写 `enterpriseId` + `problems` 对象数组，一车/一人一条。
3. Write `pending_write/create.json`，再 Read 检查每条 `problems` 及源明细行数。
4. 出 6 字段确认卡。
5. 用户确定后 Read JSON，剔除 `enterpriseNames`、`unmatchedCount`，把 `problems` 拼成 Markdown 表写入 `requirement` 后删除 `problems`，再提交 `items`。

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
        {"kind": "VEHICLE", "occurredAt": "2026-09-12", "vehiclePlate": "晋LS0715", "problemType": "轨迹异常", "fact": "总里程530.25km，完整率97.69%"}
      ]
    }
  ]
}
```

上面这份 JSON 更容易生成。禁止在冻结文件里写 `requirement` 的 Markdown 管道表或把对象数组再 `JSON.stringify` 成字符串。提交 MCP 时才按模板拼成：

```text
## 车辆问题

| 发生时间 | 车牌号 | 问题类型 | 事实 |
| --- | --- | --- | --- |
| 2026-09-12 | 晋L68222 | 超速 | 超速7次，已处理7次 |
| 2026-09-12 | 晋LS0715 | 轨迹异常 | 总里程530.25km，完整率97.69% |
```

## 多个问题维度

同一企业的 `problems` 可混放 `ENTERPRISE` / `VEHICLE` / `DRIVER`。拼表时按企业问题、车辆问题、驾驶员问题分组；空组不输出。同一车牌或同一人的多种问题分成多条对象。

## 禁止

以下都不能进入 `problems`，也不能作为提交给 MCP 的 `items[].requirement`：

```text
1. 疲劳驾驶1次（未处理）
2. 超速17次
3. 轨迹完整率低于100%
```

```json
{"issues": ["疲劳驾驶1次（未处理）", "超速17次"]}
```

```markdown
## 车辆问题

- 晋L68222超速7次
- 晋LS0715轨迹完整率97.69%
```

它们是概况、摘要数组或 Markdown 列表，不是一对象一行的 `problems`。

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

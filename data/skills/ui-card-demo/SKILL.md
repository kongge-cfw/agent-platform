---
name: 对话卡片演示验收
description: 验收平台演示对话卡片 platform_demo_confirm。用户提到测试对话卡片、演示确认卡、弹出 UI 卡片、show_ui_card、【UI卡片】、iframe 演示卡时使用。仅用于同域演示，不写业务库。
enabled: true
---

# 对话卡片演示验收

用已登记卡种 `platform_demo_confirm` 走通：`show_ui_card` → iframe 出卡 → `【UI卡片】` 回执。本技能只做验收，禁止写业务库。

## 何时启用

用户说「测试对话卡片」「弹出演示确认卡」「验收 UI 卡片」「试试 show_ui_card」或点名本技能时，立即按下面步骤执行。禁止改用 markdown 表格、编造 HTML 或自己拼 URL。

## 前置

1. 本轮必须已绑定 **show_ui_card**。未绑定则只说明：请在智能体版本「工具能力」勾选 `show_ui_card`，然后不要假装已经出卡。
2. 只传已登记的 `card_key`，禁止传 URL / HTML。

## 出卡

调用 **show_ui_card**：

| 参数 | 值 |
|---|---|
| `card_key` | `platform_demo_confirm` |
| `title` | `平台演示确认卡` |
| `actions` | `["confirm","reject"]` |
| `data` | 用下面示例；用户补充的字段可以覆盖 |

```json
{
  "demo": true,
  "summary": "这是平台同域演示卡，用于验收对话卡片闭环。",
  "order_id": "DEMO-001",
  "amount": 128.5
}
```

工具返回 `awaiting_user` 后必须停止，等待用户在卡片上点确认或驳回。未收到回执前，禁止声称已展示完毕或已写入成功。

## 回执后

收到以 `【UI卡片】` 开头的消息后，按 `action` 处理：

- `confirm`：用一两句话确认用户已确认演示数据（可复述 `payload` 要点）。禁止调用写入类 HTTP / MCP / SQL 工具。
- `reject`：用一两句话确认已驳回。禁止写库，禁止再次弹出同一张卡。
- 其他动作：只按 payload 文字继续，禁止写库。

同一 `card_key` 在用户未提供新数据、也未明确要求再看一遍前，不要连续弹出。

## 红线

- 禁止把演示卡当成真实业务单据去改库。
- 禁止用 `ask_user_question` 或 `request_user_confirmation` 替代本演示卡。
- 禁止猜测其他未登记的 `card_key`。

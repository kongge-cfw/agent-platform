# NanZi MCP 用户身份接入指南

本文面向需要接收 NanZi 用户身份的自有 MCP。用户身份传递是 MCP 级别的可选开关：只有某个 MCP 开启后，NanZi 才会发送 `X-Nanzi-User-Context`；未开启的 MCP 完全沿用原有固定 Header 调用方式。

开启后 **只发明文 JSON Header**，不加密、不加签、不验签，也不使用 Audience / Issuer / JWKS。

## 1. MCP 级配置

在 MCP 管理页打开 **「开启用户身份传递」** 并保存。Authorization Bearer Token 是否配置与身份传递相互独立。

不同 MCP 不共享固定 Authorization Bearer Token。平台 MCP 由管理员维护，用户 MCP 由所属用户维护。

## 2. 请求约定

开启后，业务 MCP 收到：

```http
Authorization: Bearer <该 MCP 的 Token 值，如已配置>
X-Nanzi-User-Context: <明文 JSON>
X-Request-ID: <request-id>
```

未开启时只收到原有认证 Header，不会发送用户身份。用户身份不放在工具 `arguments` 中。

`X-Nanzi-User-Context` 示例：

```json
{
  "user_id": "123",
  "user_name": "zhangsan",
  "real_name": "张三",
  "role": "user",
  "is_admin": false,
  "dept_code": "sales",
  "org_path": "/集团/销售部",
  "custom_attributes": {
    "employee_level": "L3",
    "region_code": "east"
  },
  "agent_id": "agent-sales-assistant",
  "agent_version_id": "agent-version-2026-01",
  "agent_name": "销售助手",
  "request_id": "req-20260901-001"
}
```

password、token、api_key、authorization、cookie、secret、private_key、session_token 等密钥类字段会被过滤。`custom_attributes` 来自用户资料 `extra_data`。

## 3. 业务 MCP 如何处理

1. 如果配置了 Authorization，先按原方式校验 Bearer Token。
2. 读取 `X-Nanzi-User-Context`，`JSON.parse` 后用 `user_id` 关联业务用户。
3. 用 `X-Request-ID` / `request_id` 关联两侧日志。
4. 业务权限、租户隔离仍由业务 MCP 自己判断。

Python 示例：

```python
import json
import hmac

from starlette.requests import Request


MCP_FIXED_AUTHORIZATION_BEARER_TOKEN = "从当前 MCP 的 Secret 读取"


def current_nanzi_user(request: Request) -> dict:
    authorization = request.headers.get("Authorization") or ""
    expected = f"Bearer {MCP_FIXED_AUTHORIZATION_BEARER_TOKEN}"
    if MCP_FIXED_AUTHORIZATION_BEARER_TOKEN and not hmac.compare_digest(authorization, expected):
        raise PermissionError("invalid authorization")

    raw = request.headers.get("X-Nanzi-User-Context") or ""
    payload = json.loads(raw)
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise PermissionError("missing user_id")
    return payload
```

在 NanZi 的 MCP 工具测试台中点击“运行测试”时，也会按当前登录用户发送明文身份。测试结果只显示 `X-Nanzi-User-Context: ********`，完整 JSON 不返回浏览器。

"""Extract readable messages from LLM provider HTTP/API failures."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse


def _message_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("msg")
        code = error.get("code") or error.get("type")
        if message:
            text = str(message).strip()
            if code and str(code).strip():
                return f"{text}（{code}）"
            return text
    if isinstance(error, str) and error.strip():
        return error.strip()

    for key in ("message", "msg", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    code = payload.get("code")
    message = payload.get("message")
    if code and message and str(message).strip():
        return f"{str(message).strip()}（{code}）"
    return None


def _message_from_response_body(body: str) -> str | None:
    text = (body or "").strip()
    if not text:
        return None
    try:
        return _message_from_payload(json.loads(text))
    except json.JSONDecodeError:
        if len(text) > 500:
            text = f"{text[:499].rstrip()}…"
        return text


def _format_http_status_message(status_code: int, detail: str | None, url: str | None) -> str:
    host = ""
    if url:
        parsed = urlparse(url)
        host = parsed.netloc or url
    prefix = f"模型 API 返回 HTTP {status_code}"
    if host:
        prefix = f"{prefix}（{host}）"
    if detail:
        return f"{prefix}：{detail}"
    return prefix


def extract_provider_exception_message(exc: BaseException) -> str | None:
    """Return a user-facing provider error summary when the exception carries one."""

    try:
        import httpx
    except ImportError:
        httpx = None  # type: ignore[assignment]

    if httpx is not None:
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            detail = _message_from_response_body(response.text)
            url = str(response.request.url) if response.request else None
            return _format_http_status_message(response.status_code, detail, url)

        if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
            return "连接模型服务超时，请检查网络或稍后重试"

        if isinstance(exc, httpx.ConnectError):
            message = str(exc).strip()
            if message:
                return f"无法连接模型服务：{message}"
            return "无法连接模型服务，请检查网络或 API Base URL"

    body = getattr(exc, "body", None)
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8", errors="replace")
        if isinstance(body, str):
            detail = _message_from_response_body(body)
        else:
            detail = _message_from_payload(body)
        status_code = getattr(exc, "status_code", None)
        if detail:
            if status_code is not None:
                return _format_http_status_message(int(status_code), detail, None)
            return detail

    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip() and message.strip() != str(exc).strip():
        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            return _format_http_status_message(int(status_code), message.strip(), None)
        return message.strip()

    return None

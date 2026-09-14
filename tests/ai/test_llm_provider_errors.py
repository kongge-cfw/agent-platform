import httpx

from app.services.ai.llm_provider_errors import extract_provider_exception_message
from app.services.ai.multimodal_support import format_execution_error, unwrap_exception_message


def test_extract_http_status_error_openai_style_body():
    request = httpx.Request(
        "POST",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "tool_choice is unsupported with this model",
                "type": "invalid_request_error",
                "code": "invalid_parameter",
            }
        },
        request=request,
    )
    exc = httpx.HTTPStatusError("client error", request=request, response=response)

    message = extract_provider_exception_message(exc)

    assert "HTTP 400" in message
    assert "dashscope.aliyuncs.com" in message
    assert "tool_choice is unsupported with this model" in message


def test_unwrap_read_timeout_uses_friendly_message():
    exc = httpx.ReadTimeout("")

    assert unwrap_exception_message(exc) == "连接模型服务超时，请检查网络或稍后重试"


def test_format_execution_error_includes_provider_detail():
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(
        400,
        json={"message": "Invalid parameter", "code": "InvalidParameter"},
        request=request,
    )
    exc = httpx.HTTPStatusError("client error", request=request, response=response)

    formatted = format_execution_error(exc)

    assert "[系统错误]" in formatted
    assert "Invalid parameter" in formatted

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CARD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _parse_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


class SysUiCardBase(BaseModel):
    card_key: str
    name: str
    description: Optional[str] = None
    render_type: str = "iframe"
    url: str
    allowed_origins: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    allowed_agent_ids: list[str] = Field(default_factory=list)
    default_height: int = 480
    token_ttl_seconds: int = 600
    is_active: bool = True

    @field_validator("card_key")
    @classmethod
    def _card_key(cls, value: str) -> str:
        text = str(value or "").strip()
        if not _CARD_KEY_RE.match(text):
            raise ValueError("card_key 须匹配 ^[a-z][a-z0-9_]{1,63}$")
        return text

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("name 不能为空")
        return text[:128]

    @field_validator("render_type")
    @classmethod
    def _render_type(cls, value: str) -> str:
        text = str(value or "iframe").strip() or "iframe"
        if text != "iframe":
            raise ValueError("首版仅支持 render_type=iframe")
        return text

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("url 不能为空")
        if text.startswith("/"):
            return text
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url 须为 http(s) 绝对地址或同域相对路径")
        return text

    @field_validator("allowed_origins", "allowed_actions", "allowed_agent_ids", mode="before")
    @classmethod
    def _json_lists(cls, value: Any) -> list[Any]:
        return _parse_json_list(value)

    @field_validator("allowed_actions")
    @classmethod
    def _actions(cls, value: list[str]) -> list[str]:
        actions = [str(item).strip() for item in value if str(item).strip()]
        if not actions:
            raise ValueError("allowed_actions 不能为空")
        for item in actions:
            if not _ACTION_RE.match(item):
                raise ValueError(f"非法 action: {item}")
        return list(dict.fromkeys(actions))

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, value: list[str]) -> list[str]:
        origins: list[str] = []
        for item in value:
            text = str(item or "").strip().rstrip("/")
            if not text:
                continue
            parsed = urlparse(text)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                origins.append(f"{parsed.scheme}://{parsed.netloc}")
            else:
                origins.append(text)
        return list(dict.fromkeys(origins))

    @field_validator("allowed_agent_ids")
    @classmethod
    def _agent_ids(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("default_height")
    @classmethod
    def _height(cls, value: int) -> int:
        height = int(value or 480)
        return min(1200, max(240, height))

    @field_validator("token_ttl_seconds")
    @classmethod
    def _ttl(cls, value: int) -> int:
        ttl = int(value or 600)
        return min(1800, max(60, ttl))

    @model_validator(mode="after")
    def _origin_matches_url(self) -> "SysUiCardBase":
        if self.url.startswith("/"):
            return self
        parsed = urlparse(self.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if self.allowed_origins and origin not in self.allowed_origins:
            raise ValueError("url 的 origin 必须包含在 allowed_origins 中")
        return self


class SysUiCardCreate(SysUiCardBase):
    pass


class SysUiCardUpdate(BaseModel):
    card_key: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    render_type: Optional[str] = None
    url: Optional[str] = None
    allowed_origins: Optional[list[str]] = None
    allowed_actions: Optional[list[str]] = None
    allowed_agent_ids: Optional[list[str]] = None
    default_height: Optional[int] = None
    token_ttl_seconds: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("card_key")
    @classmethod
    def _card_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return SysUiCardBase._card_key(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return SysUiCardBase._name(value)

    @field_validator("render_type")
    @classmethod
    def _render_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return SysUiCardBase._render_type(value)

    @field_validator("url")
    @classmethod
    def _url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return SysUiCardBase._url(value)

    @field_validator("allowed_origins", "allowed_actions", "allowed_agent_ids", mode="before")
    @classmethod
    def _json_lists(cls, value: Any) -> Any:
        if value is None:
            return None
        return _parse_json_list(value)

    @field_validator("allowed_actions")
    @classmethod
    def _actions(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return SysUiCardBase._actions(value)

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return SysUiCardBase._origins(value)

    @field_validator("allowed_agent_ids")
    @classmethod
    def _agent_ids(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return SysUiCardBase._agent_ids(value)

    @field_validator("default_height")
    @classmethod
    def _height(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        return SysUiCardBase._height(value)

    @field_validator("token_ttl_seconds")
    @classmethod
    def _ttl(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        return SysUiCardBase._ttl(value)


class SysUiCardResponse(SysUiCardBase):
    id: str
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

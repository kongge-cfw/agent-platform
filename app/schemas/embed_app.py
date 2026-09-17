from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_APP_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_DATA_PERMISSION_MODES = frozenset({"nanzi_sql_rewrite", "mcp_only"})
_STANDARD_CLAIM_KEYS = (
    "subject",
    "display_name",
    "dept_code",
    "org_path",
    "tenant_id",
    "extra_data",
)


def parse_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item is not None and str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if item is not None and str(item).strip()]
    return []


def dump_json_list(value: Any) -> str:
    items = [str(item).strip() for item in parse_json_list(value) if str(item).strip()]
    return json.dumps(items, ensure_ascii=False)


def parse_optional_role_id(value: Any) -> Optional[int]:
    if value in (None, "", 0, "0"):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("role_id 必须是整数") from exc
    return parsed if parsed > 0 else None


def parse_required_role_id(value: Any) -> int:
    parsed = parse_optional_role_id(value)
    if parsed is None:
        raise ValueError("必须关联角色")
    return parsed


class SysEmbedAppBase(BaseModel):
    name: str
    description: Optional[str] = None
    role_id: Optional[int] = None
    lock_entry_agent: bool = False
    allowed_origins: list[str] = Field(default_factory=list)
    require_identity: bool = True
    claim_keys: list[str] = Field(default_factory=list)
    data_permission_mode: str = "nanzi_sql_rewrite"
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("name 不能为空")
        return text[:128]

    @field_validator("role_id", mode="before")
    @classmethod
    def _role_id(cls, value: Any) -> Optional[int]:
        return parse_optional_role_id(value)

    @field_validator("data_permission_mode")
    @classmethod
    def _mode(cls, value: str) -> str:
        text = str(value or "nanzi_sql_rewrite").strip() or "nanzi_sql_rewrite"
        if text not in _DATA_PERMISSION_MODES:
            raise ValueError("data_permission_mode 仅支持 nanzi_sql_rewrite 或 mcp_only")
        return text

    @field_validator("allowed_origins", "claim_keys", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return [str(item).strip() for item in parse_json_list(value) if str(item).strip()]

    @model_validator(mode="after")
    def _claim_keys_shape(self) -> "SysEmbedAppBase":
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in self.claim_keys:
            key = str(raw or "").strip()
            if not key or key in seen:
                continue
            if key not in _STANDARD_CLAIM_KEYS and not key.startswith("extra_data."):
                raise ValueError(
                    "claim_keys 仅允许 subject/display_name/dept_code/org_path/tenant_id/extra_data 或 extra_data.*"
                )
            seen.add(key)
            cleaned.append(key)
        self.claim_keys = cleaned
        return self


class SysEmbedAppCreate(SysEmbedAppBase):
    role_id: int
    app_key: Optional[str] = Field(
        default=None,
        description="可选。不传则由平台自动生成。",
    )

    @field_validator("role_id", mode="before")
    @classmethod
    def _create_role_id(cls, value: Any) -> int:
        return parse_required_role_id(value)

    @field_validator("app_key")
    @classmethod
    def _optional_app_key(cls, value: Optional[str]) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if not _APP_KEY_RE.match(text):
            raise ValueError("app_key 须匹配 ^[a-z][a-z0-9_]{1,63}$")
        return text


class SysEmbedAppUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    role_id: Optional[int] = None
    lock_entry_agent: Optional[bool] = None
    allowed_origins: Optional[list[str]] = None
    require_identity: Optional[bool] = None
    claim_keys: Optional[list[str]] = None
    data_permission_mode: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = str(value).strip()
        if not text:
            raise ValueError("name 不能为空")
        return text[:128]

    @field_validator("role_id", mode="before")
    @classmethod
    def _role_id(cls, value: Any) -> int:
        if value is None:
            raise ValueError("必须关联角色")
        return parse_required_role_id(value)

    @field_validator("data_permission_mode")
    @classmethod
    def _mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = str(value).strip() or "nanzi_sql_rewrite"
        if text not in _DATA_PERMISSION_MODES:
            raise ValueError("data_permission_mode 仅支持 nanzi_sql_rewrite 或 mcp_only")
        return text

    @field_validator("allowed_origins", "claim_keys", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> Any:
        if value is None:
            return value
        return [str(item).strip() for item in parse_json_list(value) if str(item).strip()]


class SysEmbedAppResponse(SysEmbedAppBase):
    id: str
    app_key: str
    role_name: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("allowed_origins", "claim_keys", mode="before")
    @classmethod
    def _response_lists(cls, value: Any) -> list[str]:
        return [str(item).strip() for item in parse_json_list(value) if str(item).strip()]


class EmbedRoleOption(BaseModel):
    id: int
    code: str
    name: str

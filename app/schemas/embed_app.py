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
_MAX_SHORTCUT_PROMPTS = 20
_SHORTCUT_LABEL_MAX = 50
_SHORTCUT_COMMAND_MAX = 500


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


def parse_shortcut_prompts(value: Any) -> list[dict[str, str]]:
    raw: Any = value
    if value is None or value == "":
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    prompts: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:_SHORTCUT_LABEL_MAX]
        command = str(item.get("command") or "").strip()[:_SHORTCUT_COMMAND_MAX]
        if not label or not command:
            continue
        prompts.append({"label": label, "command": command})
        if len(prompts) >= _MAX_SHORTCUT_PROMPTS:
            break
    return prompts


def dump_shortcut_prompts(value: Any) -> str:
    return json.dumps(parse_shortcut_prompts(value), ensure_ascii=False)


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


def parse_optional_agent_id(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text or text == "0":
        return None
    if len(text) > 64:
        raise ValueError("default_entry_agent_id 过长")
    return text


class SysEmbedAppBase(BaseModel):
    name: str
    description: Optional[str] = None
    role_id: Optional[int] = None
    lock_entry_agent: bool = False
    default_entry_agent_id: Optional[str] = None
    allowed_origins: list[str] = Field(default_factory=list)
    require_identity: bool = True
    claim_keys: list[str] = Field(default_factory=list)
    data_permission_mode: str = "nanzi_sql_rewrite"
    shortcut_prompts: list[dict[str, str]] = Field(default_factory=list)
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

    @field_validator("default_entry_agent_id", mode="before")
    @classmethod
    def _default_entry_agent_id(cls, value: Any) -> Optional[str]:
        return parse_optional_agent_id(value)

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

    @field_validator("shortcut_prompts", mode="before")
    @classmethod
    def _shortcut_prompts(cls, value: Any) -> list[dict[str, str]]:
        return parse_shortcut_prompts(value)


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
    default_entry_agent_id: Optional[str] = None
    allowed_origins: Optional[list[str]] = None
    require_identity: Optional[bool] = None
    claim_keys: Optional[list[str]] = None
    data_permission_mode: Optional[str] = None
    shortcut_prompts: Optional[list[dict[str, str]]] = None
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
    def _role_id(cls, value: Any) -> Any:
        if value is None:
            return None
        return parse_required_role_id(value)

    @field_validator("default_entry_agent_id", mode="before")
    @classmethod
    def _default_entry_agent_id(cls, value: Any) -> Any:
        if value is None:
            return None
        return parse_optional_agent_id(value)

    @field_validator("data_permission_mode")
    @classmethod
    def _mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = str(value).strip() or "nanzi_sql_rewrite"
        if text not in _DATA_PERMISSION_MODES:
            raise ValueError("data_permission_mode 仅支持 nanzi_sql_rewrite 或 mcp_only")
        return text

    @field_validator("shortcut_prompts", mode="before")
    @classmethod
    def _update_shortcut_prompts(cls, value: Any) -> Any:
        if value is None:
            return value
        return parse_shortcut_prompts(value)

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
    default_entry_agent_name: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("allowed_origins", "claim_keys", mode="before")
    @classmethod
    def _response_lists(cls, value: Any) -> list[str]:
        return [str(item).strip() for item in parse_json_list(value) if str(item).strip()]

    @field_validator("shortcut_prompts", mode="before")
    @classmethod
    def _response_prompts(cls, value: Any) -> list[dict[str, str]]:
        return parse_shortcut_prompts(value)


class EmbedRoleOption(BaseModel):
    id: int
    code: str
    name: str


class EmbedRoleAgentOption(BaseModel):
    id: str
    name: str
    display_name: str
    is_system: bool = False

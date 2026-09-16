"""Pending UI-card instances and short-lived card tokens."""
from __future__ import annotations

import copy
import json
import time
from asyncio import Lock
from contextlib import asynccontextmanager
from typing import Any

_MEMORY_STORE: dict[str, dict[str, Any]] = {}
_MEMORY_LOCKS: dict[str, Lock] = {}


class UiCardStore:
    KEY_PREFIX = "ai:ui-card"
    DEFAULT_TTL_SECONDS = 1800

    def __init__(
        self,
        redis_client: Any = None,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        allow_memory_fallback: bool = True,
    ):
        self.redis_client = redis_client
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.allow_memory_fallback = allow_memory_fallback
        self._memory = _MEMORY_STORE

    @classmethod
    async def from_runtime(cls) -> "UiCardStore":
        from app.core.redis import get_redis

        return cls(await get_redis(), allow_memory_fallback=False)

    @classmethod
    def _key(cls, user_id: int | str, conversation_id: str, card_id: str) -> str:
        from app.services.ai.conversation_identity import require_user_id

        return f"{cls.KEY_PREFIX}:{require_user_id(user_id)}:{conversation_id}:{card_id}"

    @classmethod
    def _active_key(cls, user_id: int | str, conversation_id: str) -> str:
        from app.services.ai.conversation_identity import require_user_id

        return f"{cls.KEY_PREFIX}:active:{require_user_id(user_id)}:{conversation_id}"

    @classmethod
    def _token_key(cls, token: str) -> str:
        return f"{cls.KEY_PREFIX}:token:{token}"

    async def create_pending(
        self,
        *,
        user_id: int | str,
        conversation_id: str,
        card_id: str,
        payload: dict[str, Any],
        token: str,
        token_ttl_seconds: int,
    ) -> dict[str, Any]:
        key = self._key(user_id, conversation_id, card_id)
        active_key = self._active_key(user_id, conversation_id)
        now = int(time.time())
        async with self._submission_lock(active_key):
            active = await self._get(active_key)
            if active and active.get("status") == "pending" and not self._is_expired(active):
                old_id = active.get("card_id")
                if old_id and old_id != card_id:
                    old_key = self._key(user_id, conversation_id, str(old_id))
                    old_record = await self._get(old_key)
                    if old_record and old_record.get("status") == "pending":
                        old_record["status"] = "superseded"
                        await self._set(old_key, old_record)
            record = {
                **copy.deepcopy(payload),
                "card_id": card_id,
                "user_id": str(user_id),
                "conversation_id": conversation_id,
                "status": "pending",
                "created_at": now,
                "expires_at": now + self.ttl_seconds,
            }
            await self._set(key, record)
            await self._set(
                active_key,
                {
                    "card_id": card_id,
                    "status": "pending",
                    "expires_at": record["expires_at"],
                },
            )
            await self._set(
                self._token_key(token),
                {
                    "card_id": card_id,
                    "user_id": str(user_id),
                    "conversation_id": conversation_id,
                    "card_key": payload.get("card_key"),
                    "used": False,
                },
                ttl_seconds=max(60, int(token_ttl_seconds)),
            )
        return copy.deepcopy(record)

    async def get_pending(
        self,
        *,
        user_id: int | str,
        conversation_id: str,
        card_id: str,
    ) -> dict[str, Any] | None:
        record = await self._get(self._key(user_id, conversation_id, card_id))
        if not record or record.get("status") != "pending" or self._is_expired(record):
            return None
        return copy.deepcopy(record)

    async def get_by_token(self, token: str) -> dict[str, Any] | None:
        token_record = await self._get(self._token_key(token))
        if not token_record or token_record.get("used"):
            return None
        card_id = str(token_record.get("card_id") or "")
        user_id = str(token_record.get("user_id") or "")
        conversation_id = str(token_record.get("conversation_id") or "")
        if not card_id or not user_id or not conversation_id:
            return None
        pending = await self.get_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            card_id=card_id,
        )
        if pending is None:
            return None
        return {**pending, "token": token}

    async def submit(
        self,
        *,
        user_id: int | str,
        conversation_id: str,
        card_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        key = self._key(user_id, conversation_id, card_id)
        active_key = self._active_key(user_id, conversation_id)
        async with self._submission_lock(key):
            record = await self._get(key)
            if record is None:
                raise PermissionError("卡片不存在或不属于当前会话")
            if record.get("status") == "submitted":
                return copy.deepcopy(record)
            if record.get("status") != "pending" or self._is_expired(record):
                raise ValueError("卡片已过期，无法提交")
            allowed = {
                str(item).strip()
                for item in (record.get("actions") or [])
                if str(item).strip()
            }
            if action not in allowed:
                raise ValueError("非法 action")
            payload_raw = json.dumps(payload or {}, ensure_ascii=False)
            if len(payload_raw.encode("utf-8")) > 64 * 1024:
                raise ValueError("payload 不能超过 64KB")
            record.update(
                {
                    "status": "submitted",
                    "action": action,
                    "payload": payload,
                    "submitted_at": int(time.time()),
                }
            )
            await self._set(key, record)
            await self._delete(active_key)
            render = record.get("render") if isinstance(record.get("render"), dict) else {}
            token = str(render.get("card_token") or "").strip()
            if token:
                token_record = await self._get(self._token_key(token))
                if token_record:
                    token_record["used"] = True
                    await self._set(self._token_key(token), token_record, ttl_seconds=60)
            return copy.deepcopy(record)

    @staticmethod
    def _is_expired(record: dict[str, Any]) -> bool:
        return int(record.get("expires_at") or 0) <= int(time.time())

    async def _get(self, key: str) -> dict[str, Any] | None:
        if self.redis_client is None:
            if not self.allow_memory_fallback:
                raise RuntimeError("Redis is required for ui-card state")
            return copy.deepcopy(self._memory.get(key))
        raw = await self.redis_client.get(key)
        if not raw:
            return None
        return json.loads(raw)

    async def _set(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        ttl = self.ttl_seconds if ttl_seconds is None else max(60, int(ttl_seconds))
        if self.redis_client is None:
            if not self.allow_memory_fallback:
                raise RuntimeError("Redis is required for ui-card state")
            self._memory[key] = copy.deepcopy(value)
            return
        await self.redis_client.set(
            key,
            json.dumps(value, ensure_ascii=False),
            ex=ttl,
        )

    async def _delete(self, key: str) -> None:
        if self.redis_client is None:
            if not self.allow_memory_fallback:
                raise RuntimeError("Redis is required for ui-card state")
            self._memory.pop(key, None)
            return
        await self.redis_client.delete(key)

    @asynccontextmanager
    async def _submission_lock(self, key: str):
        if self.redis_client is not None:
            lock = self.redis_client.lock(f"{key}:lock", timeout=10, blocking_timeout=5)
            await lock.acquire()
            try:
                yield
            finally:
                await lock.release()
            return
        if not self.allow_memory_fallback:
            raise RuntimeError("Redis is required for ui-card state")
        lock = _MEMORY_LOCKS.setdefault(key, Lock())
        async with lock:
            yield

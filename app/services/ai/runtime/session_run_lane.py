from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.services.ai.conversation_identity import require_user_id
from app.services.ai.runtime.lock_renewal import renew_lock_during_hold

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TTL_SECONDS = 600
DEFAULT_WAIT_SECONDS = 0.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.1
OWNER_KEY_PREFIX = "nanzi:conv_run_owner:"
LOCK_KEY_PREFIX = "nanzi:conv_run:"
HEARTBEAT_TTL_SECONDS = 45
HEARTBEAT_INTERVAL_SECONDS = 10
# 本进程身份。重启后编号会变，上一进程留下的锁不再算作正在运行。
INSTANCE_ID = str(uuid.uuid4())
_heartbeat_task: asyncio.Task | None = None
# 追问等待模式（不是严格 FIFO 队列）：
#   reject   —— 会话繁忙时立即拒绝（旧行为）。
#   followup —— 有界等待当前 run 结束后再处理（改善"再搜一下"等连续追问体验）。
DEFAULT_FOLLOWUP_WAIT_MODE = "followup"
DEFAULT_FOLLOWUP_WAIT_SECONDS = 30.0


class ConversationRunBusyError(RuntimeError):
    """Raised when a conversation already has an active agent run."""


class ConversationRunLane:
    """Serialize agent turns per (user_id, conversation_id)."""

    def _lock_key(self, user_id: str | int | None, conversation_id: str) -> str:
        uid = require_user_id(user_id)
        safe_cid = conversation_id.replace(":", "_")
        return f"{LOCK_KEY_PREFIX}{uid}:{safe_cid}"

    @staticmethod
    def _owner_key(instance_id: str) -> str:
        return f"{OWNER_KEY_PREFIX}{instance_id}"

    @staticmethod
    def _encode_token(trace_id: str) -> str:
        return f"{INSTANCE_ID}|{trace_id}"

    @staticmethod
    def _decode_token(token: str) -> tuple[str | None, str]:
        text = str(token or "")
        if "|" not in text:
            return None, text
        instance_id, trace_id = text.split("|", 1)
        return (instance_id or None), trace_id

    @staticmethod
    def _owner_value() -> str:
        return f"{socket.gethostname()}|{os.getpid()}"

    @staticmethod
    def _parse_owner(value: str) -> tuple[str, int | None]:
        host, _, raw_pid = str(value or "").partition("|")
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            pid = None
        return host, pid

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @staticmethod
    def _safe_trace_id(value: object) -> str | None:
        text = str(value or "").strip()
        if not text or len(text) > 128:
            return None
        try:
            uuid.UUID(text)
        except (TypeError, ValueError, AttributeError):
            return None
        return text

    async def _is_enabled(self) -> bool:
        from app.services.config_service import ConfigService

        raw = await ConfigService.get("agent_session_run_lock_enabled", "true")
        return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}

    async def _ttl_seconds(self) -> int:
        from app.services.config_service import ConfigService

        raw = await ConfigService.get("agent_session_run_lock_ttl_seconds", str(DEFAULT_LOCK_TTL_SECONDS))
        try:
            return max(30, int(raw))
        except (TypeError, ValueError):
            return DEFAULT_LOCK_TTL_SECONDS

    async def _wait_seconds(self) -> float:
        from app.services.config_service import ConfigService

        raw = await ConfigService.get("agent_session_run_lock_wait_seconds", str(DEFAULT_WAIT_SECONDS))
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return DEFAULT_WAIT_SECONDS

    async def _followup_wait_mode(self) -> str:
        from app.services.config_service import ConfigService

        raw = await ConfigService.get("agent_session_followup_wait_mode", None)
        if raw is None:
            # Backward compatibility for configs created while this was named "queue mode".
            raw = await ConfigService.get(
                "agent_session_queue_mode",
                DEFAULT_FOLLOWUP_WAIT_MODE,
            )
        mode = str(raw or "").strip().lower()
        return mode if mode in {"reject", "followup"} else DEFAULT_FOLLOWUP_WAIT_MODE

    async def _followup_wait_seconds(self) -> float:
        from app.services.config_service import ConfigService

        raw = await ConfigService.get("agent_session_followup_wait_seconds", None)
        if raw is None:
            raw = await ConfigService.get(
                "agent_session_queue_followup_wait_seconds",
                str(DEFAULT_FOLLOWUP_WAIT_SECONDS),
            )
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return DEFAULT_FOLLOWUP_WAIT_SECONDS

    async def _owner_alive(self, redis, instance_id: str | None) -> bool:
        """当前进程持有的锁算活着。其他进程要有心跳，且本机进程号还在。"""
        if not instance_id:
            return False
        if instance_id == INSTANCE_ID:
            return True
        try:
            raw = await redis.get(self._owner_key(instance_id))
        except Exception as exc:
            logger.warning("[ConversationRunLane] owner lookup failed: %s", exc)
            return True
        if raw is None:
            return False
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        host, pid = self._parse_owner(str(raw))
        if host == socket.gethostname() and pid is not None and not self._pid_alive(pid):
            try:
                await redis.delete(self._owner_key(instance_id))
            except Exception as exc:
                logger.warning("[ConversationRunLane] drop dead owner failed: %s", exc)
            return False
        return True

    async def _drop_if_stale(self, redis, key: str) -> bool:
        try:
            raw = await redis.get(key)
        except Exception as exc:
            logger.warning("[ConversationRunLane] stale check failed: %s", exc)
            return False
        if raw is None:
            return False
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        token = str(raw)
        instance_id, _trace_id = self._decode_token(token)
        if await self._owner_alive(redis, instance_id):
            return False
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        try:
            deleted = await redis.eval(script, 1, key, token)
        except Exception as exc:
            logger.warning("[ConversationRunLane] drop stale lock failed: %s", exc)
            return False
        if deleted:
            logger.info("[ConversationRunLane] dropped stale lock %s", key)
        return bool(deleted)

    async def _mark_conversation_interrupted(
        self,
        *,
        user_id: str | int | None,
        conversation_id: str | None,
    ) -> None:
        cid = str(conversation_id or "").strip()
        if not cid or os.environ.get("PYTEST_CURRENT_TEST"):
            return
        from sqlalchemy import update

        from app.core.orm import AsyncSessionLocal
        from app.models.audit import AgentExecutionHistory

        try:
            async with AsyncSessionLocal() as session:
                stmt = update(AgentExecutionHistory).where(
                    AgentExecutionHistory.status == "running",
                    AgentExecutionHistory.conversation_id == cid,
                )
                if user_id is not None and str(user_id).strip():
                    stmt = stmt.where(AgentExecutionHistory.user_id == str(user_id))
                result = await session.execute(stmt.values(status="interrupted"))
                if result.rowcount:
                    await session.commit()
        except Exception as exc:
            logger.warning("[ConversationRunLane] mark interrupted failed: %s", exc)

    async def beat_once(self) -> None:
        from app.core.redis import get_redis

        redis = await get_redis()
        if redis is None:
            return
        try:
            await redis.set(
                self._owner_key(INSTANCE_ID),
                self._owner_value(),
                ex=HEARTBEAT_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("[ConversationRunLane] owner heartbeat failed: %s", exc)

    async def clear_owner(self) -> None:
        from app.core.redis import get_redis

        redis = await get_redis()
        if redis is None:
            return
        try:
            await redis.delete(self._owner_key(INSTANCE_ID))
        except Exception as exc:
            logger.warning("[ConversationRunLane] clear owner failed: %s", exc)

    async def heartbeat_loop(self) -> None:
        while True:
            await self.beat_once()
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

    async def _effective_wait_seconds(self) -> float:
        """根据追问等待模式解析默认等待时长（未显式传入 wait_seconds 时使用）。

        - 若显式配置 ``agent_session_run_lock_wait_seconds`` > 0，则优先采用（向后兼容/覆盖）。
        - 否则按追问等待模式：reject → 0；followup → 有界等待当前 run 结束。
        """
        explicit = await self._wait_seconds()
        if explicit > 0:
            return explicit
        if await self._followup_wait_mode() == "reject":
            return 0.0
        return await self._followup_wait_seconds()

    async def acquire(
        self,
        *,
        user_id: str | int | None,
        conversation_id: str | None,
        trace_id: str,
        ttl_seconds: int | None = None,
        wait_seconds: float | None = None,
    ) -> tuple[str, str] | None:
        if not conversation_id:
            return None
        if not await self._is_enabled():
            return None

        from app.core.redis import get_redis

        redis = await get_redis()
        if redis is None:
            logger.warning("[ConversationRunLane] Redis unavailable; skipping run lock")
            return None

        ttl = ttl_seconds if ttl_seconds is not None else await self._ttl_seconds()
        wait = wait_seconds if wait_seconds is not None else await self._effective_wait_seconds()
        key = self._lock_key(user_id, conversation_id)
        token = self._encode_token(trace_id or uuid.uuid4().hex)
        deadline = asyncio.get_running_loop().time() + wait

        while True:
            try:
                acquired = await redis.set(key, token, ex=ttl, nx=True)
            except Exception as exc:
                logger.warning("[ConversationRunLane] acquire failed: %s", exc)
                return None
            if not acquired and await self._drop_if_stale(redis, key):
                await self._mark_conversation_interrupted(
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                continue
            if acquired:
                # 刻意不在拿到 lane 后自动清理同会话的 per-agent 会话锁：单独凭借
                # “取得了 lane”无法证明那些 agent_lock 属于已终止的 run——正常 run
                # 持锁期间，若其 lane 因续约故障 / 进程暂停 / 被显式取消而先行失效，
                # 旧 run 的 executor 仍可能握着自己 agent_lock 在跑。此时无条件清理会
                # 误删活跃锁、破坏互斥并并发操作同一 AgentState。已退出进程的
                # agent_lock 由 AgentScopeSessionLock 按持有者心跳回收；显式取消路径
                # （force_release_all_for_conversation）负责停任务后删除对应锁。
                return key, token
            if wait <= 0:
                break
            if asyncio.get_running_loop().time() > deadline:
                break
            await asyncio.sleep(DEFAULT_POLL_INTERVAL_SECONDS)

        logger.info(
            "[ConversationRunLane] busy conversation=%s user=%s trace=%s",
            conversation_id,
            user_id,
            trace_id,
        )
        return None

    async def release(self, key: str | None, token: str | None) -> None:
        if not key or not token:
            return

        from app.core.redis import get_redis

        redis = await get_redis()
        if redis is None:
            return

        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        try:
            await redis.eval(script, 1, key, token)
        except Exception as exc:
            logger.warning("[ConversationRunLane] release failed: %s", exc)

    async def force_release(
        self,
        *,
        user_id: str | int | None,
        conversation_id: str | None,
    ) -> bool:
        """Delete the run-lane lock regardless of holder token (client cancel)."""
        if not conversation_id:
            return False

        from app.core.redis import get_redis

        redis = await get_redis()
        if redis is None:
            return False

        key = self._lock_key(user_id, conversation_id)
        try:
            deleted = await redis.delete(key)
            return bool(deleted)
        except Exception as exc:
            logger.warning("[ConversationRunLane] force_release failed: %s", exc)
            return False

    async def is_locked(
        self,
        *,
        user_id: str | int | None,
        conversation_id: str | None,
    ) -> bool:
        """Check whether the conversation run lane currently holds an active lock."""
        if not conversation_id or not await self._is_enabled():
            return False

        from app.core.redis import get_redis

        redis = await get_redis()
        if redis is None:
            return False

        key = self._lock_key(user_id, conversation_id)
        try:
            if await self._drop_if_stale(redis, key):
                await self._mark_conversation_interrupted(
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                return False
            return bool(await redis.exists(key))
        except Exception as exc:
            logger.warning("[ConversationRunLane] is_locked check failed: %s", exc)
            return False

    async def get_status(
        self,
        *,
        user_id: str | int | None,
        conversation_id: str | None,
    ) -> dict[str, object | None]:
        """读取当前会话运行状态。进程已退出的残留锁会删掉，不当作仍在运行。"""
        empty = {"active": False, "trace_id": None, "ttl_seconds": None}
        if not conversation_id:
            return empty
        try:
            enabled = await self._is_enabled()
        except Exception as exc:
            logger.warning("[ConversationRunLane] get_status config check failed: %s", exc)
            return empty
        if not enabled:
            return empty

        from app.core.redis import get_redis

        try:
            redis = await get_redis()
        except Exception as exc:
            logger.warning("[ConversationRunLane] get_status Redis unavailable: %s", exc)
            return empty
        if redis is None:
            return empty

        key = self._lock_key(user_id, conversation_id)
        try:
            raw_token = await redis.get(key)
            if raw_token is None:
                return empty
            if isinstance(raw_token, bytes):
                raw_token = raw_token.decode("utf-8", errors="ignore")
            token = str(raw_token)
            if await self._drop_if_stale(redis, key):
                await self._mark_conversation_interrupted(
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                return empty
            _instance_id, raw_trace_id = self._decode_token(token)
            # 锁值只允许返回服务端 UUID trace token；异常/非预期 Redis 内容不回传给客户端。
            trace_id = self._safe_trace_id(raw_trace_id)
            ttl_seconds = None
            ttl_reader = getattr(redis, "ttl", None)
            if ttl_reader is not None:
                raw_ttl = await ttl_reader(key)
                try:
                    parsed_ttl = int(raw_ttl)
                    if parsed_ttl >= 0:
                        ttl_seconds = parsed_ttl
                except (TypeError, ValueError):
                    pass
            return {"active": True, "trace_id": trace_id, "ttl_seconds": ttl_seconds}
        except Exception as exc:
            logger.warning("[ConversationRunLane] get_status failed: %s", exc)
            return empty

    @asynccontextmanager
    async def hold(
        self,
        *,
        user_id: str | int | None,
        conversation_id: str | None,
        trace_id: str,
        ttl_seconds: int | None = None,
        wait_seconds: float | None = None,
    ) -> AsyncIterator[bool]:
        """
        Yield True when the lane lock is held.
        Yield False when locking is skipped (no conversation_id / disabled / no redis).
        Raise ConversationRunBusyError when the lane is busy.
        """
        if not conversation_id:
            yield False
            return

        handle = await self.acquire(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            ttl_seconds=ttl_seconds,
            wait_seconds=wait_seconds,
        )
        if handle is None:
            from app.core.redis import get_redis

            if await get_redis() is not None and await self._is_enabled():
                raise ConversationRunBusyError(
                    f"Conversation {conversation_id} is already processing another request"
                )
            yield False
            return

        key, token = handle
        effective_ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else await self._ttl_seconds()
        )
        renewal = asyncio.create_task(
            renew_lock_during_hold(
                key=key,
                token=token,
                ttl_seconds=effective_ttl,
            )
        )
        try:
            yield True
        finally:
            renewal.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewal
            await self.release(key, token)

    async def reap_stale_locks(self) -> int:
        """删掉所属进程已经不在的运行锁。"""
        from app.core.redis import get_redis

        redis = await get_redis()
        if redis is None or not await self._is_enabled():
            return 0
        dropped = 0
        try:
            scanner = getattr(redis, "scan_iter", None)
            if scanner is None:
                return 0
            async for key in scanner(match=f"{LOCK_KEY_PREFIX}*", count=100):
                text = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
                if text.startswith(OWNER_KEY_PREFIX):
                    continue
                if await self._drop_if_stale(redis, text):
                    dropped += 1
        except Exception as exc:
            logger.warning("[ConversationRunLane] reap stale locks failed: %s", exc)
        if dropped:
            logger.info("[ConversationRunLane] reaped %s stale run locks", dropped)
        return dropped

    async def interrupt_history_without_live_lock(self) -> int:
        """把没有活着的运行锁、却仍标着进行中的历史收成已中断。"""
        if not await self._is_enabled():
            return 0
        from app.core.redis import get_redis

        if await get_redis() is None:
            return 0

        from sqlalchemy import select, update

        from app.core.orm import AsyncSessionLocal
        from app.models.audit import AgentExecutionHistory

        try:
            async with AsyncSessionLocal() as session:
                rows = (
                    await session.execute(
                        select(
                            AgentExecutionHistory.conversation_id,
                            AgentExecutionHistory.user_id,
                        )
                        .where(AgentExecutionHistory.status == "running")
                        .distinct()
                    )
                ).all()
                stale: list[tuple[str, str | None]] = []
                for conversation_id, user_id in rows:
                    cid = str(conversation_id or "").strip()
                    if not cid:
                        continue
                    try:
                        live = await self.is_locked(user_id=user_id, conversation_id=cid)
                    except Exception:
                        live = False
                    if not live:
                        stale.append((cid, None if user_id is None else str(user_id)))
                changed = 0
                for cid, user_id in stale:
                    stmt = update(AgentExecutionHistory).where(
                        AgentExecutionHistory.status == "running",
                        AgentExecutionHistory.conversation_id == cid,
                    )
                    if user_id is not None:
                        stmt = stmt.where(AgentExecutionHistory.user_id == user_id)
                    result = await session.execute(stmt.values(status="interrupted"))
                    changed += int(result.rowcount or 0)
                if changed:
                    await session.commit()
                    logger.info("[ConversationRunLane] marked %s history rows interrupted", changed)
                return changed
        except Exception as exc:
            logger.warning("[ConversationRunLane] interrupt stale history failed: %s", exc)
            return 0


conversation_run_lane = ConversationRunLane()


async def start_conversation_run_owner() -> None:
    """登记本进程心跳，供其他实例判断这把运行锁是否还活着。"""
    global _heartbeat_task
    await conversation_run_lane.beat_once()
    if _heartbeat_task is not None and not _heartbeat_task.done():
        return
    _heartbeat_task = asyncio.create_task(
        conversation_run_lane.heartbeat_loop(),
        name="conversation-run-owner-heartbeat",
    )


async def stop_conversation_run_owner() -> None:
    global _heartbeat_task
    task = _heartbeat_task
    _heartbeat_task = None
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await conversation_run_lane.clear_owner()


async def reap_interrupted_conversation_runs() -> None:
    """启动时清掉已退出进程留下的运行锁，并把对应历史改为已中断。"""
    await conversation_run_lane.reap_stale_locks()
    await conversation_run_lane.interrupt_history_without_live_lock()
    from app.services.ai.runtime.agentscope.session_lock import agentscope_session_lock

    await agentscope_session_lock.reap_orphaned_locks()

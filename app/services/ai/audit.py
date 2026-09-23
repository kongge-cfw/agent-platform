import logging
from typing import List, Any, Optional, Dict
from app.schemas.agent import AgentExecutionStep
from app.core.orm import AsyncSessionLocal
from app.models.audit import AgentExecutionTrace
from app.services.ai.conversation_identity import require_user_id
from app.services.ai.audit_payload import bound_audit_payload

logger = logging.getLogger(__name__)


def _is_history_receipt_query(text: str | None) -> bool:
    """确认回执和答题回执不是用户最初的问题，不能当历史卡片标题。"""
    raw = str(text or "").strip()
    if not raw:
        return False
    from app.services.ai.business_confirmation import is_business_confirmation_receipt_message
    from app.services.ai.user_question import is_user_question_receipt_message

    return is_business_confirmation_receipt_message(raw) or is_user_question_receipt_message(raw)

# 仅这些步骤类型对应真实的 LLM API 调用；tool_call / router 等不计入 Token。
# model_call：AgentScope ReAct 每次 MODEL_CALL_END 一条，与前端 SSE 累加口径一致。
# thought / synthesis：直连 LLM 或总结阶段（无 model_call 时由 synthesis 承载单次调用）。
_LLM_TOKEN_STEP_EVENTS = frozenset({"thought", "synthesis", "model_call"})


def aggregate_tokens_from_trace_buffer(trace_buffer: List[AgentExecutionStep]) -> tuple[int, int, int]:
    """
    从 trace 步骤汇总会话级 Token。
    - 每条 LLM API 调用只应出现一次（model_call 或带 usage 的 synthesis/thought）
    - ReAct 路径：多次 model_call 累加；末尾 synthesis 若为 0 token 则自动忽略
    - 无 AgentScope 的单次直答：仅 synthesis/thought 带 usage
    - 仅有 total_tokens、无分项的步骤计入 orphan 总量
    """
    if not trace_buffer:
        return 0, 0, 0

    prompt_sum = 0
    completion_sum = 0
    orphan_total = 0

    for step in trace_buffer:
        if getattr(step, "event_type", None) not in _LLM_TOKEN_STEP_EVENTS:
            continue
        p = int(getattr(step, "prompt_tokens", 0) or 0)
        c = int(getattr(step, "completion_tokens", 0) or 0)
        t = int(getattr(step, "total_tokens", 0) or 0)
        if p <= 0 and c <= 0 and t <= 0:
            continue
        if p > 0 or c > 0:
            prompt_sum += p
            completion_sum += c
        elif t > 0:
            orphan_total += t

    if prompt_sum > 0 or completion_sum > 0:
        return prompt_sum, completion_sum, prompt_sum + completion_sum + orphan_total
    return 0, 0, orphan_total


class AuditManager:
    """
    Handles trace logging and auditing for agent executions.
    """
    
    @staticmethod
    async def log_transaction(
        trace_id: str,
        agent_config: Any,
        user_query: str,
        response_content: str,
        user_info: Optional[Dict[str, Any]],
        status: str,
        duration: float,
        trace_buffer: List[AgentExecutionStep],
        conversation_id: Optional[str] = None,
        reasoning_content: Optional[str] = None,
        process_timeline: Optional[List[Dict[str, Any]]] = None,
        has_data_output: Optional[bool] = None,
    ):
        """
        High-level method to handle all audit logging (Trace Logs + History).
        Encapsulates model ID resolution.
        """
        logger.info(f"[Audit] Starting transaction log for {trace_id}. Buffer size: {len(trace_buffer) if trace_buffer else 0}")
        # 1. Save Trace Logs
        if trace_buffer:
            await AuditManager.save_trace_logs(trace_id, trace_buffer)
        else:
            logger.warning(f"[Audit] No trace logs to save for {trace_id}")

        # 2. Save History
        if agent_config:
            model_config_id = None
            model_id_snapshot = agent_config.model_name
            agent_version = agent_config.agent_version
            agent_id = agent_config.agent_id

            try:
                from app.models.ai_model import AIModel
                from sqlalchemy import select, or_
                
                async with AsyncSessionLocal() as db_session:
                    stmt = select(AIModel).where(
                    AIModel.is_active == True,
                    or_(AIModel.model_id == model_id_snapshot, AIModel.name == model_id_snapshot)
                    )
                    res = await db_session.execute(stmt)
                    aim = res.scalars().first()
                    if aim:
                        model_config_id = aim.id
                        model_id_snapshot = aim.model_id
            except Exception as ex:
                logger.warning(f"Failed to resolve model ID for auditing: {ex}")

            prompt_tokens_sum, completion_tokens_sum, total_tokens_sum = (
                aggregate_tokens_from_trace_buffer(trace_buffer) if trace_buffer else (0, 0, 0)
            )

            await AuditManager.save_history(
                trace_id=trace_id,
                agent_id=agent_id,
                query=user_query,
                summary=response_content,
                user_info=user_info,
                status=status,
                execution_time_ms=duration,
                agent_version=agent_version,
                model_id=model_id_snapshot,
                model_config_id=model_config_id,
                conversation_id=conversation_id,
                prompt_tokens=prompt_tokens_sum,
                completion_tokens=completion_tokens_sum,
                total_tokens=total_tokens_sum,
                reasoning_content=reasoning_content,
                process_timeline=process_timeline,
                has_data_output=has_data_output,
            )

    @staticmethod
    async def save_trace_logs(trace_id: str, logs: List[AgentExecutionStep]):
        """
        Persists a list of execution steps to the database.
        """
        if not logs:
            return
        
        try:
            async with AsyncSessionLocal() as session:
                orm_objects = []
                for log in logs:
                    orm_objects.append(AgentExecutionTrace(
                        trace_id=trace_id,
                        step_number=log.step_number,
                        event_type=log.event_type,
                        agent_name=log.agent_name,
                        tool_name=log.tool_name,
                        # Bound only the audit copy. AgentScope has already
                        # consumed the original result and keeps using it.
                        tool_input=bound_audit_payload(log.tool_input),
                        tool_output=bound_audit_payload(log.tool_output),
                        execution_time_ms=log.execution_time_ms,
                        status=log.status,
                        error_message=log.error_message,
                        model=log.model,
                        temperature=log.temperature,
                        prompt_tokens=getattr(log, 'prompt_tokens', 0) or 0,
                        completion_tokens=getattr(log, 'completion_tokens', 0) or 0,
                        total_tokens=getattr(log, 'total_tokens', 0) or 0,
                        span_id=getattr(log, 'span_id', None),
                        parent_span_id=getattr(log, 'parent_span_id', None),
                        meta_info=getattr(log, 'meta_info', None),
                        created_at=log.timestamp
                    ))
                session.add_all(orm_objects)
                await session.commit()
                logger.info(f"Successfully saved {len(orm_objects)} trace logs for {trace_id}")
        except Exception as e:
            logger.error(f"Failed to save trace logs for {trace_id}: {e}")

    @staticmethod
    async def save_history(
        trace_id: str, 
        agent_id: str, 
        query: str, 
        summary: str,
        user_info: dict,
        status: str = "success",
        execution_time_ms: float = 0.0,
        agent_version: str = None,
        model_id: str = None,
        model_config_id: str = None,
        conversation_id: str = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        reasoning_content: Optional[str] = None,
        process_timeline: Optional[List[Dict[str, Any]]] = None,
        has_data_output: Optional[bool] = None,
    ):
        """
        Saves the high-level conversation entry.
        """
        try:
            from sqlalchemy import select

            from app.models.audit import AgentExecutionHistory
            history_user_id = require_user_id(user_info)
            
            async with AsyncSessionLocal() as session:
                existing_result = await session.execute(
                    select(AgentExecutionHistory).where(AgentExecutionHistory.trace_id == trace_id)
                )
                existing = existing_result.scalar_one_or_none()
                if existing is not None:
                    if query and not (
                        _is_history_receipt_query(query) and not _is_history_receipt_query(existing.query)
                    ):
                        existing.query = query
                    existing.summary = summary
                    existing.status = status
                    existing.execution_time_ms = execution_time_ms
                    existing.agent_version = agent_version
                    existing.model_id = model_id
                    existing.model_config_id = model_config_id
                    existing.prompt_tokens = prompt_tokens
                    existing.completion_tokens = completion_tokens
                    existing.total_tokens = total_tokens
                    existing.reasoning_content = reasoning_content
                    existing.process_timeline = process_timeline
                    if has_data_output is not None:
                        existing.has_data_output = 1 if has_data_output else 0
                    if agent_id:
                        existing.agent_id = agent_id
                    if conversation_id:
                        existing.conversation_id = conversation_id
                    await session.commit()
                    logger.info(f"Updated conversation history for trace {trace_id}")
                    return

                history_entry = AgentExecutionHistory(
                    trace_id=trace_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    user_id=history_user_id,
                    username=user_info.get("user_name") if user_info else None,
                    query=query,
                    summary=summary,
                    reasoning_content=reasoning_content,
                    process_timeline=process_timeline,
                    status=status,
                    execution_time_ms=execution_time_ms,
                    agent_version=agent_version,
                    model_id=model_id,
                    model_config_id=model_config_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    has_data_output=(1 if has_data_output else 0),
                )
                session.add(history_entry)
                await session.commit()
                logger.info(f"Saved conversation history for trace {trace_id} (Version: {agent_version})")
        except Exception as e:
            logger.error(f"Failed to save history for {trace_id}: {e}")

    @staticmethod
    async def ensure_open_history(
        trace_id: str,
        agent_id: str,
        query: str,
        user_info: Optional[Dict[str, Any]],
        conversation_id: Optional[str] = None,
    ) -> None:
        """第一条用户问题发出时就写入历史，侧栏不必等本轮结束。"""
        text = str(query or "").strip()
        cid = str(conversation_id or "").strip()
        aid = str(agent_id or "").strip()
        tid = str(trace_id or "").strip()
        # 自动路由在这一步还没有专家。先记下会话，刷新后左侧列表不用等本轮结束。
        if not text or not cid or not tid or not user_info:
            return
        if _is_history_receipt_query(text):
            return
        try:
            history_user_id = require_user_id(user_info)
        except Exception:
            return
        try:
            from sqlalchemy import select

            from app.models.audit import AgentExecutionHistory

            async with AsyncSessionLocal() as session:
                existing_trace = await session.execute(
                    select(AgentExecutionHistory.id).where(AgentExecutionHistory.trace_id == tid)
                )
                if existing_trace.scalar_one_or_none() is not None:
                    return
                existing_conversation = await session.execute(
                    select(AgentExecutionHistory.id)
                    .where(
                        AgentExecutionHistory.conversation_id == cid,
                        AgentExecutionHistory.user_id == history_user_id,
                    )
                    .limit(1)
                )
                if existing_conversation.scalar_one_or_none() is not None:
                    return
                session.add(
                    AgentExecutionHistory(
                        trace_id=tid,
                        agent_id=aid,
                        conversation_id=cid,
                        user_id=history_user_id,
                        username=user_info.get("user_name") if user_info else None,
                        query=text,
                        summary="",
                        status="running",
                        execution_time_ms=0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        has_data_output=0,
                    )
                )
                await session.commit()
                logger.info(f"Opened conversation history for {cid}")
        except Exception as e:
            logger.error(f"Failed to open history for {cid}: {e}")

    @staticmethod
    async def attach_history_agent(trace_id: str, agent_id: str) -> None:
        """路由确定专家后，补上打开历史时还没有的智能体。"""
        tid = str(trace_id or "").strip()
        aid = str(agent_id or "").strip()
        if not tid or not aid:
            return
        try:
            from sqlalchemy import select

            from app.models.audit import AgentExecutionHistory

            async with AsyncSessionLocal() as session:
                existing_result = await session.execute(
                    select(AgentExecutionHistory).where(AgentExecutionHistory.trace_id == tid)
                )
                existing = existing_result.scalar_one_or_none()
                if existing is None or str(existing.agent_id or "").strip():
                    return
                existing.agent_id = aid
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to attach history agent for {tid}: {e}")

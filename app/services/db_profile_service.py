import asyncio
import copy
import logging
import json
import re
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, List, Tuple
from sqlalchemy import select, update, func, or_, case, cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from fastapi import BackgroundTasks

from app.core.orm import AsyncSessionLocal
from app.models.db_connection import MetaDbConnectionConfig, DbProfileTask, DbTableProfile
from app.services.db_connection_service import DbConnectionService
from app.services.db_import_service import DBImportService, DbDdlSession
from app.services.ai.runtime.agentscope.compat import SystemMessage, HumanMessage
from app.schemas.db_connection import (
    DbTableProfileSummaryResponse,
    DbTableProfileStatsResponse,
    DbTableProfileTagStat,
    DbTableProfilePageResponse,
)

logger = logging.getLogger(__name__)

# 主任务状态: 0-排队, 1-进行中, 2-完成, 3-异常, 4-用户中断
TASK_STATUS_QUEUED = 0
TASK_STATUS_RUNNING = 1
TASK_STATUS_DONE = 2
TASK_STATUS_ERROR = 3
TASK_STATUS_CANCELLED = 4

# 超过该分钟数无心跳更新，视为僵尸任务，允许重新启动
STALE_TASK_MINUTES = 10
MAX_DDL_CHARS = 60000
MAX_SAMPLE_FIELD_CHARS = 150
PROFILE_CONCURRENCY = 4
DEFAULT_PROFILE_PAGE_SIZE = 200
MAX_PROFILE_PAGE_SIZE = 200


class DbProfileService:
    """外部数据源元数据智能摸排与分析服务"""

    @staticmethod
    def _session_dialect_name(db: AsyncSession) -> str:
        try:
            return db.get_bind().dialect.name
        except Exception:
            return "mysql"

    @staticmethod
    def _is_postgresql_dialect(dialect_name: str) -> bool:
        return str(dialect_name or "").strip().lower() in {
            "postgres",
            "postgresql",
            "pg",
        }

    @staticmethod
    def _profile_field_count_expression(dialect_name: str):
        """构造字段画像数组长度表达式，适配平台主库方言。"""
        if DbProfileService._is_postgresql_dialect(dialect_name):
            return func.jsonb_array_length(DbTableProfile.columns_profile)
        return func.json_length(DbTableProfile.columns_profile)

    @staticmethod
    async def trigger_profiling_task(
        db: AsyncSession,
        config_id: int,
        background_tasks: BackgroundTasks,
        full_reset: bool = False,
    ) -> DbProfileTask:
        """
        触发该数据源配置下表/视图的智能分析摸排后台任务。
        full_reset=True 时全量重跑；否则仅处理未完成/失败/中断的表（断点续跑）。
        """
        config = await DbConnectionService.get_config(db, config_id)
        if not config:
            raise ValueError("数据源配置不存在")

        stmt_task = select(DbProfileTask).where(DbProfileTask.connection_id == config_id)
        res_task = await db.execute(stmt_task)
        existing_task = res_task.scalar_one_or_none()

        if existing_task and existing_task.status == TASK_STATUS_RUNNING:
            await DbProfileService.reconcile_profiling_task_status(db, config_id, commit=True)
            res_task = await db.execute(stmt_task)
            existing_task = res_task.scalar_one_or_none()

        if existing_task and existing_task.status == TASK_STATUS_RUNNING:
            if not DbProfileService._is_task_stale(existing_task):
                raise ValueError("当前数据源分析摸排任务正在执行中，请勿重复点击")
            logger.warning(
                "[DbProfiling] Detected stale running task for connection_id=%s, allowing restart",
                config_id,
            )
            await db.execute(
                update(DbTableProfile)
                .where(
                    DbTableProfile.connection_id == config_id,
                    DbTableProfile.status == 1,
                )
                .values(status=0, error_message=None)
            )

        db_config = {
            "host": config.host,
            "port": config.port,
            "user": config.db_user,
            "password": config.password,
            "database": config.database_name,
        }

        db_type = config.db_type.strip().lower()
        if db_type == "mysql":
            tables_info = await DBImportService.get_mysql_tables(db_config)
        elif db_type == "clickhouse":
            tables_info = await DBImportService.get_clickhouse_tables(db_config)
        elif db_type == "oracle":
            tables_info = await DBImportService.get_oracle_tables(db_config)
        elif db_type in DBImportService._sqlserver_type_aliases():
            tables_info = await DBImportService.get_sqlserver_tables(db_config)
        elif db_type in DBImportService._postgresql_type_aliases():
            tables_info = await DBImportService.get_postgresql_tables(db_config)
        else:
            raise ValueError(f"不支持的数据库类型: {config.db_type}")

        total_count = len(tables_info)
        completed_count = 0
        if existing_task and not full_reset:
            count_res = await db.execute(
                select(func.count())
                .select_from(DbTableProfile)
                .where(
                    DbTableProfile.connection_id == config_id,
                    DbTableProfile.status == 2,
                )
            )
            completed_count = int(count_res.scalar() or 0)

        if existing_task:
            existing_task.status = TASK_STATUS_RUNNING
            existing_task.total_tables = total_count
            existing_task.processed_tables = completed_count if not full_reset else 0
            existing_task.current_table = None
            existing_task.error_message = None
            task = existing_task
        else:
            task = DbProfileTask(
                connection_id=config_id,
                status=TASK_STATUS_RUNNING,
                total_tables=total_count,
                processed_tables=0,
                current_table=None,
            )
            db.add(task)

        await db.flush()

        stmt_sub = select(DbTableProfile).where(DbTableProfile.connection_id == config_id)
        res_sub = await db.execute(stmt_sub)
        existing_profiles = {p.table_name: p for p in res_sub.scalars().all()}

        active_table_names = {t["name"] for t in tables_info}

        for t_name in list(existing_profiles.keys()):
            if t_name not in active_table_names:
                await db.delete(existing_profiles[t_name])
                del existing_profiles[t_name]

        for t in tables_info:
            t_name = t["name"]
            t_type = t.get("type", "table")
            if t_name in existing_profiles:
                p = existing_profiles[t_name]
                if full_reset or p.status != 2:
                    p.status = 0
                    p.error_message = None
                p.table_type = t_type
            else:
                db.add(
                    DbTableProfile(
                        connection_id=config_id,
                        table_name=t_name,
                        table_type=t_type,
                        status=0,
                    )
                )

        await db.commit()
        background_tasks.add_task(DbProfileService.run_profiling_loop, config_id)
        return task

    @staticmethod
    async def cancel_profiling_task(db: AsyncSession, config_id: int) -> DbProfileTask:
        """用户主动中断进行中的摸排任务；已完成的表画像保留。"""
        task = await DbProfileService.get_task_status(db, config_id)
        if not task:
            raise ValueError("摸排任务不存在")
        if task.status != TASK_STATUS_RUNNING:
            raise ValueError("当前没有进行中的摸排任务")

        await db.execute(
            update(DbTableProfile)
            .where(
                DbTableProfile.connection_id == config_id,
                DbTableProfile.status == 1,
            )
            .values(status=0, error_message=None)
        )
        task.status = TASK_STATUS_CANCELLED
        task.current_table = None
        task.error_message = "用户主动中断摸排"
        await db.commit()
        await db.refresh(task)
        logger.info("[DbProfiling] Profiling task cancelled by user for connection_id=%s", config_id)
        return task

    @staticmethod
    async def get_task_status(db: AsyncSession, config_id: int) -> Optional[DbProfileTask]:
        """获取该数据源当前摸排任务进度与状态"""
        stmt = select(DbProfileTask).where(DbProfileTask.connection_id == config_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_task_status_display(
        db: AsyncSession, config_id: int
    ) -> Optional[DbProfileTask]:
        """获取任务状态并在读取时校正僵尸/漏标完成的主任务。"""
        task = await DbProfileService.get_task_status(db, config_id)
        if not task:
            return None
        return await DbProfileService.reconcile_profiling_task_status(db, config_id, commit=True)

    @staticmethod
    async def _get_profile_status_counts(
        db: AsyncSession, config_id: int
    ) -> Dict[int, int]:
        res = await db.execute(
            select(DbTableProfile.status, func.count())
            .where(DbTableProfile.connection_id == config_id)
            .group_by(DbTableProfile.status)
        )
        return {int(status): int(count) for status, count in res.all()}

    @staticmethod
    async def reconcile_profiling_task_status(
        db: AsyncSession,
        config_id: int,
        *,
        commit: bool = True,
    ) -> Optional[DbProfileTask]:
        """
        校正主任务与表级状态，解决大库摸排末尾进程重启导致「画像已全部入库但主任务仍显示进行中」的问题。
        """
        task = await DbProfileService.get_task_status(db, config_id)
        if not task or task.status != TASK_STATUS_RUNNING:
            return task

        counts = await DbProfileService._get_profile_status_counts(db, config_id)
        pending = counts.get(0, 0)
        running = counts.get(1, 0)
        success = counts.get(2, 0)
        failed = counts.get(3, 0)
        finished = success + failed

        if running > 0 and DbProfileService._is_task_stale(task):
            await db.execute(
                update(DbTableProfile)
                .where(
                    DbTableProfile.connection_id == config_id,
                    DbTableProfile.status == 1,
                )
                .values(status=0, error_message=None)
            )
            pending += running
            running = 0
            logger.warning(
                "[DbProfiling] Reset %s stale in-progress table(s) to pending for connection_id=%s",
                counts.get(1, 0),
                config_id,
            )

        if pending == 0 and running == 0 and finished > 0:
            task.status = TASK_STATUS_DONE
            task.processed_tables = finished
            task.current_table = None
            task.error_message = None
            if commit:
                await db.commit()
                await db.refresh(task)
            logger.info(
                "[DbProfiling] Reconciled task to DONE for connection_id=%s "
                "(success=%s, failed=%s, total=%s)",
                config_id,
                success,
                failed,
                task.total_tables,
            )
            return task

        return task

    @staticmethod
    async def _finalize_profiling_task(config_id: int):
        """后台循环退出时尽力将主任务标记为完成（幂等）。"""
        try:
            async with AsyncSessionLocal() as db:
                await DbProfileService.reconcile_profiling_task_status(db, config_id, commit=True)
        except Exception:
            logger.exception(
                "[DbProfiling] Failed to finalize profiling task for connection_id=%s",
                config_id,
            )

    @staticmethod
    def _apply_profile_filters(
        stmt,
        *,
        q: Optional[str] = None,
        tag: Optional[str] = None,
        is_ignored: Optional[int] = None,
        status: Optional[int] = None,
        dialect_name: str = "mysql",
    ):
        if q and q.strip():
            like_q = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    DbTableProfile.table_name.like(like_q),
                    DbTableProfile.ai_term.like(like_q),
                    DbTableProfile.ai_description.like(like_q),
                )
            )
        if tag and tag.strip():
            normalized_tag = tag.strip()
            if DbProfileService._is_postgresql_dialect(dialect_name):
                stmt = stmt.where(
                    DbTableProfile.ai_tags.op("@>")(cast([normalized_tag], JSONB))
                )
            else:
                stmt = stmt.where(
                    func.json_contains(DbTableProfile.ai_tags, f'"{normalized_tag}"')
                )
        if is_ignored is not None:
            stmt = stmt.where(DbTableProfile.is_ignored == is_ignored)
        if status is not None:
            stmt = stmt.where(DbTableProfile.status == status)
        return stmt

    @staticmethod
    def _normalize_page(page: int, page_size: int) -> Tuple[int, int]:
        page = max(int(page or 1), 1)
        page_size = min(max(int(page_size or DEFAULT_PROFILE_PAGE_SIZE), 1), MAX_PROFILE_PAGE_SIZE)
        return page, page_size

    @staticmethod
    def _apply_profile_order(
        stmt,
        *,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        q: Optional[str] = None,
    ):
        """列表排序：支持默认/相关度/可信度/表名/中文术语。"""
        sort_key = (sort_by or "default").strip().lower()
        order_key = (sort_order or "desc").strip().lower()
        if order_key not in ("asc", "desc"):
            order_key = "desc"
        q_clean = (q or "").strip()

        if sort_key in ("default", "relevance") and q_clean:
            like = f"%{q_clean}%"
            prefix = f"{q_clean}%"
            relevance = case(
                (DbTableProfile.table_name == q_clean, 0),
                (DbTableProfile.table_name.like(prefix), 1),
                (DbTableProfile.ai_term.like(like), 2),
                (DbTableProfile.ai_description.like(like), 3),
                else_=5,
            )
            return stmt.order_by(
                relevance.asc(),
                DbTableProfile.confidence_score.desc(),
                DbTableProfile.table_name.asc(),
            )

        if sort_key == "default":
            return stmt.order_by(
                DbTableProfile.confidence_score.desc(),
                DbTableProfile.table_name.asc(),
            )

        if sort_key in ("confidence", "confidence_score"):
            primary = (
                DbTableProfile.confidence_score.desc()
                if order_key == "desc"
                else DbTableProfile.confidence_score.asc()
            )
            return stmt.order_by(primary, DbTableProfile.table_name.asc())

        if sort_key in ("term", "ai_term"):
            primary = (
                DbTableProfile.ai_term.asc()
                if order_key == "asc"
                else DbTableProfile.ai_term.desc()
            )
            return stmt.order_by(primary, DbTableProfile.table_name.asc())

        primary = (
            DbTableProfile.table_name.desc()
            if order_key == "desc"
            else DbTableProfile.table_name.asc()
        )
        return stmt.order_by(primary, DbTableProfile.table_name.asc())

    @staticmethod
    async def get_table_profile_stats(
        db: AsyncSession, config_id: int
    ) -> DbTableProfileStatsResponse:
        """聚合统计与标签分布，供大库概览面板使用。"""
        base_filter = DbTableProfile.connection_id == config_id
        dialect_name = DbProfileService._session_dialect_name(db)

        total_res = await db.execute(
            select(func.count()).select_from(DbTableProfile).where(base_filter)
        )
        total = int(total_res.scalar() or 0)

        table_res = await db.execute(
            select(func.count())
            .select_from(DbTableProfile)
            .where(base_filter, DbTableProfile.table_type != "view")
        )
        table_count = int(table_res.scalar() or 0)

        view_res = await db.execute(
            select(func.count())
            .select_from(DbTableProfile)
            .where(base_filter, DbTableProfile.table_type == "view")
        )
        view_count = int(view_res.scalar() or 0)

        success_res = await db.execute(
            select(func.count())
            .select_from(DbTableProfile)
            .where(base_filter, DbTableProfile.status == 2)
        )
        success_count = int(success_res.scalar() or 0)

        importable_res = await db.execute(
            select(func.count())
            .select_from(DbTableProfile)
            .where(base_filter, DbTableProfile.status == 2, DbTableProfile.is_ignored == 0)
        )
        importable_success_count = int(importable_res.scalar() or 0)

        ignored_res = await db.execute(
            select(func.count())
            .select_from(DbTableProfile)
            .where(base_filter, DbTableProfile.status == 2, DbTableProfile.is_ignored == 1)
        )
        ignored_count = int(ignored_res.scalar() or 0)

        field_res = await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        DbProfileService._profile_field_count_expression(dialect_name)
                    ),
                    0,
                )
            )
            .select_from(DbTableProfile)
            .where(base_filter, DbTableProfile.columns_profile.isnot(None))
        )
        field_count = int(field_res.scalar() or 0)

        tag_rows = await db.execute(
            select(DbTableProfile.ai_tags).where(base_filter, DbTableProfile.status == 2)
        )
        tag_counts: Dict[str, int] = {}
        for (tags,) in tag_rows.all():
            if not isinstance(tags, list):
                continue
            for raw_tag in tags:
                if not raw_tag or not str(raw_tag).strip():
                    continue
                name = str(raw_tag).strip()
                tag_counts[name] = tag_counts.get(name, 0) + 1

        tags = [
            DbTableProfileTagStat(name=name, count=count)
            for name, count in sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))
        ]

        last_profiled_at = None
        if success_count > 0:
            last_res = await db.execute(
                select(func.max(DbTableProfile.updated_at)).where(
                    base_filter, DbTableProfile.status == 2
                )
            )
            last_profiled_at = last_res.scalar()
            task = await DbProfileService.get_task_status(db, config_id)
            if task and task.status == TASK_STATUS_DONE and task.updated_at:
                last_profiled_at = task.updated_at

        return DbTableProfileStatsResponse(
            total=total,
            table_count=table_count,
            view_count=view_count,
            field_count=field_count,
            success_count=success_count,
            importable_success_count=importable_success_count,
            ignored_count=ignored_count,
            last_profiled_at=last_profiled_at,
            tags=tags,
        )

    @staticmethod
    async def list_table_profiles_page(
        db: AsyncSession,
        config_id: int,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PROFILE_PAGE_SIZE,
        q: Optional[str] = None,
        tag: Optional[str] = None,
        is_ignored: Optional[int] = None,
        status: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> DbTableProfilePageResponse:
        """分页返回表画像摘要（不含 ddl / sample_data / columns_profile）。"""
        page, page_size = DbProfileService._normalize_page(page, page_size)

        base = select(DbTableProfile).where(DbTableProfile.connection_id == config_id)
        base = DbProfileService._apply_profile_filters(
            base,
            q=q,
            tag=tag,
            is_ignored=is_ignored,
            status=status,
            dialect_name=DbProfileService._session_dialect_name(db),
        )

        count_res = await db.execute(select(func.count()).select_from(base.subquery()))
        total = int(count_res.scalar() or 0)
        pages = max((total + page_size - 1) // page_size, 1) if total else 0

        list_stmt = (
            base.options(
                load_only(
                    DbTableProfile.id,
                    DbTableProfile.connection_id,
                    DbTableProfile.table_name,
                    DbTableProfile.table_type,
                    DbTableProfile.engine,
                    DbTableProfile.ai_term,
                    DbTableProfile.ai_description,
                    DbTableProfile.ai_tags,
                    DbTableProfile.columns_profile,
                    DbTableProfile.status,
                    DbTableProfile.confidence_score,
                    DbTableProfile.is_temporary,
                    DbTableProfile.is_ignored,
                    DbTableProfile.confidence_reason,
                    DbTableProfile.error_message,
                    DbTableProfile.created_at,
                    DbTableProfile.updated_at,
                )
            )
        )
        list_stmt = DbProfileService._apply_profile_order(
            list_stmt, sort_by=sort_by, sort_order=sort_order, q=q
        ).offset((page - 1) * page_size).limit(page_size)
        res = await db.execute(list_stmt)
        profiles = res.scalars().all()

        items = [
            DbTableProfileSummaryResponse(
                id=p.id,
                connection_id=p.connection_id,
                table_name=p.table_name,
                table_type=p.table_type,
                engine=p.engine,
                ai_term=p.ai_term,
                ai_description=p.ai_description,
                ai_tags=p.ai_tags,
                columns_count=len(p.columns_profile) if isinstance(p.columns_profile, list) else 0,
                status=p.status,
                confidence_score=p.confidence_score,
                is_temporary=p.is_temporary,
                is_ignored=p.is_ignored,
                confidence_reason=p.confidence_reason,
                error_message=p.error_message,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in profiles
        ]

        return DbTableProfilePageResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    @staticmethod
    async def get_table_profile_detail(
        db: AsyncSession, config_id: int, table_name: str
    ) -> Optional[DbTableProfile]:
        """获取单表完整画像（含 ddl、样例、字段详情），供展开/详情使用。"""
        stmt = select(DbTableProfile).where(
            DbTableProfile.connection_id == config_id,
            DbTableProfile.table_name == table_name,
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def list_table_profiles(db: AsyncSession, config_id: int) -> List[DbTableProfile]:
        """获取该数据源下已摸排/分析的表画像列表（兼容旧调用，不建议大库使用）。"""
        stmt = (
            select(DbTableProfile)
            .where(DbTableProfile.connection_id == config_id)
            .order_by(DbTableProfile.table_name)
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def run_profiling_loop(config_id: int):
        """后台摸排主循环。相同列定义只问一次模型，最多 4 张表同时进行。"""
        logger.info("[DbProfiling] Starting background profiling task for connection_id: %s", config_id)
        processed_count = 0
        total_tables = 0

        try:
            async with AsyncSessionLocal() as db:
                config = await DbConnectionService.get_config(db, config_id)
                if not config:
                    logger.error("[DbProfiling] DB Config %s not found, exiting.", config_id)
                    return

                task = await DbProfileService.get_task_status(db, config_id)
                if not task or task.status != TASK_STATUS_RUNNING:
                    logger.warning("[DbProfiling] Task not in running state, exiting.")
                    return

                stmt = (
                    select(DbTableProfile)
                    .where(
                        DbTableProfile.connection_id == config_id,
                        DbTableProfile.status == 0,
                    )
                    .order_by(DbTableProfile.table_name)
                )
                res = await db.execute(stmt)
                pending_profiles = res.scalars().all()
                pending_tables = [
                    {"table_name": p.table_name, "table_type": p.table_type}
                    for p in pending_profiles
                ]
                processed_count = int(task.processed_tables or 0)

            total_tables = len(pending_tables) + processed_count
            logger.info(
                "[DbProfiling] Connection %s: %s tables pending, %s already completed",
                config_id,
                len(pending_tables),
                processed_count,
            )

            db_config = {
                "host": config.host,
                "port": config.port,
                "user": config.db_user,
                "password": config.password,
                "database": config.database_name,
            }
            db_type = config.db_type.strip().lower()

            from app.core.llm.client import get_llm_async
            from app.services.data_adapter.factory import get_adapter

            adapter = await get_adapter(config.name)
            llm = await get_llm_async(
                streaming=False,
                temperature=0,
                thinking_enable=False,
                ignore_session_reasoning_overrides=True,
            )
            if llm is None:
                raise RuntimeError("摸排模型初始化失败")

            ddl_lock = asyncio.Lock()
            cache_lock = asyncio.Lock()
            progress_lock = asyncio.Lock()
            schema_cache: Dict[str, Dict[str, Any]] = {}
            schema_inflight: Dict[str, asyncio.Future] = {}
            progress = {"finished": processed_count, "stop": False}
            semaphore = asyncio.Semaphore(PROFILE_CONCURRENCY)
            is_postgresql = db_type in DBImportService._postgresql_type_aliases()

            async def _profile_one(table: Dict[str, Any]) -> None:
                if progress["stop"] or await DbProfileService._should_stop_profiling(config_id):
                    progress["stop"] = True
                    return

                table_name = table["table_name"]
                table_type = table.get("table_type", "table")
                logger.info("[DbProfiling] Profiling table: %s", table_name)
                await DbProfileService._mark_table_running(config_id, table_name, None)

                try:
                    async with ddl_lock:
                        ddl = await ddl_session.get_table_ddl(table_name, table_type)
                    ddl = DbProfileService._truncate_ddl(ddl)
                    sample_data_json = await DbProfileService._fetch_sample_data(
                        adapter, db_type, table_name
                    )
                    signature, compact_schema = DbProfileService._column_signature(ddl)
                    cache_key = signature or f"table:{table_name}"
                    ai_res = await DbProfileService._llm_result_for_schema(
                        llm,
                        cache_key,
                        compact_schema or ddl,
                        sample_data_json,
                        schema_cache,
                        schema_inflight,
                        cache_lock,
                    )
                    ai_res = copy.deepcopy(ai_res)
                    if is_postgresql:
                        await DbProfileService._annotate_postgresql_partition(
                            adapter, table_name, ai_res
                        )

                    llm_score, llm_temp, llm_reason, is_ignored = (
                        DbProfileService._post_process_scores(
                            ai_res, sample_data_json, table_name
                        )
                    )
                    async with progress_lock:
                        progress["finished"] += 1
                        finished = progress["finished"]

                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            update(DbTableProfile)
                            .where(
                                DbTableProfile.connection_id == config_id,
                                DbTableProfile.table_name == table_name,
                            )
                            .values(
                                ddl=ddl,
                                sample_data=sample_data_json,
                                ai_term=ai_res.get("ai_term"),
                                ai_description=ai_res.get("ai_description"),
                                ai_tags=ai_res.get("ai_tags"),
                                columns_profile=ai_res.get("columns"),
                                confidence_score=llm_score,
                                is_temporary=llm_temp,
                                is_ignored=is_ignored,
                                confidence_reason=llm_reason.strip("; "),
                                status=2,
                                error_message=None,
                            )
                        )
                        await db.execute(
                            update(DbProfileTask)
                            .where(DbProfileTask.connection_id == config_id)
                            .values(
                                processed_tables=finished,
                                current_table=table_name,
                            )
                        )
                        await db.commit()
                    logger.info(
                        "[DbProfiling] [%s/%s] Finished table: %s",
                        finished,
                        total_tables,
                        table_name,
                    )
                except Exception as ex_item:
                    logger.exception("[DbProfiling] Table %s profiling failed", table_name)
                    async with progress_lock:
                        progress["finished"] += 1
                        finished = progress["finished"]
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            update(DbTableProfile)
                            .where(
                                DbTableProfile.connection_id == config_id,
                                DbTableProfile.table_name == table_name,
                            )
                            .values(status=3, error_message=str(ex_item))
                        )
                        await db.execute(
                            update(DbProfileTask)
                            .where(DbProfileTask.connection_id == config_id)
                            .values(
                                processed_tables=finished,
                                current_table=table_name,
                            )
                        )
                        await db.commit()

            async def _profile_limited(table: Dict[str, Any]) -> None:
                async with semaphore:
                    await _profile_one(table)

            async with DbDdlSession(db_type, db_config) as ddl_session:
                await asyncio.gather(*[_profile_limited(table) for table in pending_tables])

            async with AsyncSessionLocal() as db:
                task = await DbProfileService.get_task_status(db, config_id)
                if not task or task.status != TASK_STATUS_RUNNING:
                    logger.info(
                        "[DbProfiling] Task ended early (status=%s) for connection_id=%s",
                        getattr(task, "status", None),
                        config_id,
                    )
                    return

                await db.execute(
                    update(DbProfileTask)
                    .where(DbProfileTask.connection_id == config_id)
                    .values(
                        status=TASK_STATUS_DONE,
                        processed_tables=task.total_tables,
                        current_table=None,
                        error_message=None,
                    )
                )
                await db.commit()

            logger.info(
                "[DbProfiling] Finished background profiling task for connection_id: %s",
                config_id,
            )

        except Exception as total_ex:
            logger.exception(
                "[DbProfiling] Fatal error in profiling task for config %s", config_id
            )
            async with AsyncSessionLocal() as db:
                task = await DbProfileService.get_task_status(db, config_id)
                if task and task.status == TASK_STATUS_RUNNING:
                    await db.execute(
                        update(DbProfileTask)
                        .where(DbProfileTask.connection_id == config_id)
                        .values(
                            status=TASK_STATUS_ERROR,
                            error_message=str(total_ex),
                            current_table=None,
                        )
                    )
                    await db.commit()
        finally:
            await DbProfileService._finalize_profiling_task(config_id)

    @staticmethod
    def _is_task_stale(task: DbProfileTask) -> bool:
        updated_at = task.updated_at or task.created_at
        if not updated_at:
            return True
        return datetime.now() - updated_at > timedelta(minutes=STALE_TASK_MINUTES)

    @staticmethod
    async def _should_stop_profiling(config_id: int) -> bool:
        async with AsyncSessionLocal() as db:
            task = await DbProfileService.get_task_status(db, config_id)
            return not task or task.status != TASK_STATUS_RUNNING

    @staticmethod
    async def _mark_table_running(
        config_id: int,
        table_name: str,
        processed_tables: Optional[int],
    ):
        task_values: Dict[str, Any] = {"current_table": table_name}
        if processed_tables is not None:
            task_values["processed_tables"] = processed_tables
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(DbProfileTask)
                .where(DbProfileTask.connection_id == config_id)
                .values(**task_values)
            )
            await db.execute(
                update(DbTableProfile)
                .where(
                    DbTableProfile.connection_id == config_id,
                    DbTableProfile.table_name == table_name,
                )
                .values(status=1)
            )
            await db.commit()

    @staticmethod
    def _extract_column_names(columns: Any) -> List[str]:
        names: List[str] = []
        for col in columns or []:
            if isinstance(col, dict):
                names.append(str(col.get("name", "")))
            else:
                names.append(str(col))
        return names

    @staticmethod
    def _extract_result_rows(result: Dict[str, Any]) -> List[List[Any]]:
        rows = result.get("rows")
        if rows is None:
            rows = result.get("items")
        return rows or []

    @staticmethod
    def _sanitize_sample_value(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, str):
            if len(val) > MAX_SAMPLE_FIELD_CHARS:
                return val[:MAX_SAMPLE_FIELD_CHARS] + "..."
            return val
        if isinstance(val, (dict, list, int, float, bool)):
            text = json.dumps(val, ensure_ascii=False)
            if len(text) > MAX_SAMPLE_FIELD_CHARS:
                return text[:MAX_SAMPLE_FIELD_CHARS] + "..."
            return val
        text = str(val)
        if len(text) > MAX_SAMPLE_FIELD_CHARS:
            return text[:MAX_SAMPLE_FIELD_CHARS] + "..."
        return text

    @staticmethod
    def _quote_postgresql_name(table_name: str) -> str:
        parts = [p.strip().strip('"').strip("`") for p in table_name.split(".")]
        return ".".join(f'"{p.replace(chr(34), chr(34) * 2)}"' for p in parts if p)

    @staticmethod
    async def _postgresql_sample_sql(adapter, table_name: str) -> str:
        """分区表只抽样一个叶子分区，避免 LIMIT 仍去打开全部分区。"""
        from app.services.data_adapter.postgresql import POSTGRESQL_LEAF_PARTITION_SQL

        qualified = DbProfileService._quote_postgresql_name(table_name)
        parts = [p.strip().strip('"').strip("`") for p in table_name.split(".") if p.strip()]
        if len(parts) >= 2:
            schema_name, physical_name = parts[-2], parts[-1]
        else:
            schema_name, physical_name = "public", parts[0] if parts else ""
        if not physical_name:
            return f"SELECT * FROM {qualified} LIMIT 3"
        try:
            sample_res = await adapter.execute_sql(
                POSTGRESQL_LEAF_PARTITION_SQL,
                (schema_name, physical_name),
            )
            rows = DbProfileService._extract_result_rows(sample_res)
            if rows and rows[0] and rows[0][0] and rows[0][1]:
                leaf = DbProfileService._quote_postgresql_name(f"{rows[0][0]}.{rows[0][1]}")
                logger.info("[DbProfiling] Sample partitioned table %s from leaf %s", table_name, leaf)
                return f"SELECT * FROM {leaf} LIMIT 3"
        except Exception as exc:
            logger.warning("[DbProfiling] 定位分区叶子失败 %s: %s", table_name, exc)
        return f"SELECT * FROM {qualified} LIMIT 3"

    @staticmethod
    async def _fetch_sample_data(adapter, db_type: str, table_name: str) -> str:
        quote = "`" if db_type in ("mysql", "clickhouse") else '"'
        if db_type == "oracle":
            query_sql = f'SELECT * FROM {quote}{table_name}{quote} WHERE ROWNUM <= 3'
        elif db_type in ("sqlserver", "mssql") or db_type in DBImportService._sqlserver_type_aliases():
            query_sql = f"SELECT TOP 3 * FROM {quote}{table_name}{quote}"
        elif db_type in DBImportService._postgresql_type_aliases():
            query_sql = await DbProfileService._postgresql_sample_sql(adapter, table_name)
        else:
            query_sql = f"SELECT * FROM {quote}{table_name}{quote} LIMIT 3"

        try:
            sample_res = await adapter.execute_sql(query_sql)
            rows = DbProfileService._extract_result_rows(sample_res)
            col_names = DbProfileService._extract_column_names(sample_res.get("columns", []))

            sample_dicts = []
            for row in rows:
                sanitized = [DbProfileService._sanitize_sample_value(v) for v in row]
                sample_dicts.append(dict(zip(col_names, sanitized)))

            return json.dumps(sample_dicts, ensure_ascii=False)
        except Exception as ex_sample:
            logger.warning(
                "[DbProfiling] Failed to fetch sample data for %s: %s", table_name, ex_sample
            )
            return "[]"

    @staticmethod
    def _truncate_ddl(ddl: str) -> str:
        if not ddl or len(ddl) <= MAX_DDL_CHARS:
            return ddl or ""
        return ddl[:MAX_DDL_CHARS] + "\n-- ... DDL truncated ..."

    @staticmethod
    def _column_signature(ddl: str) -> Tuple[str, str]:
        """列名加类型完全一致时返回同一签名。解析失败时签名为空，避免误复用。"""
        types = DbProfileService._parse_column_types_from_ddl(ddl)
        if not types:
            return "", ""
        lines = [f"{name} {typ}" for name, typ in types.items()]
        compact = "\n".join(lines)
        return compact, compact

    @staticmethod
    async def _llm_result_for_schema(
        llm: Any,
        cache_key: str,
        schema_text: str,
        sample_data_json: str,
        schema_cache: Dict[str, Dict[str, Any]],
        schema_inflight: Dict[str, asyncio.Future],
        cache_lock: asyncio.Lock,
    ) -> Dict[str, Any]:
        """同一套字段只发起一次模型调用，其余表等待并复用结果。"""
        owner = False
        future: Optional[asyncio.Future] = None
        async with cache_lock:
            cached = schema_cache.get(cache_key)
            if cached is not None:
                logger.info("[DbProfiling] Reuse schema profile: %s", cache_key.split("\n", 1)[0])
                return cached
            future = schema_inflight.get(cache_key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                schema_inflight[cache_key] = future
                owner = True
        if not owner:
            return await future

        try:
            ai_res = await DbProfileService._analyze_table_with_llm(
                llm, schema_text, sample_data_json
            )
            stored = copy.deepcopy(ai_res)
            async with cache_lock:
                schema_cache[cache_key] = stored
                schema_inflight.pop(cache_key, None)
            if not future.done():
                future.set_result(stored)
            return stored
        except Exception as exc:
            async with cache_lock:
                schema_inflight.pop(cache_key, None)
            if future is not None and not future.done():
                future.set_exception(exc)
                future.exception()
            raise

    @staticmethod
    def _post_process_scores(
        ai_res: Dict[str, Any], sample_data_json: str, table_name: str
    ) -> tuple[int, int, str, int]:
        llm_score = ai_res.get("confidence_score")
        if llm_score is None:
            llm_score = 100
        try:
            llm_score = int(llm_score)
        except (ValueError, TypeError):
            llm_score = 90

        llm_temp = 1 if ai_res.get("is_temporary") is True else 0
        llm_reason = ai_res.get("confidence_reason") or ""

        is_sample_empty = False
        try:
            parsed_samples = json.loads(sample_data_json)
            if not parsed_samples:
                is_sample_empty = True
        except Exception:
            is_sample_empty = True

        if is_sample_empty:
            llm_score = max(0, llm_score - 30)
            llm_reason += "; [特征检测] 样例数据为空，扣除30分"

        sensitive_patterns = [r"^tmp_", r"^temp_", r"_bak$", r"_bak_", r"^test_"]
        is_name_sensitive = any(re.search(pat, table_name.lower()) for pat in sensitive_patterns)
        if is_name_sensitive:
            llm_score = max(0, llm_score - 40)
            llm_temp = 1
            llm_reason += "; [特征检测] 表名匹配临时/备份敏感词，扣除40分"

        llm_score = min(100, max(0, llm_score))
        is_ignored = 1 if (llm_score < 60 or llm_temp == 1) else 0
        return llm_score, llm_temp, llm_reason, is_ignored

    @staticmethod
    async def _analyze_table_with_llm(
        llm: Any,
        schema_text: str,
        sample_data_json: str,
    ) -> Dict[str, Any]:
        """用已经创建好的模型解析一张表的列定义。"""
        system_prompt = (
            "你是一个精通数据资产治理的数据库专家，擅长从列定义和样例数据中提炼业务元数据含义。\n"
            "请根据【列名和类型】和【真实样例数据】，推测该表的中文业务术语、一句话用途、分类标签，以及每个字段的中文术语和一行业务描述。\n"
            "同时评估该表对于业务分析的置信度，以及它是否属于临时/低价值/中间关联表。\n\n"
            "【置信度与临时表评估标准】\n"
            "1. 若列定义和样例数据表明该表主要为关联ID中间映射、临时缓存、系统备份，或样例缺乏真实语义，应标记 is_temporary 为 true，置信度评分低于 60 分。\n"
            "2. 若包含有意义的业务属性、主数据维度或事实度量，应标记 is_temporary 为 false，置信度评分应为 80-100 分。\n"
            "3. 需给出客观、具体的评分理由（confidence_reason）。\n\n"
            "【重要约束】\n"
            "1. 必须只返回一个 JSON 对象，不要 Markdown，不要多余解释。\n"
            "2. ai_description 不超过 120 字，每个字段 desc 不超过 40 字。\n"
            "3. 返回的 JSON 必须符合以下 Schema 结构：\n"
            "{\n"
            '  "ai_term": "表的中文业务备注名，不超过100字，如: 机房能耗天报表",\n'
            '  "ai_description": "该表真实的业务用途与功能描述，不超过500字",\n'
            '  "ai_tags": ["标签1", "标签2"],\n'
            '  "confidence_score": 85,\n'
            '  "is_temporary": false,\n'
            '  "confidence_reason": "评分和临时表认定的理由说明，不超过200字，如: 结构完整且含真实指标数据，但主键不明确扣减10分",\n'
            '  "columns": [\n'
            "    {\n"
            '      "name": "字段物理列名，如 room_id",\n'
            '      "term": "字段的中文业务术语/备注名，如 机房ID",\n'
            '      "desc": "该字段的业务解释描述"\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )

        user_prompt = f"【列名和类型】:\n{schema_text}\n\n【样例数据】:\n{sample_data_json}"

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        raw_text = getattr(response, "content", "") or str(response)
        return DbProfileService._extract_json(raw_text)

    @staticmethod
    async def _annotate_postgresql_partition(adapter, table_name: str, ai_res: Dict[str, Any]) -> None:
        """把分区键写进表画像，后续问数能看到必须按该字段限定范围。"""
        if not isinstance(ai_res, dict):
            return
        parts = [p.strip().strip('"').strip("`") for p in str(table_name or "").split(".") if p.strip()]
        if len(parts) >= 2:
            physical_name = parts[-1]
        elif parts:
            physical_name = parts[0]
        else:
            return
        try:
            partition_keys = await adapter.lookup_partition_keys([physical_name])
        except Exception as exc:
            logger.warning("[DbProfiling] 读取分区键失败 %s: %s", table_name, exc)
            return
        columns = None
        if len(parts) >= 2:
            columns = partition_keys.get((parts[-2].lower(), physical_name.lower()))
        if not columns:
            columns = partition_keys.get(("public", physical_name.lower()))
        if not columns:
            matched = [
                cols for (schema_name, name), cols in partition_keys.items()
                if name == physical_name.lower()
            ]
            columns = matched[0] if matched else []
        if not columns:
            return
        shown = "、".join(columns)
        note = (
            f"该表按 {shown} 分区。查询必须在 WHERE 中传入闭合时间范围。"
            "按日分区最多跨 31 个分区，按月分区最多跨 3 个分区，避免扫描全部分区。"
        )
        description = str(ai_res.get("ai_description") or "").strip()
        if "分区" not in description:
            ai_res["ai_description"] = f"{description} {note}".strip()
        key_names = {name.lower() for name in columns}
        profile_columns = ai_res.get("columns")
        if not isinstance(profile_columns, list):
            return
        for column in profile_columns:
            if not isinstance(column, dict):
                continue
            if str(column.get("name") or "").strip().lower() not in key_names:
                continue
            column_desc = str(column.get("desc") or "").strip()
            if "分区键" in column_desc:
                continue
            column["desc"] = (
                f"{column_desc} 分区键。按日或按月分区时必须传入闭合起止时间："
                "按日最多跨 31 个分区，按月最多跨 3 个分区，不要套函数。"
            ).strip()

    @staticmethod
    def _extract_json(raw: str) -> Dict[str, Any]:
        """提取并解析返回的 JSON 内容"""
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```json") or lines[0].startswith("```"):
                text = "\n".join(lines[1:-1]).strip()
        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                raise ValueError(f"大模型返回内容无法解析为JSON: {raw}")
            return json.loads(match.group())

    @staticmethod
    def _parse_column_types_from_ddl(ddl: Optional[str]) -> Dict[str, str]:
        """从建表 DDL 粗解析列名与类型，供导入预览补全字段类型。"""
        if not ddl:
            return {}
        types: Dict[str, str] = {}
        skip_prefixes = (
            "PRIMARY", "KEY", "UNIQUE", "CONSTRAINT", "INDEX", "FOREIGN", "COMMENT", "--", "/*",
        )

        def _split_ddl_segments(body: str) -> List[str]:
            segments: List[str] = []
            current: List[str] = []
            depth = 0
            for ch in body:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth = max(depth - 1, 0)
                if ch == "," and depth == 0:
                    segment = "".join(current).strip()
                    if segment:
                        segments.append(segment)
                    current = []
                else:
                    current.append(ch)
            tail = "".join(current).strip()
            if tail:
                segments.append(tail)
            return segments

        def _extract_from_segment(segment: str):
            line = segment.strip().rstrip(",")
            if not line or line.upper().startswith(skip_prefixes):
                return
            match = re.match(
                r'^[`"\[]?(\w+)[`"\]]?\s+([A-Za-z]+(?:\s*\([^)]*\))?)',
                line,
            )
            if match:
                types[match.group(1).lower()] = match.group(2).strip()

        body_match = re.search(
            r"CREATE\s+TABLE\s+[`\"\[]?\w+[`\"\]]?\s*\((.*)\)",
            ddl,
            re.IGNORECASE | re.DOTALL,
        )
        if body_match:
            for segment in _split_ddl_segments(body_match.group(1)):
                _extract_from_segment(segment)
            return types

        for raw_line in ddl.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.upper().startswith(("CREATE", ")", *skip_prefixes)):
                continue
            _extract_from_segment(line)
        return types

    @staticmethod
    def _profile_to_import_table(profile: DbTableProfile) -> Dict[str, Any]:
        source_table_name = str(profile.table_name or "").strip()
        display_table_name = source_table_name.rsplit(".", 1)[-1]
        ddl_types = DbProfileService._parse_column_types_from_ddl(profile.ddl)
        columns: List[Dict[str, Any]] = []
        for col in profile.columns_profile or []:
            if not isinstance(col, dict):
                continue
            physical_name = str(col.get("name") or "").strip()
            if not physical_name:
                continue
            columns.append(
                {
                    "physical_name": physical_name,
                    "term": str(col.get("term") or physical_name).strip(),
                    "type": ddl_types.get(physical_name.lower(), "varchar"),
                    "description": str(col.get("desc") or "").strip(),
                    "enums": [],
                    "synonyms": [],
                }
            )

        synonyms = list(profile.ai_tags or []) if isinstance(profile.ai_tags, list) else []
        return {
            "physical_name": display_table_name,
            "term": (profile.ai_term or display_table_name or "").strip(),
            "description": (profile.ai_description or "").strip(),
            "synonyms": synonyms,
            "columns": columns,
        }

    @staticmethod
    async def build_import_preview_from_profiles(
        db: AsyncSession,
        config_id: int,
        table_names: List[str],
    ) -> Dict[str, Any]:
        """
        将已摸排成功的表画像转换为元数据导入预览结构，避免导入时重复调用 LLM 分析。
        """
        if not table_names:
            raise ValueError("请至少选择一张表")

        normalized = []
        seen = set()
        for name in table_names:
            key = str(name or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(key)

        stmt = select(DbTableProfile).where(
            DbTableProfile.connection_id == config_id,
            DbTableProfile.table_name.in_(normalized),
        )
        res = await db.execute(stmt)
        profiles = {p.table_name: p for p in res.scalars().all()}

        missing = [name for name in normalized if name not in profiles]
        if missing:
            preview = ", ".join(missing[:5])
            suffix = f" 等 {len(missing)} 张" if len(missing) > 5 else ""
            raise ValueError(f"以下表尚无摸排画像，请先在数据源管理中完成摸排：{preview}{suffix}")

        not_ready = [
            name
            for name in normalized
            if profiles[name].status != 2 or not profiles[name].columns_profile
        ]
        if not_ready:
            preview = ", ".join(not_ready[:5])
            suffix = f" 等 {len(not_ready)} 张" if len(not_ready) > 5 else ""
            raise ValueError(f"以下表摸排未完成或缺少字段画像：{preview}{suffix}")

        tables = [
            DbProfileService._profile_to_import_table(profiles[name])
            for name in normalized
        ]
        return {
            "tables": tables,
            "metrics": [],
            "relationships": [],
            "_source": "db_table_profiles",
        }

    @staticmethod
    def _parse_profile_json_field(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return default
        return default

    @staticmethod
    def _profile_column_names(columns_profile: Any) -> List[str]:
        cols = DbProfileService._parse_profile_json_field(columns_profile, [])
        names: List[str] = []
        for col in cols:
            if isinstance(col, dict):
                name = col.get("name") or col.get("column_name")
                if name:
                    names.append(str(name))
        return names

    @staticmethod
    def _is_profile_link_column(col_name: str, col_term: str = "") -> bool:
        cn = (col_name or "").lower().strip()
        if not cn or cn == "id":
            return False
        if cn.endswith("_id") or (cn.endswith("id") and len(cn) > 3):
            return True
        if cn.endswith("_no") or (cn.endswith("no") and len(cn) > 4):
            return True
        if cn.endswith("_code"):
            return True
        term = col_term or ""
        return any(k in term for k in ("ID", "Id", "编号", "主键"))

    @staticmethod
    def _link_hints_from_column(col_name: str) -> List[str]:
        cn = (col_name or "").lower().strip()
        hints: List[str] = []
        if cn.endswith("_id"):
            hints.append(cn[:-3])
        elif cn.endswith("id") and len(cn) > 3:
            hints.append(cn[:-2])
        elif cn.endswith("_no"):
            hints.append(cn[:-3])
        elif cn.endswith("_code"):
            hints.append(cn[:-5])
        else:
            hints.append(cn)
        for part in re.split(r"[_]+", cn):
            if len(part) >= 3 and part not in ("id", "no", "code", "num", "key"):
                hints.append(part)
        out: List[str] = []
        seen: set[str] = set()
        for h in hints:
            h = h.strip()
            if len(h) >= 2 and h not in seen:
                seen.add(h)
                out.append(h)
        return out

    @staticmethod
    def _table_name_tokens(table_name: str) -> set[str]:
        base = (table_name or "").split(".")[-1].lower()
        return {p for p in re.split(r"[_]+", base) if len(p) >= 2}

    @staticmethod
    def _table_name_prefix(table_name: str, parts: int = 2) -> str:
        segs = (table_name or "").split(".")[-1].upper().split("_")
        segs = [s for s in segs if s]
        if not segs:
            return ""
        return "_".join(segs[:parts]) if len(segs) >= parts else segs[0]

    @staticmethod
    def _guess_join_hint(source_table: str, target_table: str, link_col: str, target_cols: List[str]) -> str:
        target_col_set = {c.lower() for c in target_cols}
        lc = link_col
        candidates = [lc, "ID", f"{target_table.split('.')[-1]}_ID", f"{target_table.split('.')[-1]}_id", "id"]
        tgt_field = next((c for c in candidates if c.lower() in target_col_set), "ID")
        actual_tgt = next((c for c in target_cols if c.lower() == tgt_field.lower()), tgt_field)
        return f"LEFT JOIN {target_table} ON {source_table}.{lc} = {target_table}.{actual_tgt}"

    @staticmethod
    async def get_related_tables(
        db: AsyncSession,
        config_id: int,
        table_name: str,
        limit: int = 15,
    ) -> Dict[str, Any]:
        """基于摸排画像推断可能关联的表（不依赖 meta_relationships）"""
        limit = min(max(int(limit), 1), 30)
        table_name = (table_name or "").strip()
        if not table_name:
            return {"source_table": "", "items": [], "message": "未指定表名"}

        stmt = select(DbTableProfile).where(
            DbTableProfile.connection_id == config_id,
            DbTableProfile.status == 2,
            DbTableProfile.is_ignored == 0,
        )
        res = await db.execute(stmt)
        rows = res.scalars().all()

        profiles: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            tname = row.table_name
            if not tname:
                continue
            profiles[tname] = {
                "table_name": tname,
                "ai_term": row.ai_term,
                "ai_description": row.ai_description,
                "ai_tags": DbProfileService._parse_profile_json_field(row.ai_tags, []),
                "columns_profile": DbProfileService._parse_profile_json_field(row.columns_profile, []),
                "confidence_score": row.confidence_score,
                "is_temporary": bool(row.is_temporary),
            }

        source = profiles.get(table_name)
        if not source:
            return {
                "source_table": table_name,
                "items": [],
                "message": "该表尚未完成摸排或已被忽略，无法推荐关联表",
            }

        source_tags = set(source.get("ai_tags") or [])
        source_prefix = DbProfileService._table_name_prefix(table_name)
        scores: Dict[str, Dict[str, Any]] = {}

        def bump(target: str, amount: float, reason: str, match_type: str, join_hint: Optional[str] = None) -> None:
            if target == table_name or target not in profiles:
                return
            entry = scores.setdefault(
                target,
                {"score": 0.0, "reasons": [], "match_types": set(), "join_hint": None},
            )
            entry["score"] += amount
            if reason and reason not in entry["reasons"]:
                entry["reasons"].append(reason)
            entry["match_types"].add(match_type)
            if join_hint and not entry["join_hint"]:
                entry["join_hint"] = join_hint

        for col in source.get("columns_profile") or []:
            if not isinstance(col, dict):
                continue
            col_name = str(col.get("name") or col.get("column_name") or "")
            col_term = str(col.get("term") or "")
            if not DbProfileService._is_profile_link_column(col_name, col_term):
                continue
            hints = DbProfileService._link_hints_from_column(col_name)
            for other_name, other in profiles.items():
                if other_name == table_name or other.get("is_temporary"):
                    continue
                other_lower = other_name.lower()
                other_tokens = DbProfileService._table_name_tokens(other_name)
                other_cols = DbProfileService._profile_column_names(other.get("columns_profile"))
                other_col_set = {c.lower() for c in other_cols}
                matched_hint = None
                for hint in hints:
                    if hint in other_lower or hint in other_tokens:
                        matched_hint = hint
                        break
                if not matched_hint:
                    continue
                has_pk = bool(other_col_set & {"id", matched_hint, f"{matched_hint}_id", col_name.lower()})
                score = 0.55 if has_pk else 0.4
                join_hint = DbProfileService._guess_join_hint(table_name, other_name, col_name, other_cols)
                bump(
                    other_name,
                    score,
                    f"字段 {col_name} 与表 {other_name} 名称/主键推断相关",
                    "column",
                    join_hint,
                )

        for other_name, other in profiles.items():
            if other_name == table_name or other.get("is_temporary"):
                continue
            other_tags = set(other.get("ai_tags") or [])
            overlap = source_tags & other_tags
            if overlap:
                tag_str = "、".join(sorted(overlap)[:3])
                bump(
                    other_name,
                    0.12 + 0.06 * min(len(overlap), 4),
                    f"共享标签「{tag_str}」",
                    "tag",
                )

        if source_prefix:
            for other_name, other in profiles.items():
                if other_name == table_name or other.get("is_temporary"):
                    continue
                if DbProfileService._table_name_prefix(other_name) == source_prefix:
                    bump(other_name, 0.2, f"同模块前缀 {source_prefix}", "prefix")

        source_token = table_name.split(".")[-1].lower()
        for other_name, other in profiles.items():
            if other_name == table_name or other.get("is_temporary"):
                continue
            for oc in DbProfileService._profile_column_names(other.get("columns_profile")):
                ol = oc.lower()
                if source_token in ol or any(h in ol for h in DbProfileService._link_hints_from_column(source_token)):
                    bump(other_name, 0.25, f"表 {other_name} 含关联字段 {oc}", "column")
                    break

        ranked = sorted(scores.items(), key=lambda x: -x[1]["score"])
        items: List[Dict[str, Any]] = []
        for other_name, meta in ranked[:limit]:
            other = profiles[other_name]
            conf = min(0.95, max(0.35, round(meta["score"], 2)))
            items.append({
                "table_name": other_name,
                "ai_term": other.get("ai_term"),
                "confidence": conf,
                "reason": "；".join(meta["reasons"][:2]),
                "join_hint": meta.get("join_hint"),
                "match_types": sorted(meta["match_types"]),
                "confidence_score": other.get("confidence_score"),
            })

        return {
            "source_table": table_name,
            "items": items,
            "message": None if items else "未发现明显关联表，可尝试搜索或按标签筛选",
        }

    @staticmethod
    async def toggle_ignore(
        db: AsyncSession,
        config_id: int,
        table_name: str,
        is_ignored: int,
    ) -> Optional[DbTableProfile]:
        """手动更改指定物理表的忽略状态"""
        stmt = select(DbTableProfile).where(
            DbTableProfile.connection_id == config_id,
            DbTableProfile.table_name == table_name,
        )
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()
        if not profile:
            return None
        profile.is_ignored = 1 if is_ignored == 1 else 0
        await db.commit()
        return profile

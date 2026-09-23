"""PostgreSQL data-source adapter and identifier helpers."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, time as datetime_time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import BaseLoader, Environment, Undefined
from psycopg import sql

from .base import DataSourceAdapter, SQLSafetyError, standardize_items
from .models import LogicalQuery, ResultSet


class SqlLabUndefined(Undefined):
    def __str__(self):
        return "NULL"

    def __html__(self):
        return "NULL"

    def __iter__(self):
        return iter([])

    def __bool__(self):
        return False


SQL_LAB_ENV = Environment(loader=BaseLoader(), undefined=SqlLabUndefined)
POSTGRESQL_TYPES = ("postgres", "postgresql", "pg")
# 分区子表在 information_schema 里也是 BASE TABLE。摸排和导入只保留父表，避免按月分区被拆成几百张。
POSTGRESQL_LIST_TABLES_SQL = """
    SELECT n.nspname AS table_schema,
           c.relname AS table_name,
           COALESCE(obj_description(c.oid, 'pg_class'), ''),
           CASE WHEN c.relkind = 'v' THEN 'VIEW' ELSE 'BASE TABLE' END AS table_type
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND c.relkind IN ('r', 'p', 'v', 'm')
      AND NOT EXISTS (
          SELECT 1 FROM pg_inherits i WHERE i.inhrelid = c.oid
      )
    ORDER BY n.nspname, c.relname
"""
POSTGRESQL_LEAF_PARTITION_SQL = """
    SELECT child_ns.nspname, child.relname
    FROM pg_inherits i
    JOIN pg_class parent ON parent.oid = i.inhparent
    JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
    JOIN pg_class child ON child.oid = i.inhrelid
    JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
    WHERE parent_ns.nspname = %s
      AND parent.relname = %s
      AND NOT EXISTS (
          SELECT 1 FROM pg_inherits nested WHERE nested.inhparent = child.oid
      )
    ORDER BY child.reltuples DESC NULLS LAST, child.relname DESC
    LIMIT 1
"""
# 只取分区键列。表达式分区没有 partattrs 时，回退解析 pg_get_partkeydef。
POSTGRESQL_PARTITION_KEYS_SQL = """
    SELECT n.nspname,
           c.relname,
           pg_get_partkeydef(c.oid),
           COALESCE(
               array_agg(a.attname::text ORDER BY u.ord) FILTER (WHERE a.attname IS NOT NULL),
               ARRAY[]::text[]
           )
    FROM pg_partitioned_table pt
    JOIN pg_class c ON c.oid = pt.partrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN LATERAL unnest(pt.partattrs) WITH ORDINALITY AS u(attnum, ord) ON TRUE
    LEFT JOIN pg_attribute a
      ON a.attrelid = c.oid
     AND a.attnum = u.attnum
     AND NOT a.attisdropped
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND c.relname = ANY(%s)
    GROUP BY n.nspname, c.relname, c.oid
"""
# 每个父表抽最近几个叶子分区的边界，用来判断按日还是按月。
POSTGRESQL_PARTITION_GRAIN_SQL = """
    SELECT schema_name, table_name, bound_expr, child_name
    FROM (
        SELECT parent_ns.nspname AS schema_name,
               parent.relname AS table_name,
               pg_get_expr(child.relpartbound, child.oid) AS bound_expr,
               child.relname AS child_name,
               row_number() OVER (
                   PARTITION BY parent.oid
                   ORDER BY child.relname DESC
               ) AS rn
        FROM pg_inherits i
        JOIN pg_class parent ON parent.oid = i.inhparent
        JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
        JOIN pg_class child ON child.oid = i.inhrelid
        WHERE parent_ns.nspname NOT IN ('pg_catalog', 'information_schema')
          AND parent.relname = ANY(%s)
          AND NOT EXISTS (
              SELECT 1 FROM pg_inherits nested WHERE nested.inhparent = child.oid
          )
    ) samples
    WHERE rn <= 4
"""
# 按日最多跨 31 个分区，按月最多跨 3 个分区。超过就会打开太多子表。
DAY_PARTITION_MAX_UNITS = 31
MONTH_PARTITION_MAX_UNITS = 3
logger = logging.getLogger(__name__)

_PARTKEY_IDENT_RE = re.compile(r'"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*)')
_PARTKEY_SKIP_WORDS = {
    "range", "list", "hash", "at", "time", "zone", "timestamp", "date", "and", "or",
}
_EXPLAIN_PREFIX_RE = re.compile(
    r"^\s*EXPLAIN\s+(?:ANALYZE\s+)?(?:VERBOSE\s+)?",
    re.IGNORECASE,
)
_PARTBOUND_RE = re.compile(
    r"FROM\s*\(\s*'([^']+)'\s*\)\s*TO\s*\(\s*'([^']+)'\s*\)",
    re.IGNORECASE,
)
_DAY_PARTITION_NAME_RE = re.compile(r"(?:_|-)(\d{4})[_-](\d{2})[_-](\d{2})$")
_MONTH_PARTITION_NAME_RE = re.compile(r"(?:_|-)(\d{4})[_-](\d{2})$")
_TIMESTAMP_SUFFIX_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def is_postgresql_type(db_type: str) -> bool:
    return str(db_type or "").strip().lower() in POSTGRESQL_TYPES


def columns_from_partkeydef(definition: str) -> List[str]:
    """从 ``RANGE (event_time)`` 这类分区定义里抽出字段名。"""
    columns: List[str] = []
    for quoted, bare in _PARTKEY_IDENT_RE.findall(str(definition or "")):
        name = quoted or bare
        if not name or name.lower() in _PARTKEY_SKIP_WORDS:
            continue
        if name not in columns:
            columns.append(name)
    return columns


def _select_from_clause(select: Any) -> Any:
    return select.args.get("from_") or select.args.get("from")


def _walk_predicate(node: Any):
    """遍历当前谓词，不进入子查询，避免把内层条件算到外层表上。"""
    from sqlglot import exp

    yield node
    for child in node.iter_expressions():
        if isinstance(child, (exp.Subquery, exp.Select, exp.Union, exp.CTE)):
            continue
        yield from _walk_predicate(child)


def _predicate_column(node: Any) -> Optional[Tuple[str, str]]:
    from sqlglot import exp

    if not isinstance(node, exp.Column):
        return None
    name = str(node.name or "").strip().strip('"')
    if not name:
        return None
    return (str(node.table or "").strip().strip('"').lower(), name.lower())


def _constrained_columns(select: Any) -> set[Tuple[str, str]]:
    """当前 SELECT 的 WHERE / JOIN 里，直接参与范围或等值比较的字段。"""
    from sqlglot import exp

    found: set[Tuple[str, str]] = set()
    scopes: List[Any] = []
    where = select.args.get("where")
    if where is not None:
        scopes.append(where)
    for join in select.args.get("joins") or []:
        on_clause = join.args.get("on")
        if on_clause is not None:
            scopes.append(on_clause)

    for scope in scopes:
        for node in _walk_predicate(scope):
            if isinstance(node, (exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
                left = _predicate_column(node.this)
                right = _predicate_column(node.expression)
                # 字段和字段比较不能确定分区边界，分区裁剪用不上。
                if left and not right:
                    found.add(left)
                elif right and not left:
                    found.add(right)
            elif isinstance(node, exp.Between):
                column = _predicate_column(node.this)
                if column:
                    found.add(column)
            elif isinstance(node, exp.In):
                column = _predicate_column(node.this)
                expressions = list(node.expressions or [])
                if column and expressions and not any(isinstance(item, exp.Subquery) for item in expressions):
                    found.add(column)
    return found


def _inside_cte_body(table: Any, cte_name: str) -> bool:
    from sqlglot import exp

    parent = getattr(table, "parent", None)
    while parent is not None:
        if isinstance(parent, exp.CTE) and str(getattr(parent, "alias", "") or "").lower() == cte_name:
            return True
        parent = getattr(parent, "parent", None)
    return False


def _statement_cte_names(root: Any) -> set[str]:
    from sqlglot import exp

    names: set[str] = set()
    for cte in root.find_all(exp.CTE):
        alias = str(getattr(cte, "alias", "") or "").strip().strip('"')
        if alias:
            names.add(alias.lower())
    return names


def _direct_tables(select: Any) -> List[Any]:
    from sqlglot import exp

    sources: List[Any] = []
    from_clause = _select_from_clause(select)
    if from_clause is not None and isinstance(from_clause.this, exp.Table):
        sources.append(from_clause.this)
    for join in select.args.get("joins") or []:
        if isinstance(getattr(join, "this", None), exp.Table):
            sources.append(join.this)
    return sources


def partition_tables_missing_scope(
    sql_text: str,
    partition_keys: Dict[Tuple[str, str], List[str]],
) -> List[Tuple[str, List[str]]]:
    """找出会扫完全部分区的父表。解析失败时不拦截，避免误伤方言差异。"""
    if not partition_keys:
        return []
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        logger.warning("分区范围检查缺少 sqlglot，已跳过")
        return []

    cleaned = _EXPLAIN_PREFIX_RE.sub("", str(sql_text or "").strip()).strip().rstrip(";")
    if not cleaned:
        return []
    try:
        statements = sqlglot.parse(cleaned, read="postgres")
    except Exception as exc:
        logger.warning("分区范围检查无法解析 SQL，已跳过: %s", exc)
        return []

    by_name: Dict[str, List[Tuple[str, str, List[str]]]] = {}
    for (schema, name), columns in partition_keys.items():
        if columns:
            by_name.setdefault(name, []).append((schema, name, columns))

    gaps: Dict[str, List[str]] = {}
    for statement in statements or []:
        if statement is None:
            continue
        cte_names = _statement_cte_names(statement)
        for select in statement.find_all(exp.Select):
            constrained = _constrained_columns(select)
            for table in _direct_tables(select):
                name = str(table.name or "").strip().strip('"')
                schema = str(table.db or "").strip().strip('"')
                if not name:
                    continue
                name_key = name.lower()
                schema_key = schema.lower()
                if (
                    not schema_key
                    and name_key in cte_names
                    and not _inside_cte_body(table, name_key)
                ):
                    continue
                if schema_key:
                    matches = [
                        item for item in by_name.get(name_key, [])
                        if item[0] == schema_key and item[1] == name_key
                    ]
                    qualified = f"{schema}.{name}"
                else:
                    matches = list(by_name.get(name_key, []))
                    qualified = name
                for match_schema, match_name, columns in matches:
                    display = qualified if schema_key else f"{match_schema}.{match_name}"
                    alias = str(table.alias or "").strip().strip('"').lower()
                    qualifiers = {alias, match_name, name_key}
                    if schema_key:
                        qualifiers.add(f"{schema_key}.{name_key}")
                    missing = [
                        column for column in columns
                        if not any(
                            qualifier in qualifiers and column_name == column.lower()
                            for qualifier, column_name in constrained
                        ) and not any(
                            qualifier == "" and column_name == column.lower()
                            for qualifier, column_name in constrained
                        )
                    ]
                    if missing:
                        gaps[display] = missing
    return [(display, columns) for display, columns in gaps.items()]


def referenced_partition_table_names(sql_text: str) -> List[str]:
    """取出 SQL 里直接读取的物理表名，供分区键查询使用。"""
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return []

    cleaned = _EXPLAIN_PREFIX_RE.sub("", str(sql_text or "").strip()).strip().rstrip(";")
    if not cleaned:
        return []
    try:
        statements = sqlglot.parse(cleaned, read="postgres")
    except Exception:
        return []

    names: List[str] = []
    seen: set[str] = set()
    for statement in statements or []:
        if statement is None:
            continue
        cte_names = _statement_cte_names(statement)
        for select in statement.find_all(exp.Select):
            for table in _direct_tables(select):
                name = str(table.name or "").strip().strip('"')
                schema = str(table.db or "").strip().strip('"')
                if not name:
                    continue
                name_key = name.lower()
                if (
                    not schema
                    and name_key in cte_names
                    and not _inside_cte_body(table, name_key)
                ):
                    continue
                if name_key not in seen:
                    seen.add(name_key)
                    names.append(name)
    return names


def _parse_timestamp(value: str) -> Optional[datetime]:
    text = _TIMESTAMP_SUFFIX_RE.sub("", str(value or "").strip()).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def infer_partition_grain(bounds: List[str], child_names: List[str]) -> Optional[str]:
    """根据叶子分区边界或分区名判断按日还是按月。无法判断时返回 None。"""
    day_hits = 0
    month_hits = 0
    for bound in bounds:
        match = _PARTBOUND_RE.search(str(bound or "").replace("\n", " "))
        if not match:
            continue
        start = _parse_timestamp(match.group(1))
        end = _parse_timestamp(match.group(2))
        if not start or not end or end <= start:
            continue
        days = (end - start).days
        if days == 1:
            day_hits += 1
        elif 28 <= days <= 31:
            month_hits += 1
    if day_hits or month_hits:
        return "day" if day_hits >= month_hits else "month"

    for name in child_names:
        if _DAY_PARTITION_NAME_RE.search(str(name or "")):
            day_hits += 1
        elif _MONTH_PARTITION_NAME_RE.search(str(name or "")):
            month_hits += 1
    if day_hits or month_hits:
        return "day" if day_hits >= month_hits else "month"
    return None


def _literal_datetime(node: Any) -> Optional[datetime]:
    from sqlglot import exp

    if isinstance(node, exp.Literal) and not getattr(node, "is_number", False):
        return _parse_timestamp(str(node.this or ""))
    if isinstance(node, exp.Cast):
        return _literal_datetime(node.this)
    return None


def _iter_and_predicates(node: Any):
    """只取 AND 链上的条件。OR 里的时间条件不能保证分区裁剪。"""
    from sqlglot import exp

    if node is None:
        return
    if isinstance(node, (exp.Where, exp.Paren)):
        yield from _iter_and_predicates(node.this)
        return
    if isinstance(node, exp.And):
        yield from _iter_and_predicates(node.this)
        yield from _iter_and_predicates(node.expression)
        return
    if isinstance(node, exp.Or):
        return
    yield node


def _column_matches_key(
    column: Optional[Tuple[str, str]],
    qualifiers: set[str],
    key_name: str,
) -> bool:
    if not column or column[1] != key_name:
        return False
    return column[0] == "" or column[0] in qualifiers


def _time_window_units(
    select: Any,
    qualifiers: set[str],
    key_name: str,
    grain: str,
) -> Optional[int]:
    """闭合时间范围覆盖的分区个数。没有起止时间时返回 None。"""
    from sqlglot import exp

    lowers: List[Tuple[datetime, bool]] = []
    uppers: List[Tuple[datetime, bool]] = []
    in_values: List[datetime] = []
    where = select.args.get("where")
    for node in _iter_and_predicates(where):
        if isinstance(node, exp.Between):
            column = _predicate_column(node.this)
            low = _literal_datetime(node.args.get("low"))
            high = _literal_datetime(node.args.get("high"))
            if _column_matches_key(column, qualifiers, key_name) and low and high:
                lowers.append((low, False))
                uppers.append((high, False))
            continue
        if isinstance(node, exp.In):
            column = _predicate_column(node.this)
            expressions = list(node.expressions or [])
            if (
                _column_matches_key(column, qualifiers, key_name)
                and expressions
                and not any(isinstance(item, exp.Subquery) for item in expressions)
            ):
                for item in expressions:
                    parsed = _literal_datetime(item)
                    if parsed:
                        in_values.append(parsed)
            continue
        if not isinstance(node, (exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
            continue
        left = _predicate_column(node.this)
        right = _predicate_column(node.expression)
        if _column_matches_key(left, qualifiers, key_name) and not right:
            moment = _literal_datetime(node.expression)
            side = "left"
        elif _column_matches_key(right, qualifiers, key_name) and not left:
            moment = _literal_datetime(node.this)
            side = "right"
        else:
            continue
        if moment is None:
            continue
        exclusive = isinstance(node, (exp.GT, exp.LT))
        is_lower = isinstance(node, (exp.GT, exp.GTE))
        if side == "right":
            is_lower = not is_lower
        if isinstance(node, exp.EQ):
            lowers.append((moment, False))
            uppers.append((moment, False))
        elif is_lower:
            lowers.append((moment, exclusive))
        else:
            uppers.append((moment, exclusive))

    if lowers and uppers:
        lower, lower_exclusive = max(lowers, key=lambda item: (item[0], item[1]))
        upper, upper_exclusive = min(uppers, key=lambda item: (item[0], not item[1]))
        return _covered_partition_units(
            lower,
            upper,
            lower_exclusive=lower_exclusive,
            upper_exclusive=upper_exclusive,
            grain=grain,
        )
    if in_values:
        return len({_partition_bucket(item, grain) for item in in_values})
    return None


def _partition_bucket(moment: datetime, grain: str) -> Tuple[int, ...]:
    if grain == "month":
        return (moment.year, moment.month)
    return (moment.year, moment.month, moment.day)


def _covered_partition_units(
    lower: datetime,
    upper: datetime,
    *,
    lower_exclusive: bool,
    upper_exclusive: bool,
    grain: str,
) -> int:
    del lower_exclusive
    if grain == "month":
        start = lower.year * 12 + lower.month
        if upper_exclusive and upper.day == 1 and upper.time() == datetime_time.min:
            end = upper.year * 12 + upper.month - 1
        else:
            end = upper.year * 12 + upper.month
        return max(end - start + 1, 0)

    start_day = lower.date()
    if upper_exclusive and upper.time() == datetime_time.min:
        end_day = upper.date() - timedelta(days=1)
    else:
        end_day = upper.date()
    if end_day < start_day:
        return 0
    return (end_day - start_day).days + 1


def partition_time_range_error(
    sql_text: str,
    partition_keys: Dict[Tuple[str, str], List[str]],
    partition_grains: Dict[Tuple[str, str], str],
) -> Optional[str]:
    """按日、按月分区必须传入闭合时间范围，并且不能超过固定分区个数。"""
    if not partition_grains:
        return None
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None

    cleaned = _EXPLAIN_PREFIX_RE.sub("", str(sql_text or "").strip()).strip().rstrip(";")
    if not cleaned:
        return None
    try:
        statements = sqlglot.parse(cleaned, read="postgres")
    except Exception as exc:
        logger.warning("分区时间范围检查无法解析 SQL，已跳过: %s", exc)
        return None

    by_name: Dict[str, List[Tuple[str, str, List[str]]]] = {}
    for (schema, name), columns in partition_keys.items():
        if columns and partition_grains.get((schema, name)) in ("day", "month"):
            by_name.setdefault(name, []).append((schema, name, columns))

    problems: Dict[str, str] = {}
    for statement in statements or []:
        if statement is None:
            continue
        cte_names = _statement_cte_names(statement)
        for select in statement.find_all(exp.Select):
            for table in _direct_tables(select):
                name = str(table.name or "").strip().strip('"')
                schema = str(table.db or "").strip().strip('"')
                if not name:
                    continue
                name_key = name.lower()
                schema_key = schema.lower()
                if (
                    not schema_key
                    and name_key in cte_names
                    and not _inside_cte_body(table, name_key)
                ):
                    continue
                if schema_key:
                    matches = [
                        item for item in by_name.get(name_key, [])
                        if item[0] == schema_key and item[1] == name_key
                    ]
                    qualified = f"{schema}.{name}"
                else:
                    matches = list(by_name.get(name_key, []))
                    qualified = name
                alias = str(table.alias or "").strip().strip('"').lower()
                for match_schema, match_name, columns in matches:
                    display = qualified if schema_key else f"{match_schema}.{match_name}"
                    grain = partition_grains.get((match_schema, match_name))
                    if grain not in ("day", "month") or not columns:
                        continue
                    qualifiers = {alias, match_name, name_key}
                    if schema_key:
                        qualifiers.add(f"{schema_key}.{name_key}")
                    key_name = columns[0].lower()
                    units = _time_window_units(select, qualifiers, key_name, grain)
                    problem = _format_time_range_problem(display, columns[0], grain, units)
                    if problem:
                        problems[display] = problem
    if not problems:
        return None
    return "".join(problems.values())


def _format_time_range_problem(
    display: str,
    column: str,
    grain: str,
    units: Optional[int],
) -> Optional[str]:
    label = "日" if grain == "day" else "月"
    limit = DAY_PARTITION_MAX_UNITS if grain == "day" else MONTH_PARTITION_MAX_UNITS
    if units is None:
        return (
            f"表 {display} 按{label}分区（字段 {column}）。"
            f"请传入闭合时间范围，例如 {column} >= '起始' AND {column} < '结束'，"
            f"最多跨 {limit} 个{label}分区。"
            "只有单边条件会扫到该时间之后的全部分区。"
            "若用户没有给出起止时间，先向用户确认。"
        )
    if units <= 0:
        return f"表 {display} 的时间范围无效，结束时间必须晚于开始时间。"
    if units > limit:
        return (
            f"表 {display} 按{label}分区（字段 {column}）。"
            f"当前时间范围跨过 {units} 个{label}分区，超过允许的 {limit} 个。"
            f"请把 {column} 收窄到 {limit} 个分区以内。"
        )
    return None


def format_partition_scope_error(gaps: List[Tuple[str, List[str]]]) -> str:
    parts = []
    for qualified, columns in gaps:
        shown = "、".join(columns)
        if len(columns) > 1:
            parts.append(f"表 {qualified} 按 {shown} 复合分区，这些字段都要有条件")
        else:
            parts.append(f"表 {qualified} 按 {shown} 分区")
    example_column = gaps[0][1][0]
    return (
        f"{'；'.join(parts)}。"
        "当前 SQL 没有对分区字段做范围或等值过滤，会扫描全部分区。"
        f"请在 WHERE 中直接写出闭合时间范围，例如 "
        f"{example_column} >= '起始' AND {example_column} < '结束'。"
        f"按日分区最多跨 {DAY_PARTITION_MAX_UNITS} 个分区，按月分区最多跨 {MONTH_PARTITION_MAX_UNITS} 个分区。"
        "不要对分区字段套函数。若用户没有给出起止时间，先向用户确认。"
    )


def build_postgresql_conninfo(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build psycopg connection kwargs from a saved data-source config."""
    return {
        "host": config.get("host"),
        "port": int(config.get("port") or 5432),
        "dbname": config.get("database") or config.get("database_name"),
        "user": config.get("user") or config.get("db_user"),
        "password": config.get("password") or "",
        "connect_timeout": 10,
    }


def split_postgresql_identifier(name: str) -> Tuple[Optional[str], str]:
    """Split ``schema.table`` while accepting quoted identifiers."""
    parts = [part.strip().strip('"').strip("`") for part in str(name or "").split(".")]
    if len(parts) == 2 and all(parts):
        return parts[0], parts[1]
    return None, parts[-1] if parts else ""


def quote_postgresql_identifier(name: str) -> str:
    """Quote an identifier without requiring a live psycopg connection."""
    return '"' + str(name).replace('"', '""') + '"'


def qualified_identifier(name: str, default_schema: str = "public") -> sql.Composed:
    schema, table = split_postgresql_identifier(name)
    if not table:
        raise ValueError("表名不能为空")
    return sql.SQL(".").join(
        [sql.Identifier(schema or default_schema), sql.Identifier(table)]
    )


def normalize_postgresql_identifiers(sql_text: str) -> str:
    """将 SQL 中的 MySQL 反引号标识符转换为 PostgreSQL 双引号标识符。

    数据门户可能复用 MySQL 风格的物理表名（例如 ``public.ny_function``）。
    PostgreSQL 不支持反引号，因此只在 SQL 的标识符上下文中做兼容转换；
    单引号字符串、双引号标识符、注释和 dollar-quoted 字符串会原样保留。
    """
    source = str(sql_text or "")
    if "`" not in source:
        return source

    output: List[str] = []
    index = 0
    length = len(source)
    while index < length:
        current = source[index]

        # SQL 字符串中的反引号是普通文本，不能当作标识符转换。
        if current == "'":
            start = index
            index += 1
            while index < length:
                if source[index] == "'":
                    if index + 1 < length and source[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                if source[index] == "\\" and index + 1 < length:
                    index += 2
                    continue
                index += 1
            output.append(source[start:index])
            continue

        # 双引号标识符允许包含反引号，同样必须保持原样。
        if current == '"':
            start = index
            index += 1
            while index < length:
                if source[index] == '"':
                    if index + 1 < length and source[index + 1] == '"':
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            output.append(source[start:index])
            continue

        # 保留行注释和块注释内容，避免转换示例 SQL 或说明文字。
        if source.startswith("--", index):
            end = source.find("\n", index)
            if end < 0:
                output.append(source[index:])
                break
            output.append(source[index:end])
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                output.append(source[index:])
                break
            end += 2
            output.append(source[index:end])
            index = end
            continue

        # PostgreSQL 的 dollar-quoted 字符串常用于函数或复杂表达式。
        if current == "$":
            dollar_match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", source[index:])
            if dollar_match:
                delimiter = dollar_match.group(0)
                end = source.find(delimiter, index + len(delimiter))
                if end >= 0:
                    end += len(delimiter)
                    output.append(source[index:end])
                    index = end
                    continue

        if current != "`":
            output.append(current)
            index += 1
            continue

        # 读取一个 MySQL 反引号标识符，`` 表示标识符内部的单个反引号。
        start = index + 1
        index = start
        identifier_parts: List[str] = []
        buffer: List[str] = []
        closed = False
        while index < length:
            if source[index] == "`":
                if index + 1 < length and source[index + 1] == "`":
                    buffer.append("`")
                    index += 2
                    continue
                identifier_parts.append("".join(buffer))
                index += 1
                closed = True
                break
            buffer.append(source[index])
            index += 1

        if not closed:
            # 不完整的标识符交由数据库返回语法错误，避免猜测并改变原始 SQL。
            logger.warning("PostgreSQL SQL 存在未闭合的反引号标识符，保留原始内容")
            output.append(source[start - 1 :])
            break

        identifier = identifier_parts[0]
        # 上游把 schema.table 整体包在反引号中时，拆成 PostgreSQL 的限定标识符。
        quoted_parts = [quote_postgresql_identifier(part) for part in identifier.split(".")]
        output.append(".".join(quoted_parts))

    normalized = "".join(output)
    if normalized != source:
        logger.info("PostgreSQL SQL 已将 MySQL 反引号标识符转换为双引号")
    return normalized


# 业务指标历史上按 ClickHouse 方言生成；这些函数在 PostgreSQL 中需要显式改写。
_CLICKHOUSE_POSTGRESQL_FUNCTIONS = frozenset(
    {
        "parsedatetimebesteffort",
        "parsedatetimebesteffortorzero",
        "parsedatetimebesteffortornull",
        "todate",
        "todateornull",
        "todatetime",
        "todatetime64",
        "todatetimeornull",
        "toyyyymm",
        "toyyyymmdd",
        "toyyyymmddhhmmss",
        "toyear",
        "toisoyear",
        "toquarter",
        "tomonth",
        "toweek",
        "todayofyear",
        "todayofmonth",
        "todayofweek",
        "tohour",
        "tominute",
        "tosecond",
        "tostartofday",
        "tostartofhour",
        "tostartofmonth",
        "tostartofquarter",
        "tostartofyear",
        "tostartofweek",
        "datediff",
        "formatdatetime",
        "today",
    }
)


def _consume_sql_quoted_or_comment(source: str, index: int) -> Optional[int]:
    """返回字符串、标识符、注释或 dollar-quote 的结束位置。"""
    length = len(source)
    current = source[index]
    if current in ("'", '"', "`"):
        quote = current
        index += 1
        while index < length:
            if source[index] == quote:
                if index + 1 < length and source[index + 1] == quote:
                    index += 2
                    continue
                return index + 1
            if source[index] == "\\" and quote == "'" and index + 1 < length:
                index += 2
                continue
            index += 1
        return length

    if source.startswith("--", index):
        end = source.find("\n", index + 2)
        return length if end < 0 else end
    if source.startswith("/*", index):
        end = source.find("*/", index + 2)
        return length if end < 0 else end + 2
    if current == "$":
        dollar_match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", source[index:])
        if dollar_match:
            delimiter = dollar_match.group(0)
            end = source.find(delimiter, index + len(delimiter))
            return length if end < 0 else end + len(delimiter)
    return None


def _find_matching_parenthesis(source: str, opening_index: int) -> int:
    """查找函数调用右括号，忽略字符串和注释中的括号。"""
    depth = 1
    index = opening_index + 1
    while index < len(source):
        quoted_end = _consume_sql_quoted_or_comment(source, index)
        if quoted_end is not None:
            index = quoted_end
            continue
        current = source[index]
        if current == "(":
            depth += 1
        elif current == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _split_function_arguments(arguments: str) -> List[str]:
    """按顶层逗号拆分参数，保留参数内嵌套函数和字符串内容。"""
    parts: List[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(arguments):
        quoted_end = _consume_sql_quoted_or_comment(arguments, index)
        if quoted_end is not None:
            index = quoted_end
            continue
        current = arguments[index]
        if current == "(":
            depth += 1
        elif current == ")":
            depth = max(0, depth - 1)
        elif current == "," and depth == 0:
            parts.append(arguments[start:index].strip())
            start = index + 1
        index += 1
    tail = arguments[start:].strip()
    if tail or arguments.strip():
        parts.append(tail)
    return parts


def _postgresql_extract_number(field: str, argument: str) -> str:
    """生成 PostgreSQL 的数值型 EXTRACT 表达式，保持指标分组键为整数。"""
    return f"CAST(EXTRACT({field} FROM {argument}) AS INTEGER)"


def _postgresql_safe_cast(argument: str, target_type: str) -> str:
    """模拟 ClickHouse OrNull 转换：非法输入返回 NULL，而不是让查询失败。"""
    normalized_type = target_type.upper()
    return (
        f"CASE WHEN pg_input_is_valid(CAST({argument} AS TEXT), '{target_type}') "
        f"THEN CAST({argument} AS {normalized_type}) ELSE NULL END"
    )


def _convert_clickhouse_function_to_postgresql(name: str, arguments: List[str]) -> Optional[str]:
    """将一个已拆分参数的 ClickHouse 函数转换为 PostgreSQL 表达式。"""
    function_name = name.lower()
    if function_name == "parsedatetimebesteffortornull" and arguments:
        return _postgresql_safe_cast(arguments[0], "timestamp")
    if function_name in {
        "parsedatetimebesteffort",
        "parsedatetimebesteffortorzero",
        "todatetime",
        "todatetime64",
        "todatetimeornull",
    } and arguments:
        return f"CAST({arguments[0]} AS TIMESTAMP)"
    if function_name == "todateornull" and arguments:
        return _postgresql_safe_cast(arguments[0], "date")
    if function_name == "todate" and arguments:
        return f"CAST({arguments[0]} AS DATE)"
    if function_name in {"toyear"} and arguments:
        return _postgresql_extract_number("YEAR", arguments[0])
    if function_name == "toisoyear" and arguments:
        return _postgresql_extract_number("ISOYEAR", arguments[0])
    if function_name == "toquarter" and arguments:
        return _postgresql_extract_number("QUARTER", arguments[0])
    if function_name == "tomonth" and arguments:
        return _postgresql_extract_number("MONTH", arguments[0])
    if function_name == "toweek" and arguments:
        return _postgresql_extract_number("WEEK", arguments[0])
    if function_name == "todayofyear" and arguments:
        return _postgresql_extract_number("DOY", arguments[0])
    if function_name == "todayofmonth" and arguments:
        return _postgresql_extract_number("DAY", arguments[0])
    if function_name == "todayofweek" and arguments:
        return _postgresql_extract_number("ISODOW", arguments[0])
    if function_name == "tohour" and arguments:
        return _postgresql_extract_number("HOUR", arguments[0])
    if function_name == "tominute" and arguments:
        return _postgresql_extract_number("MINUTE", arguments[0])
    if function_name == "tosecond" and arguments:
        return _postgresql_extract_number("SECOND", arguments[0])
    if function_name in {"tostartofday", "tostartofhour", "tostartofmonth", "tostartofquarter", "tostartofyear", "tostartofweek"} and arguments:
        units = {
            "tostartofday": "day",
            "tostartofhour": "hour",
            "tostartofmonth": "month",
            "tostartofquarter": "quarter",
            "tostartofyear": "year",
            "tostartofweek": "week",
        }
        if function_name == "tostartofweek":
            mode = arguments[1].strip().strip("'\"") if len(arguments) > 1 else "0"
            if mode == "1":
                return f"DATE_TRUNC('week', {arguments[0]})"
            return f"DATE_TRUNC('week', {arguments[0]}) - INTERVAL '1 day'"
        return f"DATE_TRUNC('{units[function_name]}', {arguments[0]})"
    if function_name == "toyyyymm" and arguments:
        year = _postgresql_extract_number("YEAR", arguments[0])
        month = _postgresql_extract_number("MONTH", arguments[0])
        return f"(({year} * 100) + {month})"
    if function_name == "toyyyymmdd" and arguments:
        year = _postgresql_extract_number("YEAR", arguments[0])
        month = _postgresql_extract_number("MONTH", arguments[0])
        day = _postgresql_extract_number("DAY", arguments[0])
        return f"(({year} * 10000) + ({month} * 100) + {day})"
    if function_name == "toyyyymmddhhmmss" and arguments:
        year = _postgresql_extract_number("YEAR", arguments[0])
        month = _postgresql_extract_number("MONTH", arguments[0])
        day = _postgresql_extract_number("DAY", arguments[0])
        hour = _postgresql_extract_number("HOUR", arguments[0])
        minute = _postgresql_extract_number("MINUTE", arguments[0])
        second = _postgresql_extract_number("SECOND", arguments[0])
        return (
            f"(({year} * 10000000000) + ({month} * 100000000) + ({day} * 1000000) + "
            f"({hour} * 10000) + ({minute} * 100) + {second})"
        )
    if function_name == "today" and not arguments:
        return "CURRENT_DATE"
    if function_name == "formatdatetime" and len(arguments) >= 2:
        format_text = arguments[1]
        if len(format_text) >= 2 and format_text[0] == format_text[-1] == "'":
            format_text = format_text[1:-1]
            format_tokens = {
                "%Y": "YYYY",
                "%m": "MM",
                "%d": "DD",
                "%H": "HH24",
                "%i": "MI",
                "%s": "SS",
                "%F": "YYYY-MM-DD",
                "%T": "HH24:MI:SS",
                "%M": "MI",
                "%j": "DDD",
                "%u": "ID",
                "%V": "IW",
                "%G": "IYYY",
                "%r": "HH12:MI:SS AM",
            }
            for source_token, target_token in format_tokens.items():
                format_text = format_text.replace(source_token, target_token)
            if re.search(r"%[A-Za-z]", format_text):
                return None
            format_text = "'" + format_text.replace("'", "''") + "'"
        return f"TO_CHAR({arguments[0]}, {format_text})"
    if function_name == "datediff" and len(arguments) >= 3:
        unit = arguments[0].strip().strip("'\"").lower()
        start, end = arguments[1], arguments[2]
        if unit in {"day", "days"}:
            return f"CAST(({end})::date - ({start})::date AS BIGINT)"
        seconds_per_unit = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "hour": 3600, "hours": 3600}
        if unit in seconds_per_unit:
            divisor = seconds_per_unit[unit]
            return f"CAST(EXTRACT(EPOCH FROM (({end})::timestamp - ({start})::timestamp)) / {divisor} AS BIGINT)"
    return None


def normalize_postgresql_sql(sql_text: str) -> str:
    """统一转换 PostgreSQL SQL 中的标识符和常见 ClickHouse 日期函数。

    转换器采用括号/字符串感知扫描，不会改写字面量、注释或双引号标识符；无法识别的函数保持原样，
    以便将潜在的业务自定义函数交给数据库报错，并通过日志定位。
    """
    source = normalize_postgresql_identifiers(str(sql_text or ""))
    marker_pattern = r"(?i)\b(?:" + "|".join(sorted(_CLICKHOUSE_POSTGRESQL_FUNCTIONS, key=len, reverse=True)) + r")\s*\("
    if not re.search(marker_pattern, source):
        return source

    def normalize_fragment(fragment: str) -> str:
        output: List[str] = []
        index = 0
        while index < len(fragment):
            quoted_end = _consume_sql_quoted_or_comment(fragment, index)
            if quoted_end is not None:
                output.append(fragment[index:quoted_end])
                index = quoted_end
                continue
            current = fragment[index]
            if current.isalpha() or current == "_":
                name_start = index
                index += 1
                while index < len(fragment) and (fragment[index].isalnum() or fragment[index] == "_"):
                    index += 1
                name = fragment[name_start:index]
                opening = index
                while opening < len(fragment) and fragment[opening].isspace():
                    opening += 1
                if opening < len(fragment) and fragment[opening] == "(":
                    closing = _find_matching_parenthesis(fragment, opening)
                    if closing >= 0:
                        inner = normalize_fragment(fragment[opening + 1 : closing])
                        arguments = _split_function_arguments(inner)
                        converted = _convert_clickhouse_function_to_postgresql(name, arguments)
                        if converted is not None:
                            output.append(converted)
                        else:
                            output.append(fragment[name_start : opening + 1] + inner + ")")
                        index = closing + 1
                        continue
                output.append(fragment[name_start:index])
                continue
            output.append(current)
            index += 1
        return "".join(output)

    normalized = normalize_fragment(source)
    if normalized != source:
        logger.info("PostgreSQL SQL 已转换 ClickHouse 日期函数为兼容表达式")
    return normalized


class PostgreSQLAdapter(DataSourceAdapter):
    """PostgreSQL read-only adapter backed by psycopg's async connection pool."""

    def __init__(self, source_id: int):
        self.source_id = source_id

    async def execute(self, query: LogicalQuery) -> ResultSet:
        raise NotImplementedError("本地适配器仅支持执行只读物理 SQL")

    async def execute_summary(self, query: LogicalQuery, agg_fields: List[str] = None) -> Dict[str, Any]:
        raise NotImplementedError("本地适配器仅支持执行只读物理 SQL")

    async def get_tables(self) -> List[Dict[str, str]]:
        from app.services.pool_manager import DataSourcePoolManager

        pool = await DataSourcePoolManager.get_pool(self.source_id)
        query = POSTGRESQL_LIST_TABLES_SQL
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(query)
                rows = await cursor.fetchall()

        return [
            {
                "name": f"{row[0]}.{row[1]}",
                "comment": row[2] or "",
                "type": "view" if row[3] == "VIEW" else "table",
            }
            for row in rows
        ]

    async def get_columns(
        self,
        table_name: Optional[str] = None,
        custom_sql: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        from app.services.pool_manager import DataSourcePoolManager

        pool = await DataSourcePoolManager.get_pool(self.source_id)
        if custom_sql:
            raw_sql = custom_sql.strip().rstrip(";")
            try:
                raw_sql = SQL_LAB_ENV.from_string(raw_sql).render(**(params or {}))
            except Exception:
                pass
            # 字段探测也必须使用与正式执行相同的方言转换，避免保存前探测成功、预览时失败。
            raw_sql = normalize_postgresql_sql(raw_sql)
            final_sql = f"SELECT * FROM ({raw_sql}) AS _pg_columns LIMIT 0"
            async with pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(final_sql)
                    description = cursor.description or []
            return [{"name": desc[0], "type": str(desc[1]), "comment": ""} for desc in description]

        schema, table = split_postgresql_identifier(table_name or "")
        if not table:
            return []
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT c.column_name, c.data_type, c.udt_name,
                           COALESCE(col_description(
                               (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                               c.ordinal_position
                           ), '')
                    FROM information_schema.columns c
                    WHERE c.table_schema = %s AND c.table_name = %s
                    ORDER BY c.ordinal_position
                    """,
                    (schema or "public", table),
                )
                rows = await cursor.fetchall()
        return [
            {"name": row[0], "type": row[1] or row[2] or "String", "comment": row[3] or ""}
            for row in rows
        ]

    async def lookup_partition_keys(
        self,
        table_names: List[str],
    ) -> Dict[Tuple[str, str], List[str]]:
        """按表名读取分区键。键为 (schema, table) 的小写形式。"""
        names = sorted({str(name or "").strip().strip('"').lower() for name in table_names if str(name or "").strip()})
        if not names:
            return {}
        from app.services.pool_manager import DataSourcePoolManager

        pool = await DataSourcePoolManager.get_pool(self.source_id)
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(POSTGRESQL_PARTITION_KEYS_SQL, (names,))
                rows = await cursor.fetchall()

        found: Dict[Tuple[str, str], List[str]] = {}
        for schema_name, table_name, partkeydef, attnames in rows:
            columns = [str(name) for name in (attnames or []) if name]
            if not columns:
                columns = columns_from_partkeydef(str(partkeydef or ""))
            if columns:
                found[(str(schema_name).lower(), str(table_name).lower())] = columns
        return found

    async def lookup_partition_grains(self, table_names: List[str]) -> Dict[Tuple[str, str], str]:
        """识别按日或按月的 RANGE 分区。键为 (schema, table) 的小写形式。"""
        names = sorted({str(name or "").strip().strip('"').lower() for name in table_names if str(name or "").strip()})
        if not names:
            return {}
        from app.services.pool_manager import DataSourcePoolManager

        pool = await DataSourcePoolManager.get_pool(self.source_id)
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(POSTGRESQL_PARTITION_GRAIN_SQL, (names,))
                rows = await cursor.fetchall()

        grouped: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
        for schema_name, table_name, bound_expr, child_name in rows:
            key = (str(schema_name).lower(), str(table_name).lower())
            bucket = grouped.setdefault(key, {"bounds": [], "names": []})
            if bound_expr:
                bucket["bounds"].append(str(bound_expr))
            if child_name:
                bucket["names"].append(str(child_name))

        found: Dict[Tuple[str, str], str] = {}
        for key, bucket in grouped.items():
            grain = infer_partition_grain(bucket["bounds"], bucket["names"])
            if grain:
                found[key] = grain
        return found

    async def partition_scope_error(self, sql_text: str) -> Optional[str]:
        """用户 SQL 若会扫分区父表的全部分区，返回要求补上分区条件的说明。"""
        names = referenced_partition_table_names(sql_text)
        if not names:
            return None
        try:
            partition_keys = await self.lookup_partition_keys(names)
        except Exception as exc:
            logger.warning("读取分区键失败，已跳过分区范围检查: %s", exc)
            return None
        gaps = partition_tables_missing_scope(sql_text, partition_keys)
        if gaps:
            return format_partition_scope_error(gaps)
        try:
            grains = await self.lookup_partition_grains(names)
        except Exception as exc:
            logger.warning("读取分区粒度失败，已跳过时间范围检查: %s", exc)
            return None
        return partition_time_range_error(sql_text, partition_keys, grains)

    async def execute_sql(self, sql_text: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from app.services.pool_manager import DataSourcePoolManager

        # 直接执行入口覆盖历史指标 SQL，兼容 ClickHouse 日期函数和反引号标识符。
        sql_text = normalize_postgresql_sql(sql_text)
        pool = await DataSourcePoolManager.get_pool(self.source_id)
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(sql_text, params or ())
                rows = await cursor.fetchall()
                description = cursor.description or []
        return {
            "columns": [{"name": desc[0], "type": str(desc[1])} for desc in description],
            "items": standardize_items([list(row) for row in rows]),
        }

    async def preview(
        self,
        sql_text: str,
        limit: int = 100,
        params: Dict[str, Any] = None,
        offset: int = 0,
        include_total: bool = False,
    ) -> Dict[str, Any]:
        params = params or {}
        limit = min(max(int(limit or 100), 1), 1000)
        try:
            self._validate_sql_safety(sql_text)
        except SQLSafetyError as exc:
            raise ValueError(str(exc)) from exc

        rendered_sql = sql_text
        if "{{" in sql_text or "{%" in sql_text:
            try:
                rendered_sql = SQL_LAB_ENV.from_string(sql_text).render(**params)
                self._validate_sql_safety(rendered_sql)
            except SQLSafetyError as exc:
                raise ValueError(str(exc)) from exc
            except Exception as exc:
                raise ValueError(f"Jinja2 模板渲染失败: {exc}") from exc

        # 预览的 COUNT 包装与实际查询必须共享同一份已转换 SQL，否则 include_total 会单独报错。
        clean_sql = normalize_postgresql_sql(rendered_sql.strip().rstrip(";"))
        scope_error = await self.partition_scope_error(clean_sql)
        if scope_error:
            raise ValueError(scope_error)
        limit_match = re.search(r"\bLIMIT\s+(\d+)", clean_sql, re.IGNORECASE)
        if limit_match:
            final_sql = (
                clean_sql[: limit_match.start(1)]
                + str(min(int(limit_match.group(1)), limit))
                + clean_sql[limit_match.end(1) :]
            )
        else:
            final_sql = f"SELECT * FROM ({clean_sql}) AS _preview_sub LIMIT {limit}"

        from app.services.pool_manager import DataSourcePoolManager

        started = time.perf_counter()
        total_count = None
        pool = await DataSourcePoolManager.get_pool(self.source_id)
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                if include_total and not limit_match:
                    await cursor.execute(f"SELECT COUNT(*) FROM ({clean_sql}) AS _preview_count")
                    total_count = int((await cursor.fetchone())[0])
                await cursor.execute(final_sql, params or ())
                rows = await cursor.fetchall()
                description = cursor.description or []

        result = {
            "columns": [{"name": desc[0], "type": str(desc[1])} for desc in description],
            "rows": standardize_items([list(row) for row in rows]),
            "execution_time_ms": (time.perf_counter() - started) * 1000,
            "scanned_rows": 0,
            "offset": offset,
            "limit": limit,
        }
        if total_count is not None:
            result["total_count"] = total_count
        return result

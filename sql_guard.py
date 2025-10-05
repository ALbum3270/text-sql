import os
import re
from typing import Dict, Any, Set, Optional

import sqlglot
from sqlglot import exp


class SQLValidationError(Exception):
    pass


# 扩充：将 user 也纳入保留样式，统一反引号转义，避免与 MySQL 关键字冲突
RESERVED_LIKE = {"check", "desc", "key", "user"}
DEFAULT_DERIVED_ALIASES = {"d", "date", "cnt", "count", "total", "num", "dt", "day"}


def _normalize(name: str) -> str:
    if name is None:
        return ""
    # 去反引号并小写
    return name.replace("`", "").lower()


def _get_permitted_aliases() -> Set[str]:
    env_val = os.getenv("SQL_PERMITTED_ALIASES", "")
    extra = {s.strip().lower() for s in env_val.split(",") if s.strip()} if env_val else set()
    return DEFAULT_DERIVED_ALIASES | extra


def _collect_table_names(expression: exp.Expression) -> Set[str]:
    names: Set[str] = set()
    for t in expression.find_all(exp.Table):
        if isinstance(t.this, exp.Identifier):
            names.add(_normalize(t.this.name))
        else:
            names.add(_normalize(t.name))
    return {n for n in names if n}


def _collect_column_names(expression: exp.Expression) -> Set[str]:
    names: Set[str] = set()
    for c in expression.find_all(exp.Column):
        if isinstance(c.this, exp.Identifier):
            names.add(_normalize(c.this.name))
    return names


def _collect_select_aliases(expression: exp.Expression) -> Set[str]:
    aliases: Set[str] = set()
    # 遍历所有 Select 的投影，收集 AS 别名
    for sel in expression.find_all(exp.Select):
        for e in sel.expressions:
            try:
                a = e.alias
            except Exception:
                a = None
            if isinstance(a, exp.Identifier) and a.name:
                aliases.add(_normalize(a.name))
    # 兼容直接的 Alias 节点
    for a in expression.find_all(exp.Alias):
        if isinstance(a.alias, exp.Identifier) and a.alias.name:
            aliases.add(_normalize(a.alias.name))
    return aliases


def _strip_trailing_semicolon(sql: str) -> str:
    return re.sub(r";\s*$", "", sql.strip())


def _remove_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--.*?$", " ", sql, flags=re.M)
    return sql


def _has_limit(sql: str) -> bool:
    return re.search(r"(?i)\blimit\b", sql) is not None


def _clamp_limit(sql: str, max_limit: int) -> str:
    def repl_offset_count(m: re.Match) -> str:
        offset = int(m.group(1))
        count = int(m.group(2))
        count = min(count, max_limit)
        return f"LIMIT {offset}, {count}"

    def repl_single(m: re.Match) -> str:
        count = int(m.group(1))
        count = min(count, max_limit)
        return f"LIMIT {count}"

    new_sql = re.sub(r"(?i)\blimit\s*(\d+)\s*,\s*(\d+)", repl_offset_count, sql)
    new_sql2 = re.sub(r"(?i)\blimit\s*(\d+)(?!\s*,)", repl_single, new_sql)
    return new_sql2


def _fix_interval_literals(sql: str) -> str:
    return re.sub(r"(?i)\bINTERVAL\s+'(\d+)'\s+(SECOND|MINUTE|HOUR|DAY|WEEK|MONTH|QUARTER|YEAR)", r"INTERVAL \1 \2", sql)


def _quote_reserved_identifiers(sql: str) -> str:
    def repl(m: re.Match) -> str:
        return f"`{m.group(0)}`"
    for kw in RESERVED_LIKE:
        sql = re.sub(fr"(?i)(?<![`\w]){kw}(?![`\w])", repl, sql)
    return sql


def _unquote_order_dir(sql: str) -> str:
    # 兼容性：部分 Python 版本不支持局部 (?i:...) 标志，改用 flags=re.I
    sql = re.sub(r"`\s*asc\s*`", "ASC", sql, flags=re.I)
    sql = re.sub(r"`\s*desc\s*`", "DESC", sql, flags=re.I)
    return sql


def validate_and_rewrite(
    sql: str,
    dialect: str,
    m_schema: Dict[str, Any],
    max_limit: int = 200,
    keep_order_by: bool = False,
    allowed_columns_by_table: Optional[Dict[str, Any]] = None,
) -> str:
    sql = _remove_comments(sql)
    if re.search(r"[\u4e00-\u9fa5]", sql):
        raise SQLValidationError("SQL 中包含中文内容或占位，请仅输出可执行 SQL")
    if re.search(r"specific_\w+", sql, re.I):
        raise SQLValidationError("SQL 中包含示例占位符，请移除")
    if re.search(r"(?i)select\s*\*", sql):
        raise SQLValidationError("禁止 SELECT *，请显式列出所需列")

    try:
        expr = sqlglot.parse_one(sql, read=dialect)
    except Exception as e:
        raise SQLValidationError(f"SQL 解析失败: {e}")

    if not isinstance(expr, (exp.Select, exp.Union, exp.With)):
        raise SQLValidationError("仅允许 SELECT 查询（含 WITH/UNION）")

    permitted_aliases = _get_permitted_aliases()

    allowed_tables = {_normalize(t["name"]) for t in m_schema.get("tables", [])}
    table_to_columns = { _normalize(t["name"]): {_normalize(c["name"]) for c in t.get("columns", [])} for t in m_schema.get("tables", [])}

    # 如果提供了合同列白名单，则收紧列集合到合同范围（与 Schema 取交集，避免拼写错误）
    if allowed_columns_by_table:
        narrowed: Dict[str, Set[str]] = {}
        for tbl, cols in table_to_columns.items():
            contract_cols = { _normalize(c) for t, cs in allowed_columns_by_table.items() for c in (cs or []) if _normalize(t) == tbl }
            if contract_cols:
                narrowed[tbl] = cols & contract_cols
            else:
                # 若该表未在合同出现，则保持 Schema 列集（避免意外清空）
                narrowed[tbl] = cols
        table_to_columns = narrowed

    used_tables = _collect_table_names(expr)
    unknown_tables = used_tables - allowed_tables
    if unknown_tables:
        raise SQLValidationError(f"使用了未授权表: {sorted(unknown_tables)}")

    used_columns = _collect_column_names(expr)
    select_aliases = _collect_select_aliases(expr)
    if used_columns:
        # 并集：所有表的允许列（若提供合同列白名单，已在上方收紧）
        all_allowed_columns = set().union(*table_to_columns.values()) if table_to_columns else set()
        unknown_cols = used_columns - all_allowed_columns
        # 剔除 SELECT 别名与派生别名（兼容 HAVING/ORDER BY 使用别名）
        unknown_cols = unknown_cols - select_aliases - permitted_aliases
        # 跳过 ORDER BY 位置排序（数字不会进入 Column 集合，稳妥起见也排除数字样式）
        unknown_cols = {c for c in unknown_cols if not c.isdigit()}
        if unknown_cols:
            raise SQLValidationError(f"使用了未授权列: {sorted(unknown_cols)}")

    # 可选：在严格评测/安全模式下移除 ORDER BY；在宽松模式或趋势题下保留
    permissive_mode = os.getenv("SQL_PERMISSIVE_MODE", "0") == "1"
    if not permissive_mode and not keep_order_by:
        try:
            for s in expr.find_all(exp.Select):
                if s.args.get("order") is not None:
                    s.set("order", None)
        except Exception:
            pass

    try:
        base_sql = expr.sql(dialect=dialect)
    except Exception as e:
        raise SQLValidationError(f"SQL 重写失败: {e}")

    norm_sql = _strip_trailing_semicolon(base_sql)
    norm_sql = _fix_interval_literals(norm_sql)
    norm_sql = _quote_reserved_identifiers(norm_sql)
    norm_sql = _unquote_order_dir(norm_sql)

    # 宽松模式：不自动处理 LIMIT，直接返回（仍保留前面的解析与表/列校验）
    if permissive_mode:
        return norm_sql

    # 对于单行聚合（如 COUNT/SUM/AVG/MIN/MAX 且无 GROUP BY）：
    # 1) 移除任何已有的 LIMIT
    # 2) 不自动补 LIMIT，避免影响 EM/值对齐
    try:
        expr2 = sqlglot.parse_one(norm_sql, read=dialect)
        is_single_row_agg = False
        if isinstance(expr2, exp.Select):
            has_group = any(True for _ in expr2.find_all(exp.Group))
            agg_funcs = {exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max}
            has_agg = any(any(True for _ in expr2.find_all(cls)) for cls in agg_funcs)
            is_single_row_agg = has_agg and not has_group
        if is_single_row_agg:
            try:
                for s in expr2.find_all(exp.Select):
                    if s.args.get("limit") is not None:
                        s.set("limit", None)
                cleaned = expr2.sql(dialect=dialect)
                cleaned = _strip_trailing_semicolon(cleaned)
                cleaned = _fix_interval_literals(cleaned)
                cleaned = _quote_reserved_identifiers(cleaned)
                cleaned = _unquote_order_dir(cleaned)
                return cleaned
            except Exception:
                return norm_sql
    except Exception:
        pass

    if not _has_limit(norm_sql):
        return f"{norm_sql} LIMIT {max_limit}"
    return _clamp_limit(norm_sql, max_limit)

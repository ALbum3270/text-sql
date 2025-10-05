"""
AST级别的约束验证器 - 使用sqlglot进行精确的SQL结构分析

替代简单的字符串匹配，提供更准确的约束验证
"""

import re
from typing import List, Dict, Any, Set, Optional, Tuple
import sqlglot
import sqlglot.expressions as exp


class ASTValidationResult:
    """AST验证结果"""
    def __init__(self, passed: bool, errors: List[str] = None, 
                 missing_items: List[str] = None):
        self.passed = passed
        self.errors = errors or []
        self.missing_items = missing_items or []


def extract_table_references(expr: exp.Expression) -> Set[str]:
    """从SQL AST中提取所有表引用"""
    tables = set()
    
    for table in expr.find_all(exp.Table):
        if hasattr(table, 'name') and table.name:
            table_name = str(table.name)
            # 处理别名情况
            if hasattr(table, 'alias') and table.alias:
                # 保存原表名，不是别名
                tables.add(table_name.lower())
            else:
                tables.add(table_name.lower())
    
    return tables


def extract_column_references(expr: exp.Expression) -> Set[str]:
    """从SQL AST中提取所有列引用"""
    columns = set()
    
    for col in expr.find_all(exp.Column):
        if hasattr(col, 'name') and col.name:
            col_name = str(col.name)
            columns.add(col_name.lower())
    
    return columns


def extract_join_conditions(expr: exp.Expression) -> List[str]:
    """从SQL AST中提取JOIN条件"""
    joins = []
    
    for join in expr.find_all(exp.Join):
        if hasattr(join, 'on') and join.on:
            try:
                join_condition = join.on.sql(dialect="mysql")
                joins.append(join_condition.lower())
            except:
                # 如果无法转换，尝试字符串表示
                joins.append(str(join.on).lower())
    
    return joins


def extract_where_conditions(expr: exp.Expression) -> List[str]:
    """从SQL AST中提取WHERE条件"""
    conditions = []
    
    for where in expr.find_all(exp.Where):
        if where.this:
            try:
                condition = where.this.sql(dialect="mysql")
                conditions.append(condition.lower())
            except:
                # 如果无法转换，尝试字符串表示
                conditions.append(str(where.this).lower())
    
    return conditions


def normalize_predicate(predicate: str) -> str:
    """标准化谓词以便比较"""
    s = predicate or ""
    s = s.lower()
    # 移除表前缀 table.column -> column
    s = re.sub(r'\b\w+\.', '', s)
    # 规范化 NOT ... IS NULL -> ... IS NOT NULL
    s = re.sub(r"\bnot\s+([a-z_][a-z0-9_]*)\s+is\s+null\b", r"\1 is not null", s)
    # 规范化 NOT ... IS NOT NULL -> ... IS NULL（极少见，保持等价）
    s = re.sub(r"\bnot\s+([a-z_][a-z0-9_]*)\s+is\s+not\s+null\b", r"\1 is null", s)
    # 统一空格
    s = re.sub(r'\s+', ' ', s.strip())
    return s


def decompose_predicate_to_atoms(predicate: str) -> List[str]:
    """将复合谓词按 AND 拆分为原子条件，尽量保留比较/IS NULL 等子句。
    简化实现：按 AND（大小写不敏感）分割，并去除多余括号。
    """
    if not predicate:
        return []
    parts = re.split(r"(?i)\band\b", predicate)
    atoms: List[str] = []
    for p in parts:
        s = p.strip()
        # 去除一层包裹括号
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1].strip()
        if s:
            atoms.append(s)
    return atoms


def normalize_join_condition(join_condition: str) -> str:
    """标准化JOIN条件以便比较"""
    # 移除表前缀
    normalized = re.sub(r'\b\w+\.', '', join_condition.lower())
    # 标准化空格和操作符
    normalized = re.sub(r'\s*=\s*', '=', normalized)
    normalized = re.sub(r'\s+', ' ', normalized.strip())
    return normalized


def check_predicate_presence(where_conditions: List[str], 
                           required_predicate: str) -> bool:
    """检查谓词是否存在于WHERE条件中。
    支持 AND 复合谓词：要求所有子谓词都能在 WHERE 中找到（顺序无关）。"""
    atoms = decompose_predicate_to_atoms(required_predicate)
    if not atoms:
        return False
    for atom in atoms:
        atom_norm = normalize_predicate(atom)
        found = False
        for condition in where_conditions:
            condition_norm = normalize_predicate(condition)
            if atom_norm in condition_norm:
                found = True
                break
        if not found:
            return False
    return True


def check_join_presence(join_conditions: List[str], 
                       required_join: str) -> bool:
    """检查JOIN条件是否存在"""
    required_norm = normalize_join_condition(required_join)
    
    for join in join_conditions:
        join_norm = normalize_join_condition(join)
        if required_norm in join_norm:
            return True
    
    return False


def validate_must_tables_ast(expr: exp.Expression, 
                           must_tables: List[str]) -> ASTValidationResult:
    """验证必需表（AST级别）"""
    used_tables = extract_table_references(expr)
    missing_tables = []
    
    for must_table in must_tables:
        if must_table.lower() not in used_tables:
            missing_tables.append(must_table)
    
    passed = len(missing_tables) == 0
    errors = [f"缺少必需表: {table}" for table in missing_tables]
    
    return ASTValidationResult(passed, errors, missing_tables)


def validate_must_joins_ast(expr: exp.Expression, 
                          must_joins: List[str]) -> ASTValidationResult:
    """验证必需JOIN（AST级别）"""
    join_conditions = extract_join_conditions(expr)
    missing_joins = []
    
    for must_join in must_joins:
        if not check_join_presence(join_conditions, must_join):
            missing_joins.append(must_join)
    
    passed = len(missing_joins) == 0
    errors = [f"缺少必需连接: {join}" for join in missing_joins]
    
    return ASTValidationResult(passed, errors, missing_joins)


def validate_must_predicates_ast(expr: exp.Expression, 
                               must_predicates: List[str]) -> ASTValidationResult:
    """验证必需谓词（AST级别）"""
    where_conditions = extract_where_conditions(expr)
    try:
        print(f"    · AST WHERE提取: {where_conditions}")
    except Exception:
        pass
    missing_predicates = []
    
    for must_pred in must_predicates:
        ok = check_predicate_presence(where_conditions, must_pred)
        try:
            print(f"    · MUST检查: {must_pred} -> {ok}")
        except Exception:
            pass
        if not ok:
            missing_predicates.append(must_pred)
    
    passed = len(missing_predicates) == 0
    errors = [f"缺少必需条件: {pred}" for pred in missing_predicates]
    
    return ASTValidationResult(passed, errors, missing_predicates)


def validate_allowed_tables_ast(expr: exp.Expression, 
                              allowed_tables: List[str]) -> ASTValidationResult:
    """验证只使用允许的表（AST级别）"""
    used_tables = extract_table_references(expr)
    allowed_lower = [t.lower() for t in allowed_tables]
    unauthorized_tables = []
    
    for used_table in used_tables:
        if used_table not in allowed_lower:
            unauthorized_tables.append(used_table)
    
    passed = len(unauthorized_tables) == 0
    errors = [f"使用了不允许的表: {table}" for table in unauthorized_tables]
    
    return ASTValidationResult(passed, errors, unauthorized_tables)


def validate_allowed_columns_ast(expr: exp.Expression, 
                               allowed_columns: Dict[str, List[str]]) -> ASTValidationResult:
    """验证只使用允许的列（AST级别）"""
    # 构建全局允许列集合（考虑到可能的表前缀）
    all_allowed_columns = set()
    table_column_map = {}
    
    for table, columns in allowed_columns.items():
        table_lower = table.lower()
        table_column_map[table_lower] = [c.lower() for c in columns]
        for col in columns:
            all_allowed_columns.add(col.lower())
            # 也添加带表前缀的形式
            all_allowed_columns.add(f"{table_lower}.{col.lower()}")
    
    used_columns = extract_column_references(expr)
    unauthorized_columns = []
    
    for used_col in used_columns:
        # 检查是否为允许的列（考虑各种形式）
        if (used_col not in all_allowed_columns and 
            not any(used_col in table_cols for table_cols in table_column_map.values())):
            unauthorized_columns.append(used_col)
    
    passed = len(unauthorized_columns) == 0
    errors = [f"使用了不允许的列: {col}" for col in unauthorized_columns]
    
    return ASTValidationResult(passed, errors, unauthorized_columns)


def comprehensive_ast_validation(sql: str, 
                                must_tables: List[str] = None,
                                must_joins: List[str] = None, 
                                must_predicates: List[str] = None,
                                allowed_tables: List[str] = None,
                                allowed_columns: Dict[str, List[str]] = None) -> ASTValidationResult:
    """综合AST验证"""
    try:
        expr = sqlglot.parse_one(sql, read="mysql")
    except Exception as e:
        return ASTValidationResult(False, [f"SQL解析失败: {e}"])
    
    all_errors = []
    all_missing = []
    
    # 验证必需表
    if must_tables:
        result = validate_must_tables_ast(expr, must_tables)
        if not result.passed:
            all_errors.extend(result.errors)
            all_missing.extend(result.missing_items)
    
    # 验证必需JOIN
    if must_joins:
        result = validate_must_joins_ast(expr, must_joins)
        if not result.passed:
            all_errors.extend(result.errors)
            all_missing.extend(result.missing_items)
    
    # 验证必需谓词
    if must_predicates:
        result = validate_must_predicates_ast(expr, must_predicates)
        if not result.passed:
            all_errors.extend(result.errors)
            all_missing.extend(result.missing_items)
    
    # 验证允许的表
    if allowed_tables:
        result = validate_allowed_tables_ast(expr, allowed_tables)
        if not result.passed:
            all_errors.extend(result.errors)
    
    # 验证允许的列（改为硬失败，保持与合同/Guard一致）
    if allowed_columns:
        result = validate_allowed_columns_ast(expr, allowed_columns)
        if not result.passed:
            all_errors.extend(result.errors)
    
    passed = len(all_errors) == 0
    return ASTValidationResult(passed, all_errors, all_missing)


def suggest_repair_actions(validation_result: ASTValidationResult) -> List[str]:
    """基于验证结果建议修复动作"""
    actions = []
    
    for missing_item in validation_result.missing_items:
        if "=" in missing_item:  # JOIN条件
            actions.append(f"添加JOIN: {missing_item}")
        elif any(op in missing_item.lower() for op in ["is not null", "=", ">", "<", "like"]):  # 谓词
            actions.append(f"添加WHERE条件: {missing_item}")
        else:  # 表名
            actions.append(f"包含表: {missing_item}")
    
    return actions


# 使用示例和测试
if __name__ == "__main__":
    # 测试SQL
    test_sql = """
    SELECT wpa.name, wpa.app_id, wpad.level 
    FROM weak_password_app wpa 
    JOIN weak_password_app_detail wpad ON wpad.app_id = wpa.app_id 
    WHERE wpad.pass_wd IS NOT NULL 
    LIMIT 200
    """
    
    # 测试约束
    must_tables = ["weak_password_app", "weak_password_app_detail"]
    must_joins = ["weak_password_app_detail.app_id = weak_password_app.app_id"]
    must_predicates = ["weak_password_app_detail.pass_wd IS NOT NULL"]
    allowed_tables = ["weak_password_app", "weak_password_app_detail"]
    allowed_columns = {
        "weak_password_app": ["name", "app_id"],
        "weak_password_app_detail": ["level", "pass_wd", "app_id"]
    }
    
    # 执行验证
    result = comprehensive_ast_validation(
        test_sql, 
        must_tables=must_tables,
        must_joins=must_joins,
        must_predicates=must_predicates,
        allowed_tables=allowed_tables,
        allowed_columns=allowed_columns
    )
    
    print(f"验证通过: {result.passed}")
    if result.errors:
        print("错误:")
        for error in result.errors:
            print(f"  - {error}")
    
    if result.missing_items:
        print("建议修复:")
        for action in suggest_repair_actions(result):
            print(f"  - {action}")

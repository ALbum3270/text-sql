"""
纯客观验证引擎 - 只做MUST约束验证，不做语义判断

核心原则：
1. 只验证MUST约束（硬性要求）
2. 不做语义打分和排序
3. 简单的通过/不通过布尔判断
4. 必要时进行最小修复
"""

import re
from typing import List, Dict, Any, Optional, Tuple, Union
import os
import sqlglot
import sqlglot.expressions as exp
from llm_generator import SafetyContract
from llm_planner import PlanV1
from ast_validator import comprehensive_ast_validation, suggest_repair_actions


DEBUG = os.getenv("T2SQL_DEBUG", "0") == "1"


def _dbg(message: str) -> None:
    if DEBUG:
        try:
            print(message)
        except Exception:
            pass


class ValidationResult:
    """验证结果"""
    def __init__(self, passed: bool, errors: List[str] = None, 
                 fixed_sql: Optional[str] = None):
        self.passed = passed
        self.errors = errors or []
        self.fixed_sql = fixed_sql


def validate_must_constraints(sql: str, plan: PlanV1, 
                             contract: SafetyContract) -> ValidationResult:
    """验证MUST约束（使用AST级别验证）"""
    
    try:
        # 使用AST验证器进行精确验证，优先从plan获取must_tables
        plan_must_tables = getattr(plan, 'must_tables', []) or getattr(plan, 'required_tables', [])
        contract_must_tables = getattr(contract, 'must_tables', [])
        
        # 优先使用plan的must_tables，回退到contract，最后才推断
        must_tables_to_use = plan_must_tables or contract_must_tables
        if not must_tables_to_use and contract.must_joins:
            # 最后的回退：从JOIN推断（但加入更严格的验证）
            inferred_tables = []
            for join in contract.must_joins:
                tables_in_join = re.findall(r'(\w+)\.', join)
                for table in tables_in_join:
                    if table in contract.allowed_tables:  # 只接受合同允许的表
                        inferred_tables.append(table)
            must_tables_to_use = list(set(inferred_tables))
        
        try:
            ast_result = comprehensive_ast_validation(
                sql,
                must_tables=must_tables_to_use,
                must_joins=contract.must_joins,
                must_predicates=contract.must_predicates,
                allowed_tables=contract.allowed_tables,
                allowed_columns=contract.allowed_columns
            )
        except Exception as e:
            print(f"⚠️ AST验证失败，使用简单验证: {e}")
            # 回退到简单的字符串验证
            basic_errors = []
            for pred in contract.must_predicates:
                if pred.lower() not in sql.lower():
                    basic_errors.append(f"缺少必需条件: {pred}")
            for join in contract.must_joins:
                join_simple = re.sub(r'\w+\.', '', join.lower())
                if join_simple not in sql.lower():
                    basic_errors.append(f"缺少必需连接: {join}")
            
            ast_result = type('Result', (), {
                'passed': len(basic_errors) == 0,
                'errors': basic_errors
            })()
        
        return ValidationResult(
            passed=ast_result.passed,
            errors=ast_result.errors,
            fixed_sql=None
        )
    except Exception as e:
        # 如果AST验证彻底失败，FAIL-CLOSED：视为未通过，避免放行非法SQL
        _dbg(f"❌ AST验证致命失败: {e}")
        return ValidationResult(
            passed=False,
            errors=[f"AST验证失败: {e}"],
            fixed_sql=None
        )


def minimal_repair(sql: str, plan: PlanV1, contract: SafetyContract) -> str:
    """最小修复：只注入缺失的MUST约束（使用AST级别检查）"""
    if not contract.must_predicates:
        return sql
    
    # 使用AST检查而不是字符串匹配
    try:
        from ast_validator import (
            extract_where_conditions,
            normalize_predicate,
            check_predicate_presence,
            decompose_predicate_to_atoms,
        )
        import sqlglot
        import sqlglot.expressions as exp
        
        # 解析SQL为AST再提取WHERE条件
        parsed_expr = sqlglot.parse_one(sql, read="mysql")
        existing_conditions = extract_where_conditions(parsed_expr)
        existing_normalized = [normalize_predicate(cond) for cond in existing_conditions]
        
        # 基于原子谓词的缺失检测（支持 AND 复合谓词）
        missing_predicates: List[str] = []
        for must_pred in contract.must_predicates:
            atoms = decompose_predicate_to_atoms(must_pred)
            if not atoms:
                continue
            for atom in atoms:
                if not check_predicate_presence(existing_conditions, atom):
                    missing_predicates.append(atom)
        
        if not missing_predicates:
            return sql
        
        # 注入缺失的谓词
        return _inject_missing_predicates(sql, missing_predicates)
        
    except Exception as e:
        # 如果AST处理失败，回退到简单字符串匹配
        _dbg(f"⚠️ AST修复失败，使用字符串匹配: {e}")
        return _fallback_string_repair(sql, contract.must_predicates)


def _inject_missing_predicates(sql: str, predicates: List[str]) -> str:
    """注入缺失的谓词到WHERE子句（优先使用AST，回退到字符串）"""
    if not predicates:
        return sql
    
    # 尝试使用AST进行精确注入
    try:
        import sqlglot
        from sqlglot import exp
        
        parsed = sqlglot.parse_one(sql, read="mysql")
        if isinstance(parsed, exp.Select):
            # 构建新的WHERE条件
            new_conditions = []
            for pred in predicates:
                try:
                    pred_expr = sqlglot.parse_one(f"SELECT * FROM dummy WHERE {pred}", read="mysql")
                    if isinstance(pred_expr, exp.Select) and pred_expr.find(exp.Where):
                        new_conditions.append(pred_expr.find(exp.Where).this)
                except:
                    # 如果解析失败，用原始字符串
                    new_conditions.append(exp.Anonymous(this=pred))
            
            # 添加到现有WHERE条件
            if parsed.find(exp.Where):
                existing_where = parsed.find(exp.Where)
                if new_conditions:
                    # 使用 sqlglot.exp.and_ 组合条件（更稳健）。
                    # 对于修复多个原子谓词的场景，我们将它们与现有条件合并。
                    combined = exp.and_(existing_where.this, *new_conditions)
                    existing_where.set("this", combined)
            else:
                # 创建新的WHERE子句
                if new_conditions:
                    where_expr = exp.and_(*new_conditions) if len(new_conditions) > 1 else new_conditions[0]
                    parsed.set("where", exp.Where(this=where_expr))
            
            return parsed.sql(dialect="mysql")
    
    except Exception as e:
        # 回退到字符串注入
        _dbg(f"⚠️ AST注入失败，使用字符串注入: {e}")
    
    # 字符串注入回退方法
    clause = " AND ".join(f"({p})" for p in predicates)
    
    # 如果已有WHERE，追加条件
    if re.search(r"(?i)\bwhere\b", sql):
        return re.sub(r"(?i)\bwhere\b", f"WHERE {clause} AND ", sql, count=1)
    
    # 如果没有WHERE，在GROUP/ORDER/LIMIT前插入
    parts = re.split(r"(?i)(\bgroup\s+by\b|\border\s+by\b|\blimit\b)", sql, maxsplit=1)
    if len(parts) == 1:
        return sql.rstrip() + f" WHERE {clause}"
    
    return parts[0].rstrip() + f" WHERE {clause} " + "".join(parts[1:])


def _are_predicates_equivalent(pred1: str, pred2: str) -> bool:
    """检查两个谓词是否等价（简化版）"""
    # 规范化比较
    p1 = re.sub(r'\s+', ' ', pred1.strip().lower())
    p2 = re.sub(r'\s+', ' ', pred2.strip().lower())
    
    # 直接比较
    if p1 == p2:
        return True
    
    # 检查核心条件（移除表前缀）
    core1 = re.sub(r'\w+\.', '', p1)
    core2 = re.sub(r'\w+\.', '', p2)
    
    return core1 == core2


def _fallback_string_repair(sql: str, must_predicates: List[str]) -> str:
    """回退到字符串匹配的修复方法"""
    sql_lower = sql.lower()
    missing_predicates = []
    
    for must_pred in must_predicates:
        core_condition = re.sub(r'\w+\.', '', must_pred.lower())
        if core_condition not in sql_lower:
            missing_predicates.append(must_pred)
    
    if not missing_predicates:
        return sql
    
    return _inject_missing_predicates(sql, missing_predicates)


def check_basic_sql_validity(sql: str) -> ValidationResult:
    """基本SQL有效性检查"""
    errors = []
    
    # 禁止SELECT *
    if re.search(r"(?i)select\s*\*", sql):
        errors.append("禁止使用 SELECT *")
    
    # 检查中文内容
    if re.search(r"[\u4e00-\u9fa5]", sql):
        errors.append("SQL中包含中文内容")
    
    # 检查占位符
    if re.search(r"specific_\w+", sql, re.I):
        errors.append("SQL中包含示例占位符")
    
    # 尝试解析
    try:
        sqlglot.parse_one(sql, read="mysql")
    except Exception as e:
        errors.append(f"SQL语法错误: {e}")
    
    passed = len(errors) == 0
    return ValidationResult(passed, errors)


def simple_candidate_filter(candidates: List[Dict[str, Any]], 
                           plan: PlanV1, 
                           contract: SafetyContract) -> List[Tuple[int, Dict[str, Any]]]:
    """简单的候选过滤：只保留通过MUST约束的候选"""
    valid_candidates = []
    
    for i, candidate in enumerate(candidates):
        cand_dict = _to_candidate_dict(candidate)
        sql = cand_dict.get("sql", "")
        if not sql:
            continue
        
        # 检查基本有效性
        basic_result = check_basic_sql_validity(sql)
        if not basic_result.passed:
            continue
        
        # 检查MUST约束
        _dbg(f"  · 候选{i+1}原始SQL: {sql}")
        must_result = validate_must_constraints(sql, plan, contract)
        if not must_result.passed:
            # 记录失败原因
            if must_result.errors:
                _dbg(f"  · 候选{i+1}未通过MUST约束: {must_result.errors}")
            # 尝试最小修复
            repaired_sql = minimal_repair(sql, plan, contract)
            _dbg(f"    ↳ 修复后SQL: {repaired_sql}")
            recheck_result = validate_must_constraints(repaired_sql, plan, contract)
            
            if recheck_result.passed:
                # 修复成功，使用修复后的SQL
                cand_dict["sql"] = repaired_sql
                cand_dict["repaired"] = True
                valid_candidates.append((i, cand_dict))
            else:
                if recheck_result.errors:
                    _dbg(f"  · 候选{i+1}修复后仍未通过: {recheck_result.errors}")
        else:
            # 原SQL就通过了
            valid_candidates.append((i, cand_dict))
    
    return valid_candidates


def deterministic_selection(candidates: List[Tuple[int, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """确定性选择：在通过验证的候选中选择最简单的"""
    if not candidates:
        return None
    
    # LLM已经排序，我们只在同等情况下选择更简单的
    # 简单的选择策略：优先选择未修复的，然后选择SQL更短的
    def selection_key(item):
        idx, candidate = item
        sql = candidate.get("sql", "")
        is_repaired = candidate.get("repaired", False)
        
        # 优先级：未修复 > 修复过的，SQL长度越短越好
        return (is_repaired, len(sql), idx)
    
    candidates.sort(key=selection_key)
    return candidates[0][1]


def _to_candidate_dict(candidate: Union[Dict[str, Any], Any]) -> Dict[str, Any]:
    """将候选统一转换为字典形式，兼容Pydantic/BaseModel对象和原始字典。
    期望字段：sql(str), checks(List[Dict]), label(str 可选), confidence(float 可选)
    """
    # 已是字典
    if isinstance(candidate, dict):
        return dict(candidate)

    # Pydantic v2 BaseModel
    model_dump = getattr(candidate, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump()
        except Exception:
            pass

    # Pydantic v1 BaseModel
    to_dict = getattr(candidate, "dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            pass

    # 直接通过属性读取
    result: Dict[str, Any] = {}
    for key in ("sql", "checks", "label", "confidence"):
        if hasattr(candidate, key):
            try:
                result[key] = getattr(candidate, key)
            except Exception:
                pass
    return result


def compute_complexity_score(sql: str) -> float:
    """计算SQL复杂度分数（仅用于并列时的tie-breaker）"""
    try:
        expr = sqlglot.parse_one(sql, read="mysql")
        
        # 简单的复杂度指标
        join_count = len(list(expr.find_all(exp.Join)))
        column_count = len(list(expr.find_all(exp.Column)))
        where_count = len(list(expr.find_all(exp.Where)))
        subquery_count = len(list(expr.find_all(exp.Subquery)))
        
        # 复杂度分数（越低越简单）
        complexity = (join_count * 2 + 
                     max(0, column_count - 3) + 
                     max(0, where_count - 1) + 
                     subquery_count * 3)
        
        return complexity
    except:
        return 999.0  # 解析失败给最高复杂度


def validate_and_select_best(candidates: List[Dict[str, Any]], 
                            plan: PlanV1, 
                            contract: SafetyContract) -> Optional[Dict[str, Any]]:
    """验证并选择最佳候选（主入口函数）"""
    
    # 第一步：过滤通过MUST约束的候选
    valid_candidates = simple_candidate_filter(candidates, plan, contract)
    
    if not valid_candidates:
        return None
    
    # 第二步：确定性选择
    best_candidate = deterministic_selection(valid_candidates)
    
    return best_candidate

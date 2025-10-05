
# 🎉 去补丁化Text-to-SQL系统使用指南

## 核心理念
1. **本地不做语义筛选** - 只做客观验证，所有语义决策交给LLM
2. **MUST/SHOULD/MAY分层约束** - 明确区分硬性要求、强烈建议和可选项
3. **两次LLM调用架构** - Planner决策 + Generator生成，避免确认偏差
4. **AST级别验证** - 使用sqlglot进行精确的SQL结构分析

## 主要改进

### ✅ 已移除的补丁
- 硬编码关键词映射 (EDR_KEYWORDS, SYNONYM_ALIASES)
- 问题特定的if/else逻辑 (_prefer_tables_by_keywords)
- 场景特定的列加权 (want_tenant, virus_intent)
- 直接谓词注入补丁

### ✅ 新架构组件
- **llm_planner.py** - 第一次LLM调用，生成结构化计划
- **llm_generator.py** - 第二次LLM调用，在约束下生成SQL 
- **validation_engine.py** - 纯客观验证，不做语义判断
- **ast_validator.py** - AST级别的约束验证

## 使用方法

### 基本使用
```python
from llm_planner import llm_plan
from llm_generator import llm_generate_sql, make_safety_contract
from validation_engine import validate_and_select_best

# 1. 轻量召回获取原始候选
semantic_tables_raw = get_raw_candidates(question)

# 2. LLM#1 - Planner
plan = llm_plan(question, kb_hint, schema_clip, semantic_tables_raw, semantic_colmap_raw)

# 3. 构建Safety Contract
contract = make_safety_contract(
    allowed_tables=plan.must_tables,
    allowed_cols=selected_columns,
    must_predicates=plan.must_predicates,
    should_predicates=plan.should_predicates
)

# 4. LLM#2 - Generator  
candidates = llm_generate_sql(question, plan_json, contract, n_candidates=3)

# 5. 客观验证选择
best = validate_and_select_best(candidates, plan, contract)
```

### MUST/SHOULD/MAY约束
```python
plan = PlanV1(
    # 硬性要求 - 违反则失败
    must_tables=["weak_password_app_detail"],
    must_joins=["table1.id = table2.id"], 
    must_predicates=["pass_wd IS NOT NULL"],
    
    # 强烈建议 - 优先满足
    should_predicates=["detect_status = 1"],
    should_projection=["app_name", "level"],
    
    # 可选项 - 空间允许时使用
    may_projection=["last_find_time", "less_user"]
)
```

## 扩展新语义

### 方法1: 更新Planner Few-shot
在 `llm_planner.py` 中添加新的示例:
```python
Q: "新的业务问题"
Plan: {
  "must_tables": ["new_table"],
  "must_predicates": ["new_condition"],
  "should_projection": ["new_columns"]
}
```

### 方法2: 使用配置文件 (未来)
```yaml
# domain_slots/new_domain.yaml
predicates:
  new_risk_type:
    must: ["condition1 IS NOT NULL"]
    should: ["status = 1"]
```

## 优势
1. **可维护** - 新增语义只需改few-shot，不动主流程
2. **可测试** - MUST约束可验证，SHOULD偏好可A/B
3. **职责清晰** - LLM负责语义，本地负责安全
4. **可扩展** - 分层约束支持不同优先级需求

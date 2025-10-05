#!/usr/bin/env python3
"""
LLM规划器模块 - 第一次LLM调用
将用户问题转换为结构化的执行计划，包含必需表、谓词、JOIN等约束
"""

import json
import re
import os
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# 类型定义
Task = Literal["list", "count", "trend", "rank", "detail", "filter", "distribution"]
Subject = Literal["app", "node", "account", "user", "endpoint", "service", "process", "risk"]


class PlanV1(BaseModel):
    """结构化执行计划 - 支持MUST/SHOULD/MAY分层"""
    task: Task = "list"
    subject: Subject = "app"
    risk: List[str] = Field(default_factory=lambda: ["weak_password"])
    
    # MUST约束（硬性要求，必须满足）
    must_tables: List[str] = Field(default_factory=list)
    must_joins: List[str] = Field(default_factory=list)
    must_predicates: List[str] = Field(default_factory=list)
    
    # SHOULD偏好（强烈建议，优先满足）
    should_predicates: List[str] = Field(default_factory=list)
    should_projection: List[str] = Field(default_factory=list)
    should_tables: List[str] = Field(default_factory=list)
    
    # MAY选项（可选，冲突时可放弃）
    may_projection: List[str] = Field(default_factory=list)
    may_predicates: List[str] = Field(default_factory=list)
    
    # 其他属性
    timeframe_days: Optional[int] = None
    groupby: List[str] = Field(default_factory=list)
    aggregates: List[str] = Field(default_factory=list)
    alt_perspectives: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = Field(default="", description="规划推理过程")
    
    # 保持向后兼容的属性
    @property
    def required_tables(self) -> List[str]:
        return self.must_tables
    
    @property
    def required_joins(self) -> List[str]:
        return self.must_joins
    
    @property
    def required_predicates(self) -> List[str]:
        return self.must_predicates
    
    @property
    def projection_priority(self) -> List[str]:
        return self.should_projection


# 规划器提示词模板
PROMPT_SYS = """You are a precise query planner for enterprise EDR analytics.
Your job is to analyze user questions and convert them into structured execution plans.
Return STRICT JSON conforming to the provided schema. No prose, no explanations."""


def _ensure_planner_client() -> Any:
    """确保OpenAI客户端可用"""
    if OpenAI is None:
        raise RuntimeError('openai 未安装，请 `pip install openai`')
    
    # 优先使用Qwen配置
    base_url = os.getenv('QWEN_BASE_URL') or os.getenv('DASHSCOPE_BASE_URL') or os.getenv('MODELSCOPE_BASE_URL', 'https://api-inference.modelscope.cn/v1')
    api_key = os.getenv('DASHSCOPE_API_KEY') or os.getenv('QWEN_API_KEY') or os.getenv('MODELSCOPE_API_KEY')
    
    if not api_key:
        raise RuntimeError('未设置 API 密钥：DASHSCOPE_API_KEY / QWEN_API_KEY / MODELSCOPE_API_KEY')
    
    return OpenAI(base_url=base_url, api_key=api_key)


def _chat_once(system: str, user: str, model: str = None, temperature: float = 0.1) -> str:
    """单次对话调用"""
    client = _ensure_planner_client()
    model_name = model or os.getenv("QWEN_MODEL", "qwen-max")
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        temperature=temperature,
        max_tokens=2048
    )
    
    return response.choices[0].message.content.strip()


def _build_planner_prompt(
    question: str,
    kb_hint: str,
    schema_clip: str,
    semantic_tables: List[str],
    semantic_colmap: Dict[str, List[str]],
    allowed_tables: List[str],
    retry_hint: str = ""
) -> str:
    """构建规划器提示词"""
    
    schema = PlanV1.model_json_schema()
    
    # 构建Few-shot示例（使用MUST/SHOULD/MAY分层）
    fewshot = """
Examples:

Q: "哪些应用存在弱口令且可被恶意利用？"
Plan: {
  "task": "list",
  "subject": "app",
  "risk": ["weak_password", "exploitable"],
  "must_tables": ["weak_password_app", "weak_password_app_detail"],
  "must_joins": ["weak_password_app_detail.app_id = weak_password_app.app_id"],
  "must_predicates": ["weak_password_app_detail.pass_wd IS NOT NULL"],
  "should_tables": ["weak_node_status"],
  "should_predicates": ["weak_node_status.detect_status = 1"],
  "should_projection": ["weak_password_app.name", "weak_password_app.app_id", "weak_password_app_detail.level", "weak_password_app_detail.last_find_time"],
  "may_projection": ["weak_password_app_detail.node_id", "weak_password_app_detail.less_user"],
  "confidence": 0.9,
  "reasoning": "MUST: 弱口令基础数据; SHOULD: 检测状态确认可利用性; MAY: 额外上下文信息"
}

Q: "哪些应用存在弱口令？"
Plan: {
  "task": "list",
  "subject": "app",
  "risk": ["weak_password"],
  "must_tables": ["weak_password_app", "weak_password_app_detail"],
  "must_joins": ["weak_password_app_detail.app_id = weak_password_app.app_id"],
  "must_predicates": ["weak_password_app_detail.pass_wd IS NOT NULL"],
  "should_projection": ["weak_password_app.name", "weak_password_app.app_id", "weak_password_app_detail.level"],
  "may_projection": ["weak_password_app_detail.last_find_time", "weak_password_app_detail.less_user"],
  "confidence": 0.95,
  "reasoning": "MUST: 弱口令核心信息; SHOULD: 应用标识和级别; MAY: 时间和租户信息"
}

Q: "最近30天弱口令应用数量趋势"
Plan: {
  "task": "trend",
  "subject": "app", 
  "risk": ["weak_password"],
  "must_tables": ["weak_password_app_detail"],
  "must_predicates": ["weak_password_app_detail.pass_wd IS NOT NULL", "weak_password_app_detail.last_find_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)"],
  "timeframe_days": 30,
  "groupby": ["DATE(weak_password_app_detail.last_find_time)"],
  "aggregates": ["COUNT(DISTINCT weak_password_app_detail.app_id)"],
  "should_projection": ["DATE(weak_password_app_detail.last_find_time)", "COUNT(DISTINCT weak_password_app_detail.app_id)"],
  "confidence": 0.95,
  "reasoning": "MUST: 时间范围和弱口令条件; SHOULD: 按日期分组统计"
}
"""
    
    allowed_tables_str = ", ".join(sorted(allowed_tables)) if allowed_tables else ""
    # 从 schema_clip 构造严格的列白名单
    try:
        schema_obj = json.loads(schema_clip)
        _tbls = schema_obj.get("tables", [])
        allowed_cols_map = {t.get("name"): [c.get("name") for c in (t.get("columns") or [])] for t in _tbls}
    except Exception:
        allowed_cols_map = {}

    user_prompt = f"""
Question (Chinese):
{question}

Context:
- KB hint (markdown excerpt):
{kb_hint[:2000]}

- M-Schema (subset JSON):
{schema_clip[:3000]}

- Semantic candidates:
tables={semantic_tables}
columns_by_table={json.dumps(semantic_colmap, ensure_ascii=False)[:2000]}

- STRICT Allowed Tables:
{allowed_tables_str}

- STRICT Allowed Columns (per table):
{json.dumps(allowed_cols_map, ensure_ascii=False)[:2000]}

{fewshot}

Planning Rules (MUST/SHOULD/MAY Framework):
1) MUST constraints are hard requirements - SQL generation will fail if violated:
   - must_tables: Essential tables for the query (e.g., "weak_password_app_detail" for weak password queries)
   - must_joins: Critical table connections (e.g., "weak_password_app_detail.app_id = weak_password_app.app_id")  
   - must_predicates: Non-negotiable filter conditions (e.g., "weak_password_app_detail.pass_wd IS NOT NULL")

2) SHOULD constraints are strong preferences - prioritize but allow flexibility:
   - should_tables: Preferred additional tables for richer data
   - should_predicates: Important filters that enhance results (e.g., "weak_node_status.detect_status = 1")
   - should_projection: Preferred column display order

3) MAY constraints are optional - use when space/performance allows:
   - may_projection: Nice-to-have columns for additional context
   - may_predicates: Optional filters for refinement

4) CRITICAL: Use FULL table.column names in ALL constraints - never use aliases or shortcuts:
   - CORRECT: "weak_password_app_detail.pass_wd IS NOT NULL"
   - WRONG: "wpad.pass_wd IS NOT NULL" or "pass_wd IS NOT NULL"
   - CORRECT: "weak_password_app_detail.app_id = weak_password_app.app_id"
   - WRONG: "wpad.app_id = wpa.app_id"
5) ALL tables referenced in any constraint MUST be included in must_tables or should_tables.
6) For 业务应用 queries, prefer subject='app'; include timeframe_days only if time scope is implied.
7) Categorize constraints by business criticality: core functionality → MUST, enhancement → SHOULD, context → MAY.
8) Ensure constraint consistency: all predicates and joins must reference available tables.
9) Verify that table names in constraints exactly match those available in STRICT Allowed Tables. Do NOT invent tables.
10) Column references (in predicates/projection/groupby/aggregates) MUST be from the STRICT Allowed Columns map for their table.

{retry_hint}

Return ONLY JSON validated by this SCHEMA:
{json.dumps(schema, ensure_ascii=False, indent=2)}
"""
    
    return user_prompt


def llm_plan(
    question: str,
    kb_hint: str,
    schema_clip: str,
    semantic_tables: List[str],
    semantic_colmap: Dict[str, List[str]],
    model: str = None,
    temperature: float = 0.1
) -> PlanV1:
    """
    LLM规划器主函数
    
    Args:
        question: 用户问题
        kb_hint: KB摘要信息
        schema_clip: M-Schema子集JSON
        semantic_tables: 语义召回的表列表
        semantic_colmap: 语义召回的列映射
        model: 使用的模型名称
        temperature: 生成温度
    
    Returns:
        PlanV1: 结构化执行计划
    """
    try:
        # 构建提示词
        # 严格允许的表：来自 schema_clip（外部应确保只包含有效表）
        try:
            schema_obj = json.loads(schema_clip)
            allowed_tables = [t.get("name") for t in schema_obj.get("tables", [])]
        except Exception:
            allowed_tables = list(semantic_tables)

        user_prompt = _build_planner_prompt(
            question, kb_hint, schema_clip, semantic_tables, semantic_colmap, allowed_tables
        )
        
        # 调用LLM
        raw_response = _chat_once(PROMPT_SYS, user_prompt, model, temperature)
        
        # 提取并解析JSON
        json_match = re.search(r'\{.*\}', raw_response, flags=re.DOTALL)
        if not json_match:
            print(f"⚠️ 规划器响应中未找到JSON格式，使用默认计划")
            return PlanV1()
        
        json_str = json_match.group(0)
        plan_data = json.loads(json_str)
        
        # 验证并创建结构化计划
        plan = PlanV1(**plan_data)

        # 计划清洗：移除任何不在 allowed_tables 的表引用
        def _filter_tables(items: List[str]) -> List[str]:
            return [x for x in items if x in allowed_tables]

        original_must_tables = list(plan.must_tables)
        plan.must_tables = _filter_tables(plan.must_tables)
        plan.should_tables = _filter_tables(plan.should_tables)

        # 若 MUST 表被移除或 MUST 谓词/连接引用了未知表，则触发一次重试，强调约束
        def _has_unknown_table_ref(texts: List[str]) -> bool:
            import re as _re
            for text in texts or []:
                for match in _re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.", str(text)):
                    if match not in allowed_tables:
                        return True
            return False

        need_retry = (
            len(plan.must_tables) < len(original_must_tables)
            or _has_unknown_table_ref(plan.must_predicates)
            or _has_unknown_table_ref(plan.must_joins)
        )

        if need_retry:
            retry_hint = f"CRITICAL: Retry. You MUST use ONLY these tables: {', '.join(sorted(allowed_tables))}. Remove or replace any table not in this list."
            user_prompt_retry = _build_planner_prompt(
                question, kb_hint, schema_clip, semantic_tables, semantic_colmap, allowed_tables, retry_hint
            )
            raw_response_retry = _chat_once(PROMPT_SYS, user_prompt_retry, model, temperature)
            json_match_retry = re.search(r'\{.*\}', raw_response_retry, flags=re.DOTALL)
            if json_match_retry:
                plan_data_retry = json.loads(json_match_retry.group(0))
                plan = PlanV1(**plan_data_retry)
                plan.must_tables = _filter_tables(plan.must_tables)
                plan.should_tables = _filter_tables(plan.should_tables)
        
        print(f"✅ 规划器生成计划: 任务={plan.task}, 主题={plan.subject}, 风险={plan.risk}")
        if plan.required_predicates:
            print(f"   必需谓词: {plan.required_predicates}")
        if plan.projection_priority:
            print(f"   优先列: {plan.projection_priority}")
        if need_retry:
            print("   已对 Planner 进行一次约束重试并清洗计划")
        
        return plan
        
    except json.JSONDecodeError as e:
        print(f"❌ 规划器JSON解析失败: {e}")
        print(f"响应内容: {raw_response[:500]}...")
        return PlanV1()
    except Exception as e:
        print(f"❌ 规划器失败: {e}")
        return PlanV1()


def apply_plan_to_context(
    plan: PlanV1,
    table_names: List[str],
    selected_columns: Dict[str, List[str]],
    auto_evidence_parts: List[str]
) -> tuple[List[str], Dict[str, List[str]], List[str]]:
    """
    将计划应用到现有上下文
    
    Args:
        plan: 执行计划
        table_names: 当前表名列表
        selected_columns: 当前选中的列映射
        auto_evidence_parts: 自动证据部分
    
    Returns:
        tuple: (更新后的表名, 更新后的列映射, 更新后的证据)
    """
    # 1. 补充必需表
    updated_tables = list(table_names)
    for table in plan.required_tables:
        if table not in updated_tables:
            updated_tables.append(table)
    
    # 2. 应用列优先级
    updated_columns = dict(selected_columns)
    if plan.projection_priority:
        for table, cols in updated_columns.items():
            # 提取属于当前表的优先列
            table_priority_cols = []
            for col in plan.projection_priority:
                # 处理带表前缀的列名 (如 "weak_password_app.name")
                if '.' in col:
                    t, c = col.split('.', 1)
                    if t == table and c in cols:
                        table_priority_cols.append(c)
                elif col in cols:
                    table_priority_cols.append(col)
            
            # 重排列：优先列在前，其他列在后
            other_cols = [c for c in cols if c not in table_priority_cols]
            updated_columns[table] = (table_priority_cols + other_cols)[:8]
    
    # 3. 更新证据
    updated_evidence = list(auto_evidence_parts)
    
    if plan.required_predicates:
        updated_evidence.append("业务约束: " + " AND ".join(plan.required_predicates))
    
    if plan.required_joins:
        updated_evidence.append("推荐连接: " + "; ".join(plan.required_joins))
    
    if plan.timeframe_days:
        updated_evidence.append(f"时间范围: 最近{plan.timeframe_days}天")
    
    if plan.groupby:
        updated_evidence.append("分组字段: " + ", ".join(plan.groupby))
    
    if plan.aggregates:
        updated_evidence.append("聚合函数: " + ", ".join(plan.aggregates))
    
    return updated_tables, updated_columns, updated_evidence

#!/usr/bin/env python3
"""
LLM受约束生成器模块 - 第二次LLM调用
在严格的安全合同约束下生成Top-K SQL候选，包含自检验证
"""

import json
import re
import os
from typing import List, Dict, Any, Optional
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


class SQLCandidate(BaseModel):
    """SQL候选对象"""
    label: str = Field(description="候选标签，如'app视角'、'node视角'等")
    sql: str = Field(description="生成的SQL语句")
    checks: List[Dict[str, Any]] = Field(default_factory=list, description="自检项列表")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="生成置信度")


class SafetyContract(BaseModel):
    """安全合同 - 定义Generator的分层约束（MUST/SHOULD/MAY）"""
    allowed_tables: List[str] = Field(description="允许使用的表列表")
    allowed_columns: Dict[str, List[str]] = Field(description="每个表允许的列")
    
    # MUST约束 - 硬性要求
    must_tables: List[str] = Field(default_factory=list, description="必需包含的表")
    must_joins: List[str] = Field(default_factory=list, description="必需的JOIN条件")
    must_predicates: List[str] = Field(default_factory=list, description="必需的WHERE条件")
    
    # SHOULD约束 - 强烈建议
    should_predicates: List[str] = Field(default_factory=list, description="建议的WHERE条件")
    should_projection: List[str] = Field(default_factory=list, description="建议的列显示顺序")
    
    # MAY约束 - 可选
    may_predicates: List[str] = Field(default_factory=list, description="可选的WHERE条件")
    may_projection: List[str] = Field(default_factory=list, description="可选的显示列")
    
    # 其他约束
    timeframe_days: Optional[int] = Field(default=None, description="时间窗口天数")
    forbidden_clauses: List[str] = Field(default_factory=lambda: ["ORDER BY"], description="禁用子句")
    
    # 保持向后兼容
    @property
    def required_joins(self) -> List[str]:
        return self.must_joins
    
    @property
    def required_predicates(self) -> List[str]:
        return self.must_predicates


# 生成器提示词模板
PROMPT_SYS_SQL = """You are a disciplined SQL generator for enterprise EDR analytics.

CRITICAL FILTERING RULES (MUST FOLLOW):
1. Generate initial SQL candidates internally
2. For EACH candidate, perform self-check against MUST constraints
3. IMMEDIATELY DISCARD any candidate where:
   - must_predicates_present = false
   - must_joins_present = false  
   - only_allowed_tables_columns = false
4. ONLY return candidates that pass ALL MUST constraint checks
5. Rank surviving candidates by SHOULD constraint satisfaction

NEVER include failed candidates in output. If all candidates fail MUST checks, return empty candidates array.

Output format: JSON only with candidates[].sql, candidates[].checks[], candidates[].confidence.
No prose, no explanations, just the JSON structure."""


def _ensure_generator_client() -> Any:
    """确保OpenAI客户端可用"""
    if OpenAI is None:
        raise RuntimeError('openai 未安装，请 `pip install openai`')
    
    # 优先使用Qwen配置
    base_url = os.getenv('QWEN_BASE_URL') or os.getenv('DASHSCOPE_BASE_URL') or os.getenv('MODELSCOPE_BASE_URL', 'https://api-inference.modelscope.cn/v1')
    api_key = os.getenv('DASHSCOPE_API_KEY') or os.getenv('QWEN_API_KEY') or os.getenv('MODELSCOPE_API_KEY')
    
    if not api_key:
        raise RuntimeError('未设置 API 密钥：DASHSCOPE_API_KEY / QWEN_API_KEY / MODELSCOPE_API_KEY')
    
    return OpenAI(base_url=base_url, api_key=api_key)


def _chat_once_generator(system: str, user: str, model: str = None, temperature: float = 0.2) -> str:
    """单次对话调用"""
    client = _ensure_generator_client()
    model_name = model or os.getenv("QWEN_MODEL", "qwen-max")
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        temperature=temperature,
        max_tokens=3072
    )
    
    return response.choices[0].message.content.strip()


def make_safety_contract(
    allowed_tables: List[str],
    allowed_cols: Dict[str, List[str]],
    must_tables: List[str] = None,
    must_joins: List[str] = None,
    must_predicates: List[str] = None,
    should_predicates: List[str] = None,
    should_projection: List[str] = None,
    may_predicates: List[str] = None,
    may_projection: List[str] = None,
    timeframe_days: Optional[int] = None,
    forbidden_clauses: List[str] = None,
    # 保持向后兼容
    required_joins: List[str] = None,
    required_predicates: List[str] = None
) -> SafetyContract:
    """创建分层安全合同"""
    return SafetyContract(
        allowed_tables=allowed_tables,
        allowed_columns=allowed_cols,
        must_tables=must_tables or [],
        must_joins=must_joins or required_joins or [],
        must_predicates=must_predicates or required_predicates or [],
        should_predicates=should_predicates or [],
        should_projection=should_projection or [],
        may_predicates=may_predicates or [],
        may_projection=may_projection or [],
        timeframe_days=timeframe_days,
        forbidden_clauses=forbidden_clauses or ["ORDER BY"]
    )


def _build_generator_prompt(
    question: str,
    plan_json: str,
    safety_contract: SafetyContract,
    n_candidates: int = 3
) -> str:
    """构建生成器提示词"""
    
    # 构建Few-shot示例（确保与合同一致）
    fewshot = f"""
Example Input:
Question: "哪些应用存在弱口令？"
Plan: {{"task": "list", "subject": "app", "must_predicates": ["weak_password_app_detail.pass_wd IS NOT NULL"], "should_projection": ["weak_password_app.name", "weak_password_app.app_id"]}}
Contract: {{"allowed_tables": ["weak_password_app", "weak_password_app_detail"], "allowed_columns": {{"weak_password_app": ["name", "app_id"], "weak_password_app_detail": ["pass_wd", "level", "app_id"]}}, "must_joins": ["weak_password_app_detail.app_id = weak_password_app.app_id"], "must_predicates": ["weak_password_app_detail.pass_wd IS NOT NULL"]}}

Example Output:
{{
  "candidates": [
    {{
      "label": "SHOULD满足度最高",
      "sql": "SELECT wpa.name, wpa.app_id, wpad.level FROM weak_password_app wpa JOIN weak_password_app_detail wpad ON wpad.app_id = wpa.app_id WHERE wpad.pass_wd IS NOT NULL LIMIT 200",
      "checks": [
        {{"name": "must_predicates_present", "pass": true}},
        {{"name": "must_joins_present", "pass": true}},
        {{"name": "only_allowed_tables_columns", "pass": true}},
        {{"name": "should_predicates_considered", "pass": true}},
        {{"name": "timeframe_applied", "pass": true}}
      ],
      "confidence": 0.9
    }},
    {{
      "label": "基础MUST满足", 
      "sql": "SELECT wpa.name, wpa.app_id FROM weak_password_app wpa JOIN weak_password_app_detail wpad ON wpad.app_id = wpa.app_id WHERE wpad.pass_wd IS NOT NULL LIMIT 200",
      "checks": [
        {{"name": "must_predicates_present", "pass": true}},
        {{"name": "must_joins_present", "pass": true}},
        {{"name": "only_allowed_tables_columns", "pass": true}},
        {{"name": "should_predicates_considered", "pass": false}},
        {{"name": "timeframe_applied", "pass": true}}
      ],
      "confidence": 0.7
    }}
  ]
}}

CRITICAL: Only return candidates where ALL must_* checks pass. Rank candidates by SHOULD constraint satisfaction.
"""
    
    # Pydantic版本兼容性处理
    try:
        contract_json = safety_contract.model_dump_json(exclude_none=True)
    except TypeError:
        # 兼容旧版本Pydantic
        contract_json = safety_contract.json(exclude_none=True)
    
    user_prompt = f"""
Task: Generate up to {n_candidates} SQL candidates.

Question:
{question}

PLAN(JSON):
{plan_json}

SAFETY_CONTRACT(JSON):
{contract_json}

{fewshot}

Generation Rules (MUST/SHOULD/MAY Framework):
1. MUST Constraints (Hard Requirements - Failure to comply means rejection):
   - Use ONLY allowed_tables & allowed_columns from the contract
   - Include ALL must_predicates in WHERE clause
   - Include ALL must_joins when multiple tables are used
   - Respect forbidden_clauses (typically no ORDER BY)

2. SHOULD Constraints (Strong Preferences - Prioritize but allow flexibility):
   - Prefer should_predicates when they enhance the query
   - Use should_projection for column ordering and selection
   - Balance SHOULD constraints with query clarity

3. MAY Constraints (Optional - Use when space/performance allows):
   - Consider may_predicates for additional filtering
   - Include may_projection columns if they add value

4. Additional Rules:
   - Add timeframe constraints if timeframe_days is specified
   - Always include LIMIT (default 200) unless aggregating
   - Generate candidates ranked by SHOULD satisfaction (best first)
   - CRITICAL: Filter out any candidate where must_* checks fail before returning
   - Self-validate each candidate and exclude failures from the result

Return ONLY JSON in this exact format:
{{
  "candidates": [
    {{
      "label": "string description",
      "sql": "SELECT ... FROM ... WHERE ... LIMIT ...",
      "checks": [
        {{"name": "must_predicates_present", "pass": true/false}},
        {{"name": "must_joins_present", "pass": true/false}},
        {{"name": "only_allowed_tables_columns", "pass": true/false}},
        {{"name": "should_predicates_considered", "pass": true/false}},
        {{"name": "timeframe_applied", "pass": true/false}}
      ],
      "confidence": 0.0-1.0
    }}
  ]
}}
"""
    
    return user_prompt


def llm_generate_sql(
    question: str,
    plan_json: str,
    safety_contract: SafetyContract,
    n_candidates: int = 3,
    model: str = None,
    temperature: float = 0.2
) -> List[SQLCandidate]:
    """
    LLM受约束生成器主函数
    
    Args:
        question: 用户问题
        plan_json: 执行计划JSON字符串
        safety_contract: 安全合同
        n_candidates: 候选数量
        model: 使用的模型名称
        temperature: 生成温度
    
    Returns:
        List[SQLCandidate]: SQL候选列表
    """
    try:
        # 构建提示词
        user_prompt = _build_generator_prompt(
            question, plan_json, safety_contract, n_candidates
        )
        
        # 调用LLM
        raw_response = _chat_once_generator(PROMPT_SYS_SQL, user_prompt, model, temperature)
        
        # 提取并解析JSON
        json_match = re.search(r'\{.*\}', raw_response, flags=re.DOTALL)
        if not json_match:
            print(f"⚠️ 生成器响应中未找到JSON格式")
            return []
        
        json_str = json_match.group(0)
        response_data = json.loads(json_str)
        
        # 解析候选列表
        candidates = []
        for cand_data in response_data.get("candidates", []):
            try:
                candidate = SQLCandidate(**cand_data)
                candidates.append(candidate)
            except Exception as e:
                print(f"⚠️ 解析候选SQL失败: {e}")
                continue
        
        print(f"✅ 生成器产出 {len(candidates)} 个SQL候选")
        for i, cand in enumerate(candidates):
            print(f"   候选{i+1}: {cand.label} (置信度: {cand.confidence:.2f})")
        
        return candidates
        
    except json.JSONDecodeError as e:
        print(f"❌ 生成器JSON解析失败: {e}")
        print(f"响应内容: {raw_response[:500]}...")
        return []
    except Exception as e:
        print(f"❌ 生成器失败: {e}")
        return []


def score_sql_candidate(
    candidate: SQLCandidate,
    required_predicates: List[str],
    component_score_func=None
) -> float:
    """
    为SQL候选打分
    
    Args:
        candidate: SQL候选对象
        required_predicates: 必需谓词列表
        component_score_func: 组件评分函数
    
    Returns:
        float: 综合得分
    """
    # 1. 组件得分（复用现有函数）
    component_score = 0.0
    if component_score_func:
        try:
            component_score = component_score_func(candidate.sql, {})
        except:
            component_score = 0.0
    
    # 2. 槽位满足度
    slot_satisfaction = _calculate_slot_satisfaction(candidate.sql, required_predicates)
    
    # 3. 自检通过率
    check_pass_rate = _calculate_check_pass_rate(candidate.checks)
    
    # 4. 候选置信度
    confidence_score = candidate.confidence
    
    # 综合评分：组件分(30%) + 槽位满足度(40%) + 自检通过率(20%) + 置信度(10%)
    final_score = (
        0.3 * component_score +
        0.4 * slot_satisfaction +
        0.2 * check_pass_rate +
        0.1 * confidence_score
    )
    
    return final_score


def _calculate_slot_satisfaction(sql: str, required_predicates: List[str]) -> float:
    """计算槽位满足度"""
    if not required_predicates:
        return 0.5
    
    sql_lower = sql.lower()
    satisfied = sum(1 for pred in required_predicates if pred.lower() in sql_lower)
    return 0.5 + 0.5 * (satisfied / len(required_predicates))


def _calculate_check_pass_rate(checks: List[Dict[str, Any]]) -> float:
    """计算自检通过率"""
    if not checks:
        return 0.5
    
    passed = sum(1 for check in checks if check.get("pass", False))
    return passed / len(checks)


def select_best_candidate(
    candidates: List[SQLCandidate],
    required_predicates: List[str],
    component_score_func=None
) -> Optional[SQLCandidate]:
    """
    选择最佳SQL候选
    
    Args:
        candidates: SQL候选列表
        required_predicates: 必需谓词列表
        component_score_func: 组件评分函数
    
    Returns:
        Optional[SQLCandidate]: 最佳候选，如果没有则为None
    """
    if not candidates:
        return None
    
    # 为每个候选打分
    scored_candidates = []
    for candidate in candidates:
        score = score_sql_candidate(candidate, required_predicates, component_score_func)
        scored_candidates.append((score, candidate))
    
    # 按得分排序，选择最高分
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_candidate = scored_candidates[0]
    
    print(f"✅ 选择最佳候选: {best_candidate.label} (得分: {best_score:.3f})")
    
    return best_candidate

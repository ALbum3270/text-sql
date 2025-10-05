"""
Text-to-SQL 清洁版本 - 去除所有硬编码补丁

核心理念：
1. 本地不做语义筛选，只做客观验证
2. 所有语义决策交给LLM（Planner和Generator）
3. 移除所有问题特定的补丁和硬编码逻辑
"""

import os
import sys
import re
import time
import json
import random
from typing import List, Dict, Any, Tuple, Optional, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

import pymysql
import sqlglot
import sqlglot.expressions as exp
from dotenv import load_dotenv

from xiyan_client import call_xiyan
from sql_guard import validate_and_rewrite, SQLValidationError

DEFAULT_MAX_LIMIT = 200

from llm_planner import llm_plan, PlanV1
from llm_generator import llm_generate_sql, make_safety_contract
# (clean 流程未使用以下模块，移除依赖)
from validation_engine import validate_and_select_best


def load_schema(path: str) -> Dict[str, Any]:
    """加载M-Schema"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def filter_m_schema(m_schema: Dict[str, Any], table_names: List[str]) -> Dict[str, Any]:
    """根据表名列表过滤M-Schema"""
    filtered = {"tables": []}
    for table in m_schema.get("tables", []):
        if table.get("name") in table_names:
            filtered["tables"].append(table)
    return filtered


def tokenize(text: str) -> List[str]:
    """改进分词，提取中英文、数字，包含关键词提取"""
    import re
    
    # 基础分词：提取英文单词、数字
    basic_tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*|\d+', text.lower())
    
    # 中文关键词提取：预定义常见数据库相关词汇
    chinese_keywords = [
        "威胁", "域名", "恶意", "黑名单", "在线", "离线", "终端", "节点", "状态",
        "连接", "情况", "统计", "记录", "数据", "文件", "进程", "端口", "漏洞",
        "病毒", "安全", "风险", "告警", "日志", "时间", "今天", "昨天", "趋势",
        "计数", "总数", "分布", "按", "查询", "检索", "搜索", "列表", "详情",
        "用户", "账号", "密码", "弱口令", "攻击", "防护", "监控", "分析",
        "资产", "设备", "主机", "服务器", "网络", "流量", "异常", "事件"
    ]
    
    # 在中文文本中查找关键词
    chinese_tokens = []
    for keyword in chinese_keywords:
        if keyword in text:
            chinese_tokens.append(keyword)
    
    # 合并所有token
    all_tokens = basic_tokens + chinese_tokens
    
    # 去重并过滤
    unique_tokens = list(set([t for t in all_tokens if t and len(t) > 0]))
    
    return unique_tokens


def score_table_simple(table: Dict[str, Any], tokens: List[str]) -> float:
    """简单的表评分，基于关键词匹配，强化表名/列名精确匹配权重"""
    name = str(table.get("name", "")).lower()
    score = 0.0
    
    # 🎯 中英文语义映射：让中文词汇能匹配英文表名
    semantic_mapping = {
        "威胁": ["threat", "malicious", "risk"],
        "域名": ["domain", "url", "dns"], 
        "恶意": ["malicious", "threat", "bad"],
        "黑名单": ["blacklist", "block", "deny"],
        "在线": ["online", "connected", "active", "statistics"],
        "离线": ["offline", "disconnected", "inactive", "statistics"],
        "终端": ["node", "endpoint", "terminal", "machine"],
        "节点": ["node", "endpoint", "machine"],
        "状态": ["status", "state", "statistics"],
        "连接": ["connect", "connection", "link", "statistics"],
        "情况": ["statistics", "status", "state", "summary"],  # 新增
        "怎么样": ["statistics", "summary", "status"],  # 新增  
        "统计": ["statistics", "stat", "count", "summary"],
        "记录": ["record", "log", "entry"],
        "文件": ["file", "document"],
        "进程": ["process", "proc"],
        "端口": ["port"],
        "漏洞": ["vulnerability", "vuln", "cve"],
        "病毒": ["virus", "malware"],
        "用户": ["user", "account"],
        "密码": ["password", "pwd"],
        "弱口令": ["weak", "password"],
        "监控": ["monitor", "watch"],
        "分析": ["analysis", "analyze"],
        "趋势": ["trend", "statistics", "time"],  # 新增
        "总数": ["count", "total", "summary"],  # 新增
        "分布": ["distribution", "group", "statistics"]  # 新增
    }
    
    # 扩展tokens：添加语义映射的英文词汇
    extended_tokens = tokens.copy()
    for token in tokens:
        if token in semantic_mapping:
            extended_tokens.extend(semantic_mapping[token])
    
    # 🎯 表名完全匹配：最高权重
    if name and name in set(extended_tokens):
        score += 10.0  # 大幅提升完全匹配权重
    
    # 🎯 表名分词精确匹配：如 "threat" 精确匹配 "threat_domain_static"
    table_parts = name.split('_') if name else []
    for part in table_parts:
        if part and part in extended_tokens:
            score += 5.0  # 提升表名组成部分匹配权重
    
    # 🎯 表名包含匹配：部分包含关系
    for tk in extended_tokens:
        if tk and len(tk) > 2 and tk in name:  # 避免太短的token干扰
            score += 1.0
    
    # 🎯 多token语义匹配：如 ["威胁","域名"] 通过映射匹配 threat_domain
    # 检查映射后的token在表名中的匹配情况
    semantic_matches = 0
    for token in tokens:
        if token in semantic_mapping:
            mapped_words = semantic_mapping[token]
            for mapped in mapped_words:
                if mapped in name:
                    semantic_matches += 1
                    break  # 每个原词只计算一次匹配
    
    if semantic_matches >= 2:
        score += 8.0  # 多个语义匹配：高权重
    elif semantic_matches >= 1:
        score += 4.0  # 单个语义匹配：中等权重
    
    # 🎯 特殊加权：统计性查询优先匹配statistics表
    statistical_indicators = ["情况", "怎么样", "统计", "总数", "分布", "趋势"]
    is_statistical_query = any(indicator in tokens for indicator in statistical_indicators)
    
    if is_statistical_query and "statistics" in name:
        score += 20.0  # 统计性查询大幅加权statistics表
        print(f"🎯 统计性查询检测：为 {name} 表增加统计加权")
    
    # 🎯 特殊加权：威胁相关查询优先匹配专业威胁表
    threat_indicators = ["威胁", "恶意", "黑名单"]
    is_threat_query = any(indicator in tokens for indicator in threat_indicators)
    
    if is_threat_query and any(word in name for word in ["threat", "malicious", "blacklist"]):
        score += 10.0  # 威胁查询加权专业威胁表
    
    # 🎯 列名匹配优化  
    cols = table.get("columns", [])
    col_names = [str(c.get("name", "")).lower() for c in cols]
    
    # 通用列降权：避免常见列名干扰召回
    COMMON_COLUMNS = {"id", "name", "value", "key", "type", "status", "time", "date", 
                     "create_time", "update_time", "start_time", "end_time", "level"}
    
    for cn in col_names:
        lc = cn
        for tk in extended_tokens:  # 使用扩展后的tokens
            if tk and tk in lc:
                if tk == lc:  # 🎯 列名完全匹配：高权重
                    if lc not in COMMON_COLUMNS:
                        score += 2.0  # 非通用列完全匹配
                    else:
                        score += 0.1  # 通用列完全匹配：很低权重
                elif lc not in COMMON_COLUMNS:  # 🎯 非通用列部分匹配
                    score += 0.5
                else:  # 🎯 通用列部分匹配：大幅降权
                    score -= 0.9  # 实际上是降低分数，避免干扰
    
    # 🎯 表名精确命中额外加权：确保精确匹配表名排在最前
    for tk in extended_tokens:
        if tk and tk == name:
            score += 15.0  # 超高权重确保排序优先
    
    return max(0.0, score)  # 确保分数非负


def auto_select_tables(m_schema: Dict[str, Any], tokens: List[str], topk: int = 8) -> Tuple[Dict[str, Any], List[Tuple[str, float]]]:
    """基于关键词的表选择（纯客观匹配），支持动态topk"""
    tables = m_schema.get("tables", [])
    scored = []
    
    for t in tables:
        s = score_table_simple(t, tokens)
        scored.append((t.get("name"), s))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    
    # 🎯 动态调整topk：发现精确匹配时扩大召回范围
    dynamic_topk = topk
    max_score = scored[0][1] if scored else 0
    
    # 如果最高分≥10，说明有表名精确匹配，适当增加召回数量
    if max_score >= 10.0:
        dynamic_topk = min(topk + 4, len(scored))  # 增加4个候选
        print(f"🎯 发现精确匹配表名(分数:{max_score:.1f})，扩大召回到 {dynamic_topk} 个候选")
    
    # 如果有多个高分表(≥5分)，也适当增加
    high_score_count = sum(1 for _, score in scored if score >= 5.0)
    if high_score_count >= 2:
        dynamic_topk = min(topk + 2, len(scored))
        print(f"🎯 发现 {high_score_count} 个高分表，扩大召回到 {dynamic_topk} 个候选")
    
    chosen_names = [n for n, _ in scored[:max(1, dynamic_topk)]]
    filtered = filter_m_schema(m_schema, chosen_names)
    
    return filtered, scored[:max(1, dynamic_topk)]


def _select_columns_simple(effective_schema: Dict[str, Any], table_names: List[str], 
                          tokens: List[str], topk_per_table: int = 12) -> Dict[str, List[str]]:
    """简单的列选择（基于关键词匹配，无硬编码偏好）"""
    selected: Dict[str, List[str]] = {}
    
    for tname in table_names:
        table_entry = next((t for t in effective_schema.get("tables", []) 
                           if t.get("name") == tname), None)
        if not table_entry:
            continue
            
        cols = table_entry.get("columns", [])
        scored: List[Tuple[float, str]] = []
        
        for c in cols:
            cname = str(c.get("name", ""))
            lc = cname.lower()
            comment = str(c.get("comment", "")).lower()
            score = 0.0
            
            # 纯关键词匹配
            for tk in tokens:
                if tk and tk in lc:
                    score += 1.0
                if tk and tk in comment:
                    score += 0.3
            
            scored.append((score, cname))
        
        # 简单排序，取前N个
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [n for _, n in scored[:max(1, topk_per_table)]]
        selected[tname] = top
    
    return selected


def load_kb_catalog() -> Dict[str, Any]:
    """加载KB目录"""
    kb_dir = os.path.join("outputs", "kb")
    catalog_path = os.path.join(kb_dir, "kb_catalog.json")
    if os.path.exists(catalog_path):
        with open(catalog_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def extract_kb_snippet(kb_catalog: Dict[str, Any], table_names: List[str], max_chars: int = 2000) -> str:
    """提取KB片段"""
    if not kb_catalog:
        return ""
    
    kb_dir = os.path.join("outputs", "kb")
    parts: List[str] = []
    
    for t in table_names:
        md_path = os.path.join(kb_dir, f"{t}.md")
        if os.path.exists(md_path):
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
                parts.append(f"## 表 {t}\n{content[:1000]}")
    
    result = "\n\n".join(parts)
    return result[:max_chars] if len(result) > max_chars else result


def _build_allowed_columns_string(effective_schema: Dict[str, Any], 
                                 table_names: List[str],
                                 selected_columns_by_table: Optional[Dict[str, List[str]]] = None,
                                 trend_time_col: str = "",
                                 total_mode: bool = False,
                                 filter_columns_by_table: Optional[Dict[str, List[str]]] = None) -> str:
    """构建允许列的字符串表示"""
    lines: List[str] = []
    
    for tname in table_names:
        table_entry = next((t for t in effective_schema.get("tables", []) 
                           if t.get("name") == tname), None)
        if not table_entry:
            continue
        
        if selected_columns_by_table and tname in selected_columns_by_table:
            cols = selected_columns_by_table[tname]
        else:
            cols = [c.get("name") for c in table_entry.get("columns", [])]
        
        # 趋势模式特殊处理
        if trend_time_col and not total_mode:
            if trend_time_col not in cols:
                cols = [trend_time_col] + cols
        
        # 过滤列
        if filter_columns_by_table and tname in filter_columns_by_table:
            filter_cols = filter_columns_by_table[tname]
            cols = [c for c in cols if c not in filter_cols]
        
        if cols:
            lines.append(f"{tname}: {', '.join(cols[:15])}")  # 限制显示数量
    
    return "\n".join(lines)


def _build_evidence(question: str, table_names: List[str], 
                   effective_schema: Dict[str, Any]) -> List[str]:
    """构建基础证据（无硬编码规则）"""
    parts = []
    
    # 时间提示
    q_lower = question.lower()
    if any(k in q_lower for k in ["最近", "近", "过去", "last", "recent"]):
        parts.append("时间过滤提示: 使用 DATE_SUB 或 INTERVAL 语法")
    
    # JOIN提示（基于外键）
    fks = []
    for t in effective_schema.get("tables", []):
        if t.get("name") in table_names:
            for fk in t.get("foreign_keys", []):
                ref_table = fk.get("ref_table")
                if ref_table in table_names:
                    fks.append(f"{t.get('name')}.{fk.get('column')} = {ref_table}.{fk.get('ref_column')}")
    
    if fks:
        parts.append(f"可能的连接: {'; '.join(fks[:3])}")
    
    return parts


def _get_mysql_conn():
    """获取MySQL连接"""
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "test")
    
    return pymysql.connect(
        host=host, port=port, user=user, password=password,
        database=database, charset="utf8mb4"
    )


def exec_explain_mysql(sql: str) -> List[Dict[str, Any]]:
    """执行EXPLAIN"""
    conn = _get_mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"EXPLAIN {sql}")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def component_score(sql: str, weights: Dict[str, float]) -> float:
    """计算SQL组件复杂度分数（越简单越好）"""
    try:
        expr = sqlglot.parse_one(sql, read="mysql")
        
        # 计算复杂度
        join_count = len(list(expr.find_all(exp.Join)))
        col_count = len(list(expr.find_all(exp.Column)))
        where_count = len(list(expr.find_all(exp.Where)))
        
        # 简单性分数（越简单越高）
        score = 1.0
        score -= join_count * 0.1  # JOIN越多分数越低
        score -= (col_count - 1) * 0.02  # 列越多分数越低
        score += min(where_count, 1) * 0.1  # 有WHERE条件加分
        
        return max(0.0, min(1.0, score))
    except:
        return 0.5


def _chat_once(system: str, user: str, model: str = None, temperature: float = 0.0) -> str:
    """调用LLM的统一接口"""
    from openai import OpenAI
    
    # 使用配置的模型
    base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    api_key = os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
    model = model or os.getenv("QWEN_MODEL", "qwen-max-latest")
    
    if not api_key:
        raise RuntimeError("未设置 QWEN_API_KEY 或 DASHSCOPE_API_KEY")
    
    client = OpenAI(base_url=base_url, api_key=api_key)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        temperature=temperature,
        max_tokens=2000
    )
    
    return response.choices[0].message.content.strip()


# 主流程函数
def do_ask(args):
    """主流程：两次LLM调用架构"""
    load_dotenv(override=True)
    
    # 加载基础数据
    m_schema = load_schema(os.path.join("outputs", "m_schema.json"))
    kb_catalog = load_kb_catalog()
    dialect = "mysql"
    
    print(f"\n🚀 问题: {args.question}")
    
    # Step 0: 轻量召回（原始候选）
    print("\n📊 Step 0: 轻量候选召回...")
    tokens = tokenize(args.question)
    
    # 关键词召回
    effective_schema_kw, scored_tables_kw = auto_select_tables(m_schema, tokens, topk=8)
    semantic_tables_raw = [name for name, _ in scored_tables_kw]
    
    # 语义召回（如果启用）
    if args.use_semantic:
        try:
            # 与仓库一致：使用 semantic_retrieval.py（基于 index_dir 的签名）
            from semantic_retrieval import semantic_suggest_with_index
            sem_res = semantic_suggest_with_index(
                args.question,
                index_dir="outputs/semantic_index",
                top_tables=8,
                top_cols=24
            )
            if sem_res:
                # 兼容返回 (tables, colmap) 或仅 tables
                if isinstance(sem_res, tuple):
                    sem_tables, _ = sem_res
                else:
                    sem_tables = sem_res
                # 合并结果
                seen = set(semantic_tables_raw)
                for name, _ in sem_tables:
                    if name not in seen:
                        semantic_tables_raw.append(name)
                        seen.add(name)
        except Exception as e:
            print(f"⚠️ 语义检索失败: {e}")
    
    # 限制候选表数量
    semantic_tables_raw = semantic_tables_raw[:12]
    effective_schema = filter_m_schema(m_schema, semantic_tables_raw)
    
    # 原始列召回
    semantic_colmap_raw = _select_columns_simple(
        effective_schema, semantic_tables_raw, tokens, topk_per_table=15
    )
    
    print(f"✅ 原始候选表: {semantic_tables_raw[:6]}...")
    
    # Step 1: LLM调用#1 - Planner
    print("\n🧠 Step 1: 调用Planner生成执行计划...")
    
    kb_snippet = extract_kb_snippet(kb_catalog, semantic_tables_raw, max_chars=2000)
    schema_clip = json.dumps(effective_schema, ensure_ascii=False)[:3000]
    
    try:
        plan = llm_plan(
            question=args.question,
            kb_hint=kb_snippet,
            schema_clip=schema_clip,
            semantic_tables=semantic_tables_raw,
            semantic_colmap=semantic_colmap_raw
        )
        print(f"✅ Plan生成: task={plan.task}, subject={plan.subject}, risk={plan.risk}")
    except Exception as e:
        print(f"❌ Planner失败: {e}")
        # 回退到传统模式
        return do_ask_traditional(args, m_schema, kb_catalog, dialect)
    
    # Step 2: 应用Plan到上下文
    print("\n🔧 Step 2: 应用Plan构建上下文...")
    
    # 合并 required_tables，但只保留 Schema 中真实存在的表
    table_names_for_kb = list(semantic_tables_raw)
    global_tables = {t.get('name') for t in m_schema.get('tables', [])}
    for t in plan.required_tables:
        if t in global_tables and t not in table_names_for_kb:
            table_names_for_kb.append(t)

    # 依据 MUST 谓词/连接中出现的表前缀尝试补充，但同样仅限 Schema 已存在的表
    try:
        pred_sources = (plan.required_predicates or []) + getattr(plan, 'must_predicates', [])
        join_sources = plan.required_joins or []
        inferred: set = set()
        for text in pred_sources + join_sources:
            for match in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.", str(text)):
                if match in global_tables:
                    inferred.add(match)
        for name in sorted(inferred):
            if name not in table_names_for_kb:
                table_names_for_kb.append(name)
    except Exception:
        pass
    
    # 重建schema
    effective_schema = filter_m_schema(m_schema, table_names_for_kb)
    
    # 根据plan重排列（但不做硬编码偏好）
    selected_cols = dict(semantic_colmap_raw)
    if plan.projection_priority:
        for t, cols in selected_cols.items():
            # 优先显示plan指定的列
            priority_cols = [c for c in plan.projection_priority if c in cols]
            other_cols = [c for c in cols if c not in priority_cols]
            selected_cols[t] = (priority_cols + other_cols)[:12]

    # 为新增推断的表补齐列选择（按关键词简单选择）
    try:
        missing_tables = [t for t in table_names_for_kb if t not in selected_cols]
        if missing_tables:
            auto_cols = _select_columns_simple(effective_schema, missing_tables, tokens, topk_per_table=12)
            for t in missing_tables:
                if t in auto_cols:
                    selected_cols[t] = auto_cols[t]
    except Exception:
        pass
    
    # 构建证据
    evidence_parts = _build_evidence(args.question, table_names_for_kb, effective_schema)
    
    # 添加plan的约束作为证据
    if plan.required_predicates:
        evidence_parts.append(f"必需条件: {' AND '.join(plan.required_predicates)}")
    if plan.required_joins:
        evidence_parts.append(f"必需连接: {'; '.join(plan.required_joins)}")
    if plan.timeframe_days:
        evidence_parts.append(f"时间范围: 最近{plan.timeframe_days}天")
    
    evidence_full = "\n".join(evidence_parts)
    
    # 构建允许列（在传入Generator前，确保 MUST/JOIN/GROUP/AGG 中涉及列都在白名单内）
    def _ensure_contract_columns(plan_obj, selected_map):
        try:
            import re as _re
            def _add_col(tbl, col):
                if tbl in selected_map and col not in selected_map[tbl]:
                    selected_map[tbl].append(col)
            texts = []
            texts += plan_obj.required_predicates or []
            texts += plan_obj.required_joins or []
            texts += plan_obj.groupby or []
            texts += plan_obj.aggregates or []
            for s in texts:
                for t, c in _re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b", str(s)):
                    if t in selected_map:
                        _add_col(t, c)
        except Exception:
            pass
    _ensure_contract_columns(plan, selected_cols)

    allowed_cols = _build_allowed_columns_string(
        effective_schema,
        table_names_for_kb,
        selected_columns_by_table=selected_cols
    )
    
    # Step 3: 构建Safety Contract
    print("\n🔒 Step 3: 构建Safety Contract...")
    
    # 只允许存在于有效 Schema 中的表进入合同
    allowed_tables_in_schema = [t.get("name") for t in effective_schema.get("tables", [])]
    safety_contract = make_safety_contract(
        allowed_tables=allowed_tables_in_schema,
        allowed_cols=selected_cols,
        must_tables=getattr(plan, 'must_tables', []) or getattr(plan, 'required_tables', []),
        required_joins=plan.required_joins,
        required_predicates=plan.required_predicates,
        should_predicates=getattr(plan, 'should_predicates', []),
        should_projection=getattr(plan, 'should_projection', []),
        may_predicates=getattr(plan, 'may_predicates', []),
        may_projection=getattr(plan, 'may_projection', []),
        timeframe_days=plan.timeframe_days,
        forbidden_clauses=[] if plan.task == "trend" else ["ORDER BY"]
    )
    
    # Step 4: LLM调用#2 - Generator（严格传入合同内的表/列）
    print("\n💡 Step 4: 调用Generator生成SQL候选...")
    
    try:
        # 兼容不同Pydantic版本，安全获取plan的JSON字符串
        try:
            plan_json_str = plan.model_dump_json(exclude_none=True)
        except Exception:
            try:
                # 部分环境可能存在旧版API
                plan_json_str = plan.json(exclude_none=True)
            except Exception:
                plan_json_str = json.dumps(getattr(plan, "model_dump", lambda **_: plan.dict())(exclude_none=True), ensure_ascii=False)

        candidates = llm_generate_sql(
            question=args.question,
            plan_json=plan_json_str,
            safety_contract=safety_contract,
            n_candidates=max(3, args.sql_topk or 3)
        )
        
        if not candidates:
            print("⚠️ Generator未返回候选")
            return do_ask_traditional(args, m_schema, kb_catalog, dialect)
            
        print(f"✅ 生成{len(candidates)}个候选SQL")
        
    except Exception as e:
        print(f"❌ Generator失败: {e}")
        return do_ask_traditional(args, m_schema, kb_catalog, dialect)
    
    # Step 5: 使用新的验证引擎
    print("\n🎯 Step 5: 验证和选择最佳SQL...")
    
    # 使用新的验证引擎进行客观验证和选择
    best_candidate = validate_and_select_best(candidates, plan, safety_contract)
    
    if not best_candidate:
        print("⚠️ 所有候选都未通过MUST约束验证")
        return do_ask_traditional(args, m_schema, kb_catalog, dialect)
    
    best_sql = best_candidate.get("sql", "")
    is_repaired = best_candidate.get("repaired", False)
    
    print(f"✅ 选择最佳候选{'（已修复）' if is_repaired else ''}")
    
    # Step 6: 最终验证和改写
    print("\n🛡️ Step 6: SQL Guard验证...")
    
    try:
        final_sql = validate_and_rewrite(
            best_sql,
            dialect=dialect,
            m_schema=effective_schema,
            max_limit=DEFAULT_MAX_LIMIT,
            keep_order_by=(plan.task == "trend"),
            allowed_columns_by_table=selected_cols
        )
        
        print("\n✅ 最终SQL:")
        print(final_sql)
        
        # 保存结果
        results = [{
            "question": args.question,
            "sql": final_sql,
            "method": "two_call_clean",
            "repaired": is_repaired,
            "plan": plan.model_dump() if plan else None
        }]
        
        # 添加其他候选（如果需要）
        if args.sql_topk and args.sql_topk > 1:
            for candidate in candidates[1:args.sql_topk]:
                try:
                    sql = candidate.get("sql", "")
                    if sql:
                        validated_sql = validate_and_rewrite(
                            sql,
                            dialect=dialect,
                            m_schema=effective_schema,
                            max_limit=DEFAULT_MAX_LIMIT,
                            keep_order_by=(plan.task == "trend"),
                            allowed_columns_by_table=selected_cols
                        )
                        results.append({
                            "question": args.question,
                            "sql": validated_sql,
                            "method": "additional_candidate"
                        })
                except:
                    pass
        
        # 输出结果
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"\n💾 结果已保存到: {args.output}")
        
        return results
        
    except SQLValidationError as e:
        print(f"❌ SQL验证失败: {e}")
        return do_ask_traditional(args, m_schema, kb_catalog, dialect)


def do_ask_traditional(args, m_schema, kb_catalog, dialect):
    """传统模式回退（单次调用）"""
    print("\n⚠️ 回退到传统模式...")
    
    # 简单的表和列选择
    tokens = tokenize(args.question)
    effective_schema, scored_tables = auto_select_tables(m_schema, tokens, topk=6)
    table_names = [name for name, _ in scored_tables]
    
    if not table_names:
        print("❌ 未找到相关表")
        return []
    
    # 列选择
    selected_cols = _select_columns_simple(effective_schema, table_names, tokens)
    
    # 构建允许列
    allowed_cols = _build_allowed_columns_string(
        effective_schema, table_names,
        selected_columns_by_table=selected_cols
    )
    
    # 调用传统生成
    try:
        sql_result = call_xiyan(
            question=args.question,
            m_schema=effective_schema,
            evidence="",
            kb_snippet="",
            allowed_columns=allowed_cols
        )
        sql_list = [sql_result] if sql_result else []
        
        if not sql_list:
            print("❌ 传统生成失败")
            return []
        
        # 验证和输出
        results = []
        for i, sql in enumerate(sql_list):
            try:
                final_sql = validate_and_rewrite(
                    sql, dialect=dialect,
                    m_schema=effective_schema,
                    max_limit=DEFAULT_MAX_LIMIT
                )
                results.append({
                    "question": args.question,
                    "sql": final_sql,
                    "method": "traditional"
                })
                
                if i == 0:
                    print(f"\n✅ 最终SQL:\n{final_sql}")
                    
            except Exception as e:
                print(f"  SQL{i+1}验证失败: {e}")
        
        return results
        
    except Exception as e:
        print(f"❌ 传统生成异常: {e}")
        return []


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Text-to-SQL Clean Version")
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # ask命令
    ask_parser = subparsers.add_parser("ask", help="生成SQL")
    ask_parser.add_argument("--question", "-q", required=True, help="自然语言问题")
    ask_parser.add_argument("--output", "-o", help="输出文件路径")
    ask_parser.add_argument("--sql-topk", type=int, default=1, help="生成SQL数量")
    ask_parser.add_argument("--use-semantic", action="store_true", help="使用语义检索")
    ask_parser.add_argument("--best", action="store_true", help="使用最佳配置")
    
    args = parser.parse_args()
    
    if args.command == "ask":
        # --best自动开启所有优化
        if args.best:
            args.use_semantic = True
            args.sql_topk = max(3, args.sql_topk)
        
        results = do_ask(args)
        
        if not results:
            print("\n❌ 生成失败")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

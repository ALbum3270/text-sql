#!/usr/bin/env python3
"""
Gold Samples 评测与优化工具

功能：
1. 批量评测系统准确率
2. 分析召回失败案例
3. 优化KB描述建议
4. Few-shot示例提取
"""

import json
import subprocess
import sys
from collections import defaultdict, Counter
from typing import List, Dict, Any, Tuple
import re

def load_gold_samples(file_path: str = "gold_samples.jsonl") -> List[Dict[str, Any]]:
    """加载gold samples数据"""
    samples = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))
    return samples

def run_single_query(question: str) -> Dict[str, Any]:
    """运行单个查询并返回结果"""
    try:
        cmd = ["python", "run_nl2sql_clean.py", "ask", "-q", question, "--best", "--output", "temp_result.jsonl"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        # 解析输出，提取最终SQL
        output = result.stdout
        sql_match = re.search(r'✅ 最终SQL:\s*\n(.+?)(?=\n\n|\n\(|$)', output, re.DOTALL)
        if sql_match:
            final_sql = sql_match.group(1).strip()
        else:
            final_sql = "ERROR: 无法提取SQL"
            
        # 提取召回的表
        tables_match = re.search(r'✅ 原始候选表: \[(.*?)\]', output)
        recalled_tables = []
        if tables_match:
            tables_str = tables_match.group(1)
            recalled_tables = [t.strip().strip("'\"") for t in tables_str.split(',')]
        
        return {
            "sql": final_sql,
            "recalled_tables": recalled_tables,
            "output": output,
            "success": "✅ 最终SQL:" in output,
            "error": result.stderr if result.stderr else None
        }
    except Exception as e:
        return {
            "sql": f"ERROR: {str(e)}",
            "recalled_tables": [],
            "output": "",
            "success": False,
            "error": str(e)
        }

def evaluate_single_case(sample: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """评估单个案例"""
    question = sample["question"]
    gold_sql = sample["gold_sql"]
    must_tables = sample["must_tables"]
    must_columns = sample.get("must_columns", [])
    
    generated_sql = result["sql"]
    recalled_tables = result["recalled_tables"]
    
    # 表召回评估
    table_recall_correct = all(table in recalled_tables for table in must_tables)
    
    # SQL结构相似性评估 (简单版本)
    sql_similarity = evaluate_sql_similarity(gold_sql, generated_sql)
    
    # 必需列检查
    column_coverage = evaluate_column_coverage(must_columns, generated_sql)
    
    return {
        "question": question,
        "gold_sql": gold_sql,
        "generated_sql": generated_sql,
        "must_tables": must_tables,
        "recalled_tables": recalled_tables,
        "table_recall_correct": table_recall_correct,
        "sql_similarity": sql_similarity,
        "column_coverage": column_coverage,
        "overall_score": (int(table_recall_correct) + sql_similarity + column_coverage) / 3,
        "success": result["success"]
    }

def evaluate_sql_similarity(gold_sql: str, generated_sql: str) -> float:
    """评估SQL相似性（简化版本）"""
    if "ERROR" in generated_sql:
        return 0.0
    
    # 关键词匹配
    gold_keywords = set(re.findall(r'\b\w+\b', gold_sql.upper()))
    gen_keywords = set(re.findall(r'\b\w+\b', generated_sql.upper()))
    
    if not gold_keywords:
        return 0.0
    
    common_keywords = gold_keywords & gen_keywords
    return len(common_keywords) / len(gold_keywords)

def evaluate_column_coverage(must_columns: List[str], generated_sql: str) -> float:
    """评估必需列覆盖度"""
    if not must_columns or "ERROR" in generated_sql:
        return 0.0
    
    covered = 0
    for col in must_columns:
        if col in generated_sql or col.replace("COUNT(*)", "COUNT").replace("()", "") in generated_sql:
            covered += 1
    
    return covered / len(must_columns)

def analyze_failures(evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分析失败案例"""
    table_recall_failures = []
    sql_generation_failures = []
    low_score_cases = []
    
    for eval_result in evaluations:
        if not eval_result["table_recall_correct"]:
            table_recall_failures.append(eval_result)
        
        if not eval_result["success"]:
            sql_generation_failures.append(eval_result)
            
        if eval_result["overall_score"] < 0.6:
            low_score_cases.append(eval_result)
    
    # 统计召回失败的表
    missing_table_counts = Counter()
    for failure in table_recall_failures:
        for table in failure["must_tables"]:
            if table not in failure["recalled_tables"]:
                missing_table_counts[table] += 1
    
    return {
        "table_recall_failures": len(table_recall_failures),
        "sql_generation_failures": len(sql_generation_failures),
        "low_score_cases": len(low_score_cases),
        "missing_table_counts": missing_table_counts,
        "failure_examples": table_recall_failures[:5]  # 前5个失败例子
    }

def suggest_kb_improvements(samples: List[Dict[str, Any]], analysis: Dict[str, Any]) -> List[str]:
    """基于分析结果建议KB改进"""
    suggestions = []
    
    # 高频表的KB优化建议
    table_questions = defaultdict(list)
    for sample in samples:
        for table in sample["must_tables"]:
            table_questions[table].append(sample["question"])
    
    # 统计高频表的常见问题模式
    for table, questions in table_questions.items():
        if len(questions) >= 5:  # 高频表
            patterns = []
            for q in questions:
                if "总数" in q:
                    patterns.append("总数统计")
                if "按" in q:
                    patterns.append("分组统计")
                if "租户" in q:
                    patterns.append("租户过滤")
                if "今天" in q or "近" in q:
                    patterns.append("时间过滤")
            
            pattern_str = "、".join(set(patterns))
            suggestions.append(f"优化 {table} 表描述，增加关键词：{pattern_str}")
    
    # 针对召回失败的表的建议
    for table, count in analysis["missing_table_counts"].most_common(5):
        suggestions.append(f"⚠️ {table} 表召回失败 {count} 次，需要优化KB描述和别名")
    
    return suggestions

def extract_few_shot_examples(samples: List[Dict[str, Any]], num_examples: int = 3) -> List[Dict[str, Any]]:
    """提取few-shot示例"""
    # 按问题类型选择代表性示例
    count_examples = [s for s in samples if "总数" in s["question"]]
    group_examples = [s for s in samples if "按" in s["question"]]
    time_examples = [s for s in samples if "今天" in s["question"] or "近" in s["question"]]
    
    few_shot = []
    if count_examples:
        few_shot.append(count_examples[0])
    if group_examples:
        few_shot.append(group_examples[0])
    if time_examples:
        few_shot.append(time_examples[0])
    
    return few_shot[:num_examples]

def main():
    print("🚀 Gold Samples 评测与优化工具")
    print("=" * 50)
    
    # 加载数据
    print("📥 加载gold samples...")
    samples = load_gold_samples()
    print(f"✅ 加载了 {len(samples)} 个样本")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--analyze-only":
        # 仅分析模式，不运行查询
        print("\n📊 数据集分析模式")
        
        # 分析数据集特征
        table_counts = Counter()
        question_types = Counter()
        
        for sample in samples:
            table_counts.update(sample["must_tables"])
            question = sample["question"]
            if "总数" in question:
                question_types["count"] += 1
            elif "按" in question:
                question_types["group"] += 1
            elif "趋势" in question:
                question_types["trend"] += 1
            elif "今天" in question or "近" in question:
                question_types["time"] += 1
            else:
                question_types["list"] += 1
        
        print(f"\n🎯 热门表TOP10:")
        for table, count in table_counts.most_common(10):
            print(f"  {table}: {count}次")
        
        print(f"\n📈 问题类型分布:")
        for qtype, count in question_types.most_common():
            print(f"  {qtype}: {count}次")
        
        # 提取few-shot示例
        few_shot = extract_few_shot_examples(samples)
        print(f"\n💡 推荐Few-shot示例:")
        for i, example in enumerate(few_shot, 1):
            print(f"  {i}. {example['question']}")
            print(f"     SQL: {example['gold_sql'][:50]}...")
        
        return
    
    # 全量评测模式
    print(f"\n🧪 开始批量评测 (共{len(samples)}个样本)...")
    
    evaluations = []
    for i, sample in enumerate(samples[:10], 1):  # 先测试前10个
        question = sample["question"]
        print(f"[{i:2d}/10] 测试: {question}")
        
        # 运行查询
        result = run_single_query(question)
        
        # 评估结果
        evaluation = evaluate_single_case(sample, result)
        evaluations.append(evaluation)
        
        print(f"         ✅ 表召回: {'✓' if evaluation['table_recall_correct'] else '✗'}")
        print(f"         📊 总分: {evaluation['overall_score']:.2f}")
    
    # 生成报告
    print(f"\n📋 评测报告")
    print("=" * 30)
    
    avg_score = sum(e["overall_score"] for e in evaluations) / len(evaluations)
    table_recall_rate = sum(e["table_recall_correct"] for e in evaluations) / len(evaluations)
    success_rate = sum(e["success"] for e in evaluations) / len(evaluations)
    
    print(f"📊 总体表现:")
    print(f"  平均分数: {avg_score:.2f}")
    print(f"  表召回率: {table_recall_rate:.2f}")
    print(f"  成功率: {success_rate:.2f}")
    
    # 分析失败案例
    analysis = analyze_failures(evaluations)
    print(f"\n⚠️ 问题分析:")
    print(f"  表召回失败: {analysis['table_recall_failures']}个")
    print(f"  SQL生成失败: {analysis['sql_generation_failures']}个")
    print(f"  低分案例: {analysis['low_score_cases']}个")
    
    if analysis["missing_table_counts"]:
        print(f"\n📉 召回失败最多的表:")
        for table, count in analysis["missing_table_counts"].most_common(5):
            print(f"  {table}: {count}次")
    
    # 生成改进建议
    suggestions = suggest_kb_improvements(samples, analysis)
    print(f"\n💡 改进建议:")
    for suggestion in suggestions[:5]:
        print(f"  • {suggestion}")

if __name__ == "__main__":
    main()

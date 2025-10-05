#!/usr/bin/env python3
"""
基于 Gold Samples 优化 KB 描述

根据常见问题模式自动优化知识库描述
"""

import json
from collections import defaultdict, Counter
import re

def analyze_question_patterns(samples):
    """分析问题模式，提取关键词"""
    table_patterns = defaultdict(lambda: defaultdict(list))
    
    for sample in samples:
        question = sample["question"]
        tables = sample["must_tables"]
        
        for table in tables:
            # 分析问题中的关键词模式
            if "总数" in question or "数量" in question:
                table_patterns[table]["count_keywords"].append("总数统计")
                table_patterns[table]["count_keywords"].append("数量查询")
            
            if "按" in question and "统计" in question:
                table_patterns[table]["group_keywords"].append("分组统计")
                table_patterns[table]["group_keywords"].append("按类别统计")
            
            if "租户" in question:
                table_patterns[table]["tenant_keywords"].append("租户过滤")
                table_patterns[table]["tenant_keywords"].append("多租户")
            
            if "今天" in question:
                table_patterns[table]["time_keywords"].append("今天")
                table_patterns[table]["time_keywords"].append("当日统计")
            
            if "近" in question:
                table_patterns[table]["time_keywords"].append("时间范围")
                table_patterns[table]["time_keywords"].append("历史统计")
            
            if "趋势" in question:
                table_patterns[table]["trend_keywords"].append("趋势分析")
                table_patterns[table]["trend_keywords"].append("时间序列")
            
            if "威胁" in question:
                table_patterns[table]["threat_keywords"].append("威胁检测")
                table_patterns[table]["threat_keywords"].append("安全威胁")
            
            if "域名" in question:
                table_patterns[table]["domain_keywords"].append("域名管理")
                table_patterns[table]["domain_keywords"].append("DNS安全")
            
            if "终端" in question or "节点" in question:
                table_patterns[table]["endpoint_keywords"].append("终端管理")
                table_patterns[table]["endpoint_keywords"].append("设备监控")
            
            if "病毒" in question:
                table_patterns[table]["virus_keywords"].append("病毒检测")
                table_patterns[table]["virus_keywords"].append("恶意软件")
            
            if "弱口令" in question:
                table_patterns[table]["password_keywords"].append("弱口令检查")
                table_patterns[table]["password_keywords"].append("密码安全")
            
            if "漏洞" in question:
                table_patterns[table]["vuln_keywords"].append("漏洞扫描")
                table_patterns[table]["vuln_keywords"].append("安全漏洞")
    
    return table_patterns

def generate_kb_optimizations(table_patterns):
    """生成KB优化建议"""
    optimizations = {}
    
    for table, patterns in table_patterns.items():
        # 合并所有关键词
        all_keywords = []
        for category, keywords in patterns.items():
            all_keywords.extend(set(keywords))
        
        # 根据table名称确定主要用途
        base_purpose = ""
        enhanced_keywords = []
        
        if "virus" in table.lower():
            base_purpose = "病毒感染记录，恶意软件检测，终端安全威胁"
            enhanced_keywords.extend(["病毒感染", "恶意软件", "安全威胁", "终端防护"])
        
        elif "threat" in table.lower():
            if "domain" in table.lower():
                base_purpose = "威胁域名，恶意域名，域名黑名单，DNS安全威胁"
                enhanced_keywords.extend(["威胁域名", "恶意域名", "DNS威胁", "域名安全"])
            elif "ip" in table.lower():
                base_purpose = "威胁IP，恶意IP地址，网络安全威胁"
                enhanced_keywords.extend(["威胁IP", "恶意IP", "网络威胁", "IP安全"])
            elif "process" in table.lower():
                base_purpose = "威胁进程，恶意进程，进程安全监控"
                enhanced_keywords.extend(["威胁进程", "恶意进程", "进程监控", "进程安全"])
            else:
                base_purpose = "安全威胁，威胁情报，安全监控"
                enhanced_keywords.extend(["安全威胁", "威胁检测", "安全监控"])
        
        elif "weak_password" in table.lower():
            base_purpose = "弱口令检查，密码安全，终端弱密码检测"
            enhanced_keywords.extend(["弱口令", "密码安全", "弱密码", "口令检查"])
        
        elif "node" in table.lower():
            if "statistics" in table.lower():
                base_purpose = "终端状态统计，节点连接状态，在线离线统计，终端监控"
                enhanced_keywords.extend(["终端状态", "在线统计", "节点监控", "连接状态"])
            else:
                base_purpose = "终端设备，节点信息，设备管理，终端基础信息"
                enhanced_keywords.extend(["终端设备", "节点信息", "设备管理", "终端基础"])
        
        elif "vulnerability" in table.lower():
            base_purpose = "漏洞扫描，安全漏洞，漏洞检测，安全评估"
            enhanced_keywords.extend(["漏洞扫描", "安全漏洞", "漏洞检测", "安全评估"])
        
        elif "container" in table.lower():
            base_purpose = "容器管理，Docker容器，容器统计，容器监控"
            enhanced_keywords.extend(["容器管理", "Docker", "容器统计", "容器监控"])
        
        elif "base_line" in table.lower():
            base_purpose = "基线检查，安全基线，配置检查，合规检查"
            enhanced_keywords.extend(["基线检查", "安全基线", "合规检查", "配置审计"])
        
        elif "attck" in table.lower():
            base_purpose = "攻击告警，安全告警，攻击检测，安全事件"
            enhanced_keywords.extend(["攻击告警", "安全告警", "攻击检测", "安全事件"])
        
        else:
            base_purpose = f"{table} 相关数据管理"
            enhanced_keywords.extend([table.replace("_", " ")])
        
        # 添加从问题模式中提取的关键词
        enhanced_keywords.extend(all_keywords)
        enhanced_keywords = list(set(enhanced_keywords))  # 去重
        
        optimizations[table] = {
            "current_purpose": f"{table} 相关数据管理",  # 假设的当前描述
            "enhanced_purpose": base_purpose + "，" + "，".join(enhanced_keywords[:8]),  # 限制长度
            "aliases": enhanced_keywords[:15],  # 前15个作为别名
            "question_count": len(table_patterns[table])
        }
    
    return optimizations

def apply_kb_optimizations(optimizations, kb_file="outputs/kb/kb_catalog.json"):
    """应用KB优化到实际文件"""
    print(f"📝 正在优化 {kb_file}...")
    
    # 读取当前KB
    with open(kb_file, 'r', encoding='utf-8') as f:
        kb_data = json.load(f)
    
    updated_tables = []
    
    # 查找并更新表描述
    for table_info in kb_data.get("tables", []):
        table_name = table_info.get("name")
        if table_name in optimizations:
            opt = optimizations[table_name]
            
            # 更新purpose
            old_purpose = table_info.get("purpose", "")
            table_info["purpose"] = opt["enhanced_purpose"]
            
            # 更新grain（可选）
            table_info["grain"] = f"每行={table_name}记录，支持{opt['aliases'][0] if opt['aliases'] else '数据查询'}"
            
            updated_tables.append({
                "name": table_name,
                "old": old_purpose,
                "new": opt["enhanced_purpose"]
            })
            
            print(f"✅ 已更新 {table_name}")
    
    # 写回文件
    with open(kb_file, 'w', encoding='utf-8') as f:
        json.dump(kb_data, f, ensure_ascii=False, indent=2)
    
    return updated_tables

def generate_few_shot_examples(samples, output_file="few_shot_examples.json"):
    """生成few-shot示例"""
    # 按类型选择最佳示例
    categories = {
        "count": [],
        "group": [],
        "time_range": [],
        "threat": [],
        "endpoint": []
    }
    
    for sample in samples:
        question = sample["question"]
        
        if "总数" in question:
            categories["count"].append(sample)
        elif "按" in question and "统计" in question:
            categories["group"].append(sample)
        elif "近" in question or "今天" in question:
            categories["time_range"].append(sample)
        elif "威胁" in question:
            categories["threat"].append(sample)
        elif "终端" in question or "节点" in question:
            categories["endpoint"].append(sample)
    
    # 每类选择1-2个最佳示例
    few_shot_examples = []
    for category, examples in categories.items():
        if examples:
            # 选择SQL相对简单的示例
            examples.sort(key=lambda x: len(x["gold_sql"]))
            few_shot_examples.extend(examples[:2])
    
    # 保存few-shot示例
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(few_shot_examples[:6], f, ensure_ascii=False, indent=2)
    
    print(f"💡 已生成 {len(few_shot_examples[:6])} 个few-shot示例到 {output_file}")
    return few_shot_examples[:6]

def main():
    print("🚀 基于 Gold Samples 的 KB 优化工具")
    print("=" * 50)
    
    # 加载gold samples
    with open("gold_samples.jsonl", 'r', encoding='utf-8') as f:
        samples = [json.loads(line) for line in f if line.strip()]
    
    print(f"📥 加载了 {len(samples)} 个样本")
    
    # 分析问题模式
    print("🔍 分析问题模式...")
    table_patterns = analyze_question_patterns(samples)
    
    # 生成优化建议
    print("💡 生成优化建议...")
    optimizations = generate_kb_optimizations(table_patterns)
    
    # 显示优化建议
    print("\n📋 KB 优化建议:")
    for table, opt in sorted(optimizations.items(), key=lambda x: x[1]["question_count"], reverse=True)[:10]:
        print(f"\n🎯 {table} (出现{opt['question_count']}次):")
        print(f"   当前: {opt['current_purpose']}")
        print(f"   优化: {opt['enhanced_purpose']}")
        print(f"   别名: {', '.join(opt['aliases'][:5])}...")
    
    # 询问是否应用优化
    if input("\n🔧 是否应用这些优化到 kb_catalog.json? (y/N): ").lower() == 'y':
        updated = apply_kb_optimizations(optimizations)
        print(f"✅ 已更新 {len(updated)} 个表的描述")
    
    # 生成few-shot示例
    print("\n💡 生成few-shot示例...")
    few_shot = generate_few_shot_examples(samples)
    
    print("\n📊 推荐few-shot示例:")
    for i, example in enumerate(few_shot, 1):
        print(f"  {i}. {example['question']}")
        print(f"     -> 使用表: {', '.join(example['must_tables'])}")

if __name__ == "__main__":
    main()

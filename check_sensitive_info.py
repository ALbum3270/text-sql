#!/usr/bin/env python3
"""
检查代码中是否包含敏感信息
Check for sensitive information in code
"""

import os
import re
from pathlib import Path
from typing import List, Tuple

# 敏感模式定义
SENSITIVE_PATTERNS = {
    "IP地址": r'\b(?:10\.|192\.168\.|172\.(?:1[6-9]|2[0-9]|3[01])\.)[\d.]+\b',
    "数据库名": r'\bedrserver\b',
    "可能的密码": r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']{3,}["\']',
    "API密钥": r'(?:api[_-]?key|token|secret)\s*=\s*["\'][^"\']{10,}["\']',
    "租户标识": r'\b(?:dbpp|less_user)\b',
}

# 需要检查的文件扩展名
EXTENSIONS = {'.py', '.md', '.json', '.jsonl', '.txt', '.env'}

# 排除的目录
EXCLUDE_DIRS = {
    '__pycache__', 
    '.git', 
    '.vscode', 
    '.idea',
    'check_sensitive_info.py',  # 排除本脚本自己
}

# 排除的文件
EXCLUDE_FILES = {
    'CLEANUP_SUMMARY.md',  # 本身包含敏感信息示例
    'PUBLISH_CHECKLIST.md',
    'check_sensitive_info.py',
}


def should_check_file(filepath: Path) -> bool:
    """判断是否应该检查该文件"""
    # 检查扩展名
    if filepath.suffix not in EXTENSIONS:
        return False
    
    # 检查是否在排除列表中
    if filepath.name in EXCLUDE_FILES:
        return False
    
    # 检查是否在排除目录中
    for part in filepath.parts:
        if part in EXCLUDE_DIRS:
            return False
    
    return True


def check_file(filepath: Path) -> List[Tuple[str, int, str, str]]:
    """
    检查单个文件
    返回: [(模式名称, 行号, 行内容, 匹配内容)]
    """
    results = []
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                for pattern_name, pattern in SENSITIVE_PATTERNS.items():
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        results.append((
                            pattern_name,
                            line_num,
                            line.strip(),
                            match.group()
                        ))
    except Exception as e:
        print(f"⚠️ 无法读取文件 {filepath}: {e}")
    
    return results


def main():
    """主函数"""
    print("🔍 开始检查敏感信息...\n")
    
    project_root = Path('.')
    total_files = 0
    total_issues = 0
    issues_by_file = {}
    
    # 遍历所有文件
    for filepath in project_root.rglob('*'):
        if not filepath.is_file():
            continue
        
        if not should_check_file(filepath):
            continue
        
        total_files += 1
        results = check_file(filepath)
        
        if results:
            issues_by_file[filepath] = results
            total_issues += len(results)
    
    # 输出结果
    if not issues_by_file:
        print("✅ 太好了！没有发现敏感信息。")
        print(f"\n📊 已检查 {total_files} 个文件")
        return 0
    
    print(f"⚠️ 发现 {total_issues} 处潜在的敏感信息：\n")
    
    for filepath, issues in sorted(issues_by_file.items()):
        print(f"\n📄 {filepath}")
        print("=" * 80)
        
        for pattern_name, line_num, line_content, match_text in issues:
            print(f"  行 {line_num:4d} | {pattern_name:12s} | {match_text}")
            print(f"         | {line_content[:70]}")
        
        print()
    
    print("\n" + "=" * 80)
    print(f"📊 总结：在 {len(issues_by_file)} 个文件中发现 {total_issues} 处潜在问题")
    print(f"📊 已检查 {total_files} 个文件")
    print("\n⚠️ 请手动审查上述内容，确认是否需要清理！")
    
    return 1


if __name__ == '__main__':
    exit(main())


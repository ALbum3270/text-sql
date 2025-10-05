# Text-SQL 项目运行说明

## 🎯 项目概述

**Text-SQL** 是一个基于大语言模型的自然语言转SQL系统，采用两阶段架构：
- **Planner** 阶段：生成结构化查询计划
- **Generator** 阶段：基于计划生成SQL候选
- **验证层**：多层AST验证和安全防护
- **SQL Guard**：最终安全改写和收口

### ✨ 核心特性
- 🔒 **全流程强约束**：严格的Schema和列白名单控制
- 🛡️ **Fail-closed安全**：验证失败时默认拒绝，不放行错误SQL
- 📊 **智能优化**：趋势题保留ORDER BY，聚合单行自动移除LIMIT
- 🔍 **可追溯调试**：支持详细日志和批量运行分析

## 🔄 核心流程

### Step 0: 候选召回
**目标**：从海量Schema中筛选相关表和列
- **关键词召回**：基于问题文本匹配表名/列名
  - 通用列降权（id、name等常见列）
  - 表名精确命中加权
- **语义召回**（可选）：使用FAISS/HNSW向量索引
- **输出**：`effective_schema` + `selected_cols`

### Step 1: Planner（规划阶段）
**目标**：生成结构化查询计划
- **输入**：问题 + KB摘要 + effective_schema
- **约束**：提示词明确列出允许的表和列
- **容错**：自动清洗越界表/列并重试一次

### Step 2: 计划应用
**目标**：优化和补充计划内容
- 合并必需表（仅限Schema内）
- 按Planner优先级重排列
- 从MUST/JOIN/GROUP/AGG中解析列并补入selected_cols

### Step 3: 构建安全合同
**目标**：建立严格的生成约束
- `allowed_tables` = effective_schema中的真实表
- `allowed_columns` = 补齐后的selected_cols
- 根据任务类型设置ORDER BY策略

### Step 4: SQL生成
**目标**：生成多个候选SQL
- 受安全合同约束
- LLM自检过滤不合格候选
- 返回Top-K候选列表

### Step 5: 验证择优
**目标**：选择最优SQL并修复缺陷
- **基础验证**：禁止中文、占位符、SELECT *
- **MUST约束**：AST级严格检查，支持复合条件拆分
- **最小修复**：使用sqlglot AST注入缺失谓词
- **择优策略**：在通过者中选最简单的

### Step 6: 最终防护
**目标**：安全改写和格式统一
- 严格的表/列白名单检查
- ORDER BY策略（趋势保留/其它移除）
- LIMIT策略（单行聚合移除/其它补齐）

## 📁 文件架构

### 核心文件
| 文件 | 职责 | 重要性 |
|------|------|--------|
| `run_nl2sql_clean.py` | 🎯 **主入口**，流程编排(Step 0-6) | ⭐⭐⭐ |
| `llm_planner.py` | 🧠 计划生成，约束清洗，自动重试 | ⭐⭐⭐ |
| `llm_generator.py` | 🏭 SQL候选生成，安全合同建模 | ⭐⭐⭐ |
| `validation_engine.py` | ✅ 候选验证，择优，最小修复 | ⭐⭐⭐ |
| `sql_guard.py` | 🛡️ 最终防护，安全改写 | ⭐⭐⭐ |

### 辅助模块
| 文件 | 职责 |
|------|------|
| `ast_validator.py` | AST级验证，复合条件拆分 |
| `semantic_retrieval.py` | 语义检索，FAISS/HNSW索引 |
| `xiyan_client.py` | 传统回退路径 |
| `eval_batch_run.py` | 批量评测运行器 |

## 📂 数据目录

### 必需数据
```
outputs/
├── m_schema.json          # 🔧 完整数据库Schema元数据
├── kb/
│   └── kb_catalog.json    # 📚 表的知识库摘要(召回加分)
└── semantic_index/        # 🔍 语义检索索引(可选)
    ├── tables.hnsw
    ├── tables.ids.json
    ├── columns.hnsw
    ├── columns.ids.json
    └── meta.json
```

### 运行产物
```
outputs/
├── eval_run_logs.jsonl    # 📋 批量运行日志
└── eval_run_results.jsonl # 📊 批量运行结果
```

## 🚀 快速开始

### 环境准备
```bash
# 1. 安装依赖
python -m pip install -r requirements.txt

# 2. 设置API密钥 (二选一)
set QWEN_API_KEY=your_api_key        # PowerShell
export QWEN_API_KEY=your_api_key     # Linux/Mac

# 3. (可选) 构建语义索引
python -c "from semantic_retrieval import build_semantic_indices; build_semantic_indices(index_dir='outputs/semantic_index')"
```

### 基础使用
```bash
# 🎯 推荐：最佳配置运行
python run_nl2sql_clean.py ask -q "你的问题" --best

# 📊 批量运行
python eval_batch_run.py --input eval_samples.jsonl --logs outputs/eval_run_logs.jsonl --results outputs/eval_run_results.jsonl --best
```

### 命令行参数
| 参数 | 说明 | 示例 |
|------|------|------|
| `ask` | 子命令，生成SQL | - |
| `-q/--question` | 问题文本 | `-q "查询用户总数"` |
| `--best` | 🌟 最佳配置(语义召回+topk≥3) | `--best` |
| `--sql-topk` | 候选数量 | `--sql-topk 5` |
| `--use-semantic` | 单独启用语义召回 | `--use-semantic` |
| `--output` | 结果输出文件 | `--output results.jsonl` |

## ⚙️ 配置选项

### 环境变量
```bash
# 🐛 调试模式
T2SQL_DEBUG=1                    # 详细调试日志

# 🔧 运行策略  
SQL_PERMISSIVE_MODE=1           # 宽松模式(保留ORDER BY等)

# 🤖 LLM配置
QWEN_API_KEY=your_key           # API密钥
QWEN_BASE_URL=custom_url        # 自定义API地址
QWEN_MODEL=qwen-max             # 模型名称

# 🗄️ MySQL配置(可选)
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=password
MYSQL_DATABASE=your_db
```

## 💡 使用示例

### 基础查询
```sql
# 输入：cpu_architecture总量是多少
# 输出：
SELECT COUNT(*) AS total FROM cpu_architecture
```

### 趋势分析
```sql
# 输入：过去45天node_exposure_port按天计数趋势  
# 输出：
SELECT DATE(update_time) AS update_date, 
       COUNT(DISTINCT id) AS exposed_port_count 
FROM node_exposure_port 
WHERE update_time >= DATE_SUB(NOW(), INTERVAL 45 DAY) 
GROUP BY DATE(update_time) 
ORDER BY update_date
LIMIT 200
```

### 威胁检索
```sql
# 输入：有一个恶意的域名 safe.dashabi.nl，哪些终端尝试解析过该域名
# 输出：
SELECT safety_daily.receiver 
FROM safety_daily 
WHERE safety_daily.name = 'safe.dashabi.nl' 
LIMIT 200
```

## 🔧 故障排除

### 常见问题
| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 🚫 表/列越界错误 | LLM生成了Schema外的表/列 | Planner自动清洗重试；验证层fail-closed防护 |
| 📊 趋势题ORDER BY被删 | 非趋势任务默认移除ORDER BY | 确保问题包含"趋势"等关键词 |
| 🔢 聚合结果数值偏差 | LIMIT影响单行聚合 | Guard自动识别并移除LIMIT |
| 🎯 召回不准确 | 关键词匹配偏差 | 启用语义召回或优化KB别名 |

### 调试建议
```bash
# 🐛 开启调试模式查看详细流程
T2SQL_DEBUG=1 python run_nl2sql_clean.py ask -q "你的问题" --best

# 📋 检查批量运行日志
cat outputs/eval_run_logs.jsonl | jq '.step_logs'
```

## 📝 项目清理说明

为保持代码库的整洁性，已完成以下清理工作：

### ✅ 已保留
- **核心模块**：主入口、LLM调用、验证引擎、安全防护
- **辅助工具**：语义检索、传统回退、批量评测
- **必需数据**：Schema元数据、KB目录、语义索引
- **配置文件**：requirements.txt、env.example

### 🗑️ 已清理
- 测试脚本和临时评测文件
- 一次性调试脚本和遗留代码
- 重复的配置文件和示例数据
- 过时的实验性模块

> **说明**：清理过程中保留了所有运行必需的数据文件，确保系统功能完整性。


## 📚 进阶：利用 Gold Samples 提升质量

### 分析与评测
```bash
# 仅分析样本分布、热门表、推荐 few-shot
python gold_evaluation.py --analyze-only

# 小规模评测（默认取前10个，可在脚本中调整）
python gold_evaluation.py
```

### 基于样本自动优化 KB 描述
```bash
# 生成各高频表的优化建议，并可交互式写回 outputs/kb/kb_catalog.json
python optimize_kb_from_gold.py
```

运行后会生成 `few_shot_examples.json`，可作为二阶段生成器的参考范例库（不强制接入，按需使用）。


## 🔎 召回策略要点（更稳更准）
- **表名/列名直接命中权重提升**：表名精确匹配优先；列名完全匹配高权重、通用列低权重。
- **中文关键词分词**：支持“威胁、域名、在线、趋势、总数、分布、终端、漏洞、弱口令”等常见词。
- **语义映射**：如“威胁→threat”“域名→domain”“情况→statistics”，提升中英文一致性。
- **动态 topk**：存在高置信表时自动扩大召回，避免重要表被截断。
- **通用列降权**：对 id/name/time/status 等常见列降低影响，突出关键专属列。


## ⚠️ 谓词书写建议（避免回退）
- 租户过滤请写在事实表上：例如弱口令问题使用 `weak_password_node_detail.less_user = 'xxx'`。
- 时间范围优先选择事实时间列：如 `first_find_time`/`last_find_time`/`time`。
- 必要条件尽量写为 MUST（如 `pass_wd IS NOT NULL`），避免被宽松改写。


## 🧪 常用自测命令
```bash
# 今天发现的威胁域名
python run_nl2sql_clean.py ask -q "今天发现的威胁域名" --best

# 统计弱口令终端总数
python run_nl2sql_clean.py ask -q "统计弱口令终端总数" --best

# 今天终端在线情况
python run_nl2sql_clean.py ask -q "今天终端的在线情况怎么样" --best
```


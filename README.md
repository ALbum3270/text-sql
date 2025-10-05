# Text-to-SQL 企业级系统

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

> 一个基于大语言模型的企业级自然语言转SQL系统，采用**两阶段LLM架构**（Planner + Generator）和**分层约束系统**（MUST/SHOULD/MAY），实现高准确率和高安全性的SQL生成。

## ✨ 核心特性

- 🧠 **去补丁化架构** - 移除硬编码规则，语义决策完全由LLM负责
- 🔒 **多层安全防护** - AST级验证 + SQL Guard，确保生成的SQL安全可控
- 📊 **智能约束系统** - 支持硬性(MUST)/建议(SHOULD)/可选(MAY)三级约束
- 🎯 **领域优化** - 针对EDR安全场景深度定制，支持威胁查询、趋势分析等
- 📈 **完整评测体系** - 支持EM、组件F1、Value F1、执行准确性等多维度评估

## 📖 项目简介

本系统是一个面向 MySQL 的 Text-to-SQL 解决方案，基于大语言模型（如 XiYanSQL-QwenCoder、Qwen等）构建。

**主要功能：**
- 数据库结构导出为 Markdown 与 M-Schema(JSON)
- 基于知识库（KB）和语义检索的智能表/列召回
- 两阶段LLM调用：Planner（规划）+ Generator（生成）
- 严格的 SQL 安全校验与规范化
- 完整的评测流程和指标体系

**模型支持：**
- [XiYanSQL-QwenCoder-32B-2412](https://modelscope.cn/models/XGenerationLab/XiYanSQL-QwenCoder-32B-2412)
- Qwen系列模型（通过DashScope API）
- 其他兼容OpenAI API格式的模型


## 功能清单
- 导出 Schema：生成 `outputs/schema.md` 与 `outputs/m_schema.json`
- 知识库构建：按表生成含字段信息、TopN、时间范围、外键关系与示例数据的 Markdown
- NL2SQL：结合 M-Schema、KB 片段、可用列清单与外键提示，生成高质量 SQL
- SQL 安全校验：只读、禁止 `SELECT *`、列名与表名校验、自动补 LIMIT、别名与分组规范等
- 评测：离线评测准确率（逻辑与执行双维度），输出 JSON 与 Markdown 报告
- 兜底模板：常见“趋势/TopK/分布”问题失败时可回落到规则模板（可用 `--no-fallback` 关闭）


## 目录结构（节选）
- `run_nl2sql.py`：主入口，导出/提问/执行/EXPLAIN/后处理
- `schema_export_mysql.py`：导出 MySQL 结构为 Markdown + M-Schema(JSON)
- `kb_builder.py`：基于数据库内容构建 Markdown 知识库与目录
- `xiyan_client.py`：调用 ModelScope XiYanSQL 接口并封装 Prompt 注入
- `sql_guard.py`：SQL 校验与规范化（sqlglot 驱动）
- `eval_nl2sql.py`：离线评测脚本（保存 JSON/Markdown 报告，支持 `--no-fallback`）
- `gold_builder.py`：从 KB/DB 自动生成带标注 SQL 的测试集
- `requirements.txt`：依赖
- `.env.example`：环境变量示例
- `outputs/`：默认输出目录（schema/kb/evals 等）


## 安装与环境
1) 安装依赖
```bash
pip install -r requirements.txt
```

2) 环境变量（复制 `env.example` 为 `.env` 并填写）
```env
# LLM API配置
QWEN_API_KEY=your_api_key_here
MODELSCOPE_API_KEY=your_modelscope_key

# MySQL数据库配置（可选，仅当需要实际执行SQL时）
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
DB_DIALECT=mysql

# 其他配置
OUTPUT_DIR=outputs
DEFAULT_MAX_LIMIT=200
T2SQL_DEBUG=0
```

3) 激活运行环境
- 请在运行命令前先激活你的 Python/Album 环境（若使用 Album）。


## 快速开始
1) 导出数据库结构
```bash
python run_nl2sql.py export
# 仅导出部分表
python run_nl2sql.py export --tables threat_ip_static,threat_domain_static
```

2) 构建知识库（可选，但强烈建议开启以提升准确率）
```bash
python kb_builder.py --output outputs/kb --no-mask
```

3) 自然语言提问 → 生成 SQL（可执行/EXPLAIN/只校验）
```bash
# 仅生成并校验（不执行）
python run_nl2sql.py ask --question "近7天 threat_ip_static 数量趋势" --validate-only --debug

# 生成并执行，打印结果表格
python run_nl2sql.py ask --question "按 ip 统计 threat_ip_static 数量（降序）" --execute

# 自动选择相关表、打印 EXPLAIN
python run_nl2sql.py ask \
  --question "近7天 threat_ip_static 按 ip 出现次数 TOP10" \
  --auto-select --topk 8 --explain \
  --debug

# 严格模式：禁用兜底模板（仅模型直出）
python run_nl2sql.py ask --question "近7天 common_config 按 id 出现次数 TOP10" --validate-only --debug --no-fallback
```


## 评测使用
1) 生成测试集（UTF-8，无 BOM）
```bash
python gold_builder.py
# 输出：outputs/gold_samples.jsonl
```

2) 运行评测（默认：开启兜底）
```bash
python eval_nl2sql.py --testset outputs/gold_samples.jsonl --use-kb --exec \
  --out-json outputs/evals/eval_latest_fb.json \
  --out-md outputs/evals/eval_latest_fb.md
```

3) 运行评测（禁用兜底，对比用）
```bash
python eval_nl2sql.py --testset outputs/gold_samples.jsonl --use-kb --exec --no-fallback \
  --out-json outputs/evals/eval_latest_nofb.json \
  --out-md outputs/evals/eval_latest_nofb.md
```

4) 指标说明
- **EM**：Exact Match，预测 SQL 与标注 SQL 规范化后是否完全一致
- **组件 F1**：按 tables/columns/aggregates/group_by 分别计算 P/R/F1 的宏平均
- **Value F1**：SQL 中常量值集合的 F1
- **Exec_Success**：预测与标注 SQL 均能成功执行
- **Exec_Equal**：预测与标注结果集相等（集合层面）
- **RowCount_Equal**：预测与标注结果行数一致


## 关键模块说明
### `schema_export_mysql.py`
- 连接 MySQL，导出表/列/索引/注释/外键信息
- 产出：`outputs/schema.md` 与 `outputs/m_schema.json`

### `kb_builder.py`
- 从数据库采样并聚合信息，输出每张表的 Markdown：
  - 行数、时间列范围、TopN 类别列、示例行（可 `--no-mask`）
  - 外键：`- \
`column` -> `ref_table`.`ref_column``
- 生成 `outputs/kb/kb_catalog.json` 目录，供提示注入与表/列选择

### `xiyan_client.py`
- Prompt 模板（含 `{allowed_columns}`、`{kb_snippet}`、`{join_hints}`、`{evidence}` 注入位）
- 生成参数：`temperature=0.1`、`top_p=0.8`，偏确定性

### `sql_guard.py`
- 基于 `sqlglot` 解析与重写，统一方言与大小写/反引号
- 只读保护、禁止 `SELECT *`、限制/自动补 `LIMIT`、拒绝占位符与注入片段
- 校验表与列，支持别名/常见派生别名（d/date/cnt 等）
- 趋势类问题：强制仅按日期单维分组

### `run_nl2sql.py`
- `export`：导出 Schema
- `ask`：提问 → 生成 SQL → 校验/执行/EXPLAIN/后处理
- 自动注入：
  - `allowed_columns`：限定模型只可选取的列集合
  - `kb_snippet`：对应表的 KB 片段
  - `join_hints`：来自外键的显式 JOIN 提示
- 表选择：`--tables`（手动）或 `--auto-select --topk`（自动）
- 后处理：`--post-limit`
- 调试：`--debug` 打印注入与错误细节
- 兜底：默认开启；可用 `--no-fallback` 关闭

### `eval_nl2sql.py`
- 离线评测，生成 JSON 与 Markdown 报告
- 与在线一致的提示注入与校验策略，可选择 `--no-fallback`
- 执行对比：`--exec` 同时执行预测/标注 SQL 并比较结果

### `gold_builder.py`
- 结合 KB/DB 自动合成题目与标注 SQL，覆盖“趋势/TopK/分布”等常见问题形态
- 输出 `outputs/gold_samples.jsonl`


## 设计要点与策略
- **M-Schema**：结构化 JSON，便于裁剪与注入
- **知识库注入**：行数/时间范围/TopN/示例行提升语义可判别性
- **表/列裁剪**：通过 `allowed_columns` 控制列空间；趋势类自动收窄到时间列
- **外键 JOIN 提示**：在 Prompt 中显式给出表间关系，提升多表 JOIN 正确率
- **SQL Guard**：统一方言、别名识别、禁止 `SELECT *` 与注入、自动 LIMIT、趋势分组约束
- **兜底模板**：
  - 目的：工程容错，保证在模型失败时仍能给出有用答案
  - 约束：同样经过 SQL Guard 校验
  - 开关：`--no-fallback` 可禁用（线上建议开，评测可 AB 对比）
- **后处理**：支持本地截断（已移除排序，以避免拉低评测指标）


## 常见问题排查（FAQ）
- 连接失败/权限：确认 `.env` 中 `MYSQL_*` 正确、账号权限完整
- JSONL 读写乱码/BOM：评测脚本使用 `utf-8-sig` 读取；生成时统一 `encoding="utf-8"`
- 生成了 `SELECT *`：被 `sql_guard.py` 拒绝，请明确列清单或使用 `allowed_columns`
- 趋势类多维分组：被 `sql_guard.py` 拒绝；如确需多维，请修改问题描述
- KB 为空：确保数据库确有数据、指定了正确库名、运行了 `kb_builder.py`
- PowerShell 命令续行：使用反引号或逐行执行，避免 `&&` 兼容性问题


## 🎓 项目背景

本项目是在实习期间完成的 Text-to-SQL 系统重构工作。项目的核心挑战包括：

1. **架构重构** - 将原有的"补丁驱动"架构重构为"LLM驱动"架构，移除大量硬编码的if/else逻辑
2. **安全保障** - 在企业环境中确保SQL生成的安全性，实现多层验证机制
3. **准确性提升** - 通过分层约束系统和AST级别验证，显著提高SQL生成质量

**技术亮点：**
- 两阶段LLM调用设计，实现规划与生成的解耦
- 分层约束系统（MUST/SHOULD/MAY），平衡严格性和灵活性
- 去补丁化设计，通过few-shot示例而非代码补丁扩展能力

已获得公司授权发布（数据已脱敏处理）。

## 📚 相关文档

- [详细运行说明](README_RUN.md) - 完整的使用指南和命令说明
- [架构总结](ARCHITECTURE_SUMMARY.md) - 系统架构和设计思路
- [使用指南](USAGE_GUIDE.md) - 快速入门和最佳实践
- [贡献指南](CONTRIBUTING.md) - 如何参与项目开发

## ⚖️ 许可证

本项目基于 [GPL-3.0 License](LICENSE) 开源。

**重要说明：**
- 本项目采用最严格的开源协议 GPL-3.0
- 任何使用、修改或衍生本项目的代码必须：
  - 同样以 GPL-3.0 协议开源
  - 公开完整源代码
  - 保留原始版权声明
- 不允许闭源商业使用
- 示例代码以教育/研究为目的提供，实际生产环境使用请结合具体业务场景和数据合规要求进行审查与优化。

## 🙏 致谢

感谢实习期间导师和团队的支持与指导。

---

**注意事项：**
- 本仓库不包含真实业务数据，所有敏感信息已清理
- 如需运行系统，请准备自己的MySQL数据库或使用公开数据集
- 详细的数据准备说明请参考 [outputs/README.md](outputs/README.md)



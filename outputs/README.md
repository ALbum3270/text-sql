# 数据文件说明 / Data Files Directory

此目录用于存放系统生成的数据文件。这些文件**不包含在代码仓库中**（已在 `.gitignore` 中排除）。

## 📁 目录结构

```
outputs/
├── m_schema.json          # 数据库Schema的JSON格式（由导出工具生成）
├── schema.md              # 数据库Schema的Markdown文档
├── kb/                    # 知识库目录
│   ├── kb_catalog.json    # 知识库索引文件
│   └── [表名].md          # 每个表的知识库文档
└── semantic_index/        # 语义检索索引（可选）
    ├── tables.hnsw
    ├── columns.hnsw
    └── *.json
```

## 🚀 如何生成这些文件

### 1. 导出数据库Schema

使用你自己的MySQL数据库：

```bash
# 方法1：使用旧版导出工具（如果存在）
python schema_export_mysql.py

# 方法2：使用新版主程序
python run_nl2sql_clean.py export
```

这将生成：
- `outputs/m_schema.json` - 结构化的Schema数据
- `outputs/schema.md` - 可读的Schema文档

### 2. 构建知识库（可选但推荐）

```bash
# 使用旧版工具（如果存在）
python kb_builder.py --output outputs/kb --no-mask

# 或使用新版工具
python run_nl2sql_clean.py build-kb
```

这将在 `outputs/kb/` 目录下为每个表生成知识库文档。

### 3. 构建语义索引（可选）

```bash
python run_nl2sql_clean.py build-index
```

这将生成 `outputs/semantic_index/` 目录下的索引文件。

## 📝 示例数据

如果你想快速测试系统而不连接真实数据库，可以：

1. 准备一个简单的MySQL测试数据库（如 Chinook、Sakila 等公开数据集）
2. 或者使用项目中的 `eval/eval_samples.jsonl` 中的示例问题

## ⚠️ 注意事项

- ❌ **不要提交**真实的业务数据到代码仓库
- ❌ **不要提交**包含敏感信息的Schema文件
- ✅ 可以提交脱敏后的示例Schema供他人参考
- ✅ 建议在 README 中说明如何使用公开数据集测试

## 🔒 数据安全

如果你的Schema包含敏感表名或字段名：
1. 使用脱敏工具处理后再分享
2. 或者仅在本地使用，不要推送到远程仓库
3. 确保 `.gitignore` 正确配置


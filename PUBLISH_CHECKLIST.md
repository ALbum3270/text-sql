# 发布前检查清单 / Pre-publish Checklist

在将代码推送到 GitHub 之前，请确认以下所有项目：

## ✅ 已完成项

- [x] 删除 `outputs/kb/` 下的所有业务知识库文件
- [x] 删除 `outputs/m_schema.json` 真实数据库结构
- [x] 删除 `outputs/schema.md` 数据库文档
- [x] 删除 `outputs/semantic_index/` 语义索引文件
- [x] 删除评测运行日志 `eval/eval_run_logs.jsonl`
- [x] 删除评测结果 `eval/eval_run_results.jsonl`
- [x] 删除临时文件 `temp_result.jsonl`
- [x] 创建 `.gitignore` 文件
- [x] 创建 `LICENSE` 文件（MIT）
- [x] 创建 `CONTRIBUTING.md` 文件
- [x] 清理 `README.md` 中的敏感配置信息
- [x] 创建 `outputs/README.md` 数据文件说明

## 🔍 需要手动检查的项目

### 1. 环境变量文件
- [ ] 确认 `.env` 文件不存在或已在 `.gitignore` 中
- [ ] 检查 `env.example` 没有真实密钥

### 2. 代码中的硬编码信息
运行以下命令检查：
```bash
# 检查可能的IP地址
grep -r "10\.\|192\.168\." --include="*.py" .

# 检查可能的数据库名
grep -r "edrserver" --include="*.py" .

# 检查可能的密码
grep -r "password.*=" --include="*.py" . | grep -v "MYSQL_PASSWORD"
```

### 3. 示例数据文件
- [ ] 检查 `gold_samples.jsonl` 是否包含敏感查询
- [ ] 检查 `eval/eval_samples.jsonl` 是否包含敏感数据
- [ ] 检查 `eval/eval_custom.jsonl` 是否包含真实业务逻辑

### 4. 文档文件
- [ ] 检查 `README_RUN.md` 是否有内部信息
- [ ] 检查 `ARCHITECTURE_SUMMARY.md` 是否暴露业务细节
- [ ] 检查 `problem_analysis.md` 是否包含敏感信息

### 5. Git 历史
- [ ] 确认之前的提交记录中没有敏感信息
- [ ] 如果有，考虑使用新仓库或清理历史

## 📝 推荐的发布步骤

### 步骤 1: 本地验证
```bash
# 1. 检查.gitignore是否生效
git status

# 2. 查看将被提交的文件
git add .
git status

# 3. 确认没有敏感文件
```

### 步骤 2: 创建新的远程仓库
```bash
# 如果是新仓库
git init
git add .
git commit -m "Initial commit: Text-to-SQL system"

# 添加远程仓库（替换为你的GitHub仓库地址）
git remote add origin https://github.com/yourusername/text-to-sql.git
git branch -M main
git push -u origin main
```

### 步骤 3: 完善 GitHub 仓库设置
- [ ] 添加仓库描述
- [ ] 添加相关标签（tags）：`text-to-sql`, `nlp`, `llm`, `mysql`
- [ ] 启用 Issues 和 Discussions（如果需要）
- [ ] 添加 README badge

### 步骤 4: 发布后检查
- [ ] 在 GitHub 上浏览所有文件，确认无敏感信息
- [ ] 检查提交历史
- [ ] 测试克隆仓库后能否正常使用

## ⚠️ 特别注意

### 不要提交的内容：
- ❌ 真实的API密钥
- ❌ 数据库连接字符串（真实的IP/用户名/密码）
- ❌ 公司内部数据（表结构、字段名、业务逻辑）
- ❌ 客户或项目相关的敏感信息
- ❌ 日志文件
- ❌ 临时文件和缓存

### 可以提交的内容：
- ✅ 代码逻辑（已脱敏）
- ✅ 配置示例（env.example）
- ✅ 通用的示例和文档
- ✅ 开源许可证
- ✅ 项目架构和设计思路

## 🔒 额外安全建议

1. **使用 git-secrets 工具**
   ```bash
   # 安装
   git clone https://github.com/awslabs/git-secrets.git
   cd git-secrets
   make install
   
   # 配置
   cd /path/to/your/repo
   git secrets --install
   git secrets --register-aws
   ```

2. **使用 BFG Repo-Cleaner**（如果需要清理历史）
   ```bash
   # 下载 BFG
   # https://rtyley.github.io/bfg-repo-cleaner/
   
   # 清理敏感文件
   bfg --delete-files sensitive_file.json
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   ```

3. **定期审查**
   - 定期检查仓库是否不小心提交了敏感信息
   - 关注 GitHub Security Alerts

## ✅ 最终确认

在执行 `git push` 之前，请确认：
- [ ] 我已经阅读并完成了上述所有检查项
- [ ] 我确认没有任何敏感信息将被推送到公开仓库
- [ ] 我已获得必要的授权（如果是工作项目）
- [ ] 我理解一旦推送到公开仓库，信息将难以完全删除

**签名确认：** _______________ **日期：** _______________


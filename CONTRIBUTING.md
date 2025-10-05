# 贡献指南 / Contributing Guide

感谢你对本项目的关注！欢迎任何形式的贡献。

## 🤝 如何贡献

### 报告问题 (Bug Reports)

如果你发现了 bug，请创建一个 Issue，并包含：
- 问题的详细描述
- 复现步骤
- 期望的行为
- 实际的行为
- 系统环境（Python版本、操作系统等）

### 功能建议 (Feature Requests)

如果你有好的想法，欢迎创建 Issue 讨论：
- 功能的使用场景
- 预期效果
- 可能的实现方案

### 代码贡献 (Pull Requests)

1. **Fork 本仓库**
2. **创建特性分支**
   ```bash
   git checkout -b feature/AmazingFeature
   ```
3. **编写代码**
   - 遵循现有代码风格
   - 添加必要的注释
   - 更新相关文档
4. **提交更改**
   ```bash
   git commit -m 'Add some AmazingFeature'
   ```
5. **推送到分支**
   ```bash
   git push origin feature/AmazingFeature
   ```
6. **创建 Pull Request**

## 📝 代码规范

### Python 代码风格
- 遵循 PEP 8 规范
- 使用有意义的变量名和函数名
- 函数和类需要添加 docstring
- 复杂逻辑需要添加注释

### 提交信息格式
```
<type>: <subject>

<body>
```

**Type 类型：**
- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具相关

**示例：**
```
feat: 添加语义检索功能

- 实现基于HNSW的向量检索
- 支持表名和列名的语义匹配
- 添加相关配置项
```

## 🧪 测试

在提交 PR 前，请确保：
- [ ] 代码能正常运行
- [ ] 没有引入新的linter错误
- [ ] 核心功能经过测试验证
- [ ] 更新了相关文档

## 📚 文档

如果你的更改影响到用户使用方式：
- 更新 README.md
- 更新相关示例代码
- 如有必要，添加新的文档文件

## ⚖️ 许可证

通过贡献代码，你同意你的贡献将在 MIT 许可证下发布。

## 💬 交流

如有任何疑问，欢迎：
- 创建 Issue 讨论
- 在 PR 中留言
- 通过邮件联系维护者

## 🙏 感谢

感谢每一位贡献者的付出！


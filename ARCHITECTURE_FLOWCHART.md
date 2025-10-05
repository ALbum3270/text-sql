# 🎨 Text-to-SQL 系统架构流程图

## 📊 系统总体架构图

```mermaid
graph TB
    Start([用户输入自然语言问题]) --> LoadSchema[加载数据库Schema<br/>M-Schema JSON]
    LoadSchema --> Tokenize[分词与语义映射<br/>中英文关键词提取]
    
    Tokenize --> TableRetrieval[表检索<br/>语义相似度评分]
    TableRetrieval --> FilterSchema[Schema过滤<br/>保留Top-K相关表]
    
    FilterSchema --> LoadKB{知识库存在?}
    LoadKB -->|是| KBRetrieval[加载Few-shot示例<br/>从gold_samples.jsonl]
    LoadKB -->|否| SkipKB[跳过知识库]
    KBRetrieval --> LLMPlanner
    SkipKB --> LLMPlanner
    
    LLMPlanner[🤖 LLM Planner<br/>第一阶段: 规划器]
    LLMPlanner --> PlanOutput[输出结构化计划<br/>PlanV1对象]
    
    PlanOutput --> ContractBuild[构建安全合同<br/>SafetyContract]
    ContractBuild --> LLMGenerator[🤖 LLM Generator<br/>第二阶段: 生成器]
    
    LLMGenerator --> TopKSQL[生成Top-K候选SQL<br/>SQLCandidate列表]
    
    TopKSQL --> ValidationLoop{遍历候选SQL}
    
    ValidationLoop --> SQLGuard[第1层: SQL Guard<br/>安全性检查]
    SQLGuard --> GuardPass{通过?}
    GuardPass -->|否| NextCandidate[尝试下一个候选]
    
    GuardPass -->|是| ASTValidator[第2层: AST Validator<br/>结构约束检查]
    ASTValidator --> ASTPass{通过?}
    ASTPass -->|否| NextCandidate
    
    ASTPass -->|是| DBExecute[第3层: 数据库执行<br/>真实查询验证]
    DBExecute --> ExecPass{执行成功?}
    ExecPass -->|否| NextCandidate
    ExecPass -->|是| Success[✅ 返回结果]
    
    NextCandidate --> ValidationLoop
    ValidationLoop -->|所有候选失败| Fallback[❌ 返回兜底SQL<br/>SELECT 1 WHERE 1=0]
    
    Success --> End([输出最终SQL与结果])
    Fallback --> End

    style Start fill:#e1f5e1
    style End fill:#e1f5e1
    style LLMPlanner fill:#fff4e1
    style LLMGenerator fill:#fff4e1
    style SQLGuard fill:#ffe1e1
    style ASTValidator fill:#ffe1e1
    style DBExecute fill:#ffe1e1
    style Success fill:#d4edda
    style Fallback fill:#f8d7da
```

---

## 🔍 详细模块分解

### 1️⃣ Schema检索与预处理

```mermaid
graph LR
    A[用户问题] --> B[分词Tokenization]
    B --> C[语义映射<br/>威胁→threat<br/>终端→node]
    C --> D[表评分算法]
    
    D --> E[精确匹配 +10.0]
    D --> F[模糊匹配 +3.0]
    D --> G[列名匹配 +1.0]
    D --> H[描述匹配 +0.5]
    
    E --> I[按分数排序]
    F --> I
    G --> I
    H --> I
    
    I --> J[选择Top-K表<br/>默认Top-15]
    J --> K[生成过滤后的<br/>M-Schema]
    
    style A fill:#e1f5e1
    style K fill:#d4edda
```

### 2️⃣ 知识库检索（Few-shot）

```mermaid
graph LR
    A[过滤后Schema] --> B{gold_samples.jsonl<br/>存在?}
    B -->|是| C[加载所有示例]
    B -->|否| D[跳过Few-shot]
    
    C --> E[计算相似度<br/>基于表名+列名]
    E --> F[匹配must_tables +10.0]
    E --> G[匹配表名 +5.0]
    E --> H[匹配列名 +1.0]
    
    F --> I[排序并选择Top-3]
    G --> I
    H --> I
    
    I --> J[格式化为Few-shot<br/>问题+SQL对]
    
    D --> K[空Few-shot]
    J --> K
    K --> L[传递给LLM]
    
    style B fill:#fff4e1
    style L fill:#d4edda
```

### 3️⃣ LLM Planner - 第一阶段

```mermaid
graph TB
    A[用户问题 + 过滤Schema] --> B[构建Planner提示词]
    B --> C[System Prompt<br/>规划器角色定义]
    C --> D[User Prompt<br/>问题 + Schema]
    
    D --> E[🤖 调用OpenAI API<br/>GPT-4/DeepSeek等]
    E --> F[返回JSON格式计划]
    
    F --> G[解析为PlanV1对象]
    G --> H{包含结构化约束}
    
    H --> I[task: 任务类型<br/>list/count/trend等]
    H --> J[must_tables: 必需表]
    H --> K[must_joins: 必需JOIN]
    H --> L[must_predicates: 必需WHERE]
    H --> M[should_projection: 建议列]
    H --> N[timeframe_days: 时间窗口]
    
    I --> O[PlanV1完整对象]
    J --> O
    K --> O
    L --> O
    M --> O
    N --> O
    
    O --> P[传递给Generator阶段]
    
    style E fill:#fff4e1
    style O fill:#d4edda
```

### 4️⃣ 安全合同构建

```mermaid
graph LR
    A[PlanV1计划] --> B[SafetyContract构建器]
    A2[过滤后Schema] --> B
    
    B --> C[allowed_tables<br/>允许使用的表]
    B --> D[allowed_columns<br/>每表允许的列]
    B --> E[must_tables<br/>必需包含的表]
    B --> F[must_joins<br/>必需的JOIN]
    B --> G[must_predicates<br/>必需的WHERE]
    B --> H[timeframe_days<br/>时间约束]
    
    C --> I[SafetyContract对象]
    D --> I
    E --> I
    F --> I
    G --> I
    H --> I
    
    I --> J[传递给Generator]
    
    style B fill:#fff4e1
    style I fill:#d4edda
```

### 5️⃣ LLM Generator - 第二阶段

```mermaid
graph TB
    A[SafetyContract + 问题] --> B[构建Generator提示词]
    B --> C[System Prompt<br/>SQL专家角色]
    C --> D[约束注入<br/>MUST/SHOULD/MAY]
    
    D --> E[User Prompt<br/>问题 + 安全合同]
    E --> F[🤖 调用XiYan/Qwen API]
    
    F --> G[生成Top-K候选SQL]
    G --> H[候选1: 主表视角]
    G --> I[候选2: 关联表视角]
    G --> J[候选3: 备选方案]
    
    H --> K[包含自检Checks]
    I --> K
    J --> K
    
    K --> L[每个候选包含:<br/>- label 标签<br/>- sql 语句<br/>- checks 自检项<br/>- confidence 置信度]
    
    L --> M[返回SQLCandidate列表]
    M --> N[传递给验证层]
    
    style F fill:#fff4e1
    style M fill:#d4edda
```

### 6️⃣ 三层验证流水线

```mermaid
graph TB
    A[候选SQL列表] --> B{遍历每个候选}
    
    B --> C[📋 第1层: SQL Guard<br/>sql_guard.py]
    C --> D{安全检查}
    D --> E[检查危险操作<br/>DROP/DELETE/UPDATE等]
    D --> F[检查表名合法性<br/>仅允许Schema中的表]
    D --> G[检查列名合法性<br/>仅允许声明的列]
    D --> H[检查别名合法性<br/>只允许白名单别名]
    D --> I[检查复杂JOIN<br/>限制嵌套层数]
    
    E --> J{全部通过?}
    F --> J
    G --> J
    H --> J
    I --> J
    
    J -->|否| K[❌ 拒绝此候选<br/>记录错误]
    J -->|是| L[✅ 进入第2层]
    
    L --> M[📐 第2层: AST Validator<br/>ast_validator.py]
    M --> N{约束检查}
    N --> O[检查must_tables<br/>是否全部出现]
    N --> P[检查must_joins<br/>JOIN条件是否满足]
    N --> Q[检查must_predicates<br/>WHERE条件是否满足]
    N --> R[检查时间过滤<br/>timeframe_days约束]
    
    O --> S{全部满足?}
    P --> S
    Q --> S
    R --> S
    
    S -->|否| T[❌ 约束违反<br/>记录缺失项]
    S -->|是| U[✅ 进入第3层]
    
    U --> V[🗄️ 第3层: 数据库执行<br/>真实查询]
    V --> W[使用pymysql连接]
    W --> X[设置超时: 5秒]
    X --> Y[执行SQL]
    
    Y --> Z{执行结果}
    Z -->|语法错误| AA[❌ SQL语法错误]
    Z -->|超时| AB[❌ 查询超时]
    Z -->|其他错误| AC[❌ 执行失败]
    Z -->|成功| AD[✅ 返回结果集]
    
    K --> B
    T --> B
    AA --> B
    AB --> B
    AC --> B
    
    AD --> AE[🎉 验证成功<br/>返回最终SQL]
    
    B -->|所有候选失败| AF[⚠️ 返回兜底SQL<br/>SELECT 1 WHERE 1=0]
    
    style C fill:#ffe1e1
    style M fill:#ffe1e1
    style V fill:#ffe1e1
    style AE fill:#d4edda
    style AF fill:#f8d7da
```

---

## 🔄 完整端到端流程时序图

```mermaid
sequenceDiagram
    participant User as 👤 用户
    participant Main as 主程序<br/>run_nl2sql_clean.py
    participant Schema as Schema检索器
    participant KB as 知识库<br/>gold_samples.jsonl
    participant Planner as 🤖 LLM Planner
    participant Contract as 安全合同构建器
    participant Generator as 🤖 LLM Generator
    participant Guard as SQL Guard
    participant AST as AST Validator
    participant DB as 💾 MySQL数据库
    
    User->>Main: 输入问题: "近7天威胁域名统计"
    Main->>Schema: 加载完整Schema (m_schema.json)
    Schema-->>Main: 返回完整Schema
    
    Main->>Main: 分词与语义映射
    Note over Main: 威胁→threat<br/>域名→domain<br/>统计→count
    
    Main->>Schema: 表检索与评分
    Schema->>Schema: 计算每个表的相似度
    Schema-->>Main: Top-15相关表
    Note over Schema: threat_domain_static (15.0)<br/>domain_blacklist (8.0)<br/>...
    
    Main->>KB: 检索Few-shot示例
    KB->>KB: 匹配相似问题
    KB-->>Main: Top-3示例
    
    Main->>Planner: 第一阶段调用
    Note over Planner: 输入: 问题 + Schema + Few-shots
    Planner->>Planner: 分析问题意图
    Planner-->>Main: PlanV1对象
    Note over Planner: task=count<br/>must_tables=[threat_domain_static]<br/>timeframe_days=7
    
    Main->>Contract: 构建安全合同
    Contract-->>Main: SafetyContract对象
    
    Main->>Generator: 第二阶段调用
    Note over Generator: 输入: 问题 + 安全合同
    Generator->>Generator: 生成Top-3候选SQL
    Generator-->>Main: [候选1, 候选2, 候选3]
    
    loop 遍历每个候选
        Main->>Guard: 第1层验证
        Guard->>Guard: 检查安全性
        alt 安全检查失败
            Guard-->>Main: ❌ 拒绝
        else 通过
            Guard-->>Main: ✅ 通过
            Main->>AST: 第2层验证
            AST->>AST: 检查约束满足
            alt 约束违反
                AST-->>Main: ❌ 拒绝
            else 满足
                AST-->>Main: ✅ 通过
                Main->>DB: 第3层执行
                DB->>DB: 真实查询
                alt 执行错误
                    DB-->>Main: ❌ 失败
                else 成功
                    DB-->>Main: ✅ 结果集
                    Main->>User: 返回最终SQL + 结果
                end
            end
        end
    end
    
    alt 所有候选失败
        Main->>User: 返回兜底SQL<br/>SELECT 1 WHERE 1=0
    end
```

---

## 🎯 核心文件职责地图

```mermaid
graph LR
    subgraph 入口层
        A[run_nl2sql_clean.py<br/>主程序入口]
    end
    
    subgraph 规划层
        B[llm_planner.py<br/>第一阶段LLM]
        C[PlanV1<br/>结构化计划对象]
    end
    
    subgraph 生成层
        D[llm_generator.py<br/>第二阶段LLM]
        E[xiyan_client.py<br/>XiYan API客户端]
        F[SafetyContract<br/>安全合同对象]
    end
    
    subgraph 验证层
        G[sql_guard.py<br/>第1层: 安全检查]
        H[ast_validator.py<br/>第2层: 约束检查]
        I[validation_engine.py<br/>验证协调器]
    end
    
    subgraph 数据层
        J[m_schema.json<br/>数据库元数据]
        K[gold_samples.jsonl<br/>Few-shot知识库]
        L[MySQL Database<br/>真实数据库]
    end
    
    subgraph 评估层
        M[gold_evaluation.py<br/>准确率评估]
        N[eval_batch_run.py<br/>批量测试]
    end
    
    A --> B
    A --> J
    A --> K
    B --> C
    C --> D
    D --> E
    D --> F
    E --> D
    F --> G
    G --> H
    H --> I
    I --> L
    A --> M
    M --> N
    
    style A fill:#e1f5e1
    style B fill:#fff4e1
    style D fill:#fff4e1
    style G fill:#ffe1e1
    style H fill:#ffe1e1
    style I fill:#ffe1e1
    style L fill:#e3f2fd
```

---

## 🔒 三层验证详解

### 第1层: SQL Guard (安全性)

```mermaid
graph TB
    A[输入SQL] --> B[解析为AST<br/>使用sqlglot]
    B --> C{危险操作检查}
    
    C --> D[扫描DROP语句]
    C --> E[扫描DELETE语句]
    C --> F[扫描UPDATE语句]
    C --> G[扫描TRUNCATE语句]
    
    D --> H{发现危险操作?}
    E --> H
    F --> H
    G --> H
    
    H -->|是| I[❌ 立即拒绝<br/>SQLValidationError]
    H -->|否| J[✅ 继续检查]
    
    J --> K{表名检查}
    K --> L[提取所有表引用]
    L --> M[对比允许的表列表]
    M --> N{表名合法?}
    N -->|否| I
    N -->|是| O[✅ 继续检查]
    
    O --> P{列名检查}
    P --> Q[提取所有列引用]
    Q --> R[对比Schema中的列]
    R --> S{列名合法?}
    S -->|否| I
    S -->|是| T[✅ 继续检查]
    
    T --> U{别名检查}
    U --> V[提取SELECT别名]
    V --> W[对比白名单<br/>d/cnt/date等]
    W --> X{别名合法?}
    X -->|否| I
    X -->|是| Y[✅ 通过SQL Guard]
    
    Y --> Z[进入AST Validator]
    
    style I fill:#f8d7da
    style Y fill:#d4edda
```

### 第2层: AST Validator (约束满足)

```mermaid
graph TB
    A[输入SQL + 约束] --> B[解析SQL结构]
    B --> C{检查must_tables}
    
    C --> D[提取SQL中的表]
    D --> E[对比must_tables列表]
    E --> F{全部出现?}
    F -->|否| G[记录缺失表]
    F -->|是| H[✅ 表检查通过]
    
    H --> I{检查must_joins}
    I --> J[提取JOIN条件]
    J --> K[对比must_joins要求]
    K --> L{全部满足?}
    L -->|否| M[记录缺失JOIN]
    L -->|是| N[✅ JOIN检查通过]
    
    N --> O{检查must_predicates}
    O --> P[提取WHERE条件]
    P --> Q[对比must_predicates]
    Q --> R{全部满足?}
    R -->|否| S[记录缺失WHERE]
    R -->|是| T[✅ WHERE检查通过]
    
    T --> U{检查时间约束}
    U --> V[检查timeframe_days]
    V --> W[验证时间过滤语法]
    W --> X{时间约束正确?}
    X -->|否| Y[记录时间错误]
    X -->|是| Z[✅ 通过AST Validator]
    
    G --> AA[❌ 约束违反]
    M --> AA
    S --> AA
    Y --> AA
    
    AA --> AB[返回ASTValidationResult<br/>passed=False]
    Z --> AC[返回ASTValidationResult<br/>passed=True]
    
    AC --> AD[进入数据库执行]
    
    style AA fill:#f8d7da
    style Z fill:#d4edda
```

### 第3层: 数据库执行 (真实性)

```mermaid
graph LR
    A[通过AST验证的SQL] --> B[连接MySQL]
    B --> C[设置查询参数]
    C --> D[cursor.execute SQL]
    
    D --> E{执行结果}
    
    E -->|语法错误<br/>1064| F[❌ SQL语法错误]
    E -->|表不存在<br/>1146| G[❌ 表名错误]
    E -->|列不存在<br/>1054| H[❌ 列名错误]
    E -->|超时| I[❌ 查询超时]
    E -->|其他错误| J[❌ 执行异常]
    E -->|成功| K[✅ 获取结果集]
    
    K --> L[返回: SQL + 结果数据]
    
    F --> M[尝试下一个候选]
    G --> M
    H --> M
    I --> M
    J --> M
    
    style F fill:#f8d7da
    style G fill:#f8d7da
    style H fill:#f8d7da
    style I fill:#f8d7da
    style J fill:#f8d7da
    style K fill:#d4edda
```

---

## 📈 性能与扩展性

### 并发执行策略

```mermaid
graph TB
    A[批量问题列表] --> B[ThreadPoolExecutor<br/>最多8个工作线程]
    
    B --> C[线程1: 问题1]
    B --> D[线程2: 问题2]
    B --> E[线程3: 问题3]
    B --> F[线程N: 问题N]
    
    C --> G[独立执行流水线]
    D --> G
    E --> G
    F --> G
    
    G --> H[收集所有结果]
    H --> I[输出统计报告]
    
    style B fill:#e3f2fd
    style I fill:#d4edda
```

---

## 🎓 使用示例流程

```mermaid
graph LR
    A[用户问题:<br/>"近7天威胁域名统计"] --> B[Schema检索]
    B --> C[选中:<br/>threat_domain_static]
    C --> D[Planner规划:<br/>task=count<br/>timeframe_days=7]
    D --> E[Generator生成SQL]
    E --> F[候选SQL:<br/>SELECT domain_address, COUNT*<br/>FROM threat_domain_static<br/>WHERE first_find_time >= ...]
    F --> G[三层验证]
    G --> H[数据库执行]
    H --> I[返回结果:<br/>domain1: 150<br/>domain2: 89<br/>...]
    
    style A fill:#e1f5e1
    style I fill:#d4edda
```

---

## 📝 评估流程

```mermaid
graph TB
    A[gold_samples.jsonl<br/>118个测试问题] --> B[gold_evaluation.py]
    B --> C[遍历每个测试问题]
    
    C --> D[执行Text-to-SQL流水线]
    D --> E[生成预测SQL]
    E --> F[对比gold_sql]
    
    F --> G{执行结果比较}
    G --> H[检查表名匹配]
    G --> I[检查列名匹配]
    G --> J[检查约束匹配]
    
    H --> K[计算综合得分]
    I --> K
    J --> K
    
    K --> L{得分 >= 阈值?}
    L -->|是| M[✅ 测试通过]
    L -->|否| N[❌ 测试失败]
    
    M --> O[统计准确率]
    N --> O
    
    O --> P[生成评估报告<br/>准确率 / 错误分析]
    
    style A fill:#e3f2fd
    style P fill:#d4edda
```

---

## 🔧 配置与环境

```mermaid
graph LR
    A[.env 配置文件] --> B[数据库配置]
    A --> C[LLM配置]
    A --> D[系统配置]
    
    B --> E[MYSQL_HOST<br/>MYSQL_PORT<br/>MYSQL_USER<br/>MYSQL_PASSWORD<br/>MYSQL_DB]
    
    C --> F[XIYAN_MODEL<br/>MODELSCOPE_API_KEY<br/>PLANNER_MODEL<br/>OPENAI_API_KEY]
    
    D --> G[MAX_TABLE_TOPK=15<br/>DEFAULT_MAX_LIMIT=200<br/>SQL_PERMITTED_ALIASES]
    
    E --> H[run_nl2sql_clean.py]
    F --> H
    G --> H
    
    style A fill:#fff4e1
    style H fill:#d4edda
```

---

## 🎯 关键技术特性

### 两阶段LLM架构

```mermaid
graph LR
    A[单阶段方法<br/>❌ 直接生成SQL] --> B[容易出错<br/>缺乏规划]
    
    C[两阶段方法<br/>✅ Planner + Generator] --> D[第1阶段<br/>理解意图]
    D --> E[第2阶段<br/>约束生成]
    E --> F[更高准确率<br/>更可控]
    
    style A fill:#f8d7da
    style C fill:#d4edda
```

### 分层约束系统

```mermaid
graph TB
    A[约束分层] --> B[MUST 硬约束<br/>必须满足]
    A --> C[SHOULD 软约束<br/>优先满足]
    A --> D[MAY 可选<br/>冲突时放弃]
    
    B --> E[违反 → 拒绝SQL]
    C --> F[违反 → 扣分]
    D --> G[违反 → 忽略]
    
    style B fill:#ffe1e1
    style C fill:#fff4e1
    style D fill:#e3f2fd
```

---

**🎉 流程图完成！**

这些流程图展示了项目的完整工作流程，包括：
- 总体架构
- 详细模块分解
- 时序交互
- 验证流程
- 评估机制

可以直接在GitHub上查看这些Mermaid图表！


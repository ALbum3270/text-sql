import os
import json
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from openai import OpenAI


XIYAN_TEMPLATE = """
你是一名{dialect}数据库与 SQL 最佳实践专家。请依据下面的数据库结构信息与知识库片段，为用户问题生成一条正确、可执行、最优的 SQL。
必须遵循（违反任一条将视为错误）：
- 仅输出 SQL，无需解释、无额外注释、无中文占位；
- 严禁使用 SELECT *（必须只选择查询所需列）；
- 只允许使用提供的表与字段，不得虚构列/别名/常量；
- 如为“趋势/按天”问题：必须使用 DATE(时间列) 分组，并写出 WHERE 时间列 >= CURDATE() - INTERVAL N DAY；
 - 如为“TOPK/排行/前N/计数（前N）”问题：仅选择 分类列 与 COUNT(*) 两列，并写出 LIMIT N；若题面含时间范围，必须追加 WHERE 时间列 >= CURDATE() - INTERVAL N DAY；
- 必须使用 {dialect} 5.7 语法；INTERVAL 写法为 INTERVAL 7 DAY（数字不可加引号）；
 - 如有聚合，必须显式写出 GROUP BY；
   - 如为"总量/数量总计/总条数"问题：必须生成 SELECT COUNT(*) AS cnt，不得包含任意非聚合列；禁止 GROUP BY；严禁添加任何 WHERE 或 LIMIT，除非题面或证据明确要求；
 - 如题面或证据未明确规定时间范围/过滤条件，严禁引入任何 WHERE 条件（不得臆造如"过去一年/某年"的时间范围）。
 - 如遇到无法处理的问题（如表不存在、列不匹配），必须输出兜底SQL：SELECT 1 WHERE 1=0
  - 如为“时间范围/最早/最晚”问题：必须生成 SELECT MIN(时间列) AS min_time, MAX(时间列) AS max_time，不得包含任意非聚合列；禁止 GROUP BY；
- 对于可能与保留字冲突的列名（如 check/desc），应使用反引号包裹（例如 `check`）。
- 列只能从“可用列清单”中选择，严禁使用清单外的列名。

若你无法依据提供的 schema/可用列清单构造出合法 SQL（例如没有相关表或字段），请直接输出：
SELECT 1 WHERE 1=0
用于显式表示“未能召回有效查询”。

如题面涉及“租户/用户/账号/用户ID/less_user”等语义，请优先使用含有 `less_user` 的表进行过滤；
如题面涉及“主机/终端/节点”等语义，请优先使用 `node_id` 或 `machine_id` 等与主机关联的字段；
如题面涉及“病毒/染毒/木马”等语义，请优先使用 `virus_details` 表，并按需与主机/租户信息关联（如 `less_user`、`node_id`/`machine_id`）。

〖用户问题〗
{question}

〖数据库schema（裁剪后 M-Schema）〗
{db_schema}

〖可用列清单（仅可从中选择）〗
{allowed_columns}

〖知识库片段（可空）〗
{kb_snippet}

〖结构关系与注释（可空）〗
{schema_overview}

〖示例（可空，仅参考）〗
{fewshots}

〖参考信息（可空）〗
{evidence}

请直接以如下格式输出：
```sql
-- 仅输出可执行 SQL（不要输出任何额外文本）
"""


def load_client() -> OpenAI:
    """严格模式：不跨提供方回退。

    - 若 XIYAN_MODEL 看起来是 ModelScope 模型名（包含 "/" 或以 XGenerationLab/XiYan 开头），仅使用 MODELSCOPE_*
    - 否则仅使用 DashScope/QWEN 兼容端点（QWEN_BASE_URL / DASHSCOPE_BASE_URL + DASHSCOPE_API_KEY/QWEN_API_KEY）
    任一所需变量缺失则直接报错。
    """
    load_dotenv(override=True)
    model_name = os.getenv("XIYAN_MODEL", "XGenerationLab/XiYanSQL-QwenCoder-32B-2412")
    name_l = (model_name or "").lower()
    is_modelscope_model = ("/" in (model_name or "")) or name_l.startswith("xgenerationlab") or name_l.startswith("xiyan")

    if is_modelscope_model:
        base_url = os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1")
        api_key = os.getenv("MODELSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("未设置 MODELSCOPE_API_KEY（严格模式不回退）")
        return OpenAI(base_url=base_url, api_key=api_key)

    # DashScope/QWEN 兼容端点
    base_url = os.getenv("QWEN_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 DASHSCOPE_API_KEY / QWEN_API_KEY（严格模式不回退）")
    return OpenAI(base_url=base_url, api_key=api_key)


def call_xiyan(question: str, m_schema: Dict[str, Any], evidence: str = "", kb_snippet: str = "", allowed_columns: str = "", fewshots: str = "", schema_overview: str = "", model: Optional[str] = None, temperature: float = 0.0, top_p: float = 0.3, max_tokens: int = 512) -> str:
    client = load_client()
    model_name = model or os.getenv("XIYAN_MODEL", "XGenerationLab/XiYanSQL-QwenCoder-32B-2412")
    dialect = os.getenv("DB_DIALECT", "mysql")

    tpl = XIYAN_TEMPLATE.format(
        dialect=dialect,
        question=question.strip(),
        db_schema=json.dumps(m_schema, ensure_ascii=False, indent=2),
        allowed_columns=allowed_columns or "",
        kb_snippet=kb_snippet or "",
        schema_overview=schema_overview or "",
        fewshots=fewshots or "",
        evidence=evidence or ""
    )

    resp = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": tpl}],
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
    )
    text = resp.choices[0].message.content.strip()

    code = text
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            code = parts[1]
            if code.lower().startswith("sql\n"):
                code = code[4:]
    return code.strip()

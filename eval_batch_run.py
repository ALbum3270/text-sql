#!/usr/bin/env python3
"""
批量运行 eval_samples.jsonl：
- 逐条读取 question
- 调用 clean 流程（等价 --best 配置）
- 分别将完整日志与结构化结果写入两个 JSONL 文件

用法示例（PowerShell）：
  $env:T2SQL_DEBUG="1"; python eval_batch_run.py --input eval_samples.jsonl --logs outputs/eval_run_logs.jsonl --results outputs/eval_run_results.jsonl --best
"""

import os
import sys
import json
import time
import argparse
from io import StringIO
from contextlib import redirect_stdout


def _load_lines(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                yield {"question": line}


def main():
    parser = argparse.ArgumentParser(description="Batch runner for eval_samples.jsonl")
    parser.add_argument("--input", required=True, help="输入 JSONL（含 question 字段）")
    parser.add_argument("--logs", required=True, help="输出日志 JSONL 文件路径")
    parser.add_argument("--results", required=True, help="输出结果 JSONL 文件路径")
    parser.add_argument("--topk", type=int, default=3, help="每题生成 SQL 数量（--best 时至少 3）")
    parser.add_argument("--best", action="store_true", help="使用最佳配置：开启语义检索、TopK>=3")
    args = parser.parse_args()

    # 惯例：最佳配置下，开启语义检索并提升候选数
    sql_topk = max(3, args.topk) if args.best else max(1, args.topk)
    use_semantic = True if args.best else False

    # 延迟导入以便 CLI 参数先解析
    from types import SimpleNamespace
    from run_nl2sql_clean import do_ask

    # 确保输出目录存在
    os.makedirs(os.path.dirname(args.logs), exist_ok=True)
    os.makedirs(os.path.dirname(args.results), exist_ok=True)

    num_total = 0
    num_ok = 0

    with open(args.logs, "w", encoding="utf-8") as flog, open(args.results, "w", encoding="utf-8") as fres:
        for idx, item in enumerate(_load_lines(args.input), start=1):
            question = str(item.get("question") or "").strip()
            if not question:
                continue

            num_total += 1
            ts = int(time.time())

            # 构造 do_ask 的参数对象
            ns = SimpleNamespace(
                question=question,
                output=None,
                sql_topk=sql_topk,
                use_semantic=use_semantic,
                best=args.best,
            )

            # 捕获 stdout 作为运行日志
            buf = StringIO()
            results = []
            err_msg = None
            try:
                with redirect_stdout(buf):
                    results = do_ask(ns) or []
                num_ok += 1 if results else 0
            except SystemExit:
                # do_ask 内部可能调用 sys.exit，忽略为失败
                err_msg = "SystemExit during do_ask"
            except Exception as e:
                err_msg = f"Exception: {e}"

            # 写日志行
            log_rec = {
                "idx": idx,
                "ts": ts,
                "question": question,
                "error": err_msg,
                "log": buf.getvalue(),
            }
            flog.write(json.dumps(log_rec, ensure_ascii=False) + "\n")

            # 写结果行（原样透传 do_ask 返回的 results 列表）
            res_rec = {
                "idx": idx,
                "ts": ts,
                "question": question,
                "results": results,
            }
            fres.write(json.dumps(res_rec, ensure_ascii=False) + "\n")
            fres.flush(); flog.flush()

    print(f"完成：共 {num_total} 条，成功 {num_ok} 条。日志 -> {args.logs}，结果 -> {args.results}")


if __name__ == "__main__":
    main()



import os
import json
from typing import Any, Dict, List, Tuple, Optional

import math


def _safe_lower_set(text: str) -> List[str]:
    buf: List[str] = []
    cur: List[str] = []
    for ch in (text or ""):
        if ch.isalnum() or ch in ("_", "-", "."):
            cur.append(ch.lower())
        else:
            if cur:
                buf.append("".join(cur))
                cur = []
    if cur:
        buf.append("".join(cur))
    return buf


def _load_schema(schema_path: str) -> Dict[str, Any]:
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_kb_catalog(kb_path: str) -> Dict[str, Any]:
    if not os.path.exists(kb_path):
        return {}
    with open(kb_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_table_docs(m_schema: Dict[str, Any], kb_catalog: Dict[str, Any] = None) -> Tuple[List[str], List[str]]:
    # returns (ids, docs) with enhanced KB information
    kb_map = {t.get("name"): t for t in (kb_catalog.get("tables", []) if kb_catalog else [])}
    ids: List[str] = []
    docs: List[str] = []
    for t in m_schema.get("tables", []) or []:
        name = t.get("name")
        comment = (t.get("comment") or "").strip()
        cols = t.get("columns", []) or []
        col_names = [c.get("name") for c in cols][:30]
        fks = t.get("foreign_keys", []) or []
        fk_lines = [f"{name}.{fk.get('column')}->{fk.get('ref_table')}.{fk.get('ref_column')}" for fk in fks]
        
        # 从 KB 获取增强信息
        kb_entry = kb_map.get(name, {})
        purpose = kb_entry.get("purpose", "")
        good_for = kb_entry.get("good_for", [])
        aliases = kb_entry.get("aliases", [])
        top_values = kb_entry.get("top_values", [])
        
        text = []
        text.append(f"[TABLE] {name}")
        
        # 优先使用 KB 的 purpose
        if purpose:
            text.append(f"用途:{purpose}")
        elif comment:
            text.append(f"描述:{comment}")
            
        # 添加适用场景
        if good_for:
            text.append(f"适用:{', '.join(good_for[:3])}")
            
        # 添加别名关键词
        if aliases:
            text.append(f"关键词:{', '.join(aliases[:8])}")
            
        # 添加示例值
        if top_values:
            text.append(f"示例值:{', '.join(str(v) for v in top_values[:6])}")
            
        if col_names:
            text.append(f"列:{', '.join(col_names)}")
        if fk_lines:
            text.append(f"外键:{'; '.join(fk_lines)}")
            
        ids.append(name)
        docs.append("\n".join(text))
    return ids, docs


def _build_column_docs(m_schema: Dict[str, Any], kb_catalog: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    # returns (ids like table.col, docs) with enhanced KB information
    kb_map = {t.get("name"): t for t in (kb_catalog.get("tables", []) if kb_catalog else [])}
    ids: List[str] = []
    docs: List[str] = []
    for t in m_schema.get("tables", []) or []:
        tname = t.get("name")
        cols = t.get("columns", []) or []
        kb_entry = kb_map.get(tname) or {}
        
        # 旧格式的 topn_columns（向后兼容）
        topn_cols = (kb_entry.get("topn_columns") or {})
        
        # 新格式的 KB columns 信息
        kb_columns = {c.get("name"): c for c in (kb_entry.get("columns") or [])}
        
        for c in cols:
            cname = c.get("name")
            dtype = c.get("type")
            comment = (c.get("comment") or "").strip()
            
            # 从 KB catalog 获取列的增强信息
            kb_col = kb_columns.get(cname, {})
            kb_desc = kb_col.get("desc", "")
            kb_aliases = kb_col.get("aliases", [])
            kb_top_values = kb_col.get("top_values", [])
            
            # 优先使用 KB 的 top_values，否则使用旧格式
            if kb_top_values:
                topv_txt = ", ".join([str(v) for v in kb_top_values[:8]])
            else:
                # 向后兼容旧格式
                topv_raw = topn_cols.get(cname) or []
                topv_pairs: List[Tuple[str, float]] = []
                for item in topv_raw:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        v = str(item[0])
                        try:
                            cnt = float(item[1])
                        except Exception:
                            cnt = 0.0
                        topv_pairs.append((v, cnt))
                    else:
                        topv_pairs.append((str(item), 0.0))
                topv_pairs = topv_pairs[:8]
                topv_txt = ", ".join([f"{v}:{int(cnt)}" if not math.isnan(cnt) else v for v, cnt in topv_pairs])
            
            text_lines = [f"[COLUMN] {tname}.{cname}", f"类型:{dtype}"]
            
            # 优先使用 KB 的描述
            if kb_desc:
                text_lines.append(f"描述:{kb_desc}")
            elif comment:
                text_lines.append(f"注释:{comment}")
                
            # 添加列别名关键词
            if kb_aliases:
                text_lines.append(f"别名:{', '.join(kb_aliases[:6])}")
                
            if topv_txt:
                text_lines.append(f"TopN值:{topv_txt}")
                
            ids.append(f"{tname}.{cname}")
            docs.append("\n".join(text_lines))
    return ids, docs


def _maybe_load_st_model(model_name: str, use_gpu: bool = True):
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import torch
    except Exception:
        return None
    try:
        # 设置设备
        device = 'cuda' if use_gpu and torch.cuda.is_available() else 'cpu'
        # 某些多语模型（如 Alibaba-NLP/gte-multilingual-base）需要信任远端代码
        # 新版 sentence-transformers 支持 trust_remote_code 参数向下传递至 transformers
        try:
            model = SentenceTransformer(model_name, device=device, trust_remote_code=True)  # type: ignore
        except TypeError:
            # 旧版不支持该参数，回退为不带 trust_remote_code（部分模型可能加载失败）
            model = SentenceTransformer(model_name, device=device)
        print(f"语义模型加载到: {device}")
        return model
    except Exception:
        return None


def _encode_texts(model, texts: List[str]) -> Optional[List[List[float]]]:
    if model is None:
        return None
    try:
        emb = model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
        return emb.tolist()
    except Exception:
        return None


def _cosine_sim_matrix(q_vec: List[float], mat: List[List[float]]) -> List[float]:
    res: List[float] = []
    # q_vec and mat rows are already normalized (if generated by ST), but fallback gracefully
    import math as _m
    def _norm(v: List[float]) -> float:
        return _m.sqrt(sum(x * x for x in v)) or 1.0
    qn = _norm(q_vec)
    for row in mat:
        rn = _norm(row)
        dot = sum(a * b for a, b in zip(q_vec, row))
        res.append(dot / (qn * rn))
    return res


def _lexical_score(question: str, text: str) -> float:
    # simple keyword overlap score
    # expand Chinese domain terms to English aliases for better overlap with schema names
    qtoks_raw = set(_safe_lower_set(question))
    # minimal built-in alias for EDR domain
    alias_map = {
        "弱口令": ["weak_password"],
        "弱密码": ["weak_password"],
        "弱凭证": ["weak_password"],
        "弱账号": ["weak_password"],
        "弱帐户": ["weak_password"],
        "染毒": ["virus", "malware", "horse"],
        "感染": ["virus", "malware", "horse"],
        "中毒": ["virus", "malware", "horse"],
        "木马": ["horse", "malware"],
        "病毒": ["virus", "malware"],
        "威胁": ["threat", "attck"],
        "攻击": ["threat", "attck"],
        "告警": ["alert", "attck_warning"],
        "预警": ["alert", "attck_warning"],
        "终端": ["node", "host"],
        "主机": ["node", "host"],
        "漏洞": ["vul", "vulnerability", "ai_asset_vul", "vulnerability_mark", "vulnerability_scan_task", "vulnerability_task_node_status", "vulnerability_scan_task_node"],
    }
    qtoks = set(qtoks_raw)
    for zh, en_list in alias_map.items():
        if any(zh in tk for tk in qtoks_raw):
            for en in en_list:
                qtoks.add(en)
    ttoks = set(_safe_lower_set(text))
    if not qtoks or not ttoks:
        return 0.0
    inter = qtoks & ttoks
    return len(inter) / (len(qtoks) ** 0.5 + 1e-6)


def suggest_by_semantics(
    question: str,
    m_schema: Dict[str, Any],
    kb_catalog: Dict[str, Any],
    model_name: str = "moka-ai/m3e-base",
    top_tables: int = 6,
    top_cols: int = 24,
    value_bonus: float = 0.2,
    use_gpu: bool = True,
    lexical_bonus: float = 0.1,
) -> Tuple[List[Tuple[str, float]], Dict[str, List[str]]]:
    """
    Returns (ranked_tables, selected_columns_by_table)
    - ranked_tables: list of (table_name, score)
    - selected_columns_by_table: per table top columns (by semantic/lexical fusion)
    Fallback to lexical-only if sentence-transformers not available.
    """
    # Build docs
    table_ids, table_docs = _build_table_docs(m_schema, kb_catalog)
    col_ids, col_docs = _build_column_docs(m_schema, kb_catalog)

    # Prepare embedding model (optional)
    model = _maybe_load_st_model(model_name, use_gpu)
    # Encode
    t_emb = _encode_texts(model, table_docs)
    c_emb = _encode_texts(model, col_docs)
    q_emb = _encode_texts(model, [question])

    # Scoring
    table_scores: List[Tuple[str, float]] = []
    column_scores: List[Tuple[str, float]] = []

    if model is not None and t_emb is not None and c_emb is not None and q_emb is not None:
        q_vec = q_emb[0]
        # cosine similarity
        t_scores = _cosine_sim_matrix(q_vec, t_emb)
        c_scores = _cosine_sim_matrix(q_vec, c_emb)
        table_scores = list(zip(table_ids, t_scores))
        column_scores = list(zip(col_ids, c_scores))
    else:
        # lexical fallback
        table_scores = [(tid, _lexical_score(question, doc)) for tid, doc in zip(table_ids, table_docs)]
        column_scores = [(cid, _lexical_score(question, doc)) for cid, doc in zip(col_ids, col_docs)]

    # Value-word bonus from KB (both old and new format)
    kb_map = {t.get("name"): t for t in (kb_catalog.get("tables", []) if kb_catalog else [])}
    q_tokens = set(_safe_lower_set(question))
    value_hit_cols: set = set()
    alias_hit_cols: set = set()
    
    for cid, _ in column_scores:
        tname, cname = cid.split(".", 1)
        entry = kb_map.get(tname) or {}
        
        # 检查新格式的列信息
        kb_columns = {c.get("name"): c for c in (entry.get("columns") or [])}
        kb_col = kb_columns.get(cname, {})
        
        # 检查别名匹配
        for alias in (kb_col.get("aliases") or []):
            if str(alias).lower() in q_tokens:
                alias_hit_cols.add(cid)
                break
        
        # 检查值匹配（新格式）
        for val in (kb_col.get("top_values") or [])[:10]:
            if str(val).lower() in q_tokens:
                value_hit_cols.add(cid)
                break
        
        # 检查值匹配（旧格式，向后兼容）
        if cid not in value_hit_cols:
            topn = entry.get("topn_columns", {}).get(cname) or []
            for item in topn[:10]:
                val = str(item[0]).lower() if isinstance(item, (list, tuple)) and item else str(item).lower()
                if val and val in q_tokens:
                    value_hit_cols.add(cid)
                    break

    # Fuse to table level
    best_col_per_table: Dict[str, float] = {}
    for cid, score in column_scores:
        tname = cid.split(".", 1)[0]
        best_col_per_table[tname] = max(best_col_per_table.get(tname, 0.0), score)

    fused_scores: Dict[str, float] = {}
    tscore_map = {t: s for t, s in table_scores}
    for t in table_ids:
        s_sem_tab = tscore_map.get(t, 0.0)
        s_sem_col = best_col_per_table.get(t, 0.0)
        fused = max(1.0 * s_sem_tab, 0.9 * s_sem_col)
        # lexical/alias light bonus: if the question tokens overlap table name tokens
        if set(_safe_lower_set(t)) & q_tokens:
            fused += lexical_bonus
        
        # Core table priority boost (avoid derivative tables outranking core ones)
        core_tables = {"node", "virus_details", "threat_ip_static", "threat_domain_static", 
                      "threat_file_static", "weak_password_app_detail", "weak_password_node_detail", 
                      "ai_asset_vul", "node_process", "node_listen_info", "node_exposure_port"}
        if t in core_tables:
            # Check if question mentions core concepts that should use this table
            core_keywords = {
                "node": ["终端", "主机", "设备", "机器", "台", "部署"],
                "virus_details": ["病毒", "染毒", "感染", "木马", "恶意"],
                "node_process": ["进程", "软件", "apache", "tomcat", "服务"],
                "node_listen_info": ["端口", "监听", "22", "3389", "ssh", "rdp"],
                "node_exposure_port": ["暴露", "外网", "互联网"],
                "weak_password_node_detail": ["弱口令", "弱密码", "账号"],
            }
            table_keywords = core_keywords.get(t, [])
            if any(kw.lower() in question.lower() for kw in table_keywords):
                fused += 0.15  # 核心表相关性加分
        
        # table-level alias bonus from KB
        entry = kb_map.get(t, {})
        for alias in (entry.get("aliases") or []):
            if str(alias).lower() in q_tokens:
                fused += lexical_bonus * 1.5  # 表级别别名加分更高
                break
        
        # value bonus if any column in this table hit values
        if any(cid.startswith(t + ".") for cid in value_hit_cols):
            fused += value_bonus
            
        # alias bonus if any column in this table hit aliases
        if any(cid.startswith(t + ".") for cid in alias_hit_cols):
            fused += value_bonus * 0.8  # 别名匹配略低于值匹配
        fused_scores[t] = fused

    ranked_tables = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[: max(1, top_tables)]

    # Select top columns per table (by column_scores)
    col_score_map: Dict[str, float] = {cid: s for cid, s in column_scores}
    selected_columns_by_table: Dict[str, List[str]] = {}
    for t, _ in ranked_tables:
        cands = [(cid.split(".", 1)[1], col_score_map[cid]) for cid in col_score_map.keys() if cid.startswith(t + ".")]
        cands.sort(key=lambda x: x[1], reverse=True)
        selected_columns_by_table[t] = [c for c, _ in cands[: max(1, top_cols // max(1, len(ranked_tables)) + 1)]]

    return ranked_tables, selected_columns_by_table


def semantic_suggest(
    question: str,
    m_schema_path: str = os.path.join("outputs", "m_schema.json"),
    kb_catalog_path: str = os.path.join("outputs", "kb", "kb_catalog.json"),
    model_name: str = "moka-ai/m3e-base",
    top_tables: int = 6,
    top_cols: int = 24,
) -> Tuple[List[Tuple[str, float]], Dict[str, List[str]]]:
    m_schema = _load_schema(m_schema_path)
    kb_catalog = _load_kb_catalog(kb_catalog_path)
    return suggest_by_semantics(
        question,
        m_schema=m_schema,
        kb_catalog=kb_catalog,
        model_name=model_name,
        top_tables=top_tables,
        top_cols=top_cols,
    )


# ------------------------
# 离线索引（FAISS 持久化）与缓存
# ------------------------

def _safe_write_json(path: str, obj: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def build_semantic_indices(
    index_dir: str = os.path.join("outputs", "semantic_index"),
    m_schema_path: str = os.path.join("outputs", "m_schema.json"),
    kb_catalog_path: str = os.path.join("outputs", "kb", "kb_catalog.json"),
    model_name: str = "moka-ai/m3e-base",
    hnsw_m: int = 32,
    ef_construction: int = 80,
) -> Dict[str, Any]:
    """构建并持久化 FAISS 索引（表/列两套），写入 ids 与 meta。"""
    try:
        import faiss  # type: ignore
    except Exception as e:
        raise RuntimeError("未安装 faiss-cpu，无法构建离线索引") from e

    m_schema = _load_schema(m_schema_path)
    kb_catalog = _load_kb_catalog(kb_catalog_path)

    table_ids, table_docs = _build_table_docs(m_schema, kb_catalog)
    col_ids, col_docs = _build_column_docs(m_schema, kb_catalog)

    model = _maybe_load_st_model(model_name)
    if model is None:
        raise RuntimeError("sentence-transformers 加载失败，无法构建索引")

    tbl_emb = _encode_texts(model, table_docs)
    col_emb = _encode_texts(model, col_docs)
    if tbl_emb is None or col_emb is None:
        raise RuntimeError("嵌入计算失败，无法构建索引")

    dim = len(tbl_emb[0]) if tbl_emb else (len(col_emb[0]) if col_emb else 0)
    if dim <= 0:
        raise RuntimeError("嵌入维度异常")

    os.makedirs(index_dir, exist_ok=True)
    # HNSW 索引
    tbl_index = faiss.IndexHNSWFlat(dim, hnsw_m)
    tbl_index.hnsw.efConstruction = ef_construction
    col_index = faiss.IndexHNSWFlat(dim, hnsw_m)
    col_index.hnsw.efConstruction = ef_construction

    import numpy as np  # type: ignore
    tbl_mat = np.asarray(tbl_emb, dtype="float32")
    col_mat = np.asarray(col_emb, dtype="float32")
    tbl_index.add(tbl_mat)
    col_index.add(col_mat)

    # 写入磁盘
    import faiss  # ensure imported
    faiss.write_index(tbl_index, os.path.join(index_dir, "tables.hnsw"))
    faiss.write_index(col_index, os.path.join(index_dir, "columns.hnsw"))
    _safe_write_json(os.path.join(index_dir, "tables.ids.json"), table_ids)
    _safe_write_json(os.path.join(index_dir, "columns.ids.json"), col_ids)
    _safe_write_json(
        os.path.join(index_dir, "meta.json"),
        {"model": model_name, "dim": dim, "num_tables": len(table_ids), "num_columns": len(col_ids)},
    )
    return {"index_dir": index_dir, "model": model_name, "dim": dim, "tables": len(table_ids), "columns": len(col_ids)}


def semantic_suggest_with_index(
    question: str,
    index_dir: str = os.path.join("outputs", "semantic_index"),
    model_name: str = "moka-ai/m3e-base",
    top_tables: int = 6,
    top_cols: int = 24,
) -> Optional[Tuple[List[Tuple[str, float]], Dict[str, List[str]]]]:
    """使用已构建的 FAISS 索引进行检索；若索引或模型不可用返回 None。"""
    try:
        import faiss  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None

    tbl_idx_path = os.path.join(index_dir, "tables.hnsw")
    col_idx_path = os.path.join(index_dir, "columns.hnsw")
    tbl_ids_path = os.path.join(index_dir, "tables.ids.json")
    col_ids_path = os.path.join(index_dir, "columns.ids.json")
    meta_path = os.path.join(index_dir, "meta.json")
    if not (os.path.exists(tbl_idx_path) and os.path.exists(col_idx_path) and os.path.exists(tbl_ids_path) and os.path.exists(col_ids_path) and os.path.exists(meta_path)):
        return None

    meta = json.load(open(meta_path, "r", encoding="utf-8"))
    if meta.get("model") != model_name:
        # 模型不一致，避免维度不匹配
        return None

    tbl_index = faiss.read_index(tbl_idx_path)
    col_index = faiss.read_index(col_idx_path)
    table_ids: List[str] = json.load(open(tbl_ids_path, "r", encoding="utf-8"))
    col_ids: List[str] = json.load(open(col_ids_path, "r", encoding="utf-8"))

    model = _maybe_load_st_model(model_name)
    if model is None:
        return None
    q_vec = _encode_texts(model, [question])
    if q_vec is None:
        return None
    q = np.asarray(q_vec, dtype="float32")
    Dt, It = tbl_index.search(q, top_tables)
    Dc, Ic = col_index.search(q, top_cols)

    tbl_cands = [(table_ids[i], float(Dt[0][k])) for k, i in enumerate(It[0]) if 0 <= i < len(table_ids)]
    col_cands = [(col_ids[i], float(Dc[0][k])) for k, i in enumerate(Ic[0]) if 0 <= i < len(col_ids)]

    # 应用与内存语义检索相同的知识库加权逻辑
    try:
        # 加载 KB catalog (FAISS检索时也需要应用知识库加权)
        kb_catalog_path = os.path.join("outputs", "kb", "kb_catalog.json")
        kb_catalog = _load_kb_catalog(kb_catalog_path) if os.path.exists(kb_catalog_path) else {}
        
        # 应用相同的 value/alias bonus 逻辑
        kb_map = {t.get("name"): t for t in (kb_catalog.get("tables", []) if kb_catalog else [])}
        q_tokens = set(_safe_lower_set(question))
        value_hit_cols: set = set()
        alias_hit_cols: set = set()
        
        for cid, _ in col_cands:
            tname, cname = cid.split(".", 1)
            entry = kb_map.get(tname) or {}
            
            # 检查新格式的列信息
            kb_columns = {c.get("name"): c for c in (entry.get("columns") or [])}
            kb_col = kb_columns.get(cname, {})
            
            # 检查别名匹配
            for alias in (kb_col.get("aliases") or []):
                if str(alias).lower() in q_tokens:
                    alias_hit_cols.add(cid)
                    break
            
            # 检查值匹配（新格式）
            for val in (kb_col.get("top_values") or [])[:10]:
                if str(val).lower() in q_tokens:
                    value_hit_cols.add(cid)
                    break
            
            # 检查值匹配（旧格式，向后兼容）
            if cid not in value_hit_cols:
                topn = entry.get("topn_columns", {}).get(cname) or []
                for item in topn[:10]:
                    val = str(item[0]).lower() if isinstance(item, (list, tuple)) and item else str(item).lower()
                    if val and val in q_tokens:
                        value_hit_cols.add(cid)
                        break
    except Exception:
        kb_map = {}
        q_tokens = set()
        value_hit_cols = set()
        alias_hit_cols = set()

    # 融合为 (ranked_tables, selected_columns_by_table) - 应用相同的加权逻辑
    table_scores: Dict[str, float] = {}
    best_col_per_table: Dict[str, float] = {}
    for t, s in tbl_cands:
        table_scores[t] = max(table_scores.get(t, 0.0), s)
    for cid, s in col_cands:
        t = cid.split(".", 1)[0]
        best_col_per_table[t] = max(best_col_per_table.get(t, 0.0), s)

    # 应用增强的融合逻辑（与内存语义检索一致）
    fused_scores: Dict[str, float] = {}
    all_table_names = set(list(table_scores.keys()) + list(best_col_per_table.keys()))
    
    for t in all_table_names:
        s_sem_tab = table_scores.get(t, 0.0)
        s_sem_col = best_col_per_table.get(t, 0.0)
        fused = max(1.0 * s_sem_tab, 0.9 * s_sem_col)
        
        # lexical/alias light bonus: if the question tokens overlap table name tokens
        if set(_safe_lower_set(t)) & q_tokens:
            fused += 0.1  # lexical_bonus
        
        # Core table priority boost (同内存检索逻辑)
        core_tables = {"node", "virus_details", "threat_ip_static", "threat_domain_static", 
                      "threat_file_static", "weak_password_app_detail", "weak_password_node_detail", 
                      "ai_asset_vul", "node_process", "node_listen_info", "node_exposure_port"}
        if t in core_tables:
            # Check if question mentions core concepts that should use this table
            core_keywords = {
                "node": ["终端", "主机", "设备", "机器", "台", "部署"],
                "virus_details": ["病毒", "染毒", "感染", "木马", "恶意"],
                "node_process": ["进程", "软件", "apache", "tomcat", "服务"],
                "node_listen_info": ["端口", "监听", "22", "3389", "ssh", "rdp"],
                "node_exposure_port": ["暴露", "外网", "互联网"],
                "weak_password_node_detail": ["弱口令", "弱密码", "账号"],
            }
            table_keywords = core_keywords.get(t, [])
            if any(kw.lower() in question.lower() for kw in table_keywords):
                fused += 0.15  # 核心表相关性加分
        
        # table-level alias bonus from KB
        entry = kb_map.get(t, {})
        for alias in (entry.get("aliases") or []):
            if str(alias).lower() in q_tokens:
                fused += 0.1 * 1.5  # 表级别别名加分更高
                break
        
        # value bonus if any column in this table hit values
        if any(cid.startswith(t + ".") for cid in value_hit_cols):
            fused += 0.2  # value_bonus
            
        # alias bonus if any column in this table hit aliases
        if any(cid.startswith(t + ".") for cid in alias_hit_cols):
            fused += 0.2 * 0.8  # 别名匹配略低于值匹配
            
        fused_scores[t] = fused

    ranked_tables = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[: max(1, top_tables)]

    col_score_map: Dict[str, float] = {cid: s for cid, s in col_cands}
    selected_columns_by_table: Dict[str, List[str]] = {}
    for t, _ in ranked_tables:
        cands = [(cid.split(".", 1)[1], col_score_map[cid]) for cid in col_score_map.keys() if cid.startswith(t + ".")]
        cands.sort(key=lambda x: x[1], reverse=True)
        per_t = max(1, top_cols // max(1, len(ranked_tables)) + 1)
        selected_columns_by_table[t] = [c for c, _ in cands[: per_t]]

    return ranked_tables, selected_columns_by_table



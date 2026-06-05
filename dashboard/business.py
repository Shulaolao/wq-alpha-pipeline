#!/usr/bin/env python3
"""
WQ Dashboard - 业务逻辑层
=========================
从 server.py 提取的核心业务逻辑: 字段提取、时长计算、状态构建、正交性分析。
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Use absolute imports for direct execution, relative for module mode
try:
    import data_access as da
except ImportError:
    from . import data_access as da


# ─── 字段提取 ──────────────────────────────────────────────────────

SKIP_FIELDS = frozenset({
    'rank','ts_mean','ts_delta','ts_av_diff','ts_min','ts_max',
    'ts_sum','ts_std','ts_rank','ts_argmax','ts_argmin','ts_corr',
    'ts_covariance','ts_zscore','ts_decay_linear',
    'group_rank','scale','neutralize','abs','signed_power',
    'log','sqrt','min','max','sum','mean','std','covariance',
    'correlation','sign','clip','winsorize','ind_neutral',
    'subindustry','sector','industry','group','product',
})


def extract_fields(expr: str) -> List[str]:
    """从 WQ alpha 表达式中提取数据字段名。"""
    fields = set()
    for tok in re.findall(r'[a-z_]\w+', expr or ''):
        if tok not in SKIP_FIELDS:
            fields.add(tok)
    return sorted(fields)


# ─── 时长计算 ──────────────────────────────────────────────────────

def compute_duration(started_at: Optional[str]) -> Optional[str]:
    """计算从 started_at 到现在的持续时长。"""
    if not started_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        now = datetime.now(timezone.utc) if start.tzinfo else datetime.now()
        elapsed = (now - start).total_seconds()
        h, r = divmod(int(elapsed), 3600)
        m, s = divmod(r, 60)
        if h > 0:
            return f"{h}h{m}m"
        return f"{m}m{s}s"
    except Exception:
        return None


# ─── 进度提取 ──────────────────────────────────────────────────────

_SIM_PCT_RE = re.compile(r'(\d+)%')


def extract_sim_progress(log_entries: List[Dict[str, str]]) -> Optional[float]:
    """从日志条目中提取仿真进度 (0-1)。"""
    for entry in reversed(log_entries):
        raw = entry.get("raw", "")
        m = _SIM_PCT_RE.search(raw)
        if m and ("IS" in raw or "Quick" in raw or "Tune IS" in raw):
            pct = int(m.group(1))
            if 0 < pct < 100:
                return pct / 100.0
    return None


# ─── 状态数据构建 ─────────────────────────────────────────────────

# In-memory cache (same semantics as original)
_status_cache: Dict[str, Any] = {"data": None, "ts": 0}
_CACHE_TTL = 2  # seconds


def _get_status_data() -> Dict[str, Any]:
    """
    构建完整的状态数据字典。
    包含: status, phase, counts, batch info, cumulative stats, field_chart, log, actives, errors.
    带 2 秒内存缓存。
    """
    import time
    now = time.time()
    if _status_cache["data"] and (now - _status_cache["ts"]) < _CACHE_TTL:
        return dict(_status_cache["data"])  # shallow copy — caller may mutate

    # 1. Load state
    full_state = da.load_workflow_state("workflow")
    batch_state = da.load_batch_state()
    cumulative = da.get_cumulative_stats()

    # 2. Read logs
    log_entries = da.read_lines_safe(da.LOG_FILE, 100)

    # 3. Field chart
    fields_used = full_state.get("fields_used", {})
    max_count = max(fields_used.values()) if fields_used else 1
    field_chart = [
        {"field": k, "count": v, "pct": round(v / max_count * 100, 1)}
        for k, v in sorted(fields_used.items(), key=lambda x: -x[1])
    ] if fields_used else []

    # 4. Current batch candidate
    batch = full_state.get("current_batch", [])
    batch_idx = full_state.get("batch_idx", 0)
    current = dict(batch[batch_idx]) if batch and batch_idx < len(batch) else None

    # 5. Sim progress
    sim_progress = extract_sim_progress(log_entries)
    if current:
        current["sim_progress"] = sim_progress

    # 6. Duration
    started_at = full_state.get("started_at", "")
    duration = compute_duration(started_at)

    # 7. Last activity
    last_activity = None
    if log_entries:
        last_raw = log_entries[-1].get("raw", "")
        last_activity = last_raw[-120:] if len(last_raw) > 120 else last_raw

    # 8. Assemble
    data = {
        "status": full_state.get("status", "idle"),
        "phase": full_state.get("phase", "init"),
        "active_count": full_state.get("active_count", 0),
        "target": 20,
        "started_at": started_at,
        "last_updated": full_state.get("last_updated", ""),
        "duration": duration,
        "last_activity": last_activity,
        "current_candidate": current,
        "batch_total": len(batch),
        "batch_index": batch_idx + 1 if batch else 0,
        "batch_id": batch_state.get("batch_id", ""),
        "candidates_generated": full_state.get("candidates_generated", 0),
        "candidates_passed_is": full_state.get("candidates_passed_is", 0),
        "candidates_passed_sc": full_state.get("candidates_passed_sc", 0),
        "candidates_submitted": full_state.get("candidates_submitted", 0),
        "iterations": full_state.get("iterations", 0),
        "cumulative_stats": cumulative,
        "errors": full_state.get("errors", [])[-5:],
        "field_chart": field_chart,
        "log": log_entries,
        "actives": full_state.get("actives_data", []),
    }

    # 9. Override with cumulative stats if more accurate
    if cumulative:
        if cumulative.get("total_generated", 0) > data["candidates_generated"]:
            data["candidates_generated"] = cumulative["total_generated"]
        if cumulative.get("total_is_pass", 0) > data["candidates_passed_is"]:
            data["candidates_passed_is"] = cumulative["total_is_pass"]
        if cumulative.get("total_sc_pass", 0) > data["candidates_passed_sc"]:
            data["candidates_passed_sc"] = cumulative["total_sc_pass"]
        if cumulative.get("total_submitted", 0) > data["candidates_submitted"]:
            data["candidates_submitted"] = cumulative["total_submitted"]

    # 10. Expose failure counters
    data["candidates_is_fail"] = cumulative.get("total_is_fail", 0) if cumulative else 0
    data["candidates_sc_fail"] = cumulative.get("total_sc_fail", 0) if cumulative else 0
    data["candidates_failed"] = cumulative.get("total_failed", 0) if cumulative else 0

    _status_cache["data"] = data
    _status_cache["ts"] = now
    return dict(_status_cache["data"])


# ─── 正交性分析 ────────────────────────────────────────────────────

def build_orthogonality_data(actives: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    基于已激活的 Alpha 集合，计算 Jaccard 相似度并构建正交性图。
    返回: {node_count, edge_count, sim_min/max/avg, nodes, edges}
    """
    parsed = []
    for a in actives:
        fields = extract_fields(a.get("expr", ""))
        parsed.append({
            "id": a.get("id", "?"),
            "expr": a.get("expr", ""),
            "fields": fields,
            "field_count": len(fields),
        })

    n = len(parsed)
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            fi = set(parsed[i]["fields"])
            fj = set(parsed[j]["fields"])
            union = fi | fj
            if not union:
                continue
            jaccard = len(fi & fj) / len(union)
            if jaccard > 0:
                edges.append({
                    "source": parsed[i]["id"],
                    "target": parsed[j]["id"],
                    "similarity": round(jaccard, 3),
                    "shared_fields": sorted(fi & fj),
                })

    sims = [e["similarity"] for e in edges]
    return {
        "node_count": n,
        "edge_count": len(edges),
        "sim_min": round(min(sims), 3) if sims else 0,
        "sim_max": round(max(sims), 3) if sims else 0,
        "sim_avg": round(sum(sims) / len(sims), 3) if sims else 0,
        "nodes": parsed,
        "edges": edges,
    }


# ─── 候选批次详情 ─────────────────────────────────────────────────

def build_batch_details(batch: List[Dict[str, Any]], batch_idx: int,
                        batch_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建当前批次详情。
    返回: {batch_id, batch_size, current_index, current_name, phases,
           created_at, updated_at, candidates}
    """
    enriched = []
    for i, c in enumerate(batch):
        fields = extract_fields(c.get("expr", ""))
        entry = {
            "index": i,
            "name": c.get("name", f"candidate_{i}"),
            "expr": c.get("expr", ""),
            "skeleton": c.get("skeleton", ""),
            "weight": c.get("weight", 0),
            "orthogonality_score": c.get("orthogonality_score", 0),
            "fields": fields,
            "field_count": len(fields),
            "is_current": (i == batch_idx),
            "status": c.get("is_status", "PENDING"),
            "alpha_id": c.get("alpha_id"),
            "sim_id": c.get("sim_id"),
            "sharpe": c.get("sharpe"),
            "fitness": c.get("fitness"),
        }
        enriched.append(entry)

    return {
        "batch_id": batch_state.get("batch_id", "unknown"),
        "batch_size": len(batch),
        "current_index": batch_idx,
        "current_name": batch[batch_idx].get("name", "?") if batch and batch_idx < len(batch) else None,
        "phases": batch_state.get("phases", {}),
        "created_at": batch_state.get("created_at", ""),
        "updated_at": batch_state.get("updated_at", ""),
        "candidates": enriched,
    }


# ─── Active Alpha 详情 ────────────────────────────────────────────

def build_actives_summary(actives: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    构建已激活 Alpha 的摘要。
    返回: {total, target, remaining, pct, alphas}
    """
    enriched = []
    for a in actives:
        fields = extract_fields(a.get("expr", ""))
        enriched.append({
            "id": a.get("id", "?"),
            "expr": a.get("expr", ""),
            "fields": fields,
            "field_count": len(fields),
        })

    total = len(enriched)
    target = 20
    return {
        "total": total,
        "target": target,
        "remaining": max(0, target - total),
        "pct": round(total / target * 100, 1) if total else 0,
        "alphas": enriched,
    }


# ─── 完整轮询数据 ─────────────────────────────────────────────────

def build_poll_data(status_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    在 status_data 基础上附加 history 和 orthogonality，
    供 /api/poll 单接口使用。
    """
    import wq_db
    # History
    try:
        hist = wq_db.get_all_alpha_history(limit=50)
        status_data["history"] = [dict(r) for r in hist.get("events", [])]
        status_data["history_total"] = hist.get("total", 0)
    except Exception:
        status_data["history"] = []
        status_data["history_total"] = 0

    # Orthogonality
    o = da.load_orthogonality_state()
    status_data["orthogonality"] = o if o.get("nodes") else {
        "nodes": [], "edges": [], "node_count": 0, "edge_count": 0
    }
    return status_data

#!/usr/bin/env python3
"""
WQ Dashboard Server v2 — Full Data API
Reads ~/.wq_workflow_v2.json, ~/.wq_workflow_v2.log, ~/.wq_batch_state.json
Exposes all pipeline data: active alphas, batch details, orthogonality, history
"""
import json, os, re, time
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, jsonify, request

app = Flask(__name__)

# ─── CORS: allow frontend on any port ──────────────────────────────────
@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    if origin and ("localhost" in origin or "127.0.0.1" in origin or "ngrok-free.app" in origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response

HOME = Path.home()
STATE_FILE = HOME / ".wq_workflow_v2.json"
LOG_FILE = HOME / ".wq_workflow_v2.log"
BATCH_FILE = HOME / ".wq_batch_state.json"
STDERR_FILE = HOME / ".wq_workflow_v2_stderr.log"

# ─── Helpers ───────────────────────────────────────────────────────────

def read_json_safe(path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except: pass
    return {}

def read_lines_safe(path, n=100):
    try:
        if not path.exists():
            return []
        text = path.read_text()
        lines = text.strip().split("\n")
        parsed = []
        for line in lines[-n:]:
            entry = {"raw": line}
            m = re.match(r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\|(\w+)\|(.+)", line)
            if m:
                entry["time"] = m.group(1)
                entry["level"] = m.group(2)
                entry["msg"] = m.group(3)
            else:
                entry["level"] = "INFO"
                entry["msg"] = line
            parsed.append(entry)
        return parsed
    except:
        return []

def extract_fields(expr):
    """Extract data fields from a WQ alpha expression."""
    SKIP = frozenset({
        'rank','ts_mean','ts_delta','ts_av_diff','ts_min','ts_max',
        'ts_sum','ts_std','ts_rank','ts_argmax','ts_argmin','ts_argmax',
        'ts_argmin','ts_corr','ts_covariance','ts_zscore','ts_decay_linear',
        'group_rank','scale','neutralize','abs','signed_power',
        'log','sqrt','min','max','sum','mean','std','covariance',
        'correlation','sign','clip','winsorize','ind_neutral',
        'subindustry','sector','industry','group','product',
    })
    fields = set()
    for tok in re.findall(r'[a-z_]\w+', expr or ''):
        if tok not in SKIP:
            fields.add(tok)
    return sorted(fields)

def parse_log_timestamp(ts_str):
    try:
        dt = datetime.strptime(ts_str.strip(), "%m-%d %H:%M:%S")
        dt = dt.replace(year=datetime.now().year)
        return dt.isoformat()
    except ValueError:
        return ts_str

def compute_duration(started_at):
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
    except:
        return None

# ─── Main Status ───────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    state = read_json_safe(STATE_FILE)
    batch_state = read_json_safe(BATCH_FILE)
    log_entries = read_lines_safe(LOG_FILE, 100)

    # ── Field usage ──
    fields_used = state.get("fields_used", {})
    total_fields = max(len(fields_used), 1)
    max_count = max(fields_used.values()) if fields_used else 1
    field_chart = [
        {"field": k, "count": v, "pct": round(v / max_count * 100, 1)}
        for k, v in sorted(fields_used.items(), key=lambda x: -x[1])
    ] if fields_used else []

    # ── Current batch info ──
    batch = state.get("current_batch", [])
    batch_idx = state.get("batch_idx", 0)
    current = batch[batch_idx] if batch and batch_idx < len(batch) else None

    # ── SIM progress from log ──
    sim_progress = None
    for entry in reversed(log_entries):
        raw = entry.get("raw", "")
        m = re.search(r"(\d+)%", raw)
        if m and ("IS" in raw or "Quick" in raw or "Tune IS" in raw):
            pct = int(m.group(1))
            if 0 < pct < 100:
                sim_progress = pct / 100.0
                break
    if current:
        current["sim_progress"] = sim_progress

    # ── Session timing ──
    started_at = state.get("started_at", "")
    duration = compute_duration(started_at)

    # ── Last activity from latest log entry ──
    last_activity = None
    if log_entries:
        last_raw = log_entries[-1].get("raw", "")
        last_activity = last_raw[-120:] if len(last_raw) > 120 else last_raw

    return jsonify({
        # Pipeline basics
        "status": state.get("status", "idle"),
        "phase": state.get("phase", "init"),
        "active_count": state.get("active_count", 0),
        "target": 20,

        # Timing
        "started_at": started_at,
        "last_updated": state.get("last_updated", ""),
        "duration": duration,
        "last_activity": last_activity,

        # Current candidate
        "current_candidate": current,

        # Batch progress
        "batch_total": len(batch),
        "batch_index": batch_idx + 1 if batch else 0,
        "batch_id": batch_state.get("batch_id", ""),

        # Run totals
        "candidates_generated": state.get("candidates_generated", 0),
        "candidates_passed_is": state.get("candidates_passed_is", 0),
        "candidates_passed_sc": state.get("candidates_passed_sc", 0),
        "candidates_submitted": state.get("candidates_submitted", 0),
        "iterations": state.get("iterations", 0),

        # Errors
        "errors": state.get("errors", [])[-5:],

        # Charts & logs
        "field_chart": field_chart,
        "log": log_entries,

        # Full actives (all, not just 5)
        "actives": state.get("actives_data", []),
    })

# ─── All Active Alphas with Details ────────────────────────────────────

@app.route("/api/actives")
def api_actives():
    state = read_json_safe(STATE_FILE)
    actives = state.get("actives_data", [])

    enriched = []
    for a in actives:
        fields = extract_fields(a.get("expr", ""))
        enriched.append({
            "id": a.get("id", "?"),
            "expr": a.get("expr", ""),
            "fields": fields,
            "field_count": len(fields),
        })

    return jsonify({
        "total": len(enriched),
        "target": 20,
        "remaining": max(0, 20 - len(enriched)),
        "pct": round(len(enriched) / 20 * 100, 1) if enriched else 0,
        "alphas": enriched,
    })

# ─── Current Batch Details ─────────────────────────────────────────────

@app.route("/api/batch")
def api_batch():
    state = read_json_safe(STATE_FILE)
    batch_state = read_json_safe(BATCH_FILE)

    batch = state.get("current_batch", [])
    batch_idx = state.get("batch_idx", 0)

    # Enrich each candidate with field analysis
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
            "alpha_id": c.get("alpha_id", None),
            "sim_id": c.get("sim_id", None),
            "sharpe": c.get("sharpe"),
            "fitness": c.get("fitness"),
        }
        enriched.append(entry)

    # Phase progress from batch_state
    phases = batch_state.get("phases", {})

    return jsonify({
        "batch_id": batch_state.get("batch_id", "unknown"),
        "batch_size": len(batch),
        "current_index": batch_idx,
        "current_name": batch[batch_idx].get("name", "?") if batch and batch_idx < len(batch) else None,
        "phases": phases,
        "created_at": batch_state.get("created_at", ""),
        "updated_at": batch_state.get("updated_at", ""),
        "candidates": enriched,
    })

# ─── Orthogonality Graph ──────────────────────────────────────────────

@app.route("/api/orthogonality")
def api_orthogonality():
    state = read_json_safe(STATE_FILE)
    actives = state.get("actives_data", [])

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

    # Stats
    sims = [e["similarity"] for e in edges]
    return jsonify({
        "node_count": n,
        "edge_count": len(edges),
        "sim_min": round(min(sims), 3) if sims else 0,
        "sim_max": round(max(sims), 3) if sims else 0,
        "sim_avg": round(sum(sims) / len(sims), 3) if sims else 0,
        "nodes": parsed,
        "edges": edges,
    })

# ─── History ───────────────────────────────────────────────────────────

@app.route("/api/history")
def api_history():
    log_text = ""
    try:
        if LOG_FILE.exists():
            log_text = LOG_FILE.read_text()
    except:
        pass

    history = []
    patterns = [
        (r"IS Done.*?([\d.]+).*?([\d.]+)", "is_done", lambda m: {"sharpe": float(m.group(1)), "fitness": float(m.group(2))}),
        (r"SC Done.*?([\d.]+)", "sc_done", lambda m: {"sc_value": float(m.group(1))}),
        (r"SC.*?([\d.]+).*?PASS", "sc_pass", lambda m: {"sc_value": float(m.group(1))}),
        (r"SC.*?([\d.]+).*?FAIL", "sc_fail", lambda m: {"sc_value": float(m.group(1))}),
        (r"Submitted.*?(\d+)", "submitted", lambda m: {"count": int(m.group(1))}),
        (r"Generated.*?(\d+)", "generated", lambda m: {"count": int(m.group(1))}),
        (r"Phase.*?complete", "phase_complete", lambda m: {}),
        (r"候选失败", "candidate_fail", lambda m: {}),
        (r"✅.*resolved", "sim_resolved", lambda m: {}),
        (r"IS failed", "is_fail", lambda m: {}),
        (r"IS passed", "is_pass", lambda m: {}),
    ]

    for line in log_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = re.match(r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\|(\w+)\|(.+)", line)
        if not match:
            continue
        ts_str, level, message = match.groups()
        iso_ts = parse_log_timestamp(ts_str)

        for pattern, etype, extractor in patterns:
            m = re.search(pattern, message, re.IGNORECASE)
            if m:
                details = extractor(m)
                history.append({
                    "timestamp": iso_ts,
                    "level": level,
                    "event": etype,
                    "details": details,
                    "raw": message[:150],
                })
                break

    return jsonify({
        "total": len(history),
        "events": history,
    })

# ─── Log ───────────────────────────────────────────────────────────────

@app.route("/api/log")
def api_log():
    n = request.args.get("lines", 100, type=int)
    return jsonify({
        "total": -1,  # unknown
        "returned": min(n, 500),
        "entries": read_lines_safe(LOG_FILE, min(n, 500)),
    })

# ─── Serve Legacy HTML (keep for compat) ───────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "name": "wq-alpha-pipeline",
        "api": "/api/status",
        "frontend": "http://localhost:8766",
        "docs": "https://github.com/Shulaolao/wq-alpha-pipeline",
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8767))
    print(f"🚀 WQ Dashboard v2 starting on http://0.0.0.0:{port}")
    print(f"   State: {STATE_FILE}")
    print(f"   Batch: {BATCH_FILE}")
    print(f"   Log:   {LOG_FILE}")
    app.run(host="0.0.0.0", port=port, debug=False)

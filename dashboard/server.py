#!/usr/bin/env python3
"""
WQ Dashboard Server v3 — SQLite-backed
========================================
优先读 SQLite 数据库，兼容旧 JSON 文件。
Exposes all pipeline data: active alphas, batch details, orthogonality, history, cumulative stats
"""
import json, os, re, time, sys
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, jsonify, request

# Add scripts dir for wq_db import
_SCRIPT_DIR = Path(os.environ.get("WQ_SCRIPTS_DIR", Path.home() / ".hermes" / "scripts"))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import wq_db

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
STATE_FILE = HOME / ".wq_workflow_v2.json"  # fallback
LOG_FILE = HOME / ".wq_workflow_v2.log"

# ─── In-memory cache ─────────────────────────────────────────────────────
_status_cache = {"data": None, "ts": 0}
CACHE_TTL = 2  # seconds — data rarely changes this frequently
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
    """Read last n lines efficiently — uses tail(1) to avoid loading the whole file."""
    import subprocess
    try:
        if not path.exists():
            return []
        out = subprocess.check_output(["tail", "-n", str(n), str(path)], timeout=1)
        text = out.decode("utf-8", errors="replace")
        lines = text.strip().split("\n")
    except Exception:
        try:
            if path.exists():
                text = path.read_text()
                lines = text.strip().split("\n")
            else:
                return []
        except:
            return []
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

def extract_fields(expr):
    """Extract data fields from a WQ alpha expression."""
    SKIP = frozenset({
        'rank','ts_mean','ts_delta','ts_av_diff','ts_min','ts_max',
        'ts_sum','ts_std','ts_rank','ts_argmax','ts_argmin','ts_corr',
        'ts_covariance','ts_zscore','ts_decay_linear',
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
    """Full pipeline status (kept for backward compat, /api/poll is preferred)."""
    return jsonify(_get_status_data())


def _get_status_data():
    """Shared helper: return the full status dict used by /api/status and /api/poll."""
    global _status_cache
    now = time.time()
    if _status_cache["data"] and (now - _status_cache["ts"]) < CACHE_TTL:
        return dict(_status_cache["data"])  # shallow copy — caller may mutate

    full_state = wq_db.load_workflow_state("workflow")
    if not full_state:
        full_state = read_json_safe(STATE_FILE)
    batch_state = read_json_safe(BATCH_FILE)
    log_entries = read_lines_safe(LOG_FILE, 100)
    cumulative = wq_db.get_cumulative_stats()

    fields_used = full_state.get("fields_used", {})
    max_count = max(fields_used.values()) if fields_used else 1
    field_chart = [
        {"field": k, "count": v, "pct": round(v / max_count * 100, 1)}
        for k, v in sorted(fields_used.items(), key=lambda x: -x[1])
    ] if fields_used else []

    batch = full_state.get("current_batch", [])
    batch_idx = full_state.get("batch_idx", 0)
    current = batch[batch_idx] if batch and batch_idx < len(batch) else None

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

    started_at = full_state.get("started_at", "")
    duration = compute_duration(started_at)

    last_activity = None
    if log_entries:
        last_raw = log_entries[-1].get("raw", "")
        last_activity = last_raw[-120:] if len(last_raw) > 120 else last_raw

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
    # If cumulative_stats is more accurate (pipeline updates it via record_alpha_event),
    # override the workflow_state counters with cumulative values
    if cumulative:
        if cumulative.get("total_generated", 0) > data["candidates_generated"]:
            data["candidates_generated"] = cumulative["total_generated"]
        if cumulative.get("total_is_pass", 0) > data["candidates_passed_is"]:
            data["candidates_passed_is"] = cumulative["total_is_pass"]
        if cumulative.get("total_sc_pass", 0) > data["candidates_passed_sc"]:
            data["candidates_passed_sc"] = cumulative["total_sc_pass"]
        if cumulative.get("total_submitted", 0) > data["candidates_submitted"]:
            data["candidates_submitted"] = cumulative["total_submitted"]
    _status_cache["data"] = data
    _status_cache["ts"] = now
    return dict(_status_cache["data"])


@app.route("/api/poll")
def api_poll():
    """Single endpoint returning all dashboard data in one request."""
    data = _get_status_data()
    # Add recent history (last 10 events) and orthogonality
    hist = wq_db.get_all_alpha_history(limit=50)
    data["history"] = [dict(r) for r in hist.get("events", [])]
    data["history_total"] = hist.get("total", 0)
    o = wq_db.load_workflow_state("orthogonality")
    if not o:
        o = read_json_safe(HOME / ".wq_orthogonality.json")
    data["orthogonality"] = o if o.get("nodes") else {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0}
    return jsonify(data)

# ─── All Active Alphas with Details ────────────────────────────────────

@app.route("/api/actives")
def api_actives():
    full_state = wq_db.load_workflow_state("workflow")
    if not full_state:
        full_state = read_json_safe(STATE_FILE)
    actives = full_state.get("actives_data", [])

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
    full_state = wq_db.load_workflow_state("workflow")
    if not full_state:
        full_state = read_json_safe(STATE_FILE)
    batch_state = read_json_safe(BATCH_FILE)

    batch = full_state.get("current_batch", [])
    batch_idx = full_state.get("batch_idx", 0)

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
    full_state = wq_db.load_workflow_state("workflow")
    if not full_state:
        full_state = read_json_safe(STATE_FILE)
    actives = full_state.get("actives_data", [])

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

# ─── History (from SQLite) ───────────────────────────────────────────

@app.route("/api/history")
def api_history():
    # Primary: read from SQLite
    try:
        result = wq_db.get_all_alpha_history(limit=200)
        if result["total"] > 0:
            return jsonify(result)
    except Exception as e:
        print(f"SQLite history error: {e}", flush=True)
    
    # Fallback: parse log file (legacy)
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
        
        def parse_ts(ts):
            try:
                dt = datetime.strptime(ts.strip(), "%m-%d %H:%M:%S")
                dt = dt.replace(year=datetime.now().year)
                return dt.isoformat()
            except ValueError:
                return ts
        iso_ts = parse_ts(ts_str)

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

# ─── Alpha Events Timeline (new endpoint) ────────────────────────────

@app.route("/api/events")
def api_events():
    """Get alpha lifecycle events from SQLite."""
    limit = request.args.get("limit", 100, type=int)
    try:
        events = wq_db.get_recent_alpha_events(limit=limit)
        return jsonify({
            "total": limit,
            "events": events,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── Cumulative Stats Endpoint ───────────────────────────────────────

@app.route("/api/cumulative")
def api_cumulative():
    """Get cumulative counters from SQLite."""
    try:
        stats = wq_db.get_cumulative_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── Log (from SQLite, fallback to file) ───────────────────────────────

@app.route("/api/log")
def api_log():
    n = request.args.get("lines", 100, type=int)
    try:
        # Try SQLite first
        log_entries = wq_db.get_workflow_logs(limit=n)
        # Convert to same format as file-based
        formatted = []
        for entry in log_entries:
            formatted.append({
                "time": entry["timestamp"],
                "level": entry["level"],
                "msg": entry["message"],
                "alpha_name": entry.get("alpha_name"),
            })
        return jsonify({
            "total": len(formatted),
            "returned": len(formatted),
            "entries": formatted,
            "source": "sqlite",
        })
    except Exception as e:
        print(f"SQLite log error, falling back to file: {e}", flush=True)
    
    # Fallback: file
    return jsonify({
        "total": -1,
        "returned": min(n, 500),
        "entries": read_lines_safe(LOG_FILE, min(n, 500)),
        "source": "file",
    })

# ─── Error Logs ──────────────────────────────────────────────────────

@app.route("/api/logs/errors")
def api_errors():
    try:
        errors = wq_db.get_error_logs(limit=100)
        return jsonify({
            "total": len(errors),
            "entries": errors,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/logs/warnings")
def api_warnings():
    try:
        warns = wq_db.get_warn_logs(limit=100)
        return jsonify({
            "total": len(warns),
            "entries": warns,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── Alpha History & Submitted ──────────────────────────────────────

@app.route("/api/alphas/history")
def api_alphas_history():
    """Get alpha event history from SQLite."""
    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
        data = wq_db.get_all_alpha_history(limit=limit, offset=offset)
        # Rename "events" key to "alphas" for frontend compat
        return jsonify({
            "total": data["total"],
            "alphas": data["events"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/alphas/submitted")
def api_alphas_submitted():
    """Get all submitted alphas with IS/SC metrics."""
    try:
        alphas = wq_db.get_submitted_alphas()
        return jsonify({
            "total": len(alphas),
            "alphas": alphas,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/improvements")
def api_improvements():
    """Get alpha improvements (IS→SC→optimized records) from SQLite."""
    # Also try JSON log file for meta-optimization records
    IMPROVEMENT_JSON = HOME / ".wq_improvement_log.json"
    improvement_json = read_json_safe(IMPROVEMENT_JSON)
    
    try:
        # Query: alphas where IS pass but SC fail, then later SC pass
        conn = wq_db.get_db()
        try:
            rows = conn.execute(
                """SELECT name, expr, event_type, sharpe, fitness, sc_value, sc_result, created_at
                   FROM alpha_events
                   WHERE event_type IN ('sc_pass', 'sc_fail', 'is_pass', 'optimized')
                   ORDER BY created_at DESC
                   LIMIT 50"""
            ).fetchall()
            improvements = [dict(r) for r in rows]
        finally:
            conn.close()
        
        # If JSON file has meta-optimization records, return them as 'records'
        # SQLite results as 'improvements' for backward compat
        if isinstance(improvement_json, list) and len(improvement_json) > 0:
            # Sort newest first
            sorted_records = sorted(improvement_json, key=lambda r: r.get("timestamp", ""), reverse=True)
            return jsonify({
                "total": len(sorted_records),
                "records": sorted_records,
                "improvements": improvements,
            })
        else:
            return jsonify({
                "total": len(improvements),
                "improvements": improvements,
            })
    except Exception as e:
        # Fallback to JSON file if SQLite fails
        if isinstance(improvement_json, list) and len(improvement_json) > 0:
            sorted_records = sorted(improvement_json, key=lambda r: r.get("timestamp", ""), reverse=True)
            return jsonify({
                "total": len(sorted_records),
                "records": sorted_records,
            })
        return jsonify({"error": str(e)}), 500

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
    print(f"🚀 WQ Dashboard v3 starting on http://0.0.0.0:{port}")
    print(f"   DB:      {wq_db.DB_PATH}")
    print(f"   State:   {STATE_FILE} (fallback)")
    print(f"   Log:     {LOG_FILE}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

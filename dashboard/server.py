#!/usr/bin/env python3
"""
WQ Dashboard Server
Reads ~/.wq_workflow_v2.json and ~/.wq_workflow_v2.log
Serves dark-mode single-page dashboard on port 8765
"""
import json, os, re, time
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)
HOME = Path.home()
STATE_FILE = HOME / ".wq_workflow_v2.json"
LOG_FILE = HOME / ".wq_workflow_v2.log"
STDERR_FILE = HOME / ".wq_workflow_v2_stderr.log"

def read_json_safe(path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except: pass
    return {}

def read_lines_safe(path, n=30):
    try:
        if not path.exists():
            return []
        text = path.read_text()
        lines = text.strip().split("\n")
        # Parse lines with timestamp and level for color-coding
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

def get_active_actives(samples=5):
    """Extract sample expressions from state"""
    state = read_json_safe(STATE_FILE)
    actives = state.get("actives_data", [])
    return actives[:samples]

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/status")
def api_status():
    state = read_json_safe(STATE_FILE)
    log_entries = read_lines_safe(LOG_FILE, 100)
    
    # Compute field usage from state if available
    fields_used = state.get("fields_used", {})
    field_chart = [{"field": k, "count": v} for k, v in sorted(fields_used.items(), key=lambda x: -x[1])] if fields_used else []
    
    # Current batch info
    batch = state.get("current_batch", [])
    batch_idx = state.get("batch_idx", 0)
    current = batch[batch_idx] if batch and batch_idx < len(batch) else None
    
    # SIM progress from log (parse most recent "X%" line)
    sim_progress = None
    for entry in reversed(log_entries):
        m = re.search(r"(\d+)%", entry.get("raw", ""))
        if m and ("IS" in entry.get("raw", "") or "Tune IS" in entry.get("raw", "")):
            pct = int(m.group(1))
            if pct > 0 and pct < 100:
                sim_progress = pct / 100.0
                break
    if current:
        current["sim_progress"] = sim_progress
    
    return jsonify({
        "status": state.get("status", "idle"),
        "phase": state.get("phase", "init"),
        "active_count": state.get("active_count", 0),
        "target": 20,
        "last_updated": state.get("last_updated", ""),
        "started_at": state.get("started_at", ""),
        "current_candidate": current,
        "candidates_generated": state.get("candidates_generated", 0),
        "candidates_passed_is": state.get("candidates_passed_is", 0),
        "candidates_passed_sc": state.get("candidates_passed_sc", 0),
        "candidates_submitted": state.get("candidates_submitted", 0),
        "iterations": state.get("iterations", 0),
        "errors": state.get("errors", [])[-3:],
        "field_chart": field_chart,
        "log": log_entries,
        "actives_sample": get_active_actives(),
    })

@app.route("/api/history")
def api_history():
    """Parse log for historical completion events and return structured records."""
    log_text = ""
    try:
        if LOG_FILE.exists():
            log_text = LOG_FILE.read_text()
    except:
        pass
    history = []
    patterns = [
        (r"IS Done.*?(\d+\.\d+).*?(\d+\.\d+)", "is_done"),
        (r"SC Done.*?(\d+\.\d+)", "sc_done"),
        (r"Submitted.*?(\d+)", "submitted"),
        (r"Generated.*?(\d+)", "generated"),
        (r"Phase.*?complete", "phase_complete"),
    ]
    for line in log_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = re.match(r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\|(\w+)\|(.+)", line)
        if not match:
            continue
        timestamp_str, level, message = match.groups()
        try:
            dt = datetime.strptime(timestamp_str.strip(), "%m-%d %H:%M:%S")
            dt = dt.replace(year=datetime.now().year)
            iso_ts = dt.isoformat()
        except ValueError:
            iso_ts = timestamp_str
        event_type = None
        details = {}
        for pattern, etype in patterns:
            m = re.search(pattern, message, re.IGNORECASE)
            if m:
                event_type = etype
                if etype == "is_done":
                    details["sharpe"] = float(m.group(1))
                    details["fitness"] = float(m.group(2))
                elif etype == "sc_done":
                    details["sc_value"] = float(m.group(1))
                elif etype in ("submitted", "generated"):
                    details["count"] = int(m.group(1))
                break
        if event_type:
            history.append({
                "timestamp": iso_ts,
                "level": level,
                "event": event_type,
                "details": details,
                "raw": message
            })
    return jsonify(history)

@app.route("/api/log")
def api_log():
    n = int(request.args.get("lines", 50)) if request.args.get("lines") else 50
    return jsonify(read_lines_safe(LOG_FILE, min(n, 200)))

# For requests import
from flask import request

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    print(f"🚀 WQ Dashboard starting on http://0.0.0.0:{port}")
    print(f"   State: {STATE_FILE}")
    print(f"   Log:   {LOG_FILE}")
    app.run(host="0.0.0.0", port=port, debug=False)

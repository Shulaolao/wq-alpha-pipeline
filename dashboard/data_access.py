#!/usr/bin/env python3
"""
WQ Dashboard - 数据访问层
=========================
负责所有文件/数据库读取操作, 提供统一的数据访问接口。
"""
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


HOME = Path.home()
STATE_FILE = HOME / ".wq_workflow_v2.json"
BATCH_FILE = HOME / ".wq_batch_state.json"
LOG_FILE = HOME / ".wq_workflow_v2.log"
STDERR_FILE = HOME / ".wq_workflow_v2_stderr.log"
ORTHOGONALITY_FILE = HOME / ".wq_orthogonality.json"


# ─── JSON 文件读取 ────────────────────────────────────────────────

def read_json_safe(path: Path) -> Dict[str, Any]:
    """安全读取 JSON 文件, 失败返回空字典。"""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def load_workflow_state(key: str = "workflow") -> Dict[str, Any]:
    """从 wq_db 或 JSON 文件加载工作流状态。"""
    try:
        import wq_db
        state = wq_db.load_workflow_state(key)
        if state:
            return state
    except Exception:
        pass
    return read_json_safe(STATE_FILE)


def load_batch_state() -> Dict[str, Any]:
    """加载批次状态。"""
    return read_json_safe(BATCH_FILE)


def load_orthogonality_state() -> Dict[str, Any]:
    """加载正交性数据。"""
    o = load_workflow_state("orthogonality")
    if not o:
        o = read_json_safe(ORTHOGONALITY_FILE)
    return o if o.get("nodes") else {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0}


# ─── 日志文件读取 ────────────────────────────────────────────────

def read_lines_safe(path: Path, n: int = 100) -> List[Dict[str, str]]:
    """高效读取日志最后 N 行。使用 tail 命令避免加载整个文件。"""
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
        except Exception:
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


def get_log_lines(n: int = 100, source: str = "auto") -> tuple:
    """
    获取日志条目。
    返回 (entries, source_used)。
    """
    try:
        import wq_db
        log_entries = wq_db.get_workflow_logs(limit=n)
        formatted = []
        for entry in log_entries:
            formatted.append({
                "time": entry["timestamp"],
                "level": entry["level"],
                "msg": entry["message"],
                "alpha_name": entry.get("alpha_name"),
            })
        return formatted, "sqlite"
    except Exception as e:
        print(f"SQLite log error, falling back to file: {e}", flush=True)

    lines = read_lines_safe(LOG_FILE, min(n, 500))
    return lines, "file"


def get_error_lines(limit: int = 100) -> tuple:
    """获取错误日志。"""
    try:
        import wq_db
        errors = wq_db.get_error_logs(limit=limit)
        return errors, "sqlite"
    except Exception as e:
        return {"error": str(e)}, 500


def get_warning_lines(limit: int = 100) -> tuple:
    """获取警告日志。"""
    try:
        import wq_db
        warns = wq_db.get_warn_logs(limit=limit)
        return warns, "sqlite"
    except Exception as e:
        return {"error": str(e)}, 500


# ─── 累计统计 ────────────────────────────────────────────────────

def get_cumulative_stats() -> Optional[Dict[str, Any]]:
    """获取累计统计数据。优先从 wq_db 读取。"""
    try:
        import wq_db
        return wq_db.get_cumulative_stats()
    except Exception:
        return None


# ─── Alpha 事件/历史 ────────────────────────────────────────────

def get_recent_alpha_events(limit: int = 100) -> tuple:
    """获取最近的 Alpha 事件。"""
    try:
        import wq_db
        events = wq_db.get_recent_alpha_events(limit=limit)
        return events, None
    except Exception as e:
        return [], str(e)


def get_alpha_history_flat(limit: int = 200, offset: int = 0) -> tuple:
    """获取 Alpha 历史（扁平格式）。"""
    try:
        import wq_db
        result = wq_db.get_alpha_history_flat(limit=limit, offset=offset)
        return result, None
    except Exception as e:
        return {"total": 0, "events": []}, str(e)


def get_all_alphas_summary(limit: int = 200, offset: int = 0) -> tuple:
    """获取所有 Alpha 的完整生命周期摘要。"""
    try:
        import wq_db
        result = wq_db.get_all_alphas_summary(limit=limit, offset=offset)
        return result, None
    except Exception as e:
        return {"total": 0, "alphas": []}, str(e)


def get_submitted_alphas() -> tuple:
    """获取所有已提交的 Alpha 及其 IS/SC 指标。"""
    try:
        import wq_db
        alphas = wq_db.get_submitted_alphas()
        return alphas, None
    except Exception as e:
        return [], str(e)


# ─── 改进记录 ────────────────────────────────────────────────────

def get_improvements(limit: int = 50) -> tuple:
    """获取自我进化改进记录。"""
    try:
        import wq_db
        improvements_db = wq_db.get_improvements(limit=limit)
        total = wq_db.count_improvements()

        conn = wq_db.get_db()
        try:
            rows = conn.execute(
                """SELECT name, expr, event_type, sharpe, fitness, sc_value, sc_result, created_at
                   FROM alpha_events
                   WHERE event_type IN ('sc_pass', 'sc_fail', 'is_pass', 'optimized')
                   ORDER BY created_at DESC
                   LIMIT 50"""
            ).fetchall()
            alpha_events = [dict(r) for r in rows]
        finally:
            conn.close()

        return {
            "total": total,
            "records": improvements_db,
            "improvements": alpha_events,
        }, None
    except Exception as e:
        return {"error": str(e)}, 500


# ─── 日志解析（用于历史端点） ────────────────────────────────────

LOG_PATTERNS = [
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


def parse_log_text_for_history(log_text: str) -> List[Dict[str, Any]]:
    """从原始日志文本解析历史事件。"""
    from datetime import datetime

    history = []

    for line in log_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = re.match(r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\|(\w+)\|(.+)", line)
        if not match:
            continue

        ts_str, level, message = match.groups()

        try:
            dt = datetime.strptime(ts_str.strip(), "%m-%d %H:%M:%S")
            dt = dt.replace(year=datetime.now().year)
            iso_ts = dt.isoformat()
        except ValueError:
            iso_ts = ts_str

        for pattern, etype, extractor in LOG_PATTERNS:
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

    return history

#!/usr/bin/env python3
"""
WQ 工作流 SQLite 数据库模块
=============================
替代 state.json，持久化存储：
1. alpha_events - 每个 alpha 全生命周期事件（生成/IS pass/SC pass/提交/失败）
2. workflow_state - 工作流运行时状态
3. alpha_cumulative - 累计统计数据（dashboard 优先读取）
"""
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

DB_PATH = Path.home() / ".wq_workflow_v2.db"


def get_db() -> sqlite3.Connection:
    """Get database connection with WAL mode and proper settings."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database schema. Safe to call multiple times (idempotent)."""
    conn = get_db()
    try:
        conn.executescript("""
            -- Workflow runtime state (replaces state.json)
            CREATE TABLE IF NOT EXISTS workflow_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );

            -- Alpha lifecycle events: every candidate generates one row per event
            CREATE TABLE IF NOT EXISTS alpha_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alpha_id TEXT,                    -- WQ alpha ID (if submitted)
                name TEXT NOT NULL,               -- Alpha name
                expr TEXT NOT NULL,               -- Expression code
                event_type TEXT NOT NULL,         -- generated / is_pass / is_fail / sc_pass / sc_fail / submitted / failed / optimized
                sharpe REAL,
                fitness REAL,
                sc_value REAL,
                sc_result TEXT,
                is_status TEXT,                   -- PASS / TUNE / FAIL / TIMEOUT
                phase TEXT,                       -- quick_test / full_sim / sc_submit / submit
                duration_seconds REAL,
                notes TEXT,                       -- Extra context
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Create index for fast queries by name, event_type, event_type
            CREATE INDEX IF NOT EXISTS idx_alpha_events_name ON alpha_events(name);
            CREATE INDEX IF NOT EXISTS idx_alpha_events_type ON alpha_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_alpha_events_created ON alpha_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_alpha_events_alpha_id ON alpha_events(alpha_id);

            -- Alpha cumulative stats (one row per alpha, updated on each event)
            CREATE TABLE IF NOT EXISTS alpha_stats (
                name TEXT PRIMARY KEY,
                expr TEXT NOT NULL,
                alpha_id TEXT,
                sharpe REAL,
                fitness REAL,
                sc_value REAL,
                is_status TEXT,
                sc_result TEXT,
                status TEXT NOT NULL DEFAULT 'generated',  -- generated / is_pass / sc_pass / submitted / failed
                total_attempts INTEGER NOT NULL DEFAULT 1,
                first_generated_at TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                is_duration REAL,
                sc_duration REAL
            );

            -- Global cumulative counters (singleton table)
            CREATE TABLE IF NOT EXISTS cumulative_stats (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0,
                last_updated TEXT NOT NULL
            );

            -- Seed with initial counters
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_generated', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_is_pass', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_is_fail', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_is_tune', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_sc_pass', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_sc_fail', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_sc_timeout', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_submitted', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_failed', 0, datetime('now'));
            INSERT OR IGNORE INTO cumulative_stats (key, value, last_updated)
                VALUES ('total_optimized', 0, datetime('now'));

            -- Workflow log entries: all alpha-related log lines
            CREATE TABLE IF NOT EXISTS workflow_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,            -- INFO / WARN / ERROR / DEBUG
                alpha_name TEXT,                -- alpha name if applicable
                message TEXT NOT NULL,          -- log message (truncated if long)
                truncated INTEGER NOT NULL DEFAULT 0,  -- 1 if message was truncated
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Index for fast log queries
            CREATE INDEX IF NOT EXISTS idx_workflow_logs_created ON workflow_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_workflow_logs_level ON workflow_logs(level);
            CREATE INDEX IF NOT EXISTS idx_workflow_logs_alpha ON workflow_logs(alpha_name);

            -- Quadruple → SC pass/fail regression tracking (v3.17)
            -- Collects per-quadruple historical SC results for data-driven predictions
            CREATE TABLE IF NOT EXISTS quadruple_sc_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quad_key TEXT NOT NULL,           -- normalized "A/B,C/D" string
                sc_pass INTEGER NOT NULL DEFAULT 0,
                sc_fail INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                pass_rate REAL,                  -- sc_pass / total
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_quad_sc_key ON quadruple_sc_stats(quad_key);
            CREATE INDEX IF NOT EXISTS idx_quad_sc_rate ON quadruple_sc_stats(pass_rate DESC);

            -- Self-evolution improvements (meta-optimization records)
            CREATE TABLE IF NOT EXISTS improvements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,          -- ISO timestamp
                category TEXT NOT NULL,           -- bug_fix / service_recovery / optimization
                type TEXT NOT NULL,               -- user-friendly type
                description TEXT NOT NULL,        -- short summary
                meta_analysis TEXT NOT NULL DEFAULT '{}', -- JSON blob with bottleneck/pattern/health etc.
                details TEXT NOT NULL DEFAULT '{}', -- JSON blob with additional context (bug analysis, etc.)
                executed_changes TEXT NOT NULL DEFAULT '[]', -- JSON array
                skipped_proposals TEXT NOT NULL DEFAULT '[]', -- JSON array
                feishu_report TEXT NOT NULL DEFAULT '{}', -- JSON blob
                data_window TEXT,                 -- human-readable time range
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_improvements_ts ON improvements(timestamp);
            CREATE INDEX IF NOT EXISTS idx_improvements_cat ON improvements(category);

            -- Migrate existing state.json data into SQLite if file exists
            -- (run once on first startup)
        """)
        conn.commit()
    finally:
        conn.close()


def save_workflow_state(key: str, value: dict):
    """Save a workflow state key-value pair."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO workflow_state (key, value, updated_at)
               VALUES (?, ?, ?)""",
            (key, json.dumps(value, default=str), datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def load_workflow_state(key: str) -> dict:
    """Load a workflow state value by key."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value FROM workflow_state WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return json.loads(row["value"])
        return {}
    finally:
        conn.close()


# ─── Alpha Event Recording ─────────────────────────────────────────

def record_alpha_event(
    name: str,
    expr: str,
    event_type: str,
    alpha_id: str = None,
    sharpe: float = None,
    fitness: float = None,
    sc_value: float = None,
    sc_result: str = None,
    is_status: str = None,
    phase: str = None,
    notes: str = None,
    duration: float = None,
):
    """
    Record an alpha lifecycle event.
    
    event_type: generated | is_pass | is_fail | is_tune | sc_pass | sc_fail | submitted | failed | optimized
    
    This also updates alpha_stats (upsert) and cumulative_stats.
    """
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        
        # 1. Insert event
        conn.execute(
            """INSERT INTO alpha_events 
               (alpha_id, name, expr, event_type, sharpe, fitness, sc_value, 
                sc_result, is_status, phase, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (alpha_id, name, expr, event_type, sharpe, fitness, sc_value,
             sc_result, is_status, phase, notes, now)
        )
        
        # 2. Upsert alpha_stats
        conn.execute(
            """INSERT INTO alpha_stats 
               (name, expr, alpha_id, sharpe, fitness, sc_value, sc_result, 
                is_status, status, total_attempts, first_generated_at, last_updated,
                is_duration, sc_duration)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   alpha_id = COALESCE(excluded.alpha_id, alpha_stats.alpha_id),
                   expr = excluded.expr,
                   sharpe = COALESCE(excluded.sharpe, alpha_stats.sharpe),
                   fitness = COALESCE(excluded.fitness, alpha_stats.fitness),
                   sc_value = COALESCE(excluded.sc_value, alpha_stats.sc_value),
                   sc_result = COALESCE(excluded.sc_result, alpha_stats.sc_result),
                   is_status = COALESCE(excluded.is_status, alpha_stats.is_status),
                   status = excluded.status,
                   total_attempts = alpha_stats.total_attempts + 1,
                   last_updated = excluded.last_updated,
                   is_duration = COALESCE(excluded.is_duration, alpha_stats.is_duration),
                   sc_duration = COALESCE(excluded.sc_duration, alpha_stats.sc_duration)""",
            (name, expr, alpha_id, sharpe, fitness, sc_value, sc_result,
             is_status, _event_to_status(event_type), now, now,
             duration, duration)
        )
        
        # 3. Increment cumulative counters
        counter_map = {
            "generated": "total_generated",
            "is_pass": "total_is_pass",
            "is_fail": "total_is_fail",
            "is_tune": "total_is_tune",
            "sc_pass": "total_sc_pass",
            "sc_fail": "total_sc_fail",
            "submitted": "total_submitted",
            "failed": "total_failed",
            "optimized": "total_optimized",
            "sc_timeout_pending": "total_sc_timeout",
        }
        counter_key = counter_map.get(event_type)
        if counter_key:
            conn.execute(
                """UPDATE cumulative_stats 
                   SET value = value + 1, last_updated = ?
                   WHERE key = ?""",
                (now, counter_key)
            )
        
        conn.commit()
    finally:
        conn.close()


def _event_to_status(event_type: str) -> str:
    """Map event_type to alpha_stats.status."""
    mapping = {
        "generated": "generated",
        "is_pass": "is_pass",
        "is_tune": "is_pass",
        "is_fail": "is_fail",
        "sc_pass": "sc_pass",
        "sc_fail": "sc_fail",
        "submitted": "submitted",
        "failed": "failed",
        "optimized": "is_pass",
        "sc_timeout_pending": "sc_timeout_pending",
    }
    return mapping.get(event_type, "generated")


# ─── Quadruple → SC Regression Tracking (v3.17) ─────────────────────

def record_quadruple_sc(quad_key: str, sc_passed: bool):
    """
    Record a quadruple's SC result for regression modeling.
    
    quad_key: normalized "A/B,C/D" string extracted from a MULT expression
    sc_passed: True if SC passed, False if SC failed
    """
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        if sc_passed:
            conn.execute(
                """INSERT INTO quadruple_sc_stats (quad_key, sc_pass, sc_fail, total, last_seen)
                   VALUES (?, 1, 0, 1, ?)
                   ON CONFLICT(quad_key) DO UPDATE SET
                       sc_pass = sc_pass + 1,
                       total = total + 1,
                       pass_rate = (sc_pass + 1) / total,
                       last_seen = ?""",
                (quad_key, now, now)
            )
        else:
            conn.execute(
                """INSERT INTO quadruple_sc_stats (quad_key, sc_pass, sc_fail, total, last_seen)
                   VALUES (?, 0, 1, 1, ?)
                   ON CONFLICT(quad_key) DO UPDATE SET
                       sc_fail = sc_fail + 1,
                       total = total + 1,
                       pass_rate = sc_pass / total,
                       last_seen = ?""",
                (quad_key, now, now)
            )
        conn.commit()
    finally:
        conn.close()


def get_quadruple_sc_stats(quad_key: str = None, min_total: int = 3) -> list:
    """
    Query quadruple SC pass rate.
    
    If quad_key is None, returns all quadruples sorted by pass_rate DESC.
    min_total: minimum number of observations to trust the stat.
    """
    conn = get_db()
    try:
        if quad_key:
            row = conn.execute(
                """SELECT * FROM quadruple_sc_stats WHERE quad_key = ?""",
                (quad_key,)
            ).fetchone()
            return dict(row) if row else None
        else:
            rows = conn.execute(
                """SELECT * FROM quadruple_sc_stats
                   WHERE total >= ? ORDER BY pass_rate DESC""",
                (min_total,)
            ).fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def get_quad_sc_penalty(quad_key: str, current_score: float) -> tuple:
    """
    Apply historical SC pass rate as a penalty to the orthogonality score.
    
    Returns (adjusted_score, penalty_amount).
    
    Rules:
    - < 3 samples: no penalty (not enough data)
    - pass_rate ≥ 0.7: no penalty (proven positive)
    - pass_rate 0.5-0.7: -1 penalty (marginal)
    - pass_rate < 0.5: -3 penalty (known bad combination)
    """
    stats = get_quadruple_sc_stats(quad_key, min_total=3)
    if not stats:
        return current_score, 0.0
    pr = stats.get("pass_rate", 0.5)
    penalty = 0.0
    if pr < 0.5:
        penalty = 3.0
    elif pr < 0.7:
        penalty = 1.0
    return max(0, current_score - penalty), penalty


# ─── Query Helpers for Dashboard ────────────────────────────────────

def get_cumulative_stats() -> dict:
    """Get all cumulative counters."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT key, value FROM cumulative_stats"
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        conn.close()


def get_recent_alpha_events(limit: int = 50) -> list:
    """Get recent alpha events for dashboard activity log."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM alpha_events 
               ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_alpha_by_name(name: str) -> Optional[dict]:
    """Get latest stats for a specific alpha."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM alpha_stats WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_alpha_history(limit: int = 200, offset: int = 0) -> dict:
    """Get alpha history for dashboard /api/history."""
    conn = get_db()
    try:
        # Get distinct alpha names with latest stats
        rows = conn.execute(
            """SELECT * FROM alpha_stats 
               ORDER BY last_updated DESC LIMIT ? OFFSET ?""",
            (limit, offset)
        ).fetchall()
        
        events = []
        for r in rows:
            # Get all events for this alpha
            alpha_events = conn.execute(
                """SELECT event_type, sharpe, fitness, sc_value, sc_result, 
                          is_status, notes, created_at
                   FROM alpha_events WHERE name = ?
                   ORDER BY created_at ASC""",
                (r["name"],)
            ).fetchall()
            
            events.append({
                "name": r["name"],
                "expr": r["expr"],
                "alpha_id": r["alpha_id"],
                "status": r["status"],
                "sharpe": r["sharpe"],
                "fitness": r["fitness"],
                "sc_value": r["sc_value"],
                "events": [dict(e) for e in alpha_events],
            })
        
        # Get total count
        total = conn.execute("SELECT COUNT(*) as cnt FROM alpha_stats").fetchone()["cnt"]
        
        return {"total": total, "events": events}
    finally:
        conn.close()


def get_alpha_history_flat(limit: int = 200, offset: int = 0) -> dict:
    """Get flat alpha event history for dashboard Timeline.
    
    Returns individual alpha_events rows (not grouped by alpha),
    matching the HistoryEvent frontend type.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT name, event_type, sharpe, fitness, sc_value, sc_result,
                      is_status, phase, duration_seconds as duration, created_at, alpha_id
               FROM alpha_events
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset)
        ).fetchall()
        
        events = [dict(r) for r in rows]
        total = conn.execute("SELECT COUNT(*) as cnt FROM alpha_events").fetchone()["cnt"]
        
        return {"total": total, "events": events}
    finally:
        conn.close()


def get_all_alphas_summary(limit: int = 200, offset: int = 0) -> dict:
    """Get per-alpha summary with full lifecycle stats and state chain.
    
    Returns one row per distinct alpha name with:
    - latest expr, alpha_id
    - first_generated, last_updated
    - best sharpe/fitness, latest sc_value/sc_result
    - current status (derived from event chain ordering)
    - event_type timeline (for state chain display)
    """
    conn = get_db()
    try:
        # Use alpha_stats as base (one row per alpha), enrich with event timeline
        rows = conn.execute(
            """SELECT s.*,
                      (SELECT MIN(created_at) FROM alpha_events e WHERE e.name = s.name) as first_generated_at,
                      (SELECT created_at FROM alpha_events e 
                       WHERE e.name = s.name AND e.event_type IN ('is_pass','is_tune','sc_pass','sc_fail','submitted','failed')
                       ORDER BY created_at DESC LIMIT 1) as last_milestone_at
               FROM alpha_stats s
               ORDER BY s.last_updated DESC
               LIMIT ? OFFSET ?""",
            (limit, offset)
        ).fetchall()
        
        alphas = []
        for r in rows:
            # Fetch the full event timeline for state chain
            events = conn.execute(
                """SELECT event_type, sharpe, fitness, sc_value, sc_result, is_status, created_at
                   FROM alpha_events WHERE name = ?
                   ORDER BY created_at ASC""",
                (r["name"],)
            ).fetchall()
            
            # Build state chain deduplicated (consecutive same type collapsed)
            chain = []
            prev = None
            for e in events:
                et = e["event_type"]
                if et != prev:
                    chain.append({
                        "event_type": et,
                        "sharpe": e["sharpe"],
                        "fitness": e["fitness"],
                        "sc_value": e["sc_value"],
                        "sc_result": e["sc_result"],
                        "is_status": e["is_status"],
                        "created_at": e["created_at"],
                    })
                    prev = et
            
            # Determine current status from last meaningful event
            last_status = r["status"]  # from alpha_stats
            
            alphas.append({
                "name": r["name"],
                "expr": r["expr"],
                "alpha_id": r["alpha_id"],
                "sharpe": r["sharpe"],
                "fitness": r["fitness"],
                "sc_value": r["sc_value"],
                "sc_result": r["sc_result"],
                "is_status": r["is_status"],
                "status": last_status,
                "total_attempts": r["total_attempts"],
                "first_generated_at": r["first_generated_at"],
                "last_milestone_at": r["last_milestone_at"],
                "last_updated": r["last_updated"],
                "state_chain": chain,
                "chain_length": len(chain),
            })
        
        total = conn.execute("SELECT COUNT(*) as cnt FROM alpha_stats").fetchone()["cnt"]
        
        return {"total": total, "alphas": alphas}
    finally:
        conn.close()


def get_submitted_alphas() -> list:
    """Get all submitted (ACTIVE) alphas."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM alpha_stats 
               WHERE status = 'submitted'
               ORDER BY last_updated DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def export_state_to_db(old_state_file: Path):
    """Migrate existing state.json to SQLite on first run."""
    if not old_state_file.exists():
        return
    
    try:
        state = json.loads(old_state_file.read_text())
    except:
        return
    
    # Update cumulative stats from state counters
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        
        # Save full state as a single key for backward compat
        save_workflow_state("workflow", state)
        
        # Update cumulative counters
        updates = {
            "total_generated": state.get("candidates_generated", 0),
            "total_is_pass": state.get("candidates_passed_is", 0),
            "total_sc_pass": state.get("candidates_passed_sc", 0),
            "total_submitted": state.get("candidates_submitted", 0),
        }
        for key, value in updates.items():
            if value > 0:
                conn.execute(
                    """UPDATE cumulative_stats 
                       SET value = ?, last_updated = ?
                       WHERE key = ?""",
                    (value, now, key)
                )
        
        conn.commit()
        print(f"✅ Migrated state.json ({old_state_file}) → SQLite")
    finally:
        conn.close()


# ─── Workflow Log Recording ──────────────────────────────────────────

_MAX_LOG_MSG = 2000  # max bytes for message column

def log_to_db(level: str, message: str, alpha_name: str = None):
    """Record a log line to SQLite. Async-friendly: uses short-lived conn."""
    conn = get_db()
    try:
        truncated = 0
        msg = message[:_MAX_LOG_MSG]
        if len(message) > _MAX_LOG_MSG:
            msg = message[:_MAX_LOG_MSG] + "..."
            truncated = 1
        
        conn.execute(
            """INSERT INTO workflow_logs (timestamp, level, alpha_name, message, truncated, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (datetime.now().strftime("%m-%d %H:%M:%S"), level, alpha_name, msg, truncated,
             datetime.now().isoformat())
        )
        conn.commit()
    except Exception:
        pass  # Never crash workflow if DB write fails
    finally:
        conn.close()


def get_workflow_logs(limit: int = 200, level_filter: str = None) -> list:
    """Get workflow log entries from SQLite."""
    conn = get_db()
    try:
        if level_filter:
            rows = conn.execute(
                """SELECT * FROM workflow_logs 
                   WHERE level = ? ORDER BY created_at DESC LIMIT ?""",
                (level_filter, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM workflow_logs 
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_error_logs(limit: int = 50) -> list:
    """Get all ERROR level logs."""
    return get_workflow_logs(limit=limit, level_filter="ERROR")


def get_warn_logs(limit: int = 100) -> list:
    """Get all WARN level logs."""
    return get_workflow_logs(limit=limit, level_filter="WARN")


# ─── Improvement Records ──────────────────────────────────────────────

def record_improvement(record: dict):
    """Insert a self-evolution improvement record into SQLite.
    
    record keys: timestamp, category, type, description, meta_analysis,
                 details, executed_changes, skipped_proposals, feishu_report, data_window
    """
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO improvements
               (timestamp, category, type, description, meta_analysis, details,
                executed_changes, skipped_proposals, feishu_report, data_window)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("timestamp", datetime.now().isoformat()),
                record.get("category", "general"),
                record.get("type", "general"),
                record.get("description", ""),
                json.dumps(record.get("meta_analysis", {}), default=str, ensure_ascii=False),
                json.dumps(record.get("details", {}), default=str, ensure_ascii=False),
                json.dumps(record.get("executed_changes", []), default=str, ensure_ascii=False),
                json.dumps(record.get("skipped_proposals", []), default=str, ensure_ascii=False),
                json.dumps(record.get("feishu_report", {}), default=str, ensure_ascii=False),
                record.get("data_window", None),
            )
        )
        conn.commit()
    finally:
        conn.close()


def normalize_improvement_record(raw: dict) -> dict:
    """Normalize a DB improvement record to match frontend ImprovementRecord shape.
    
    The JSON log file has two formats:
      OLD (records 0-2): meta_analysis.bottleneck/funnel/health, feishu_report, data_window
      NEW (records 3-4): category, type, description, details (bug analysis etc.)
    Both formats may coexist. We normalize to a single output shape.
    """
    # Detect OLD format (has meta_analysis + feishu_report)
    has_meta = "meta_analysis" in raw and raw["meta_analysis"]
    has_report = "feishu_report" in raw and raw["feishu_report"]
    
    if has_meta or has_report:
        # OLD format normalization
        meta = raw.get("meta_analysis") or {}
        report = raw.get("feishu_report") or {}
        changes = raw.get("executed_changes") or []
        skipped = raw.get("skipped_proposals") or []

        normalized_meta = {}
        if meta:
            normalized_meta["bottleneck_identified"] = meta.get("bottleneck") or ""
            normalized_meta["pattern_discovered"] = meta.get("pattern") or ""
            funnel_raw = meta.get("funnel") or meta.get("conversion_funnel")
            if isinstance(funnel_raw, str):
                normalized_meta["conversion_funnel"] = {"summary": funnel_raw}
            elif isinstance(funnel_raw, dict):
                normalized_meta["conversion_funnel"] = funnel_raw
            normalized_meta["pipeline_health"] = meta.get("health") or ""
            for k, v in meta.items():
                if k not in normalized_meta and k not in ("bottleneck", "pattern", "funnel", "health"):
                    normalized_meta[k] = v

        normalized_report = {}
        if report:
            normalized_report["summary"] = report.get("summary", report.get("title", ""))
            normalized_report["title"] = report.get("title", "")
            normalized_report["changes_count"] = report.get("changes_count", 0)
            normalized_report["trigger_time"] = report.get("trigger_time", "")
            normalized_report["pipeline_restarted"] = report.get("pipeline_restarted", False)

        normalized_changes = []
        for ch in changes:
            nc = dict(ch)
            for key in ("target", "type", "description", "motivation", "verification"):
                nc.setdefault(key, "")
            normalized_changes.append(nc)

        normalized_skipped = []
        for sp in skipped:
            ns = {"description": sp.get("description") or sp.get("proposal", ""), "reason": sp.get("reason", "")}
            normalized_skipped.append(ns)

        return {
            "timestamp": raw.get("timestamp", ""),
            "data_window": raw.get("data_window", ""),
            "meta_analysis": normalized_meta if normalized_meta else None,
            "executed_changes": normalized_changes if normalized_changes else None,
            "skipped_proposals": normalized_skipped if normalized_skipped else None,
            "feishu_report": normalized_report if normalized_report else None,
            "category": raw.get("category", ""),
            "type": raw.get("type", ""),
            "description": raw.get("description", ""),
            "details": raw.get("details", {}),
        }
    else:
        # NEW format (has details with bug analysis etc.)
        details = raw.get("details") or {}
        changes = raw.get("executed_changes") or []
        skipped = raw.get("skipped_proposals") or []

        # Build a meta_analysis from details for OLD-format compatibility
        normalized_meta = {}
        if details:
            # Map common detail keys to frontend expectations
            if "root_cause" in details:
                normalized_meta["bottleneck_identified"] = details["root_cause"]
            if "funnel_leak" in details:
                normalized_meta["conversion_funnel"] = {"summary": details["funnel_leak"]}
            if "impact" in details:
                normalized_meta["pipeline_health"] = details["impact"]
            # Keep all detail keys as extra
            for k, v in details.items():
                normalized_meta[f"detail_{k}"] = v

        normalized_changes = []
        for ch in changes:
            nc = dict(ch)
            for key in ("target", "type", "description", "motivation", "verification"):
                nc.setdefault(key, "")
            normalized_changes.append(nc)

        normalized_skipped = []
        for sp in skipped:
            ns = {"description": sp.get("description") or sp.get("proposal", ""), "reason": sp.get("reason", "")}
            normalized_skipped.append(ns)

        # Use description as header text
        desc = raw.get("description", "")
        if not desc and details:
            desc = details.get("bug") or details.get("action") or ""

        return {
            "timestamp": raw.get("timestamp", ""),
            "data_window": raw.get("data_window", ""),
            "meta_analysis": normalized_meta if normalized_meta else None,
            "executed_changes": normalized_changes if normalized_changes else None,
            "skipped_proposals": normalized_skipped if normalized_skipped else None,
            "feishu_report": None,
            "category": raw.get("category", ""),
            "type": raw.get("type", ""),
            "description": desc,
            "details": details,
        }


def get_improvements(limit: int = 50) -> list:
    """Get improvement records from SQLite, newest first.
    Each record is normalized to match frontend ImprovementRecord shape."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, timestamp, category, type, description,
                      meta_analysis, details,
                      executed_changes, skipped_proposals,
                      feishu_report, data_window
               FROM improvements
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
        results = []
        for r in rows:
            # Reconstruct the original JSON-structured record from DB columns
            raw = {
                "timestamp": r["timestamp"],
                "category": r["category"],
                "type": r["type"],
                "description": r["description"],
                "meta_analysis": json.loads(r["meta_analysis"]) if r["meta_analysis"] else {},
                "details": json.loads(r["details"]) if r["details"] else {},
                "executed_changes": json.loads(r["executed_changes"]) if r["executed_changes"] else [],
                "skipped_proposals": json.loads(r["skipped_proposals"]) if r["skipped_proposals"] else [],
                "feishu_report": json.loads(r["feishu_report"]) if r["feishu_report"] else {},
                "data_window": r["data_window"],
            }
            results.append(normalize_improvement_record(raw))
        return results
    finally:
        conn.close()


def count_improvements() -> int:
    """Total improvement record count."""
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM improvements").fetchone()
        return row["cnt"]
    finally:
        conn.close()


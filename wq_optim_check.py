#!/usr/bin/env python3
"""
WQ Meta-Optimization Check: Adaptive batch-based trigger.
Reads pipeline state from SQLite and decides if optimization is needed.
Called by cron as check script — stdout is injected into prompt context.

v2: Rewritten to use SQLite (wq_db) instead of non-existent .json state file.
"""
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import wq_db as _wqdb

TRACKER_FILE = Path(os.path.expanduser("~/.wq_optim_tracker.json"))

def load_tracker() -> dict:
    if TRACKER_FILE.exists():
        return json.loads(TRACKER_FILE.read_text())
    return {
        "batches_since_optimization": 0,
        "last_optimization_at": None,
        "last_batch_idx": 0,
        "last_batch_total": 0,
        "opt_count": 0,
        "opt_had_changes": False,
        "consecutive_noop": 0,
    }

def save_tracker(t: dict):
    TRACKER_FILE.write_text(json.dumps(t, indent=2, default=str))

def main():
    t = load_tracker()

    # ── Load state from SQLite ──
    state = _wqdb.load_workflow_state("workflow")
    if not state:
        print("OPTIMIZE=no")
        print("REASON=No active pipeline state in SQLite")
        return

    batch_idx = state.get("batch_idx", 0) or 0
    iterations = state.get("iterations", 0) or 0
    active_count = state.get("active_count", 0) or 0
    stuck_batches = state.get("stuck_batches", 0) or 0
    dead_pairs = state.get("dead_pairs_count", 0) or 0
    is_passed = state.get("candidates_passed_is", 0) or 0
    sc_passed = state.get("candidates_passed_sc", 0) or 0
    submitted = state.get("candidates_submitted", 0) or 0
    errors = state.get("errors", [])
    phase = state.get("phase", "unknown")
    fields_used = state.get("fields_used", {})

    # ── Calculate batches since last optimization ──
    batch_total = state.get("batch_total", 3) or 3
    absolute_batch = iterations * batch_total + batch_idx
    last_abs = t.get("last_batch_total", 0) or 0
    t["batches_since_optimization"] = absolute_batch - last_abs
    t["last_batch_idx"] = batch_idx
    t["last_batch_total"] = absolute_batch
    save_tracker(t)

    batches_elapsed = t["batches_since_optimization"]

    # ── Dynamic threshold logic ──
    base_threshold = 8  # every 8 batches normally

    # Near target → less frequent (don't disrupt)
    if active_count >= 18:
        base_threshold = 14
    # Stuck → more frequent (need intervention)
    if stuck_batches >= 3:
        base_threshold = 4
    # Many dead pairs → more frequent
    if dead_pairs > 60:
        base_threshold = min(base_threshold, 6)

    # If last optimization was a noop multiple times → increase threshold
    noop_penalty = min(t.get("consecutive_noop", 0), 5)
    threshold = base_threshold + noop_penalty

    if batches_elapsed < threshold:
        print("OPTIMIZE=no")
        print(f"REASON=Batches since optim: {batches_elapsed} < threshold: {threshold}")
        print(f"THRESHOLD_DETAIL=base={base_threshold} active={active_count} stuck={stuck_batches} noop_penalty={noop_penalty}")
        return

    # ── Build optimization context ──
    issues = []

    # Field saturation check
    field_scores = sorted(fields_used.items(), key=lambda x: -x[1])
    if field_scores:
        top_field, top_count = field_scores[0]
        if top_count >= 8:
            issues.append(f"FIELD_SATURATED={top_field}={top_count}")

    zero_usage = [f for f, c in field_scores if c == 0]
    if zero_usage:
        issues.append(f"UNUSED_FIELDS={','.join(zero_usage[:5])}")

    # Stuck detection
    if stuck_batches >= 2:
        issues.append(f"STUCK=stuck_batches={stuck_batches}")

    # Dead pair rate
    if dead_pairs > 40:
        issues.append(f"HIGH_DEAD_PAIRS={dead_pairs}")

    # Pass rate
    total_candidates = max(state.get("candidates_generated", 0) or 0, 1)
    pass_rate = is_passed / total_candidates if total_candidates > 0 else 0
    if pass_rate < 0.05 and total_candidates > 20:
        issues.append(f"LOW_IS_PASS_RATE={pass_rate:.1%} ({is_passed}/{total_candidates})")

    # Error analysis
    recent_errors = errors[-5:] if errors else []
    if recent_errors:
        error_types = {}
        for e in recent_errors:
            key = e.split("(")[0].strip()[:60] if "(" in e else e[:60]
            error_types[key] = error_types.get(key, 0) + 1
        top_errors = sorted(error_types.items(), key=lambda x: -x[1])[:3]
        issues.append(f"RECENT_ERRORS={'; '.join(f'{err}({c})' for err, c in top_errors)}")

    # Phase stuck detection
    if phase == "quick_test" and errors:
        issues.append(f"PHASE_STUCK=quick_test")

    # ── Output ──
    print("OPTIMIZE=yes")
    print(f"BATCHES_ELAPSED={batches_elapsed}")
    print(f"THRESHOLD={threshold}")
    print(f"THRESHOLD_DETAIL=base={base_threshold} active={active_count} stuck={stuck_batches} noop_penalty={noop_penalty}")
    print(f"ACTIVE={active_count}/20")
    print(f"ITERATIONS={iterations}")
    print(f"BATCH_IDX={batch_idx}")
    print(f"PHASE={phase}")
    print(f"IS_PASSED={is_passed}")
    print(f"SC_PASSED={sc_passed}")
    print(f"SUBMITTED={submitted}")
    print(f"STUCK_BATCHES={stuck_batches}")
    print(f"DEAD_PAIRS={dead_pairs}")
    print(f"ISSUES={'; '.join(issues)}" if issues else "ISSUES=No critical issues detected")

if __name__ == "__main__":
    main()

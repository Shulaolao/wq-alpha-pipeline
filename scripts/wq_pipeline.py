#!/usr/bin/env python3
"""
WQ Pipeline — 三阶段解耦架构

Phase A: 健康检查 → 创建 sim → 写状态文件
Phase B: 读状态 → 轮询 IS → 更新
Phase C: 读状态 → 提 SC → 轮询结果

用法: python3 wq_pipeline.py --phase A|B|C [--expressions ~/.wq_expressions.json]
"""
import json, time, sys, os, ssl, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests, urllib3
urllib3.disable_warnings()
urllib3.util.ssl_.DEFAULT_CIPHERS = ":".join(["ECDHE+AESGCM","ECDHE+CHACHA20","DHE+AESGCM","DHE+CHACHA20"])
_tls12_ctx = ssl.create_default_context()
_tls12_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
_tls12_ctx.maximum_version = ssl.TLSVersion.TLSv1_2
_tls12_ctx.check_hostname = False
_tls12_ctx.verify_mode = ssl.CERT_NONE

class _TLS12Adapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _tls12_ctx
        return super().init_poolmanager(*args, **kwargs)

# ─── Config ───────────────────────────────────────────
API = "https://api.worldquantbrain.com"
EMAIL = "shufengln@gmail.com"
PASS = "123321sf"
HOME = Path.home()
STATE_FILE = HOME / ".wq_batch_state.json"
DEFAULT_EXPR_FILE = HOME / ".wq_expressions.json"
SC_TIMEOUT = 600  # 10 min
POLL_INTERVAL = 15

DEFAULT_SETTINGS = {
    "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
    "delay": 1, "decay": 2, "neutralization": "INDUSTRY", "truncation": 0.08,
    "pasteurization": "ON", "unitHandling": "VERIFY", "nanHandling": "OFF",
    "language": "FASTEXPR", "visualization": False,
    "startDate": "2019-01-01", "endDate": "2023-12-31", "testPeriod": "P1Y"
}

LIGHT_SETTINGS = dict(DEFAULT_SETTINGS)
LIGHT_SETTINGS.update({"delay": 1, "decay": 1})

def ts():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')

def log(msg):
    print(f"[{ts()}] {msg}", flush=True)

def fresh_session():
    s = requests.Session()
    s.mount("https://", _TLS12Adapter())
    s.verify = False
    s.trust_env = False
    s.proxies = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
    r = s.post(f"{API}/authentication", auth=(EMAIL, PASS), timeout=60)
    if r.status_code == 201:
        return s
    raise RuntimeError(f"Auth failed: {r.status_code}")

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"batch_id": None, "expressions": [], "phases": {"A": "pending", "B": "pending", "C": "pending"}, "created_at": None, "updated_at": None}

def save_state(state):
    state["updated_at"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    log(f"💾 State saved ({len(state['expressions'])} exprs)")

def load_expressions(path=None):
    f = Path(path) if path else DEFAULT_EXPR_FILE
    return json.loads(f.read_text()) if f.exists() else []

def get_settings(name):
    return dict(DEFAULT_SETTINGS)

# ─── Health Check ─────────────────────────────────────
def health_check():
    """Create a lightweight sim to verify platform is operational"""
    s = fresh_session()
    payload = {"type": "REGULAR", "regular": "rank(close)", "settings": LIGHT_SETTINGS}
    r = s.post(f"{API}/simulations", json=payload, timeout=30)
    if r.status_code != 201:
        log(f"❌ Health check: POST failed ({r.status_code})")
        return False
    sim_id = r.headers.get("Location", "").split("/")[-1]
    for i in range(12):  # 3 min max
        time.sleep(15)
        r2 = s.get(f"{API}/simulations/{sim_id}", timeout=60)
        if r2.status_code == 200:
            d = r2.json()
            if d.get("alpha"):
                log(f"✅ Health check PASS ({i*15}s)")
                return True
            if d.get("progress") and d["progress"] < 0.01 and i > 4:
                log(f"❌ Health check: stuck at {d['progress']} (platform may be down)")
                return False
    log("❌ Health check timeout")
    return False

# ─── Phase A: Create Simulations ──────────────────────
def phase_a():
    log("="*50)
    log("PHASE A: Create Simulations")
    
    state = load_state()
    if state["phases"]["A"] == "done":
        log("Phase A already done, skipping")
        return
    
    # Health check first
    if not health_check():
        log("⚠️ Health check failed — aborting Phase A, will retry next cycle")
        state["phases"]["A"] = "failed"
        save_state(state)
        return
    
    # Load expressions
    exprs = load_expressions()
    if not exprs:
        log("⚠️ No expressions configured in .wq_expressions.json")
        state["phases"]["A"] = "done"
        save_state(state)
        return
    
    # Create batch ID
    batch_id = f"v{datetime.now().strftime('%m%d_%H%M')}"
    state["batch_id"] = batch_id
    state["created_at"] = datetime.now().isoformat()
    
    # Prepare expression entries
    new_exprs = []
    for exp in exprs:
        new_exprs.append({
            "name": exp["name"],
            "expr": exp["expr"],
            "sim_id": None,
            "alpha_id": None,
            "sharpe": None,
            "fitness": None,
            "phase": "pending",
            "is_status": None,
            "sc_value": None,
            "sc_result": None
        })
    state["expressions"] = new_exprs
    
    # Create sims — each with fresh session
    for e in state["expressions"]:
        try:
            s = fresh_session()
            settings = get_settings(e["name"])
            payload = {"type": "REGULAR", "regular": e["expr"], "settings": settings}
            r = s.post(f"{API}/simulations", json=payload, timeout=90)
            
            if r.status_code == 201:
                sim_id = r.headers.get("Location", "").split("/")[-1]
                e["sim_id"] = sim_id
                e["phase"] = "sim_created"
                log(f"✅ {e['name']}: sim_id={sim_id}")
            elif r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 900))
                log(f"⚠️ {e['name']}: 429 (retry after {retry_after}s)")
                if retry_after < 300:
                    log(f"   Waiting {retry_after}s then retrying...")
                    time.sleep(retry_after)
                    r = s.post(f"{API}/simulations", json=payload, timeout=90)
                    if r.status_code == 201:
                        sim_id = r.headers.get("Location", "").split("/")[-1]
                        e["sim_id"] = sim_id
                        e["phase"] = "sim_created"
                        log(f"✅ {e['name']}: sim_id={sim_id} (retry)")
                    else:
                        e["phase"] = "failed"
                        log(f"❌ {e['name']}: still {r.status_code} after retry")
                else:
                    e["phase"] = "rate_limited"
                    log(f"   Cooldown too long, will retry next cycle")
            else:
                e["phase"] = "failed"
                log(f"❌ {e['name']}: HTTP {r.status_code} {r.text[:100]}")
        except Exception as ex:
            e["phase"] = "failed"
            log(f"❌ {e['name']}: {ex}")
        
        time.sleep(2)  # Gentle pace between sims
    
    # Mark phase
    all_done = all(e["phase"] in ("sim_created", "failed", "rate_limited") for e in state["expressions"])
    state["phases"]["A"] = "done" if all_done else "partial"
    save_state(state)
    
    created = sum(1 for e in state["expressions"] if e["phase"] == "sim_created")
    failed = sum(1 for e in state["expressions"] if e["phase"] in ("failed", "rate_limited"))
    log(f"\n📊 Phase A result: {created} created, {failed} failed")
    log("PHASE A COMPLETE")

# ─── Phase B: Poll IS ─────────────────────────────────
def phase_b():
    log("="*50)
    log("PHASE B: Poll IS Results")
    
    state = load_state()
    if state["phases"]["B"] == "done":
        log("Phase B already done, checking for newly completed sims...")
    if not state["expressions"]:
        log("No pending expressions to poll")
        return
    
    s = fresh_session()
    any_pending = False
    
    for e in state["expressions"]:
        if e["phase"] not in ("sim_created", "polling_is"):
            continue
        
        e["phase"] = "polling_is"
        sim_id = e["sim_id"]
        if not sim_id:
            continue
        
        try:
            r = s.get(f"{API}/simulations/{sim_id}", timeout=60)
            if r.status_code != 200:
                log(f"⚠️ {e['name']}: GET sim HTTP {r.status_code}")
                any_pending = True
                continue
            
            d = r.json()
            alpha_id = d.get("alpha")
            pct = d.get("progress")
            
            if alpha_id:
                e["alpha_id"] = alpha_id
                e["phase"] = "is_ready"
                
                # Fetch IS data
                r2 = s.get(f"{API}/alphas/{alpha_id}", timeout=30)
                if r2.status_code == 200:
                    ad = r2.json()
                    checks = ad.get("is", {}).get("checks", []) if isinstance(ad.get("is"), dict) else []
                    stats = ad.get("is", {}).get("statistics", {}) if isinstance(ad.get("is"), dict) else {}
                    e["sharpe"] = stats.get("sharpe")
                    e["fitness"] = stats.get("fitness")
                    
                    passes = sum(1 for c in checks if c.get("result") == "PASS")
                    fails = sum(1 for c in checks if c.get("result") == "FAIL")
                    
                    # Check SC separately (might still be PENDING)
                    sc_check = next((c for c in checks if c["name"] == "SELF_CORRELATION"), None)
                    sc_status = sc_check.get("result", "PENDING") if sc_check else "PENDING"
                    
                    e["is_status"] = "PASS" if (fails == 0 and passes >= 7) else "FAIL"
                    log(f"✅ {e['name']}: alpha={alpha_id} S={e['sharpe']} F={e['fitness']} | {passes}P/{fails}F | IS={e['is_status']} | SC={sc_status}")
                    
                    if e["is_status"] == "PASS":
                        # Set name/metadata
                        try:
                            s.patch(f"{API}/alphas/{alpha_id}", json={"name": e["name"], "color": "GREEN", "category": "FUNDAMENTAL", "tags": ["auto-generated"]}, timeout=15)
                        except: pass
            elif pct is not None and pct < 1.0:
                log(f"⏳ {e['name']}: {pct:.2f}...")
                any_pending = True
            elif d.get("status") == "ERROR":
                e["phase"] = "failed"
                e["is_status"] = "ERROR"
                log(f"❌ {e['name']}: SIM ERROR")
            elif pct is not None and pct >= 1.0:
                log(f"⏳ {e['name']}: pct=1.0 but no alpha_id (still processing)")
                any_pending = True
            else:
                log(f"⏳ {e['name']}: status={d.get('status')} progress={pct}")
                any_pending = True
        
        except Exception as ex:
            log(f"⚠️ {e['name']}: poll error: {ex}")
            any_pending = True
    
    if any_pending:
        state["phases"]["B"] = "partial"
        log("ℹ️ Some sims still pending — next poll cycle will continue")
    else:
        state["phases"]["B"] = "done"
        log("✅ All sims resolved")
    
    save_state(state)
    
    passed = sum(1 for e in state["expressions"] if e.get("is_status") == "PASS")
    failed = sum(1 for e in state["expressions"] if e.get("is_status") in ("FAIL", "ERROR"))
    pending = sum(1 for e in state["expressions"] if e["phase"] in ("sim_created", "polling_is"))
    log(f"\n📊 Phase B: {passed} PASS, {failed} FAIL, {pending} still pending")
    log("PHASE B COMPLETE")

# ─── Phase C: Submit SC ───────────────────────────────
def phase_c():
    log("="*50)
    log("PHASE C: Submit SC Checks")
    
    state = load_state()
    if state["phases"]["C"] == "done":
        log("Phase C already done")
        return
    
    s = fresh_session()
    any_pending_sc = False
    
    for e in state["expressions"]:
        if e.get("is_status") != "PASS":
            continue
        if e.get("sc_result") in ("PASS", "FAIL"):
            continue
        
        alpha_id = e.get("alpha_id")
        if not alpha_id:
            continue
        
        # Submit for SC
        log(f"📬 {e['name']} ({alpha_id}): submitting SC...")
        try:
            r = s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
            
            if r.status_code in (200, 201, 202):
                log(f"   Submitted (HTTP {r.status_code}), polling...")
            elif r.status_code == 403:
                # SC already computed, extract from 403 body
                try:
                    body = r.json()
                    checks = body.get("is", {}).get("checks", [])
                    sc = next((c for c in checks if c["name"] == "SELF_CORRELATION"), None)
                    if sc and sc.get("result") != "PENDING":
                        e["sc_value"] = sc.get("value")
                        e["sc_result"] = sc.get("result")
                        log(f"   SC={e['sc_value']} result={e['sc_result']} (from 403)")
                        continue
                except: pass
                log(f"   403 but SC not found, will poll")
            else:
                log(f"❌ Submit failed: HTTP {r.status_code}")
                continue
            
            # Poll for SC result
            start = time.time()
            while time.time() - start < SC_TIMEOUT:
                time.sleep(POLL_INTERVAL)
                try:
                    r2 = s.get(f"{API}/alphas/{alpha_id}", timeout=30)
                    if r2.status_code == 200:
                        ad = r2.json()
                        checks = ad.get("is", {}).get("checks", []) if isinstance(ad.get("is"), dict) else []
                        sc = next((c for c in checks if c["name"] == "SELF_CORRELATION"), None)
                        if sc and sc.get("result") != "PENDING":
                            e["sc_value"] = sc.get("value")
                            e["sc_result"] = sc.get("result")
                            log(f"   SC={e['sc_value']} result={e['sc_result']}")
                            break
                        if ad.get("status") == "ACTIVE":
                            e["sc_value"] = 0
                            e["sc_result"] = "PASS"
                            e["phase"] = "active"
                            log(f"   ACTIVE!")
                            break
                except: pass
            else:
                # Timeout — try 403 probe
                log(f"   Poll timeout, trying 403 probe...")
                try:
                    r3 = s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
                    if r3.status_code == 403:
                        body = r3.json()
                        sc = next((c for c in body.get("is", {}).get("checks", []) if c["name"] == "SELF_CORRELATION"), None)
                        if sc:
                            e["sc_value"] = sc.get("value")
                            e["sc_result"] = sc.get("result")
                            log(f"   SC={e['sc_value']} result={e['sc_result']} (403 probe)")
                except: pass
                
                if e.get("sc_result") is None:
                    e["sc_result"] = "TIMEOUT"
                    any_pending_sc = True
                    log(f"⚠️ SC timed out for {e['name']}")
        
        except Exception as ex:
            log(f"❌ {e['name']}: {ex}")
            any_pending_sc = True
        
        time.sleep(3)  # Gentle pace
    
    if any_pending_sc:
        state["phases"]["C"] = "partial"
    else:
        all_done = all(
            e.get("sc_result") in ("PASS", "FAIL", "TIMEOUT") or e.get("is_status") != "PASS"
            for e in state["expressions"]
        )
        state["phases"]["C"] = "done" if all_done else "partial"
    
    save_state(state)
    
    passed = sum(1 for e in state["expressions"] if e.get("sc_result") == "PASS")
    failed = sum(1 for e in state["expressions"] if e.get("sc_result") in ("FAIL", "TIMEOUT"))
    pending = sum(1 for e in state["expressions"] if e.get("is_status") == "PASS" and e.get("sc_result") is None and e.get("sc_value") is None)
    log(f"\n📊 Phase C: {passed} PASS, {failed} FAIL, {pending} pending")
    log("PHASE C COMPLETE")

# ─── Expression Pool for Auto-Generation ──────────────
# Each entry: (name_pattern, expr_pattern, note)
# {n} in name gets replaced with batch counter
EXPRESSION_POOL = [
    # ── 核心换动量字段 (保持强ratio对, 换动量破SC) ──
    ("EbitdaCapOpIncEq_HighMom_{n}", "rank(ebitda/cap)*rank(operating_income/equity)+0.7*rank(ts_mean(high,5))", "换高动量"),
    ("EbitdaCapOpIncEq_OpenMom_{n}", "rank(ebitda/cap)*rank(operating_income/equity)+0.7*rank(ts_mean(open,5))", "换开动量"),
    ("EbitdaCapOpIncEq_LogVol_{n}", "rank(ebitda/cap)*rank(operating_income/equity)+0.7*rank(log(volume))", "log成交量"),
    
    # ── 非对称乘法 (ratio×裸字段) ──
    ("EbitdaCapDebtHighVol_{n}", "rank(ebitda/cap)*rank(debt/high)+0.7*rank(ts_mean(volume,5))", "新ratio debt/high"),
    ("EbitdaCapOpIncHighVol_{n}", "rank(ebitda/cap)*rank(operating_income/high)+0.7*rank(ts_mean(volume,5))", "新ratio op_inc/high"),
    ("EbitdaCapDebtOpenVol_{n}", "rank(ebitda/cap)*rank(debt/open)+0.7*rank(ts_mean(volume,5))", "新ratio debt/open"),
    
    # ── 近miss调参重试 ──
    ("EbitdaCapDebtVol_d1_{n}", "rank(ebitda/cap)*rank(debt)+0.7*rank(ts_mean(volume,5))", "S=1.16近miss"),
    ("EbitdaCapRevEvVol_d1_{n}", "rank(ebitda/cap)*rank(revenue/enterprise_value)+0.7*rank(ts_mean(volume,5))", "S=1.12近miss"),
]

TRIED_FILE = HOME / ".wq_tried_expressions.json"

def load_tried():
    if TRIED_FILE.exists():
        return json.loads(TRIED_FILE.read_text())
    return {"counter": 0, "tried": [], "next_index": 0}

def save_tried(data):
    TRIED_FILE.write_text(json.dumps(data, indent=2))

def generate_next_batch(count=2):
    """Generate next batch of expressions from the pool, rotating through"""
    tried = load_tried()
    idx = tried["next_index"]
    counter = tried["counter"] + 1
    
    batch = []
    for i in range(count):
        pool_idx = (idx + i) % len(EXPRESSION_POOL)
        entry = EXPRESSION_POOL[pool_idx]
        name = entry[0].replace("{n}", str(counter))
        expr = entry[1]
        batch.append({"name": name, "expr": expr, "settings": "default", "note": entry[2]})
    
    tried["counter"] = counter
    tried["next_index"] = (idx + count) % len(EXPRESSION_POOL)
    tried["tried"].extend([e["name"] for e in batch])
    save_tried(tried)
    
    return batch

# ─── Phase D: Auto-Iterate ────────────────────────────
TARGET_ACTIVE = 20

def phase_d():
    log("=" * 50)
    log("PHASE D: Check & Iterate")
    
    TARGET = TARGET_ACTIVE
    
    s = fresh_session()
    
    # Get current ACTIVE count
    actives = []
    url = f"{API}/users/self/alphas?limit=200&status=ACTIVE"
    while url:
        r = s.get(url, timeout=30)
        if r.status_code != 200:
            log(f"❌ Failed to fetch ACTIVE: {r.status_code}")
            break
        body = r.json()
        for a in body.get("results", []):
            reg = a.get("regular", {})
            expr = reg.get("code", "") if isinstance(reg, dict) else ""
            actives.append({"id": a["id"], "expr": expr[:60]})
        url = body.get("next")
        time.sleep(0.5)
    
    current = len(actives)
    log(f"📊 Current ACTIVE: {current}/{TARGET}")
    
    if current >= TARGET:
        log(f"\n🏆 TARGET REACHED! {current} ACTIVE alphas")
        log("No new batch needed.")
        return
    
    need = TARGET - current
    log(f"Need {need} more ACTIVE")
    
    # Generate next batch
    batch_size = min(3, max(1, need))
    batch = generate_next_batch(batch_size)
    
    log(f"\n🔮 Generating batch #{load_tried()['counter']} ({len(batch)} expressions):")
    for b in batch:
        log(f"  {b['name']}: {b['expr']} ({b.get('note','')})")
    
    # Write expressions file
    DEFAULT_EXPR_FILE.write_text(json.dumps(batch, indent=2))
    log(f"✅ Written to {DEFAULT_EXPR_FILE}")
    
    # Clean state file for next cycle
    state = load_state()
    state["expressions"] = []
    state["phases"] = {"A": "pending", "B": "pending", "C": "pending"}
    state["batch_id"] = f"v{load_tried()['counter']}"
    save_state(state)
    
    # Summary
    log(f"\n📊 Phase D Complete")
    log(f"  Current: {current}/{TARGET} ACTIVE")
    log(f"  Next batch: {len(batch)} expressions")
    log(f"  Next Phase A will auto-kick off at the next scheduled time")
    log(f"\n{'='*20} CYCLE BREAKDOWN {'='*20}")
    for b in batch:
        log(f"  {b['name']}: {b['expr']}")
    log(f"\n🔄 Cycle will auto-repeat until {TARGET} ACTIVE reached")
    log("PHASE D COMPLETE")

if __name__ == "__main__":
    if "--phase" not in sys.argv:
        print("Usage: python3 wq_pipeline.py --phase A|B|C|D [--expressions path.json]")
        sys.exit(1)
    
    phase = sys.argv[sys.argv.index("--phase") + 1].upper()
    expr_path = None
    if "--expressions" in sys.argv:
        idx = sys.argv.index("--expressions")
        expr_path = sys.argv[idx + 1]
    
    if phase == "A":
        phase_a()
    elif phase == "B":
        phase_b()
    elif phase == "C":
        phase_c()
    elif phase == "D":
        phase_d()
    else:
        print(f"Unknown phase: {phase}")
        sys.exit(1)

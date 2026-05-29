#!/usr/bin/env python3
"""
WQ 工作流 v2 — 单进程全链路自适应流水线
============================================

替代：Phase A/B/C/Retry/D + 旧生成 cron，共 6 个定时任务 → 1 个后台进程

流程：
  1. ORTHOGONALITY — 分析 15 ACTIVE 字段使用频率 → 找最低重叠组合
  2. GENERATE — 按正交性分数生成 2-3 候选
  3. QUICK_TEST — 轻量 sim（1年回测期）过滤弱信号
  4. FULL_SIM — 全量 sim + 自适应 IS 轮询
  5. TUNE_IS — IS 不通过则调参/换算子重试
  6. SC_SUBMIT — 提交 SC + 自适应轮询
  7. TUNE_SC — SC≥0.7 则换字段对重试
  8. SUBMIT — 正式提交
  9. LOOP — 直到 20 ACTIVE

状态文件：~/.wq_workflow_v2.json
日志：~/.wq_workflow_v2.log
"""

import json, time, sys, os, ssl, re, signal, logging, traceback, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

import requests, urllib3
urllib3.disable_warnings()
_TLS_CTX = ssl.create_default_context()
_TLS_CTX.check_hostname = False
_TLS_CTX.verify_mode = ssl.CERT_NONE

class _TLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _TLS_CTX
        return super().init_poolmanager(*args, **kwargs)

# ═══ Configuration ═══════════════════════════════════
API = "https://api.worldquantbrain.com"
EMAIL = os.environ.get("WQ_EMAIL", "shufengln@gmail.com")
PASS = os.environ.get("WQ_PASS", "123321sf")
HOME = Path.home()
STATE_FILE = HOME / ".wq_workflow_v2.json"
LOG_FILE = HOME / ".wq_workflow_v2.log"
TARGET_ACTIVE = 20

# ── Default settings ──
DEFAULT_SETTINGS = {
    "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
    "delay": 1, "decay": 2, "neutralization": "INDUSTRY", "truncation": 0.08,
    "pasteurization": "ON", "unitHandling": "VERIFY", "nanHandling": "OFF",
    "language": "FASTEXPR", "visualization": False,
    "startDate": "2019-01-01", "endDate": "2023-12-31", "testPeriod": "P1Y"
}

# Lightweight settings for quick test (1 year, faster)
QUICK_SETTINGS = dict(DEFAULT_SETTINGS)
QUICK_SETTINGS.update({
    "startDate": "2022-01-01", "endDate": "2023-12-31",
    "testPeriod": "P6M", "delay": 1, "decay": 1
})

# ── Field ontology (for orthogonality analysis) ──
# Verified WQ fields (tested in expression engine)
# fundamental6 + pv1 - confirmed working via 80+ historical expressions + field tests
ALL_WQ_FIELDS = [
    # fundamental6
    "revenue", "enterprise_value", "debt", "equity", "operating_income",
    "ebitda", "cap", "cash", "sales",
    # pv1 (price/volume)
    "close", "volume", "adv20", "returns", "vwap", "open", "high", "low",
]

# Operators to recognize in expressions (for orthogonality analysis of structure)
ALL_WQ_OPERATORS = [
    "rank", "ts_mean", "ts_sum", "ts_std", "ts_corr", "ts_rank",
    "ts_min", "ts_max", "ts_argmin", "ts_argmax", "ts_zscore",
    "ts_delta", "ts_trend", "ts_percentile", "scale", "group_rank",
    "log", "sign", "abs", "max", "min", "clip", "ind_neutral",
    "sector_neutral", "zscore", "winsorize", "truncate",
]

FIELD_PATTERN = re.compile(r'\b(' + '|'.join(re.escape(f) for f in ALL_WQ_FIELDS) + r')\b')
RATIO_PATTERN = re.compile(r'\b(' + '|'.join(re.escape(f) for f in ALL_WQ_FIELDS) + r')/(' + '|'.join(re.escape(f) for f in ALL_WQ_FIELDS) + r')')

# ── Field time-frequency compatibility groups ──
# Mixing daily-updated (pv1) with quarterly-updated (fundamental6) fields in ratio pairs
# causes NA coverage misalignment → S=None in WQ engine
PV1_FIELDS = {"close", "volume", "adv20", "returns", "vwap", "open", "high", "low"}
FUND_FIELDS = {"revenue", "enterprise_value", "debt", "equity", "operating_income", "ebitda", "cap", "cash", "sales"}

# AST structure skeleton types (for collision detection)
# Same-skeleton over-use triggers WQ low-correlation penalty
SKELETON_MULT = "mult_ratio"   # rank(A/B)*rank(C/D) + W*rank(M)
SKELETON_SUB = "sub_delta"     # rank(X) - rank(ts_delta(Y,N))
SKELETON_SINGLE = "single"     # single factor: rank(ts_rank(X,N))

# Proven field pairs (verified by IS PASS history in this account)
VERIFIED_NUM_DEN_PAIRS = [
    ("revenue", "enterprise_value"),  # 78JZ5zQO
    ("debt", "equity"),               # 78JZ5zQO
    ("revenue", "cap"),               # omVljNem
    ("operating_income", "cap"),      # omVljNem
    ("revenue", "equity"),            # rKA3vKra
    ("operating_income", "equity"),   # E5kZ7p60
    ("debt", "enterprise_value"),     # omnl5gGv
    ("ebitda", "cap"),                # verified v0529_1609
    ("ebitda", "enterprise_value"),   # verified
    ("sales", "enterprise_value"),    # verified
    ("sales", "cap"),                 # verified
    ("cash", "enterprise_value"),     # verified
    ("cash", "cap"),                  # verified
]

# ═══ Logging ═══════════════════════════════════════
logger = logging.getLogger("wq_v2")
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(str(LOG_FILE), mode="a")
_fh.setFormatter(logging.Formatter('%(asctime)s|%(levelname)s|%(message)s', datefmt='%m-%d %H:%M:%S'))
_logger = logging.StreamHandler()
_logger.setFormatter(logging.Formatter('%(asctime)s|%(message)s', datefmt='%H:%M:%S'))
logger.addHandler(_fh)
logger.addHandler(_logger)

def log(msg, level="info"):
    getattr(logger, level, logger.info)(msg)

# ═══ State Management ═════════════════════════════
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "status": "idle",
        "phase": "init",
        "current_batch": [],
        "batch_idx": 0,
        "active_count": 0,
        "actives_data": [],
        "fields_used": {},
        "candidates_generated": 0,
        "candidates_passed_is": 0,
        "candidates_passed_sc": 0,
        "candidates_submitted": 0,
        "iterations": 0,
        "errors": [],
        "started_at": None,
        "last_updated": None,
    }

def save_state(state: dict):
    state["last_updated"] = datetime.now().isoformat()
    # Truncate errors to last 20 to prevent file bloat
    if len(state.get("errors", [])) > 20:
        state["errors"] = state["errors"][-20:]
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

# ═══ Session ═══════════════════════════════════════
def fresh_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _TLSAdapter())
    s.verify = False
    s.trust_env = False
    import os
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "http://127.0.0.1:7897"
    s.proxies = {"http": proxy, "https": proxy}
    r = s.post(f"{API}/authentication", auth=(EMAIL, PASS), timeout=60)
    if r.status_code == 201:
        log("🔐 Auth OK")
        return s
    raise RuntimeError(f"Auth failed: {r.status_code} {r.text[:200]}")

# ═══ ORTHOGONALITY ANALYSIS ═══════════════════════
def fetch_active_alphas(s: requests.Session) -> list:
    """Fetch all ACTIVE alphas with expressions"""
    alphas = []
    url = f"{API}/users/self/alphas?limit=200&status=ACTIVE"
    while url:
        r = s.get(url, timeout=30)
        if r.status_code != 200:
            log(f"❌ Fetch ACTIVE: HTTP {r.status_code}", "error")
            break
        body = r.json()
        for a in body.get("results", []):
            reg = a.get("regular", {})
            expr = reg.get("code", "") if isinstance(reg, dict) else ""
            alphas.append({"id": a["id"], "expr": expr, "name": a.get("name", "")})
        url = body.get("next")
        time.sleep(0.3)
    log(f"📊 Found {len(alphas)} ACTIVE alphas")
    return alphas

def analyze_orthogonality(alphas: list) -> dict:
    """
    Parse all ACTIVE expressions → field usage frequency map + structure types.
    
    Returns:
        fields_used: {field: count_of_actives_using_it}
        structures: list of (type, fields_used)
        field_pairs_used: set of frozensets of field pairs used in ratio/expression
    """
    fields_used = {f: 0 for f in ALL_WQ_FIELDS}
    structures = []
    field_pairs_used = set()
    
    for a in alphas:
        expr = a["expr"]
        # Extract all fields
        fields = set(FIELD_PATTERN.findall(expr))
        for f in fields:
            if f in fields_used:
                fields_used[f] += 1
        
        # Determine structure type
        subtracted = False
        multiplied = False
        has_ratio = bool(RATIO_PATTERN.search(expr))
        
        if "*" in expr and "+" in expr:
            multiplied = True
        elif "*" in expr and "+" not in expr:
            multiplied = True
        elif "-" in expr:
            subtracted = True
        
        if subtracted:
            struct_type = "subtraction"
        elif multiplied:
            if has_ratio:
                struct_type = "multiplication_ratio"
            else:
                struct_type = "multiplication_field"
        else:
            struct_type = "unknown"
        
        structures.append({"type": struct_type, "fields": fields, "expr": expr[:80]})
        
        # Extract field pairs from ratios
        for m in RATIO_PATTERN.finditer(expr):
            pair = frozenset([m.group(1), m.group(2)])
            field_pairs_used.add(pair)
    
    # Sort fields by usage (most used first)
    sorted_fields = sorted(fields_used.items(), key=lambda x: -x[1])
    
    log(f"\n📊 ORTHOGONALITY ANALYSIS:")
    log(f"  Structures: {sum(1 for s in structures if s['type']=='subtraction')} subtraction, "
        f"{sum(1 for s in structures if s['type']=='multiplication_ratio')} multiplication")
    
    # Show 0-usage fields
    zero_usage = [f for f, c in sorted_fields if c == 0]
    low_usage = [f for f, c in sorted_fields if c == 1]
    log(f"  ⬜ 0-usage fields ({len(zero_usage)}): {', '.join(zero_usage[:10])}")
    log(f"  🔵 1-usage fields ({len(low_usage)}): {', '.join(low_usage[:10])}")
    
    return {
        "fields_used": fields_used,
        "structures": structures,
        "field_pairs_used": field_pairs_used,
        "zero_usage_fields": zero_usage,
        "low_usage_fields": low_usage,
        "subtraction_count": sum(1 for s in structures if s['type']=='subtraction'),
        "multiplication_count": sum(1 for s in structures if s['type']=='multiplication_ratio'),
    }

# ═══ CANDIDATE GENERATION (Orthogonality-Driven) ══
def score_candidate_orthogonality(expr: str, ortho: dict, active_exprs: list) -> float:
    """
    Score a candidate expression for orthogonality against existing ACTIVE.
    Higher = more orthogonal (better SC prospects).
    
    v3: Structure-agnostic scoring with AST-level collision penalty.
    """
    fields = set(FIELD_PATTERN.findall(expr))
    field_usage = ortho["fields_used"]
    
    # Base score: sum of inverse usage frequency
    novelty_score = 0
    for f in fields:
        usage = field_usage.get(f, 0)
        if usage == 0:
            novelty_score += 8  # Unused fields
        elif usage == 1:
            novelty_score += 4
        elif usage == 2:
            novelty_score += 2
        else:
            novelty_score += 0.5
    
    # Penalty for reused field pairs
    for pair in ortho["field_pairs_used"]:
        for m in RATIO_PATTERN.finditer(expr):
            candidate_pair = frozenset([m.group(1), m.group(2)])
            if candidate_pair == pair:
                novelty_score -= 3
    
    # ── AST structure collision penalty ──
    # Count how many existing actives use the same skeleton
    mult_pattern = re.compile(r'rank\([^)]+\)\*rank\([^)]+\)\+')
    sub_pattern = re.compile(r'rank\([^)]+\)\s*-\s*rank\(')
    
    has_mult = bool(mult_pattern.search(expr))
    has_sub = bool(sub_pattern.search(expr))
    
    mult_count = ortho.get("multiplication_count", 0)
    sub_count = ortho.get("subtraction_count", 0)
    
    # Penalize generating into an already-crowded skeleton
    if has_mult and mult_count >= 2:
        novelty_score -= 5  # Heavy penalty: multiplication skeleton already crowded
    elif has_sub and sub_count >= 5:
        novelty_score -= 3  # Subtraction also getting crowded
    
    return novelty_score

def _get_field_group(field: str) -> str:
    """Return 'pv1', 'fund', or 'other' for time-frequency compatibility."""
    if field in PV1_FIELDS:
        return "pv1"
    if field in FUND_FIELDS:
        return "fund"
    return "other"

def _get_skeleton_type(expr: str) -> str:
    """Classify an expression into AST skeleton type."""
    mult_pattern = re.compile(r'rank\([^)]+\)\*rank\([^)]+\)\+')
    sub_pattern = re.compile(r'rank\([^)]+\)\s*-\s*rank\(')
    if mult_pattern.search(expr):
        return SKELETON_MULT
    if sub_pattern.search(expr):
        return SKELETON_SUB
    return SKELETON_SINGLE

def _build_ratio_pool(ortho: dict) -> list:
    """
    Build list of (expr_str, name) for ratio pairs, filtered by:
    1. Time-frequency compatibility (no pv1/fund mixing)
    2. Field usage < threshold
    3. Unused pair
    """
    field_usage = ortho["fields_used"]
    used_pairs = ortho["field_pairs_used"]
    
    # Priority: verified pairs (known working), then low-usage fields
    pool = []
    seen = set()
    
    # First pass: verified pairs from history
    for num, den in VERIFIED_NUM_DEN_PAIRS:
        num_group = _get_field_group(num)
        den_group = _get_field_group(den)
        if num_group != den_group:
            continue  # Time-frequency mismatch
        key = frozenset([num, den])
        if key in used_pairs:
            continue  # Already used by active
        if key in seen:
            continue
        seen.add(key)
        pool.append((f"rank({num}/{den})", f"{num}_{den}"))
    
    # Second pass: low-usage fields (0-1 usage)
    usage_sorted = sorted(field_usage.items(), key=lambda x: x[1])
    for f, c in usage_sorted:
        if c > 1 or f == "close":
            continue
        for den in ["cap", "enterprise_value", "equity"]:
            if den == f:
                continue
            g1 = _get_field_group(f)
            g2 = _get_field_group(den)
            if g1 != g2:
                continue
            key = frozenset([f, den])
            if key in used_pairs or key in seen:
                continue
            seen.add(key)
            pool.append((f"rank({f}/{den})", f"{f}_{den}"))
    
    # Third pass: zero-usage fields
    zero = ortho.get("zero_usage_fields", [])
    for f in zero[:6]:
        for den in ["cap", "enterprise_value", "equity"]:
            if den == f:
                continue
            g1 = _get_field_group(f)
            g2 = _get_field_group(den)
            if g1 != g2:
                continue
            key = frozenset([f, den])
            if key in seen:
                continue
            seen.add(key)
            pool.append((f"rank({f}/{den})", f"{f}_{den}"))
    
    return pool

def _generate_mult_candidates(ratio_pool: list, ortho: dict, active_exprs: list) -> list:
    """Generate multiplication skeleton candidates: rank(A/B)*rank(C/D)+W*rank(M)."""
    candidates = []
    momentums = [
        ("ts_mean(volume,5)", "vol_mom"),
        ("ts_mean(adv20,5)", "adv_mom"),
        ("ts_std(returns,5)", "ret_vol"),
        ("ts_corr(close,volume,10)", "pv_corr"),
        ("ts_zscore(volume,5)", "vol_zsc"),
        ("ts_mean(returns,5)", "ret_tre"),
    ]
    seen = set()
    for (r1_str, r1_name) in ratio_pool[:5]:
        r1_fields = set(FIELD_PATTERN.findall(r1_str))
        for (r2_str, r2_name) in ratio_pool[:5]:
            if r1_str == r2_str:
                continue
            r2_fields = set(FIELD_PATTERN.findall(r2_str))
            if r1_fields & r2_fields:
                continue
            # Check group compatibility: both ratios must be same group
            all_groups = {_get_field_group(f) for f in (r1_fields | r2_fields)}
            if len(all_groups) > 1:
                continue
            for mom_str, mom_name in momentums[:3]:
                for w in [0.3, 0.5, 0.7]:
                    expr = f"{r1_str}*{r2_str}+{w}*rank({mom_str})"
                    if expr in seen:
                        continue
                    seen.add(expr)
                    score = score_candidate_orthogonality(expr, ortho, active_exprs)
                    name = f"M_{r1_name}_{r2_name}_{mom_name}_w{int(w*10)}"[:40]
                    name = name.replace("-","_").replace(" ","")
                    candidates.append({
                        "name": name, "expr": expr,
                        "orthogonality_score": score,
                        "skeleton": SKELETON_MULT,
                        "weight": w,
                    })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates

def _generate_sub_candidates(ratio_pool: list, ortho: dict, active_exprs: list) -> list:
    """Generate subtraction skeleton candidates: rank(A/B) - rank(ts_*(C,N))."""
    candidates = []
    subtractions = [
        ("ts_delta(close,10)", "delta_close_10"),
        ("ts_delta(close,20)", "delta_close_20"),
        ("ts_delta(volume,5)", "delta_vol_5"),
        ("ts_delta(adv20,5)", "delta_adv_5"),
        ("ts_delta(returns,5)", "delta_ret_5"),
        ("ts_std(returns,10)", "std_ret_10"),
        ("ts_std(adv20,10)", "std_adv_10"),
        ("ts_zscore(volume,10)", "zsc_vol_10"),
        ("ts_corr(close,volume,20)", "corr_pv_20"),
    ]
    seen = set()
    for (ratio_str, ratio_name) in ratio_pool[:5]:
        for sub_str, sub_name in subtractions[:5]:
            expr = f"{ratio_str} - rank({sub_str})"
            if expr in seen:
                continue
            seen.add(expr)
            score = score_candidate_orthogonality(expr, ortho, active_exprs)
            name = f"S_{ratio_name}_{sub_name}"[:40]
            name = name.replace("-","_").replace(" ","")
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": score,
                "skeleton": SKELETON_SUB,
                "weight": 0.5,
            })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates

def generate_candidates(ortho: dict, active_exprs: list, n: int = 3) -> list:
    """
    v3: AST-aware candidate generation with time-frequency filtering.
    
    Decision tree:
    1. If multiplication skeleton < 2 in active → generate MULT candidates
    2. If multiplication >= 2 → generate SUB candidates instead
    3. Final selection: pick top-n with diverse ratio pairs
    
    Never mixes pv1 and fundamental fields in the same ratio pair.
    Never reuses exact field pairs from active alphas.
    """
    ratio_pool = _build_ratio_pool(ortho)
    
    if not ratio_pool:
        log("  ⚠️ No ratio pairs available for generation!")
        return []
    
    mult_count = ortho.get("multiplication_count", 0)
    sub_count = ortho.get("subtraction_count", 0)
    
    log(f"  🏗 AST structure balance: {mult_count} mult / {sub_count} sub in active")
    
    # Decision: which skeleton to generate?
    use_mult = mult_count < 2  # Prefer multiplication if < 2 exist
    use_sub = not use_mult and sub_count < 6  # Fall back to subtraction
    
    all_candidates = []
    
    if use_mult:
        log("  🟢 Generating MULTIPLICATION candidates (skeleton under-utilized)")
        all_candidates = _generate_mult_candidates(ratio_pool, ortho, active_exprs)
    
    if use_sub:
        log("  🔵 Generating SUBTRACTION candidates (multiplication saturated)")
        sub_candidates = _generate_sub_candidates(ratio_pool, ortho, active_exprs)
        all_candidates.extend(sub_candidates)
    
    if not all_candidates:
        log("  ⚠️ No candidates generated!")
        return []
    
    # Deduplicate by expression
    seen_exprs = set()
    deduped = []
    for c in all_candidates:
        if c["expr"] in seen_exprs:
            continue
        seen_exprs.add(c["expr"])
        deduped.append(c)
    
    # Sort by orthogonality score
    deduped.sort(key=lambda x: -x["orthogonality_score"])
    
    # Final selection: top-n, ensuring skeleton diversity
    result = []
    seen_skeletons = set()
    for c in deduped:
        if len(result) >= n:
            break
        # Prefer diverse skeletons
        sk = c.get("skeleton", "")
        if sk in seen_skeletons and len(seen_skeletons) < 2 and len([x for x in deduped if x.get("skeleton") != sk]) > 0:
            # Skip if we already have this skeleton and there's a different one available
            # But accept if we've exhausted other skeletons
            continue
        seen_skeletons.add(sk)
        result.append(c)
    
    # Fill remaining slots if we had skeleton diversity constraint
    if len(result) < n:
        for c in deduped:
            if len(result) >= n:
                break
            if c not in result:
                result.append(c)
    
    for c in result:
        log(f"  🎯 [{c.get('skeleton','?')[:4].upper()}] {c['name']}")
        log(f"        expr: {c['expr']}")
        log(f"        ortho_score: {c['orthogonality_score']:.1f}")
    
    return result

# ═══ ADAPTIVE POLLING ════════════════════════════
def adaptive_poll(session, url: str, poll_name: str,
                   success_condition, max_wait: int = 1800,
                   initial_interval: float = 10,
                   fallback_interval: float = 60,
                   stuck_threshold: int = 0) -> Optional[Any]:
    """
    Adaptive polling: fast at first, slow down over time.
    stuck_threshold: if > 0 and progress stays at 0 for this many secs, abort.
    Returns the value from success_condition when met, or None on timeout/stuck.
    """
    start = time.time()
    interval = initial_interval
    last_slowdown = start
    last_progress = 0
    stuck_since = None
    
    log(f"⏳ Polling {poll_name} (max {max_wait}s, start every {initial_interval}s)")
    
    while time.time() - start < max_wait:
        elapsed = time.time() - start
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 200:
                data = r.json()
                result = success_condition(data)
                if result is not None:
                    log(f"✅ {poll_name}: resolved in {elapsed:.0f}s")
                    return result
                
                # Log progress if available
                pct = data.get("progress", 0)
                if isinstance(pct, (int, float)) and pct < 1.0:
                    pct_pct = pct * 100
                else:
                    pct_pct = None
                
                if pct_pct is not None and time.time() - last_slowdown > 30:
                    log(f"⏳ {poll_name}: {pct_pct:.0f}% ({elapsed:.0f}s)")
                
                # Stuck detection: if progress stuck at 0 past threshold, abort
                if stuck_threshold > 0 and isinstance(pct, (int, float)):
                    if pct == 0 and elapsed > 30:
                        if stuck_since is None:
                            stuck_since = time.time()
                        elif time.time() - stuck_since > stuck_threshold:
                            log(f"❌ {poll_name}: stuck at 0% for {stuck_threshold}s, aborting", "error")
                            return None
                    else:
                        stuck_since = None  # progress moved, reset
            elif r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 60))
                log(f"⚠️ 429: waiting {retry}s")
                time.sleep(retry)
                continue
        except Exception as e:
            log(f"⚠️ Poll error: {e}")
            # Transient error: retry after short delay, don't sleep full interval
            time.sleep(5)
            continue
        
        # Adaptive interval: every 2 min without result, back off
        if elapsed > 120 and interval < fallback_interval:
            interval = fallback_interval
            last_slowdown = time.time()
            log(f"🐢 {poll_name}: slowing to every {interval}s")
        
        if elapsed > 600 and interval < 120:
            interval = 120
            log(f"🐢 {poll_name}: slowing to every 120s")
        
        time.sleep(interval)
    
    log(f"❌ {poll_name}: TIMEOUT ({max_wait}s)", "error")
    return None


# ═══ Notification — ZERO LLM tokens, pure HTTP POST ══
_FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
_FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
_FEISHU_OPEN_ID = "ou_51323a303e1343ca0fb0f9a7fd4d8452"
_FEISHU_TOKEN_CACHE = {"token": "", "expires": 0}
_NOTIFY_COOLDOWN = {}  # prevent spam within same event

def _feishu_token() -> str:
    """Get Feishu tenant_access_token (cached, valid 2h). Zero LLM cost."""
    now = time.time()
    if _FEISHU_TOKEN_CACHE["token"] and now < _FEISHU_TOKEN_CACHE["expires"] - 60:
        return _FEISHU_TOKEN_CACHE["token"]
    try:
        r = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": _FEISHU_APP_ID, "app_secret": _FEISHU_APP_SECRET},
            timeout=15
        )
        if r.status_code == 200:
            d = r.json()
            _FEISHU_TOKEN_CACHE["token"] = d.get("tenant_access_token", "")
            _FEISHU_TOKEN_CACHE["expires"] = now + d.get("expire", 7100)
            return _FEISHU_TOKEN_CACHE["token"]
    except:
        pass
    return ""

def notify(message: str, emoji: str = "ℹ️", dedup_key: str = None):
    """Send Feishu DM notification. Zero LLM token cost - pure REST API call."""
    if not _FEISHU_APP_ID or not _FEISHU_APP_SECRET:
        log(f"📬 Notify: {emoji} {message[:60]} (no Feishu configured)")
        return
    
    # Deduplicate: same key within 30s = skip
    if dedup_key:
        now = time.time()
        if dedup_key in _NOTIFY_COOLDOWN and now - _NOTIFY_COOLDOWN[dedup_key] < 30:
            return
        _NOTIFY_COOLDOWN[dedup_key] = now
    
    token = _feishu_token()
    if not token:
        log("📬 Notify: failed to get Feishu token")
        return
    
    try:
        text = f"WQ Workflow\n{emoji} {message}"
        content = json.dumps({"text": text})
        r = requests.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}"},
            json={"receive_id": _FEISHU_OPEN_ID, "msg_type": "text", "content": content},
            timeout=15
        )
        if r.status_code == 200:
            log(f"📬 Notify sent: {emoji} {message[:50]}")
        else:
            log(f"📬 Notify: HTTP {r.status_code} {r.text[:80]}")
    except Exception as e:
        log(f"📬 Notify error: {e}")


# ═══ WORKFLOW PHASES ══════════════════════════════
class Workflow:
    """Main workflow orchestrator"""
    
    def __init__(self):
        self.state = load_state()
        self.s = None
        self.running = True
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
    
    def _handle_signal(self, sig, frame):
        log(f"\n⚠️ Received signal {sig}, shutting down gracefully...")
        self.running = False
        self.state["status"] = "paused"
        save_state(self.state)
        os._exit(0)
    
    def save_checkpoint(self):
        save_state(self.state)
    
    def run(self):
        """Main loop — continues until 20 ACTIVE or interrupted"""
        log("=" * 60)
        log("🚀 WQ Workflow v2 started")
        self.state["status"] = "running"
        self.state["started_at"] = self.state.get("started_at") or datetime.now().isoformat()
        self.save_checkpoint()
        retry_attempt = 0
        
        while self.running:
            try:
                self.s = fresh_session()
                retry_attempt = 0  # reset on success
                self._main_loop()
            except Exception as e:
                log(f"💥 Session error: {e}", "error")
                log(traceback.format_exc())
                self.state["errors"].append(str(e))
                self.save_checkpoint()
                # Exponential backoff: 30s → 60s → 120s → 240s → caps at 300s
                retry_attempt += 1
                backoff = min(30 * (2 ** (retry_attempt - 1)), 300)
                log(f"🔄 Retry {retry_attempt} in {backoff}s...")
                time.sleep(backoff)
                continue
    
    def _main_loop(self):
        while self.running:
            # 1. Check current ACTIVE count
            actives = fetch_active_alphas(self.s)
            active_count = len(actives)
            self.state["active_count"] = active_count
            self.state["actives_data"] = [{"id": a["id"], "expr": a["expr"][:80]} for a in actives]
            
            log(f"\n{'='*50}")
            log(f"📊 Current: {active_count}/{TARGET_ACTIVE} ACTIVE")
            
            if active_count >= TARGET_ACTIVE:
                log(f"\n🏆 TARGET REACHED! {active_count} ACTIVE alphas")
                self.state["status"] = "done"
                self.save_checkpoint()
                return
            
            # 2. Orthogonality analysis
            ortho = analyze_orthogonality(actives)
            self.state["fields_used"] = ortho["fields_used"]
            self.state["phase"] = "orthogonality"
            self.save_checkpoint()
            
            # 3. Generate candidates
            candidates = generate_candidates(ortho, [a["expr"] for a in actives], n=3)
            if not candidates:
                log("❌ No candidates generated — platform may need new data sources", "error")
                time.sleep(3600)
                continue
            
            self.state["current_batch"] = candidates
            self.state["batch_idx"] = 0
            self.state["phase"] = "generate"
            self.save_checkpoint()
            
            # 4. Process each candidate
            for idx, cand in enumerate(candidates):
                if not self.running:
                    return
                log(f"\n{'='*50}")
                log(f"🎯 Processing candidate {idx+1}/{len(candidates)}: {cand['name']}")
                
                self.state["batch_idx"] = idx
                self.state["phase"] = "quick_test"
                self.save_checkpoint()
                
                # ── 4a. QUICK TEST — fast 1-year filter ──
                if not self._quick_test(cand):
                    log(f"⏩ {cand['name']}: quick test failed, skip (S<1.0)")
                    continue
                
                # ── 4b. FULL SIM → Adaptive IS Poll ──
                self.state["phase"] = "full_sim"
                self.save_checkpoint()
                success = self._run_full_sim(cand)
                if not success:
                    log(f"❌ {cand['name']}: IS failed, trying tune...")
                    success = self._tune_and_retry(cand, ortho, "is")
                    if not success:
                        log(f"✖️ {cand['name']}: all IS variations failed, skip")
                        notify(f"候选失败 ✖️ {cand['name']}\nIS {cand.get('sharpe','?')}/{cand.get('fitness','?')}，调参重试后仍失败",
                               emoji="⚠️", dedup_key=f"cand_fail_{cand.get('alpha_id','')}")
                        continue
                
                # ── 4b. SC SUBMIT → Adaptive SC Poll ──
                self.state["phase"] = "sc_submit"
                self.save_checkpoint()
                success = self._run_sc(cand)
                if not success:
                    log(f"❌ {cand['name']}: SC failed ({cand.get('sc_value', '?')})")
                    log(f"   Trying SC tune (different fields)...")
                    success = self._tune_and_retry(cand, ortho, "sc")
                    if not success:
                        log(f"✖️ {cand['name']}: all SC variations failed, skip")
                        notify(f"SC耗尽 ✖️ {cand['name']}\nSC={cand.get('sc_value','?')}，换字段调参后仍失败",
                               emoji="⚠️", dedup_key=f"sc_fail_{cand.get('alpha_id','')}")
                        continue
                
                # ── 4c. SUBMIT ──
                self.state["phase"] = "submit"
                self.save_checkpoint()
                self._submit_alpha(cand, cand.get("alpha_id"))
        
        # After batch done, save and loop back
        self.state["candidates_generated"] += len(candidates)
        self.state["iterations"] += 1
        self.save_checkpoint()
        
        log(f"\n🔄 Batch complete. Current: {self.state['active_count']}/{TARGET_ACTIVE}")
        log("Restarting orthogonality analysis for next batch...")
    
    def _quick_test(self, cand: dict) -> bool:
        """Quick 1-year sim to filter weak signals before full sim"""
        payload = {"type": "REGULAR", "regular": cand["expr"], "settings": QUICK_SETTINGS}
        try:
            r = self.s.post(f"{API}/simulations", json=payload, timeout=60)
        except Exception as e:
            log(f"⏩ Quick test POST failed: {e}", "error")
            return True  # pass through on error, let full sim decide
        if r.status_code != 201:
            log(f"⏩ Quick test: HTTP {r.status_code}", "error")
            return True
        sim_id = r.headers.get("Location", "").split("/")[-1]

        def quick_ready(data):
            return data.get("alpha") if data.get("alpha") else None

        alpha_id = adaptive_poll(
            self.s, f"{API}/simulations/{sim_id}",
            f"Quick {cand['name']}",
            quick_ready, max_wait=600,
            initial_interval=10, fallback_interval=30,
        )
        if not alpha_id:
            log(f"⏩ Quick test: timeout, pass through")
            return True
        # Fetch IS stats
        r2 = self.s.get(f"{API}/alphas/{alpha_id}", timeout=30)
        if r2.status_code != 200:
            return True
        body = r2.json()
        stats = body.get("is", {}).get("statistics", {}) if isinstance(body.get("is"), dict) else {}
        sharpe = stats.get("sharpe")
        log(f"⏩ Quick test: S={sharpe}")
        # Pass through: only reject if S is clearly bad (not None and < 1.0)
        if sharpe is not None and sharpe < 1.0:
            log(f"⏩ Quick test: S={sharpe:.2f} < 1.0, skipping")
            return False
        log(f"⏩ Quick test: S={sharpe} >= 1.0, proceeding to full sim")
        return True

    def _run_full_sim(self, cand: dict) -> bool:
        """Create full sim → adaptive IS poll"""
        payload = {"type": "REGULAR", "regular": cand["expr"], "settings": DEFAULT_SETTINGS}

        try:
            r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
        except Exception as e:
            log(f"❌ POST sim failed: {e}", "error")
            cand["error"] = str(e)
            return False

        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", 900))
            log(f"⚠️ 429: waiting {min(retry, 120)}s")
            time.sleep(min(retry, 120))
            try:
                r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
            except Exception as e:
                log(f"❌ Retry failed: {e}", "error")
                return False

        if r.status_code != 201:
            log(f"❌ Sim create: HTTP {r.status_code} {r.text[:100]}", "error")
            return False

        sim_id = r.headers.get("Location", "").split("/")[-1]
        cand["sim_id"] = sim_id
        log(f"📝 sim_id={sim_id}")

        def is_ready(data):
            alpha_id = data.get("alpha")
            if alpha_id:
                return alpha_id
            return None

        alpha_id = adaptive_poll(
            self.s, f"{API}/simulations/{sim_id}",
            f"IS {cand['name']}",
            is_ready, max_wait=3600,
            initial_interval=15, fallback_interval=60,
            stuck_threshold=300
        )

        if not alpha_id:
            cand["is_status"] = "TIMEOUT"
            return False

        cand["alpha_id"] = alpha_id
        log(f"✅ sim resolved: alpha_id={alpha_id}")

        r2 = self.s.get(f"{API}/alphas/{alpha_id}", timeout=30)
        if r2.status_code != 200:
            log(f"⚠️ Fetch alpha: HTTP {r2.status_code}")
            return False

        ad = r2.json()
        checks = ad.get("is", {}).get("checks", []) if isinstance(ad.get("is"), dict) else []
        stats = ad.get("is", {}).get("statistics", {}) if isinstance(ad.get("is"), dict) else {}

        cand["sharpe"] = stats.get("sharpe")
        cand["fitness"] = stats.get("fitness")

        passes = sum(1 for c in checks if c.get("result") == "PASS")
        fails = sum(1 for c in checks if c.get("result") == "FAIL")

        is_pass = (fails == 0 and passes >= 7)
        cand["is_status"] = "PASS" if is_pass else "FAIL"

        log(f"📊 IS: S={cand['sharpe']} F={cand['fitness']} | {passes}P/{fails}F | {cand['is_status']}")

        if is_pass:
            notify(f"IS PASS ✅ {cand['name']}\nS={cand['sharpe']} F={cand['fitness']}\n{cand['expr'][:80]}",
                   emoji="✅", dedup_key=f"is_{cand.get('alpha_id','')}")
            try:
                self.s.patch(f"{API}/alphas/{alpha_id}",
                    json={"name": cand["name"], "color": "GREEN",
                          "category": "FUNDAMENTAL", "tags": ["workflow-v2"]}, timeout=15)
            except:
                pass

        return is_pass
    
    def _run_sc(self, cand: dict) -> bool:
        """Submit SC → adaptive SC poll"""
        alpha_id = cand.get("alpha_id")
        if not alpha_id:
            return False
        
        log(f"📬 Submitting SC for {alpha_id}...")
        
        try:
            r = self.s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
        except Exception as e:
            log(f"❌ SC submit: {e}", "error")
            return False
        
        if r.status_code in (200, 201, 202):
            log(f"   SC submitted (HTTP {r.status_code})")
        elif r.status_code == 403:
            # SC already computed
            try:
                body = r.json()
                checks = body.get("is", {}).get("checks", []) if isinstance(body.get("is"), dict) else []
                sc = next((c for c in checks if c["name"] == "SELF_CORRELATION"), None)
                if sc and sc.get("result") != "PENDING":
                    cand["sc_value"] = sc.get("value")
                    cand["sc_result"] = sc.get("result")
                    log(f"   SC={sc.get('value')} (from 403)")
                    return sc.get("result") == "PASS"
            except: pass
            log(f"   403 but no SC yet, polling...")
        else:
            log(f"❌ SC submit: HTTP {r.status_code} {r.text[:100]}", "error")
            return False
        
        # Adaptive SC poll
        def sc_ready(data):
            checks_data = data.get("is", {}).get("checks", []) if isinstance(data.get("is"), dict) else []
            sc = next((c for c in checks_data if c["name"] == "SELF_CORRELATION"), None)
            if sc and sc.get("result") != "PENDING":
                return sc
            if data.get("status") == "ACTIVE":
                return {"result": "PASS", "value": 0}
            return None
        
        sc_result = adaptive_poll(
            self.s, f"{API}/alphas/{alpha_id}",
            f"SC {cand['name']}",
            sc_ready, max_wait=3600,  # 1 hour max
            initial_interval=30, fallback_interval=120
        )
        
        if not sc_result:
            # Try 403 probe as fallback
            try:
                r3 = self.s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
                if r3.status_code == 403:
                    body = r3.json()
                    checks = body.get("is", {}).get("checks", []) if isinstance(body.get("is"), dict) else []
                    sc = next((c for c in checks if c["name"] == "SELF_CORRELATION"), None)
                    if sc:
                        sc_result = sc
            except: pass
        
        if not sc_result:
            cand["sc_result"] = "TIMEOUT"
            return False
        
        cand["sc_value"] = sc_result.get("value")
        cand["sc_result"] = sc_result.get("result")
        is_pass = sc_result.get("result") == "PASS"
        
        log(f"📊 SC={cand['sc_value']} result={cand['sc_result']}")
        if is_pass:
            notify(f"SC通过 ✅ {cand['name']}\nSC={cand['sc_value']}\n{cand['expr'][:60]}",
                   emoji="✅", dedup_key=f"sc_{cand.get('alpha_id','')}")
        return is_pass
    
    def _submit_alpha(self, cand: dict, alpha_id: str):
        """Submit the alpha to formal pool"""
        if not alpha_id:
            log(f"❌ No alpha_id to submit", "error")
            return
        
        log(f"📬 Submitting {alpha_id} ({cand['name']})...")
        
        try:
            r = self.s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
        except Exception as e:
            log(f"❌ Submit failed: {e}", "error")
            return
        
        if r.status_code in (200, 201, 202):
            log(f"✅ Submitted! status={r.status_code}")
            cand["submitted"] = True
            self.state["candidates_submitted"] = self.state.get("candidates_submitted", 0) + 1
            self.state["candidates_passed_is"] = self.state.get("candidates_passed_is", 0) + 1
            self.state["candidates_passed_sc"] = self.state.get("candidates_passed_sc", 0) + 1
            self.save_checkpoint()
            
            log(f"\n{'='*50}")
            log(f"🎉 NEW ACTIVE: {cand['name']}")
            log(f"   expr: {cand['expr']}")
            log(f"   S={cand.get('sharpe')} F={cand.get('fitness')} SC={cand.get('sc_value')}")
            log(f"{'='*50}")
            notify(f"新ACTIVE 🎉 {cand['name']}\nS={cand.get('sharpe')} F={cand.get('fitness')} SC={cand.get('sc_value')}\n{cand['expr'][:60]}",
                   emoji="🎉", dedup_key=f"active_{cand.get('alpha_id','')}")
        else:
            log(f"❌ Submit: HTTP {r.status_code} {r.text[:100]}", "error")
    
    def _tune_and_retry(self, cand: dict, ortho: dict, failed_phase: str) -> bool:
        """
        Generate tuned variations of a candidate and retry.
        failed_phase: "is" or "sc"
        """
        max_tune_attempts = 5  # Up to 5 tuning attempts per candidate
        variations = []
        
        base_expr = cand["expr"]
        base_name = cand["name"]
        weight = cand.get("weight", 0.7)
        
        log(f"\n🔧 Tuning {failed_phase.upper()} for {base_name}...")
        
        if failed_phase == "is":
            # IS failure: try different operators and weight adjustments
            # If S < 1.25, the ratio pair signal is weak. Try different operators
            
            # Variation 1: Different momentum operator
            mom_variants = [
                ("rank(ts_mean(volume,5))", "vol_mom"),
                ("rank(ts_std(returns,5))", "ret_vol"),
                ("rank(ts_mean(adv20,5))", "adv_mom"),
                ("rank(log(adv20))", "log_adv"),
                ("rank(ts_mean(low,5))", "low_mom"),
                ("rank(ts_corr(close,volume,10))", "corr_cv"),
            ]
            
            # Extract the ratio prefix (everything before the last +)
            # Base format: ratio1*ratio2+W*rank(momentum)
            ratio_prefix = base_expr.rsplit("+", 1)[0] if "+" in base_expr else base_expr
            
            for new_w in [0.3, 0.5, 0.7, 0.9]:
                for (mom, mom_name) in mom_variants:
                    # Reconstruct expression cleanly — no fragile regex
                    new_expr = f"{ratio_prefix}+{new_w}*{mom}"
                    if new_expr != base_expr and new_expr not in [v["expr"] for v in variations]:
                        variations.append({
                            "name": f"{base_name}_tune{mom_name[:3]}_w{int(new_w*10)}"[:40],
                            "expr": new_expr,
                            "weight": new_w,
                            "momentum": mom,
                            "momentum_field": mom_name,
                            "orthogonality_score": cand.get("orthogonality_score", 0) + 1,
                        })
                        if len(variations) >= max_tune_attempts:
                            break
                if len(variations) >= max_tune_attempts:
                    break
            
            # If still too few variations or first 3 all fail similarly, try new ratio pairs
            if len(variations) < 3 or all(v.get("momentum_field","") != "corr_cv" for v in variations):
                # Generate diverse ratio pair variations from ortho data
                field_usage = ortho["fields_used"]
                used_pairs = ortho.get("field_pairs_used", set())
                denoms = [d for d in ["cap", "enterprise_value", "equity", "high", "open", "low", "sales"]
                          if field_usage.get(d, 0) <= 2]
                nums = [f for f in ALL_WQ_FIELDS if field_usage.get(f, 0) <= 1 and f not in ["close"]]
                pair_count = 0
                for num in nums[:4]:
                    for den in denoms[:3]:
                        if num == den:
                            continue
                        if frozenset([num, den]) in used_pairs:
                            continue
                        for num2 in nums[:4]:
                            if num2 == num:
                                continue
                            for den2 in denoms[:3]:
                                if den2 == den or num2 == den2:
                                    continue
                                if {num, den} & {num2, den2}:
                                    continue
                                for (mom, mom_name) in [("ts_mean(volume,5)", "vol_mom"), ("ts_std(returns,5)", "ret_vol")]:
                                    for w in [0.5, 0.7]:
                                        expr = f"rank({num}/{den})*rank({num2}/{den2})+{w}*rank({mom})"
                                        if expr not in [v["expr"] for v in variations]:
                                            variations.append({
                                                "name": f"Tune_{num[:3]}{den[:3]}_{num2[:3]}{den2[:3]}_{mom_name[:4]}w{int(w*10)}"[:40],
                                                "expr": expr,
                                                "weight": w,
                                            })
                                            pair_count += 1
                                            if pair_count >= max_tune_attempts - len(variations):
                                                break
                                    if pair_count >= max_tune_attempts - len(variations):
                                        break
                            if pair_count >= max_tune_attempts - len(variations):
                                break
                        if pair_count >= max_tune_attempts - len(variations):
                            break
                    if pair_count >= max_tune_attempts - len(variations):
                        break
        
        else:
            # SC failure: try entirely different field pairs
            # Use the orthogonality data to find the most orthogonal field combinations
            field_usage = ortho["fields_used"]
            used_pairs = ortho.get("field_pairs_used", set())
            
            denoms = ["cap", "high", "open", "low", "sales", "enterprise_value", "equity"]
            denoms = [d for d in denoms if field_usage.get(d, 0) <= 2]
            
            nums = [f for f in ALL_WQ_FIELDS if field_usage.get(f, 0) <= 1]
            nums = [n for n in nums if n not in ["close"]]  # exclude close (too common)
            
            mom_pool = [
                ("ts_mean(volume,5)", "vol_mom"),
                ("ts_std(returns,5)", "ret_vol"),
                ("ts_mean(adv20,5)", "adv_mom"),
                ("log(volume)", "log_vol"),
            ]
            
            pair_count = 0
            for num in nums[:6]:
                for den in denoms[:4]:
                    if num == den:
                        continue
                    pair = frozenset([num, den])
                    if pair in used_pairs:
                        continue
                    
                    for num2 in nums[:6]:
                        if num2 == num:
                            continue
                        for den2 in denoms[:4]:
                            if den2 == den or num2 == den2:
                                continue
                            pair2 = frozenset([num2, den2])
                            # Ensure no field overlap between the two ratios
                            if {num, den} & {num2, den2}:
                                continue
                            
                            for (mom, mom_name) in mom_pool[:2]:
                                for w in [0.5, 0.7]:
                                    expr = f"rank({num}/{den})*rank({num2}/{den2})+{w}*rank({mom})"
                                    if expr not in [v["expr"] for v in variations]:
                                        name = f"SCtune_{num[:3]}{den[:3]}_{num2[:3]}{den2[:3]}_{mom_name[:4]}w{int(w*10)}"[:40]
                                        variations.append({
                                            "name": name,
                                            "expr": expr,
                                            "weight": w,
                                            "orthogonality_score": cand.get("orthogonality_score", 0) + 2,
                                        })
                                        pair_count += 1
                                        if pair_count >= max_tune_attempts:
                                            break
                            if pair_count >= max_tune_attempts:
                                break
                        if pair_count >= max_tune_attempts:
                            break
                    if pair_count >= max_tune_attempts:
                        break
                if pair_count >= max_tune_attempts:
                    break
        
        # Try each variation
        log(f"  Generated {len(variations)} tuned variations")
        
        for v_idx, var in enumerate(variations):
            if not self.running:
                return False
            
            log(f"\n  Tune {v_idx+1}/{len(variations)}: {var['name']}")
            log(f"    expr: {var['expr']}")
            
            # Full sim
            payload = {"type": "REGULAR", "regular": var["expr"], "settings": DEFAULT_SETTINGS}
            try:
                r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
            except Exception as e:
                log(f"    ❌ POST: {e}")
                continue
            
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 60))
                log(f"    ⚠️ 429: wait {retry}s")
                time.sleep(min(retry, 60))
                try:
                    r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
                except:
                    continue
            
            if r.status_code != 201:
                log(f"    ❌ HTTP {r.status_code}")
                continue
            
            sim_id = r.headers.get("Location", "").split("/")[-1]
            var["sim_id"] = sim_id
            
            # Adaptive IS poll
            def is_ready(data):
                aid = data.get("alpha")
                return aid if aid else None
            
            alpha_id = adaptive_poll(
                self.s, f"{API}/simulations/{sim_id}",
                f"Tune IS {var['name']}",
                is_ready, max_wait=3600,
                initial_interval=15, fallback_interval=60,
                stuck_threshold=300  # abort if stuck at 0% for 5 min
            )
            
            if not alpha_id:
                log(f"    ❌ IS timeout")
                continue
            
            var["alpha_id"] = alpha_id
            
            # Fetch IS details
            r2 = self.s.get(f"{API}/alphas/{alpha_id}", timeout=30)
            if r2.status_code != 200:
                continue
            
            ad = r2.json()
            checks = ad.get("is", {}).get("checks", []) if isinstance(ad.get("is"), dict) else []
            stats = ad.get("is", {}).get("statistics", {}) if isinstance(ad.get("is"), dict) else {}
            
            var["sharpe"] = stats.get("sharpe")
            var["fitness"] = stats.get("fitness")
            passes = sum(1 for c in checks if c.get("result") == "PASS")
            fails = sum(1 for c in checks if c.get("result") == "FAIL")
            is_pass = (fails == 0 and passes >= 7)
            
            log(f"    IS: S={var['sharpe']} F={var['fitness']} | {passes}P/{fails}F")
            
            if not is_pass:
                log(f"    ❌ IS failed")
                continue
            
            # Set metadata
            try:
                self.s.patch(f"{API}/alphas/{alpha_id}",
                    json={"name": var["name"], "color": "GREEN",
                          "category": "FUNDAMENTAL", "tags": ["workflow-v2-tune"]}, timeout=15)
            except: pass
            
            # If IS failure was the original issue, we're done
            if failed_phase == "is":
                # Copy results back to original cand
                cand["alpha_id"] = alpha_id
                cand["sharpe"] = var["sharpe"]
                cand["fitness"] = var["fitness"]
                cand["is_status"] = "PASS"
                cand["expr"] = var["expr"]
                cand["name"] = var["name"]
                self.state["candidates_passed_is"] = self.state.get("candidates_passed_is", 0) + 1
                self.save_checkpoint()
                return True
            
            # If IS passed but original failed was SC, try SC now
            if failed_phase == "sc":
                sc_pass = self._run_sc(var)
                if sc_pass:
                    # SC passed! Copy results
                    cand["alpha_id"] = alpha_id
                    cand["sharpe"] = var["sharpe"]
                    cand["fitness"] = var["fitness"]
                    cand["is_status"] = "PASS"
                    cand["sc_value"] = var.get("sc_value")
                    cand["sc_result"] = "PASS"
                    cand["expr"] = var["expr"]
                    cand["name"] = var["name"]
                    self.state["candidates_passed_is"] = self.state.get("candidates_passed_is", 0) + 1
                    self.state["candidates_passed_sc"] = self.state.get("candidates_passed_sc", 0) + 1
                    self.save_checkpoint()
                    return True
                else:
                    log(f"    ❌ SC failed for tuned version: {var.get('sc_value', '?')}")
        
        log(f"  ✖️ All {len(variations)} tuned variations failed")
        notify(f"调参耗尽 ✖️ {cand['name']}\n{failed_phase.upper()}方向{len(variations)}个变体全失败",
               emoji="⚠️", dedup_key=f"tune_fail_{cand.get('alpha_id','')}")
        return False


# ═══ MAIN ════════════════════════════════════════
if __name__ == "__main__":
    workflow = Workflow()
    workflow.run()

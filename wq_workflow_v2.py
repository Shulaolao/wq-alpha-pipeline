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
SKELETON_MULT = "mult_ratio"       # rank(A/B)*rank(C/D) + W*rank(M)
SKELETON_SUB = "sub_delta"         # rank(X) - rank(ts_delta(Y,N))
SKELETON_PURE_ADD = "pure_add"     # rank(A/B) + rank(C/D) — no time series
SKELETON_PURE_MULT = "pure_mult"   # rank(A/B)*rank(C/D) — no momentum
SKELETON_DIRECT_RANK = "direct_rank"  # rank(A) +/- rank(B) — no ratio
SKELETON_THREE_TERM = "three_term" # rank(A/B) + rank(C/D) - rank(ts_*(X,N))
SKELETON_IND_NEUT = "ind_neut"     # ind_neutral(rank(ts_*(X))) + rank(fund_ratio)
SKELETON_SINGLE = "single"         # single factor: rank(ts_rank(X,N))

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
        state = json.loads(STATE_FILE.read_text())
        # Handle old key name "failed_exprs" → migrate to "failed_expressions"
        if "failed_exprs" in state and "failed_expressions" not in state:
            state["failed_expressions"] = state.pop("failed_exprs")
        return state
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
        "failed_expressions": [],   # expressions that have been fully exhausted
        "stuck_batches": 0,          # consecutive batches with 0 passes
    }

def save_state(state: dict):
    state["last_updated"] = datetime.now().isoformat()
    # Truncate errors to last 20 to prevent file bloat
    if len(state.get("errors", [])) > 20:
        state["errors"] = state["errors"][-20:]
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

# ═══ Proxy / Connectivity ═══════════════════════════
CLASH_SOCK = "/tmp/verge/verge-mihomo.sock"
def _clash_switch(node_name: str, group: str = "🚀节点选择") -> bool:
    """Switch Clash proxy node via Unix socket. Returns True on success."""
    import subprocess, urllib.parse
    encoded_group = urllib.parse.quote(group, safe="")
    body = json.dumps({"name": node_name})
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5",
             "--unix-socket", CLASH_SOCK, "-X", "PUT",
             f"http://localhost/proxies/{encoded_group}",
             "-H", "Content-Type: application/json",
             "-d", body],
            capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False

def _clash_get_current(group: str = "🚀节点选择") -> str:
    """Get current node name for a Clash proxy group."""
    import subprocess, urllib.parse
    encoded_group = urllib.parse.quote(group, safe="")
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5",
             "--unix-socket", CLASH_SOCK,
             f"http://localhost/proxies/{encoded_group}"],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout:
            data = json.loads(r.stdout)
            return data.get("now", "")
    except Exception:
        pass
    return ""

# Known-working proxy nodes for WQ API (US/Singapore nodes with good TLS to AWS US-East)
WQ_FALLBACK_NODES = [
    "🇺🇸美国圣何塞01 | 三网推荐",
    "🇸🇬AWS新加坡03 | 移动联通推荐",
    "🇺🇸美国圣何塞01-0.1倍",
    "🇸🇬新加坡 | 高速专线-hy2",
    "🇸🇬新加坡3 | 高速专线-hy2",
]

def ensure_wq_connectivity(s: requests.Session) -> bool:
    """Test WQ API connectivity; on SSL failure, auto-switch proxy nodes."""
    import subprocess
    for attempt in range(4):
        try:
            r = s.post(f"{API}/authentication", auth=(EMAIL, PASS), timeout=20)
            log(f"📡 WQ API reachable (HTTP {r.status_code})")
            return True
        except (requests.exceptions.SSLError,
                requests.exceptions.ConnectionError) as e:
            current_node = _clash_get_current()
            err = str(e)[:80]
            if attempt >= 3:
                log(f"❌ WQ unreachable after all proxy switches: {err}", "error")
                return False
            log(f"⚠️ WQ SSL error (node={current_node}): {err}", "warn")
            # Try next fallback node
            if attempt < len(WQ_FALLBACK_NODES):
                node = WQ_FALLBACK_NODES[attempt]
                log(f"  🔄 Switching to {node}...")
                if _clash_switch(node):
                    log(f"  ✅ Switched to {node}")
                    time.sleep(1)  # Let proxy settle
                else:
                    log(f"  ⚠️ Switch to {node} failed, trying next")
        except Exception as e:
            log(f"⚠️ WQ connectivity error: {e}", "error")
            return False
    return False

# ═══ Session ═══════════════════════════════════════
def fresh_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _TLSAdapter())
    s.verify = False
    s.trust_env = False
    # Use Clash proxy (port 7897) — required from China network
    s.proxies = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
    # 2 retry attempts on same proxy (SSL EOF is intermittent)
    for attempt in range(3):
        try:
            r = s.post(f"{API}/authentication", auth=(EMAIL, PASS), timeout=60)
            if r.status_code == 201:
                log("🔐 Auth OK")
                return s
            raise RuntimeError(f"Auth failed: {r.status_code} {r.text[:200]}")
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            if attempt >= 2:
                raise RuntimeError(f"WQ unreachable after 3 attempts: {e}")
            log(f"⚠️ Auth attempt {attempt+1} failed: {str(e)[:60]}, retrying...")
            time.sleep(3)
    raise RuntimeError("Auth: unexpected")

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
        
        # Determine structure type — granular classification
        subtracted = False
        multiplied = False
        has_ratio = bool(RATIO_PATTERN.search(expr))
        has_group_rank = "group_rank" in expr
        has_ind_neutral = "ind_neutral" in expr
        direct_fields = re.findall(r'\brank\(([a-z_]+)\)', expr)
        direct_fields_no_ts = [f for f in direct_fields if f not in ALL_WQ_OPERATORS and f != "ts_dataset"]
        has_direct_rank = len([f for f in direct_fields_no_ts if f in ALL_WQ_FIELDS]) >= 2
        plus_count = expr.count("+")
        mult_has_plus = "*" in expr and "+" in expr

        if has_ind_neutral:
            struct_type = "ind_neutral"
        elif has_group_rank:
            struct_type = "group_neutral"
        elif has_direct_rank and "+" in expr and "*" not in expr:
            struct_type = "direct_add"
        elif has_direct_rank and "-" in expr and "*" not in expr:
            struct_type = "direct_sub"
        elif mult_has_plus:
            # Check if it has a momentum term (rank(momentum) after +)
            has_momentum = bool(re.search(r'\+[\d.]+[*]*rank\((?:ts_)?', expr))
            if has_momentum:
                struct_type = "mult_ratio"
            else:
                struct_type = "pure_mult"
        elif "*" in expr and "+" not in expr:
            if has_ratio:
                struct_type = "pure_mult"
            else:
                struct_type = "mult_field"
        elif "-" in expr:
            struct_type = "subtraction"
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
    sub_count = sum(1 for s in structures if s['type'] in ('subtraction','direct_sub'))
    mult_count = sum(1 for s in structures if s['type'] in ('mult_ratio','pure_mult','mult_field'))
    pure_add_count = sum(1 for s in structures if s['type'] == 'direct_add')
    group_count = sum(1 for s in structures if s['type'] == 'group_neutral')
    log(f"  Structures: {mult_count} mult | {sub_count} sub | {pure_add_count} add | {group_count} group")
    
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
        "subtraction_count": sub_count,
        "multiplication_count": mult_count,
        "add_count": pure_add_count,
        "group_count": group_count,
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
    
    # Actual count of true MULT skeletons (ratio*ratio+ pattern)
    true_mult = sum(1 for s in ortho.get("structures", [])
                    if s["type"] == "multiplication_ratio")
    
    # Penalize adding to the already-dominant skeleton
    if has_sub and sub_count > mult_count:
        novelty_score -= 3  # Subtraction is dominant, prefer other structures
    elif has_mult and true_mult >= 3:
        novelty_score -= 2  # MULT also getting full
    
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

def _build_ratio_pool(ortho: dict, skip_zero_occupancy: bool = False) -> list:
    """
    Build list of (expr_str, name) for ratio pairs, filtered by:
    1. Time-frequency compatibility (no pv1/fund mixing)
    2. Field usage < threshold
    3. Unused pair
    
    When skip_zero_occupancy=True, skip zero-usage fields that have been
    proven to produce S=None in TOP3000 (ebitda, cash, sales) in ALL passes.
    """
    field_usage = ortho["fields_used"]
    used_pairs = ortho["field_pairs_used"]
    zero_usage_fields = {"ebitda", "cash", "sales"}
    
    # Priority: verified pairs (known working), then low-usage fields
    pool = []
    seen = set()
    
    # First pass: verified pairs from history
    for num, den in VERIFIED_NUM_DEN_PAIRS:
        if skip_zero_occupancy:
            # Skip zero-usage fields from verified pairs too — they're
            # proven dead-ends in TOP3000 despite having positive IS history
            if num in zero_usage_fields or den in zero_usage_fields:
                continue
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
        if skip_zero_occupancy and f in zero_usage_fields:
            continue  # Skip zero-usage fields in second pass too
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
        if skip_zero_occupancy and f in {"ebitda", "cash", "sales"}:
            continue  # Skip fields proven to produce S=None
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
    """Generate multiplication skeleton candidates: rank(A/B)*rank(C/D)+W*rank(M).

    Builds TEMPLATES (unique field combinations), scores each template,
    then picks best weight per template to produce diverse candidates.
    """
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
    # Step 1: Build templates — unique (r1, r2, mom) templates
    templates = []
    template_seen = set()
    for (r1_str, r1_name) in ratio_pool[:5]:
        r1_fields = set(FIELD_PATTERN.findall(r1_str))
        for (r2_str, r2_name) in ratio_pool[:5]:
            if r1_str == r2_str:
                continue
            r2_fields = set(FIELD_PATTERN.findall(r2_str))
            if r1_fields & r2_fields:
                continue
            all_groups = {_get_field_group(f) for f in (r1_fields | r2_fields)}
            if len(all_groups) > 1:
                continue
            for mom_str, mom_name in momentums[:3]:
                tkey = (r1_str, r2_str, mom_str)
                if tkey in template_seen:
                    continue
                template_seen.add(tkey)
                # Score the template (median weight as representative)
                median_expr = f"{r1_str}*{r2_str}+0.5*rank({mom_str})"
                score = score_candidate_orthogonality(median_expr, ortho, active_exprs)
                templates.append({
                    "r1_str": r1_str, "r1_name": r1_name,
                    "r2_str": r2_str, "r2_name": r2_name,
                    "mom_str": mom_str, "mom_name": mom_name,
                    "score": score,
                })
    templates.sort(key=lambda t: -t["score"])

    # Step 2: For top templates, generate all weight variants
    for tmpl in templates:
        for w in [0.3, 0.5, 0.7]:
            expr = f"{tmpl['r1_str']}*{tmpl['r2_str']}+{w}*rank({tmpl['mom_str']})"
            if expr in seen:
                continue
            seen.add(expr)
            name = f"M_{tmpl['r1_name']}_{tmpl['r2_name']}_{tmpl['mom_name']}_w{int(w*10)}"[:40]
            name = name.replace("-","_").replace(" ","")
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": tmpl["score"],  # template score, not per-variant
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


def _generate_fund_growth_sub_candidates(ortho: dict, active_exprs: list) -> list:
    """
    Generate subtraction candidates using FUNDAMENTAL GROWTH RATES.
    Key insight: rank(ts_delta(ratio, N)) maintains frequency consistency
    with other fundamental operators, avoiding the S=None coverage mismatch.
    Pattern: -1*rank(ts_delta(ratio, N)) + rank(daily_signal)
    Based on working pattern from: E5kZ7p60 = -1*rank(ts_delta(close,5)) + rank(operating_income/equity)
    """
    candidates = []
    # Fundamental ratios that have been verified as working
    fund_ratios = [
        ("revenue/equity", "rev_eq"),
        ("operating_income/equity", "oi_eq"),
        ("revenue/enterprise_value", "rev_ev"),
        ("operating_income/cap", "oi_cap"),
        ("debt/equity", "de"),
        ("debt/enterprise_value", "de_ev"),
        ("revenue/cap", "rev_cap"),
    ]
    # Daily signals to ADD (not subtract) — momentum/reversal signals
    daily_signals = [
        ("ts_delta(close, 5)", "delta_close_5"),
        ("ts_delta(close, 10)", "delta_close_10"),
        ("-1*ts_delta(close, 5)", "neg_delta_close_5"),
        ("-1*ts_delta(close, 10)", "neg_delta_close_10"),
        ("ts_zscore(close, 20)", "zsc_close_20"),
        ("ts_rank(returns, 20)", "rank_ret_20"),
    ]
    seen = set()
    for (ratio, ratio_name) in fund_ratios:
        for (signal, sig_name) in daily_signals:
            # Pattern: fundamental + daily_signal (addition, not subtraction)
            # This matches working alphas: E5kZ7p60, rKA3vKra
            expr = f"-1*rank({signal}) + rank({ratio})"
            if expr in seen:
                continue
            seen.add(expr)
            score = score_candidate_orthogonality(expr, ortho, active_exprs)
            name = f"S_g{ratio_name}_{sig_name}"[:40]
            name = name.replace("-","_").replace(" ","")
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": score,
                "skeleton": SKELETON_SUB,
                "weight": 0.5,
            })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates

def _generate_new_ratio_variations(cand: dict, variations: list, ortho: dict, max_attempts: int):
    """Generate tune variations using completely new field pairs.
    Used when original ratio pair is S=None (coverage mismatch)."""
    field_usage = ortho["fields_used"]
    used_pairs = ortho.get("field_pairs_used", set())
    
    # Only use proven denoms paired with low-usage fund fields
    denoms = ["cap", "enterprise_value", "equity"]
    nums = ["revenue", "operating_income", "debt"]  # Only fields with proven coverage
    
    pair_count = 0
    for num in nums:
        for den in denoms:
            if num == den:
                continue
            pair = frozenset([num, den])
            if pair in used_pairs:
                continue
            g1 = "fund" if num in FUND_FIELDS else "pv1"
            g2 = "fund" if den in FUND_FIELDS else "pv1"
            if g1 != g2:
                continue
            for num2 in nums:
                if num2 == num:
                    continue
                for den2 in denoms:
                    if den2 == den or num2 == den2:
                        continue
                    pair2 = frozenset([num2, den2])
                    if pair2 in used_pairs:
                        continue
                    if {num, den} & {num2, den2}:
                        continue
                    g1b = "fund" if num2 in FUND_FIELDS else "pv1"
                    g2b = "fund" if den2 in FUND_FIELDS else "pv1"
                    if g1b != g2b:
                        continue
                    for w in [0.5, 0.7]:
                        expr = f"rank({num}/{den})*rank({num2}/{den2})+{w}*rank(ts_mean(volume,5))"
                        if expr not in [v["expr"] for v in variations]:
                            variations.append({
                                "name": f"Tune_{num[:3]}{den[:3]}_{num2[:3]}{den2[:3]}_w{int(w*10)}"[:40],
                                "expr": expr,
                                "weight": w,
                            })
                            pair_count += 1
                            if pair_count >= max_attempts:
                                break
                    if pair_count >= max_attempts:
                        break
                if pair_count >= max_attempts:
                    break
            if pair_count >= max_attempts:
                break
        if pair_count >= max_attempts:
            break


def _generate_fund_growth_mul_candidates(ortho: dict, active_exprs: list) -> list:
    """Generate MULTIPLICATION candidates using proven fundamental ratios.
    Pattern: rank(A/B)*rank(C/D) + W*rank(momentum)
    Allows reusing existing field pairs with new momentum/weight combos."""
    candidates = []
    
    fund_ratios = [
        ("revenue/enterprise_value", "rev_ev"),
        ("debt/equity", "de"),
        ("revenue/cap", "rev_cap"),
        ("operating_income/cap", "oi_cap"),
        ("revenue/equity", "rev_eq"),
        ("operating_income/equity", "oi_eq"),
        ("debt/enterprise_value", "de_ev"),
    ]
    momentums = [
        ("ts_mean(volume,5)", "vol"),
        ("ts_mean(adv20,5)", "adv"),
        ("log(volume)", "logv"),
        ("ts_corr(close,volume,10)", "corr_cv"),
    ]
    seen = set()
    
    for r1_str, r1_name in fund_ratios:
        r1_fields = set(FIELD_PATTERN.findall(r1_str))
        for r2_str, r2_name in fund_ratios:
            if r1_str == r2_str:
                continue
            r2_fields = set(FIELD_PATTERN.findall(r2_str))
            if r1_fields & r2_fields:
                continue
            all_groups = {_get_field_group(f) for f in (r1_fields | r2_fields)}
            if len(all_groups) > 1:
                continue
            for mom_str, mom_name in momentums:
                for w in [0.3, 0.5, 0.7, 0.9]:
                    expr = f"rank({r1_str})*rank({r2_str})+{w}*rank({mom_str})"
                    if expr in seen:
                        continue
                    # Skip if exact expression already exists in active
                    if expr in active_exprs:
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
    # Deduplicate by expression string
    seen_exprs = set()
    deduped = []
    for c in candidates:
        if c["expr"] in seen_exprs:
            continue
        seen_exprs.add(c["expr"])
        deduped.append(c)
    deduped.sort(key=lambda x: -x["orthogonality_score"])
    return deduped


# ═══ NEW STRUCTURAL GENERATORS ═══════════════════
# These fill the 7 identified structural gaps in the 15 ACTIVE portfolio.
# Gaps: no pure-add, no pure-mult, no direct-rank-add, no three-term mix,
#       no ind_neutral, no ratio-lag, no frequency-cross (beyond 2 existing)

def _generate_pure_add_candidates(ortho: dict, active_exprs: list) -> list:
    """
    gap_fill: pure_add — rank(A/B) + rank(C/D)
    Two fundamental ratios added together, no time series component.
    Zero momentum/trend signal — pure cross-sectional fundamental comparison.
    This avoids S=None entirely since both terms are ratio ranks.
    """
    candidates = []
    fund_ratios = [
        ("revenue/enterprise_value", "rev_ev"),
        ("debt/equity", "de"),
        ("revenue/cap", "rev_cap"),
        ("operating_income/cap", "oi_cap"),
        ("debt/enterprise_value", "de_ev"),
        ("revenue/equity", "rev_eq"),
        ("operating_income/equity", "oi_eq"),
    ]
    seen = set()
    for (r1_str, r1_name) in fund_ratios:
        r1_fields = set(FIELD_PATTERN.findall(r1_str))
        for (r2_str, r2_name) in fund_ratios:
            if r1_str == r2_str:
                continue
            r2_fields = set(FIELD_PATTERN.findall(r2_str))
            # Allow field overlap — different denominators create different signals
            expr = f"rank({r1_str})+rank({r2_str})"
            if expr in seen:
                continue
            if expr in active_exprs:
                continue
            seen.add(expr)
            score = score_candidate_orthogonality(expr, ortho, active_exprs)
            name = f"A_{r1_name}_{r2_name}"[:40]
            name = name.replace("-","_").replace(" ","")
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": score,  # P2: boost unified in _sort_key
                "skeleton": SKELETON_PURE_ADD,
            })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_pure_mult_candidates(ortho: dict, active_exprs: list) -> list:
    """
    gap_fill: pure_mult — rank(A/B)*rank(C/D)
    Ratio multiplication without momentum term.
    Uses proven fundamental ratios only. Less field/operator usage than full MULT.
    """
    candidates = []
    fund_ratios = [
        ("revenue/enterprise_value", "rev_ev"),
        ("debt/equity", "de"),
        ("revenue/cap", "rev_cap"),
        ("operating_income/cap", "oi_cap"),
        ("debt/enterprise_value", "de_ev"),
        ("revenue/equity", "rev_eq"),
        ("operating_income/equity", "oi_eq"),
    ]
    seen = set()
    for (r1_str, r1_name) in fund_ratios:
        r1_fields = set(FIELD_PATTERN.findall(r1_str))
        for (r2_str, r2_name) in fund_ratios:
            if r1_str == r2_str:
                continue
            r2_fields = set(FIELD_PATTERN.findall(r2_str))
            if r1_fields & r2_fields:
                continue  # No field overlap between ratios
            expr = f"rank({r1_str})*rank({r2_str})"
            if expr in seen:
                continue
            if expr in active_exprs:
                continue
            seen.add(expr)
            score = score_candidate_orthogonality(expr, ortho, active_exprs)
            name = f"PM_{r1_name}_{r2_name}"[:40]
            name = name.replace("-","_").replace(" ","")
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": score,  # P2
                "skeleton": SKELETON_PURE_MULT,
            })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_direct_rank_candidates(ortho: dict, active_exprs: list) -> list:
    """
    gap_fill: direct_rank — rank(A) +/- rank(B)
    Direct field rank cross-section, no ratio, no time series.
    Based on working ACTIVE: LLnNAYv1 = rank(debt) - 2*rank(returns)
    Lowest possible field/operator occupancy. Avoids S=None entirely.
    """
    candidates = []
    # Use fund fields (limited rows, stable cross-section) + pv1 fields (daily)
    fund_fields = ["revenue", "debt", "operating_income", "ebitda", "cap", "enterprise_value"]
    pv1_fields = ["returns", "volume", "adv20", "high", "low", "open"]
    combos = [
        # (field_a, field_b, operator, weight, name_suffix)
        # Addition: both signals should move in similar direction
        ("revenue", "cap", "+", 1.0, "rev_cap_add"),
        ("debt", "equity", "+", 1.0, "debt_eq_add"),
        ("operating_income", "cap", "+", 1.0, "oi_cap_add"),
        ("revenue", "enterprise_value", "+", 1.0, "rev_ev_add"),
        # Subtraction with weight: one signal minus the other
        ("revenue", "cap", "-", 1.0, "rev_cap_sub"),
        ("debt", "equity", "-", 1.0, "debt_eq_sub"),
        ("revenue", "enterprise_value", "-", 1.0, "rev_ev_sub"),
        ("operating_income", "cap", "-", 1.0, "oi_cap_sub"),
        # Cross-domain mix: fundamental + pv1 (proven by LLnNAYv1)
        ("debt", "returns", "-", 2.0, "debt_ret_sub2"),
        ("revenue", "returns", "-", 1.0, "rev_ret_sub"),
        ("cap", "returns", "+", 1.0, "cap_ret_add"),
        ("operating_income", "volume", "-", 1.0, "oi_vol_sub"),
        # Double addition: three-fundamental push
        ("revenue", "debt", "+", 1.0, "rev_debt_add"),
        ("operating_income", "debt", "+", 1.0, "oi_debt_add"),
    ]
    seen = set()
    for f_a, f_b, op, w, suffix in combos:
        if op == "+":
            expr = f"rank({f_a})+{w}*rank({f_b})"
        else:
            expr = f"rank({f_a})-{w}*rank({f_b})"
        if expr in seen or expr in active_exprs:
            continue
        seen.add(expr)
        score = score_candidate_orthogonality(expr, ortho, active_exprs)
        name = f"DR_{suffix}"[:40]
        candidates.append({
            "name": name, "expr": expr,
            "orthogonality_score": score,  # P2: no skeleton boost here — _sort_key handles it
            "skeleton": SKELETON_DIRECT_RANK,
            "weight": w,
        })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_three_term_candidates(ortho: dict, active_exprs: list) -> list:
    """
    gap_fill: three_term — rank(A/B) + rank(C/D) - rank(ts_*(X,N))
    Three terms: two fundamental ratios plus a reversal/momentum signal.
    Captures: fundamental value + fundamental quality - price trend.
    """
    candidates = []
    fund_ratios = [
        ("revenue/enterprise_value", "rev_ev"),
        ("debt/equity", "de"),
        ("revenue/cap", "rev_cap"),
        ("operating_income/cap", "oi_cap"),
        ("debt/enterprise_value", "de_ev"),
    ]
    pv1_signals = [
        ("ts_delta(close,5)", "dcl5"),
        ("ts_mean(returns,5)", "mret5"),
        ("ts_zscore(volume,10)", "zvol10"),
        ("ts_corr(close,volume,15)", "cpv15"),
    ]
    seen = set()
    for (r1_str, r1_name) in fund_ratios[:4]:
        for (r2_str, r2_name) in fund_ratios[:4]:
            if r1_str == r2_str:
                continue
            for (sig_str, sig_name) in pv1_signals:
                for w in [0.5, 0.7]:
                    expr = f"rank({r1_str})+rank({r2_str})-{w}*rank({sig_str})"
                    if expr in seen or expr in active_exprs:
                        continue
                    seen.add(expr)
                    score = score_candidate_orthogonality(expr, ortho, active_exprs)
                    name = f"3T_{r1_name}_{r2_name}_{sig_name}_w{int(w*10)}"[:40]
                    name = name.replace("-","_").replace(" ","")
                    candidates.append({
                        "name": name, "expr": expr,
                        "orthogonality_score": score,  # P2
                        "skeleton": SKELETON_THREE_TERM,
                        "weight": w,
                    })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_ind_neut_candidates(ortho: dict, active_exprs: list) -> list:
    """
    gap_fill: ind_neut — ind_neutral(rank(ts_*(X,N))) + rank(fund_ratio)
    Industry-neutralized momentum/reversal signal + fundamental ratio.
    WQ engine supports ind_neutral on single-term signals.
    This structure: (sector-adjusted momentum) + (fundamental value).
    """
    candidates = []
    momentum_signals = [
        ("ts_rank(returns,20)", "mom20"),
        ("ts_rank(returns,60)", "mom60"),
        ("ts_delta(close,10)", "d10"),
        ("ts_mean(volume,5)", "v5"),
    ]
    fund_ratios = [
        ("revenue/enterprise_value", "rev_ev"),
        ("operating_income/cap", "oi_cap"),
        ("debt/equity", "de"),
        ("revenue/cap", "rev_cap"),
    ]
    seen = set()
    for (sig_str, sig_name) in momentum_signals:
        for (ratio_str, ratio_name) in fund_ratios:
            for w in [0.5, 0.7]:
                expr = f"ind_neutral(rank({sig_str}))+{w}*rank({ratio_str})"
                if expr in seen or expr in active_exprs:
                    continue
                seen.add(expr)
                score = score_candidate_orthogonality(expr, ortho, active_exprs)
                name = f"IN_{sig_name}_{ratio_name}_w{int(w*10)}"[:40]
                name = name.replace("-","_").replace(" ","")
                candidates.append({
                    "name": name, "expr": expr,
                    "orthogonality_score": score,  # P2
                    "skeleton": SKELETON_IND_NEUT,
                    "weight": w,
                })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_ratio_lag_candidates(ortho: dict, active_exprs: list) -> list:
    """
    gap_fill: ratio_lag — rank(A/B) - rank(ts_lag(A/B, N))
    Same ratio, current vs lagged. Captures fundamental change rate.
    The lag operator keeps frequency consistent (fund/fund vs fund/fund),
    avoiding the S=None coverage mismatch entirely.
    """
    candidates = []
    fund_ratios = [
        ("revenue/enterprise_value", "rev_ev"),
        ("debt/equity", "de"),
        ("revenue/cap", "rev_cap"),
        ("operating_income/cap", "oi_cap"),
        ("debt/enterprise_value", "de_ev"),
        ("revenue/equity", "rev_eq"),
        ("operating_income/equity", "oi_eq"),
    ]
    lags = [20, 60, 250]  # 1mo, 3mo, 1year
    seen = set()
    for (ratio_str, ratio_name) in fund_ratios:
        for n in lags:
            expr = f"rank({ratio_str})-rank(ts_lag({ratio_str},{n}))"
            if expr in seen or expr in active_exprs:
                continue
            seen.add(expr)
            score = score_candidate_orthogonality(expr, ortho, active_exprs)
            name = f"RL_{ratio_name}_lag{n}"[:40]
            name = name.replace("-","_").replace(" ","")
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": score + 4,
                "skeleton": SKELETON_SUB,  # Still structurally a subtraction
                "lag": n,
            })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def generate_candidates(ortho: dict, active_exprs: list, n: int = 3,
                        failed_exprs: list = None, stuck_batches: int = 0) -> list:
    """
    v3: AST-aware candidate generation with time-frequency filtering.
    
    Decision tree:
    1. If multiplication skeleton < 2 in active → generate MULT candidates
    2. If multiplication >= 2 → generate SUB candidates instead
    3. When stuck (stuck_batches >= 2): skip zero-occupancy fields, force
       proven field templates to break out of the dead-end loop
    4. Final selection: pick top-n with diverse ratio pairs
    
    Never mixes pv1 and fundamental fields in the same ratio pair.
    Never reuses exact field pairs from active alphas.
    Never regenerates expressions that are in failed_exprs list.
    """
    ratio_pool = _build_ratio_pool(ortho, skip_zero_occupancy=(stuck_batches >= 2))
    
    mult_count = ortho.get("multiplication_count", 0)
    sub_count = ortho.get("subtraction_count", 0)
    
    log(f"  🏗 AST structure balance: {mult_count} mult / {sub_count} sub in active")
    
    all_candidates = []
    
    if ratio_pool:
        # Decision: which skeleton to generate?
        use_mult = mult_count < 2  # Prefer multiplication if < 2 exist
        use_sub = not use_mult and sub_count < 6  # Fall back to subtraction
        
        if use_mult:
            log("  🟢 Generating MULTIPLICATION candidates (skeleton under-utilized)")
            all_candidates = _generate_mult_candidates(ratio_pool, ortho, active_exprs)
        
        if use_sub:
            log("  🔵 Generating SUBTRACTION candidates (multiplication saturated)")
            sub_candidates = _generate_sub_candidates(ratio_pool, ortho, active_exprs)
            all_candidates.extend(sub_candidates)
    else:
        log("  ⚠️ No ratio pairs available — falling back to fundamental growth templates")
    
    # Always add growth-based subtraction (fundamental + daily signal addition)
    # This pattern avoids coverage mismatch and uses only non-zero-usage fields
    growth_sub = _generate_fund_growth_sub_candidates(ortho, active_exprs)
    log(f"  📈 Adding {len(growth_sub)} fundamental growth subtraction candidates")
    all_candidates.extend(growth_sub)
    
    # Also add multiplication candidates from verified fund ratios
    growth_mul = _generate_fund_growth_mul_candidates(ortho, active_exprs)
    if growth_mul:
        log(f"  ✖️ Adding {len(growth_mul)} multiplication candidates (preferred over sub)")
        all_candidates.extend(growth_mul)

    # ── NEW STRUCTURAL GENERATORS ──
    # These fill structural gaps in the current portfolio (see gap_fill docs above)
    # Each uses only proven field pairs, avoiding S=None (ebitda/cash/sales)

    pure_add = _generate_pure_add_candidates(ortho, active_exprs)
    if pure_add:
        log(f"  ➕ Adding {len(pure_add)} PURE_ADD candidates")
        all_candidates.extend(pure_add)

    pure_mult = _generate_pure_mult_candidates(ortho, active_exprs)
    if pure_mult:
        log(f"  ✖️ Adding {len(pure_mult)} PURE_MULT candidates")
        all_candidates.extend(pure_mult)

    direct_rank = _generate_direct_rank_candidates(ortho, active_exprs)
    if direct_rank:
        log(f"  📊 Adding {len(direct_rank)} DIRECT_RANK candidates (no-ratio, no-ts)")
        all_candidates.extend(direct_rank)

    three_term = _generate_three_term_candidates(ortho, active_exprs)
    if three_term:
        log(f"  🔢 Adding {len(three_term)} THREE_TERM candidates")
        all_candidates.extend(three_term)

    ind_neut = _generate_ind_neut_candidates(ortho, active_exprs)
    if ind_neut:
        log(f"  🏭 Adding {len(ind_neut)} IND_NEUT candidates")
        all_candidates.extend(ind_neut)

    ratio_lag = _generate_ratio_lag_candidates(ortho, active_exprs)
    if ratio_lag:
        log(f"  ⏰ Adding {len(ratio_lag)} RATIO_LAG candidates")
        all_candidates.extend(ratio_lag)
    
    if not all_candidates:
        log("  ⚠️ No candidates generated!", "error")
        return []
    
    # Deduplicate by expression
    seen_exprs = set()
    # Also track failed expressions to avoid regenerating dead-end candidates
    if failed_exprs:
        for fe in failed_exprs:
            seen_exprs.add(fe)
    deduped = []
    for c in all_candidates:
        if c["expr"] in seen_exprs:
            continue
        seen_exprs.add(c["expr"])
        deduped.append(c)
    
# ── Tiered selection: MULT is primary — proven working in TOP3000 ──
    # Non-MULT skeletons (subtraction, IND_NEUT, DIRECT_RANK, add, etc.)
    # systematically produce S=None in TOP3000. Only use them if MULT pool
    # doesn't have enough candidates to fill the batch.
    # Within MULT, pick one per template (field combo) for diversity.
    mult_pool = [c for c in deduped if c.get("skeleton") == SKELETON_MULT]
    other_pool = [c for c in deduped if c.get("skeleton") != SKELETON_MULT]
    
    def _sort_key(c):
        return -c["orthogonality_score"]
    
    mult_pool.sort(key=_sort_key)
    other_pool.sort(key=_sort_key)
    
    # Select from MULT: group by template (r1+r2+mom), pick best weight per template
    seen_templates = set()
    mult_selected = []
    for c in mult_pool:
        if len(mult_selected) >= n:
            break
        # Template key: strip weight to get the base field combination
        import re
        tkey = re.sub(r'\+[0-9.]+[\*]rank\([^)]+\)$', '', c["expr"])
        if tkey in seen_templates:
            continue
        seen_templates.add(tkey)
        mult_selected.append(c)
    
    result = mult_selected[:n]
    if len(result) < n:
        for c in other_pool:
            if len(result) >= n:
                break
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
            candidates = generate_candidates(
                ortho, [a["expr"] for a in actives], n=3,
                failed_exprs=self.state.get("failed_expressions", []),
                stuck_batches=self.state.get("stuck_batches", 0),
            )
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
                quick_pass = self._quick_test(cand)
                if quick_pass == "skip":
                    log(f"⏩ {cand['name']}: S=None detected, skip (dead pair)")
                    self.state["batch_progress"] = idx + 1
                    self.save_checkpoint()
                    continue
                if not quick_pass:
                    log(f"⏩ {cand['name']}: quick test failed, skip (S<1.0)")
                    self.state["batch_progress"] = idx + 1
                    self.save_checkpoint()
                    continue
                
                # ── 4b. FULL SIM → Adaptive IS Poll ──
                self.state["phase"] = "full_sim"
                self.save_checkpoint()
                success = self._run_full_sim(cand)
                if not success:
                    success = self._tune_and_retry(cand, ortho, "is")
                    if not success:
                        log(f"✖️ {cand['name']}: all IS variations failed, skip")
                        self.state["batch_progress"] = idx + 1
                        self.save_checkpoint()
                        notify(f"候选失败 ✖️ {cand['name']}\
IS {cand.get('sharpe','?')}/{cand.get('fitness','?')}，调参重试后仍失败",
                               emoji="⚠️", dedup_key=f"cand_fail_{cand.get('alpha_id','')}")
                        continue
                elif cand.get("is_status") == "TUNE":
                    log(f"🔧 {cand['name']}: IS TUNE (metrics strong, checks borderline), routing to tune")
                    success = self._tune_and_retry(cand, ortho, "is")
                    if not success:
                        log(f"✖️ {cand['name']}: tune also couldn't fix checks, skip")
                        self.state["batch_progress"] = idx + 1
                        self.save_checkpoint()
                        notify(f"调参未修复 ⚠️ {cand['name']}\nS={cand.get('sharpe','?')} 调参后仍无法通过check",
                               emoji="⚠️", dedup_key=f"tune_fail_{cand.get('alpha_id','')}")
                        continue
                
                # ── 4c. IS OPTIMIZATION (post-pass tune) ──
                is_sharpe = cand.get("sharpe", 0) or 0
                is_fitness = cand.get("fitness", 0) or 0
                if cand.get("is_status") == "PASS" and self._should_optimize(is_sharpe, is_fitness):
                    strategy = self._get_optimization_strategy(is_sharpe, is_fitness)
                    # ── Strategy dispatch ──
                    log(f"📈 IS PASS S={is_sharpe:.2f} F={is_fitness:.2f}")
                    log(f"   {strategy['description']}")
                    log(f"   Grid: {strategy['strategy_desc']}")
                    improved = self._tune_and_retry(cand, ortho, "is", is_optimization=True, opt_strategy=strategy)
                    if improved:
                        log(f"✅ Optimization improved S! Continuing with optimized variant")
                    else:
                        log(f"ℹ️ No improvement from optimization, proceeding with original")
                
                # ── 4d. SC SUBMIT → Adaptive SC Poll ──
                self.state["phase"] = "sc_submit"
                self.save_checkpoint()
                success = self._run_sc(cand)
                if not success:
                    log(f"❌ {cand['name']}: SC failed ({cand.get('sc_value', '?')})")
                    log(f"   Trying SC tune (different fields)...")
                    success = self._tune_and_retry(cand, ortho, "sc")
                    if not success:
                        log(f"✖️ {cand['name']}: all SC variations failed, skip")
                        self.state["batch_progress"] = idx + 1
                        self.save_checkpoint()
                        notify(f"SC耗尽 ✖️ {cand['name']}\nSC={cand.get('sc_value','?')}，换字段调参后仍失败",
                               emoji="⚠️", dedup_key=f"sc_fail_{cand.get('alpha_id','')}")
                        continue

                # ── 4e. SUBMIT ──
                self.state["phase"] = "submit"
                self.save_checkpoint()
                self._submit_alpha(cand, cand.get("alpha_id"))
                self.state["batch_progress"] = idx + 1
                self.save_checkpoint()
        
        # ──AFTER BATCH DONE─debug─
        log(f"    🔍 POST-LOOP: n={len(candidates)} submitted={[c.get('submitted') for c in candidates]} stuck_before={self.state.get('stuck_batches',0)}")
        # After batch done, save and loop back
        self.state["candidates_generated"] = self.state.get("candidates_generated", 0) + len(candidates)
        self.state["iterations"] = self.state.get("iterations", 0) + 1
        
        # ── Track batch success / stuck detection ──
        any_passed = any(c.get("submitted") for c in candidates)
        if any_passed:
            self.state["stuck_batches"] = 0
        else:
            self.state["stuck_batches"] = self.state.get("stuck_batches", 0) + 1
            # Register failed expressions for dead-end detection
            failed_list = self.state.setdefault("failed_expressions", [])
            for c in candidates:
                expr = c.get("expr", "")
                if expr and expr not in failed_list:
                    failed_list.append(expr)
                    log(f"  📝 Registered failed expr ({len(failed_list)} total): {expr[:60]}")
            # Keep list bounded
            if len(failed_list) > 50:
                self.state["failed_expressions"] = failed_list[-50:]
            if self.state["stuck_batches"] >= 3:
                log(f"⚠️  {self.state['stuck_batches']} consecutive batches with 0 passes. "
                    f"Switching to stuck mode (skip zero-occupancy fields).",
                    "warn")
        
        self.save_checkpoint()
        
        log(f"\n🔄 Batch complete. Current: {self.state['active_count']}/{TARGET_ACTIVE}")
        log("Restarting orthogonality analysis for next batch...")
    
    def _quick_test(self, cand: dict):
        """Quick 1-year sim to filter weak signals before full sim.
        Returns: True (proceed), False (weak S), or "skip" (S=None/dead pair)."""
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
        # S=None = coverage mismatch / dead pair — skip entire candidate
        if sharpe is None:
            log(f"⏩ Quick test: S=None (dead pair), skipping candidate")
            return "skip"
        if sharpe < 1.0:
            log(f"⏩ Quick test: S={sharpe:.2f} < 1.0, skipping")
            return False
        log(f"⏩ Quick test: S={sharpe:.2f} >= 1.0, proceeding to full sim")
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

        sharpe_val = stats.get("sharpe")
        fitness_val = stats.get("fitness")

        # P1: S=None means dead pair — don't treat as PASS even if checks look good
        is_pass = (sharpe_val is not None and fails <= 1 and passes >= 6)
        # Soft pass: metrics strong but checks barely miss → route to tuning
        soft_pass = (sharpe_val is not None and sharpe_val >= 1.25
                     and fails <= 2 and passes >= 4
                     and not is_pass)

        if is_pass:
            cand["is_status"] = "PASS"
        elif soft_pass:
            cand["is_status"] = "TUNE"
            log(f"📊 IS: S={sharpe_val:.2f} F={fitness_val} | {passes}P/{fails}F | scoring strong but checks miss, routing to tune")
        else:
            cand["is_status"] = "FAIL"

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
        elif soft_pass:
            notify(f"IS TUNE 🔧 {cand['name']}\nS={sharpe_val:.2f} F={fitness_val}\n{cand['expr'][:60]}",
                   emoji="🔧", dedup_key=f"is_tune_{cand.get('alpha_id','')}")

        return is_pass or soft_pass
    
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
            log(f"❌ Submit: HTTP {r.status_code} {r.text[:100]}\n", "error")
    
    # ── Optimization Strategy ─────────────────────────────────
    
    def _should_optimize(self, S: float, F: float) -> bool:
        """Determine if this candidate is worth IS optimization."""
        S = S or 0
        F = F or 0
        if S >= 2.0:              # already excellent, don't risk it
            return False
        if S < 1.0:                # shouldn't happen with PASS, but safety
            return False
        return True  # anything in [1.0, 2.0) is worth trying
    
    def _get_optimization_strategy(self, S: float, F: float) -> dict:
        """
        Analyze S/F profile and return the right tuning strategy.
        
        Thresholds derived from past successful alphas:
        - RevEV_DebtEq_VolMom: S=1.34, F=1.19  (balanced)
        - EbitdaCapOpIncEq_LogVol_1: S=1.46, F=1.23 (S-high-mid, F-mid)
        
        Strategies:
        - S_high_F_low:  S≥1.30, F<1.15  → momentum dominates, reduce/switch to stable
        - F_high_S_low:  F≥1.20, S<1.30  → good structure, weak signal → boost momentum
        - Balanced:      other            → grid search
        """
        S = S or 0
        F = F or 0
        
        mom_pool = [
            ("rank(ts_mean(volume,5))",  "vol_mom"),
            ("rank(ts_mean(adv20,5))",   "adv_mom"),
            ("rank(log(adv20))",         "log_adv"),
            ("rank(ts_mean(low,5))",     "low_mom"),
            ("rank(ts_corr(close,volume,10))", "corr_cv"),
        ]
        mom_map = {k: (e, n) for e, (n, k) in enumerate([(m, n) for m, n in mom_pool])}  # reverse lookup
        # simpler: build dict
        mom_dict = {name: expr for expr, name in mom_pool}
        
        if S >= 1.30 and F < 1.15:
            # S-high / F-low: momentum dominates → reduce weight, try stable fields
            return {
                "mode": "s_high_f_low",
                "description": "⚖️ S高F低 · 动量过重 → 降低权重/换稳定动量",
                "strategy_desc": "weights=[0.3, 0.5] × stable_mom=[adv20, low, log_adv]",
                "weights": [0.3, 0.5],
                "mom_fields": ["adv_mom", "low_mom", "log_adv"],
                "moments": [mom_dict.get("adv_mom"), mom_dict.get("low_mom"), mom_dict.get("log_adv")],
            }
        
        if F >= 1.20 and S < 1.30:
            # F-high / S-low: good check quality, weak signal → boost momentum
            return {
                "mode": "f_high_s_low",
                "description": "⚡ F高S低 · 结构好信号弱 → 增加权重/换高信号动量",
                "strategy_desc": "weights=[0.7, 0.9, 1.2] × boost_mom=[volume, corr_cv, low]",
                "weights": [0.7, 0.9, 1.2],
                "mom_fields": ["vol_mom", "corr_cv", "low_mom"],
                "moments": [mom_dict.get("vol_mom"), mom_dict.get("corr_cv"), mom_dict.get("low_mom")],
            }
        
        # Default: balanced grid search
        return {
            "mode": "balanced",
            "description": "🎯 均衡 · 全搜索最佳动量权重组合",
            "strategy_desc": "weights=[0.3, 0.5, 0.7, 0.9] × all_5_mom",
            "weights": [0.3, 0.5, 0.7, 0.9],
            "mom_fields": ["vol_mom", "adv_mom", "log_adv", "low_mom", "corr_cv"],
            "moments": [mom_dict[n] for n in ["vol_mom", "adv_mom", "log_adv", "low_mom", "corr_cv"]],
        }
    
    def _tune_and_retry(self, cand: dict, ortho: dict, failed_phase: str,
                         is_optimization: bool = False,
                         opt_strategy: dict = None) -> bool:
        """
        Generate tuned variations of a candidate and retry.
        failed_phase: "is" or "sc"
        is_optimization: True = post-pass tuning (test all, pick best S > original)
        """
        max_tune_attempts = 8 if is_optimization else 5
        variations = []
        
        
        # Initialize optimization state
        if is_optimization:
            self._best_opt_sharpe = -999
            self._best_opt_var = None
        
        base_expr = cand["expr"]
        base_name = cand["name"]
        base_sharpe = cand.get("sharpe", 0) or 0
        weight = cand.get("weight", 0.7)
        
        log(f"\n🔧 Tuning {failed_phase.upper()} for {base_name}..." + 
            (" (optimization mode)" if is_optimization else ""))
        
        if failed_phase == "is":
            # IS failure: try different operators and weight adjustments
            orig_sharpe = cand.get("sharpe")
            
            if is_optimization and opt_strategy:
                # ── Strategy-driven optimization variation generation ──
                log(f"  📋 Using optimization strategy: {opt_strategy['description']}")
                ratio_prefix = base_expr.rsplit("+", 1)[0] if "+" in base_expr else base_expr
                gen_count = 0
                for new_w in opt_strategy["weights"]:
                    for idx, mom_name in enumerate(opt_strategy["mom_fields"]):
                        mom = opt_strategy["moments"][idx]
                        new_expr = f"{ratio_prefix}+{new_w}*{mom}"
                        if new_expr != base_expr and new_expr not in set(v["expr"] for v in variations):
                            variations.append({
                                "name": f"{base_name}_opt{mom_name[:3]}_w{int(new_w*10)}"[:40],
                                "expr": new_expr,
                                "weight": new_w,
                                "momentum": mom,
                                "momentum_field": mom_name,
                                "orthogonality_score": cand.get("orthogonality_score", 0) + 1,
                            })
                            gen_count += 1
                            if gen_count >= max_tune_attempts:
                                break
                    if gen_count >= max_tune_attempts:
                        break
                log(f"  Generated {len(variations)} strategy-aligned variations")
            
            elif orig_sharpe is None:
                # S=None means the ratio pair itself is broken (coverage mismatch).
                # Don't waste time on momentum swaps — go directly to new ratio pairs.
                log(f"  ⚡ S=None detected: skipping momentum swaps, going directly to new ratio pairs")
                _generate_new_ratio_variations(cand, variations, ortho, max_tune_attempts)
            else:
                # S<1.25: the ratio pair is valid but weak. Try different operators
                # Variation 1: Different momentum operator
                mom_variants = [
                    ("rank(ts_mean(volume,5))", "vol_mom"),
                    ("rank(ts_mean(adv20,5))", "adv_mom"),
                    ("rank(log(adv20))", "log_adv"),
                    ("rank(ts_mean(low,5))", "low_mom"),
                    ("rank(ts_corr(close,volume,10))", "corr_cv"),
                ]
                # NOTE: "rank(ts_std(returns,5))" removed — always stalls at 0% on WQ engine
                
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
                    _generate_new_ratio_variations(cand, variations, ortho, max_tune_attempts)

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
                ("ts_mean(adv20,5)", "adv_mom"),
                ("log(volume)", "log_vol"),
            ]
            # NOTE: "ts_std(returns,5)" removed from all pools — always stalls at 0%
            
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
            sharpe_val = stats.get("sharpe")
            # P1: S=None means dead pair — don't treat as PASS even if checks look good
            is_pass = (sharpe_val is not None and fails <= 1 and passes >= 6)
            # Soft pass in tune: S >= 1.25 with minor check misses → still counts as success
            soft_pass = (sharpe_val is not None and sharpe_val >= 1.25
                         and fails <= 2 and passes >= 4 and not is_pass)

            log(f"    IS: S={var['sharpe']} F={var['fitness']} | {passes}P/{fails}F")

            if not (is_pass or soft_pass):
                log(f"    ❌ IS failed")
                if var['sharpe'] is None:
                    log(f"    S=None (dead pair), skipping remaining tunes")
                    break
                continue

            if soft_pass:
                log(f"    ✅ Soft IS pass (S={sharpe_val:.2f}, {passes}P/{fails}F) — metrics strong, accepting as tune success")
            
            # Set metadata
            try:
                self.s.patch(f"{API}/alphas/{alpha_id}",
                    json={"name": var["name"], "color": "GREEN",
                          "category": "FUNDAMENTAL", "tags": ["workflow-v2-tune"]}, timeout=15)
            except: pass
            
            if is_optimization:
                # Optimization mode: track best variant by S, test ALL variations
                var_sharpe = var.get("sharpe", 0) or 0
                if var_sharpe > self._best_opt_sharpe:
                    self._best_opt_sharpe = var_sharpe
                    self._best_opt_var = {
                        "alpha_id": alpha_id,
                        "sharpe": var["sharpe"],
                        "fitness": var["fitness"],
                        "expr": var["expr"],
                        "name": var["name"],
                    }
                    log(f"    📈 New best optimization variant: S={var_sharpe:.2f}")
                continue  # Test remaining variations
            
            # Normal mode: first success wins
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
        
        # ── Post-loop: optimization mode check ──
        if is_optimization:
            best_s = self._best_opt_sharpe
            log(f"  Optimization complete: best S={best_s:.2f} vs original S={base_sharpe:.2f}")
            if best_s > base_sharpe and self._best_opt_var:
                bv = self._best_opt_var
                cand["alpha_id"] = bv["alpha_id"]
                cand["sharpe"] = bv["sharpe"]
                cand["fitness"] = bv["fitness"]
                cand["is_status"] = "PASS"
                cand["expr"] = bv["expr"]
                cand["name"] = bv["name"]
                log(f"  ✅ Optimization IMPROVED S: {base_sharpe:.2f} -> {best_s:.2f}")
                notify(f"调优提升 📈 {cand['name']}\nS: {base_sharpe:.2f} -> {best_s:.2f}",
                       emoji="📈", dedup_key=f"opt_{cand.get('alpha_id','')}")
                return True
            log(f"  ℹ️ Optimization: no improvement over original S={base_sharpe:.2f}, keeping original")
            return False  # Keep original
        
        log(f"  ✖️ All {len(variations)} tuned variations failed")
        notify(f"调参耗尽 ✖️ {cand['name']}\n{failed_phase.upper()}方向{len(variations)}个变体全失败",
               emoji="⚠️", dedup_key=f"tune_fail_{cand.get('alpha_id','')}")
        return False


# ═══ MAIN ════════════════════════════════════════
if __name__ == "__main__":
    workflow = Workflow()
    workflow.run()

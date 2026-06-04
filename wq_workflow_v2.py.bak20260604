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
from typing import Optional, Any, Tuple, List

# ═══ Auto-load .env from home directory ═══
# ⚠️ MUST use os.path.expanduser() not Path.home() — launchd does NOT set HOME env var
# Path.home() would return '/' under launchd, loading /root/.hermes/.env (nonexistent)
_env_path = Path(os.path.expanduser("~/.hermes/.env"))
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

import requests, urllib3, re
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
EMAIL = os.environ.get("WQ_EMAIL")
if not EMAIL:
    raise EnvironmentError("WQ_EMAIL not set. Set via .env or export WQ_EMAIL=...")
PASS = os.environ.get("WQ_PASS")
if not PASS:
    raise EnvironmentError("WQ_PASS not set. Set via .env or export WQ_PASS=...")
HOME = Path.home()
STATE_FILE = HOME / ".wq_workflow_v2.json"
LOG_FILE = HOME / ".wq_workflow_v2.log"
TARGET_ACTIVE = 20

# ── Token auto-refresh ──
# WQ token TTL = 14400s (4h). Refresh at 3h to keep 1h margin.
_TOKEN_REFRESH_INTERVAL = 3 * 3600  # 3 hours
_last_auth_time = 0  # set by fresh_session()

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
# WARNING: ONLY include operators that are PROVEN to work on WQ platform.
# sign(), abs(), max(), min(), clip(), zscore(), winsorize(), truncate() are NOT verified WQ operators.
ALL_WQ_OPERATORS = [
    "rank", "ts_mean", "ts_sum", "ts_std", "ts_corr", "ts_rank",
    "ts_min", "ts_max", "ts_argmin", "ts_argmax", "ts_zscore",
    "ts_delta", "ts_trend", "ts_percentile", "scale", "group_rank",
    "log", "ind_neutral",
    "sector_neutral",
]

FIELD_PATTERN = re.compile(r'\b(' + '|'.join(re.escape(f) for f in ALL_WQ_FIELDS) + r')\b')
RATIO_PATTERN = re.compile(r'\b(' + '|'.join(re.escape(f) for f in ALL_WQ_FIELDS) + r')/(' + '|'.join(re.escape(f) for f in ALL_WQ_FIELDS) + r')')

# Regex to extract ratio pattern from ANY ratio, including nested ones like
# rank(ts_delta(close,5)/enterprise_value). Captures raw text on each side of slash.
RATIO_PATTERN_STRICT = re.compile(r'rank\(\s*([^)]+)\s*/\s*([^)]+)\s*\)')

# ── Ratio pattern families for SELF_CORRELATION modeling ──
# WQ SC considers signals from the same "pattern family" as correlated,
# even if individual fields differ. e.g. rev/ev, rev/cap, rev/equity
# all belong to the "revenue-as-numerator" family.
_NUM_TO_FAMILY = {}
for _f in ["revenue", "debt", "operating_income", "cap", "enterprise_value", "equity", "ebitda", "sales", "cash"]:
    _NUM_TO_FAMILY[_f] = _f

DENOM_FAMILY_MAP = {
    "enterprise_value": "ev",
    "cap": "cap",
    "equity": "equity",
    "sales": "sales",
    "revenue": "revenue",
    "debt": "debt",
    "operating_income": "oi",
    "ebitda": "ebitda",
    "cash": "cash",
}

def _extract_ratio_patterns(expr: str) -> list:
    """Extract ratio patterns from expression as (numerator_family, denominator_family) tuples.

    For nested ratios like rank(ts_delta(close,5)/enterprise_value),
    extracts the effective field ratio family (e.g. 'close' -> 'ev').
    For simple ratios like rank(debt/equity), extracts ('debt', 'equity').
    """
    patterns = []
    for m in RATIO_PATTERN_STRICT.finditer(expr):
        num_raw = m.group(1).strip()
        den_raw = m.group(2).strip()
        num_fields = FIELD_PATTERN.findall(num_raw)
        den_fields = FIELD_PATTERN.findall(den_raw)
        if num_fields and den_fields:
            num_field = num_fields[-1]
            den_field = den_fields[-1]
            num_family = _NUM_TO_FAMILY.get(num_field, num_field)
            den_family = DENOM_FAMILY_MAP.get(den_field, den_field)
            patterns.append((num_family, den_family))
    return patterns


# ── Field quadruple extraction for MULT expressions ──
# For rank(A/B)*rank(C/D), extracts the quadruple (A,B,C,D).
# This is the most granular SC predictor: WQ SELF_CORRELATION checks
# if the two ratio signals are correlated at the field level.
# Pair-family tracking is a second-order approximation; quadruple tracking
# captures the exact field interaction.
_QUAD_PATTERN = re.compile(
    r'rank\(\s*([^)]+)\s*/\s*([^)]+)\s*\)\s*\*\s*rank\(\s*([^)]+)\s*/\s*([^)]+)\s*\)'
)


def _extract_field_quadruples(expr: str) -> list:
    """Extract field quadruples from MULT expressions.

    For rank(A/B)*rank(C/D), returns list of (a, b, c, d) where each is
    the effective field (last field found in the numerator/denominator).

    Handles nested ratios: rank(ts_delta(close,5)/enterprise_value)*rank(debt/equity)
    → [('close', 'enterprise_value', 'debt', 'equity')]

    Returns empty list for non-MULT expressions.
    """
    quadruples = []
    for m in _QUAD_PATTERN.finditer(expr):
        num1_raw = m.group(1).strip()
        den1_raw = m.group(2).strip()
        num2_raw = m.group(3).strip()
        den2_raw = m.group(4).strip()

        # Extract effective fields (last field found in each side)
        num1_fields = FIELD_PATTERN.findall(num1_raw)
        den1_fields = FIELD_PATTERN.findall(den1_raw)
        num2_fields = FIELD_PATTERN.findall(num2_raw)
        den2_fields = FIELD_PATTERN.findall(den2_raw)

        if all([num1_fields, den1_fields, num2_fields, den2_fields]):
            a = num1_fields[-1]
            b = den1_fields[-1]
            c = num2_fields[-1]
            d = den2_fields[-1]
            # Normalize: frozenset of (pair1, pair2) so (A/B, C/D) == (C/D, A/B)
            pair1 = tuple(sorted([a, b]))
            pair2 = tuple(sorted([c, d]))
            quad = tuple(sorted([pair1, pair2]))
            quadruples.append(quad)
    return quadruples


def _normalize_quad_key(quad) -> str:
    """
    Convert a quadruple tuple to a normalized string key for DB lookup.
    quad is: ((a, b), (c, d)) where each pair is sorted alphabetically.
    Output: "a/b,c/d" normalized.
    """
    if not quad:
        return ""
    pair1_str = "/".join(quad[0])
    pair2_str = "/".join(quad[1])
    # Normalize: sort pair order so (A/B,C/D) == (C/D,A/B)
    if pair1_str <= pair2_str:
        return f"{pair1_str},{pair2_str}"
    return f"{pair2_str},{pair1_str}"

# ── Field time-frequency compatibility groups ──
# Mixing daily-updated (pv1) with quarterly-updated (fundamental6) fields in ratio pairs
# causes NA coverage misalignment → S=None in WQ engine
PV1_FIELDS = {"close", "volume", "adv20", "returns", "vwap", "open", "high", "low"}
FUND_FIELDS = {"revenue", "enterprise_value", "debt", "equity", "operating_income", "ebitda", "cap", "cash", "sales"}

# WQ neutralization dimensions — tried in gradient order for SC fail degradation.
# INDUSTRY (current default) is coarsest; SECTOR/SubINDUSTRY peel finer layers,
# reducing pseudo-correlation in SELF_CORRELATION checks.
NEUTRALIZATION_DIMS = ["INDUSTRY", "SECTOR", "SUBINDUSTRY"]

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

# v3 Advanced Skeletons (directions A-D)
SKELETON_CROSS_GATE = "cross_gate"       # A: 跨域条件门控 rank(pv1_signal)*sign(ts_delta(fund,N))
SKELETON_DEEP_CASCADE = "deep_cascade"   # B: 深度嵌套 ts_rank(ts_corr(rank(A),rank(B),N),M)
SKELETON_NONLINEAR_BREAKER = "nonlinear_breaker"  # C: 非线性 ts_argmax/close, N)*sign(ts_delta(ratio,N))
SKELETON_TSRANK_CORR = "tsrank_corr"     # B: ts_rank(ts_corr(rank(A),rank(B),N1),N2)
SKELETON_SIGN_SWITCH = "sign_switch"     # C: sign(ts_delta(close,N)) * rank(fund_ratio)
SKELETON_TREND_BREAK = "trend_break"     # C: ts_argmax(volume,N)/ts_argmax(volume,2N) * rank(close/money)
SKELETON_VOL_ADJ = "vol_adj"             # C: rank(close/volume) / ts_std(returns,N)
SKELETON_RESIDUAL = "residual"           # B: ts_rank(ts_residual(close,returns,N),M)

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

# ═══ Database ═══════════════════════════════════════════════════════
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import wq_db as _wqdb
STATE_KEY = "workflow"

# Init DB on startup
_wqdb.init_db()

# Migrate existing state.json to SQLite (one-time)
if STATE_FILE.exists():
    _wqdb.export_state_to_db(STATE_FILE)

def load_state() -> dict:
    """Load workflow state from SQLite, with JSON crash-recovery fallback."""
    raw = _wqdb.load_workflow_state(STATE_KEY)
    # Handle old key name "failed_exprs" → migrate to "failed_expressions"
    if "failed_exprs" in raw and "failed_expressions" not in raw:
        raw["failed_expressions"] = raw.pop("failed_exprs")
    if raw:
        state = raw
    else:
        state = {
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
            "failed_expressions": [],
            "stuck_batches": 0,
            "batches_since_optimization": 0,
            "last_optimization_at": None,
            "skeleton_popularity": {},
            "skeleton_popularity_decay": 1.0,
        }
    # CRASH-RECOVERY: if skeleton_popularity is empty but JSON backup exists, restore
    try:
        import os
        backup_path = os.path.expanduser("~/.wq_skeleton_popularity.json")
        if os.path.exists(backup_path):
            backup = json.load(open(backup_path))
            if not state.get("skeleton_popularity") and backup:
                state["skeleton_popularity"] = backup
    except:
        pass
    return state

def save_state(state: dict):
    """Save workflow state to SQLite."""
    state["last_updated"] = datetime.now().isoformat()
    # Truncate errors to last 20 to prevent bloat
    if len(state.get("errors", [])) > 20:
        state["errors"] = state["errors"][-20:]
    _wqdb.save_workflow_state(STATE_KEY, state)

# ═══ Enhanced log: also write to SQLite ─────────────
_original_log = log
def log(msg, level="info"):
    _original_log(msg, level)
    try:
        _wqdb.log_to_db(level.upper(), msg)
    except Exception:
        pass  # Never crash workflow if DB log fails

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
    global _last_auth_time
    s = requests.Session()
    s.mount("https", _TLSAdapter())
    s.verify = False
    s.trust_env = False
    # Use Clash proxy (port 7897) — required from China network
    s.proxies = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
    # 2 retry attempts on same proxy (SSL EOF is intermittent)
    for attempt in range(3):
        try:
            r = s.post(f"{API}/authentication", auth=(EMAIL, PASS), timeout=60)
            if r.status_code == 201:
                _last_auth_time = time.time()
                log("🔐 Auth OK")
                return s
            raise RuntimeError(f"Auth failed: {r.status_code} {r.text[:200]}")
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            if attempt >= 2:
                raise RuntimeError(f"WQ unreachable after 3 attempts: {e}")
            log(f"⚠️ Auth attempt {attempt+1} failed: {str(e)[:60]}, retrying...")
            time.sleep(3)
    raise RuntimeError("Auth: unexpected")


def _ensure_valid_session(session: requests.Session) -> requests.Session:
    """Auto-refresh session token if >3h old or if 401 detected. Returns (session, was_refreshed)."""
    global _last_auth_time
    now = time.time()
    if now - _last_auth_time > _TOKEN_REFRESH_INTERVAL:
        log(f"🔄 Token expired ({now - _last_auth_time:.0f}s since auth), refreshing...")
        new_s = fresh_session()
        _last_auth_time = now  # fresh_session() sets it, but be safe
        return new_s
    return session

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
    ratio_pattern_freq = {}  # {(num_family, den_family): count_of_actives}
    active_quadruples = {}  # {quadruple_key: [expr_snippets]} — field-level pair tracking

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
        
        # ── NEW: Extract ratio pattern families for SELF_CORRELATION modeling ──
        for (num_fam, den_fam) in _extract_ratio_patterns(expr):
            key = (num_fam, den_fam)
            ratio_pattern_freq[key] = ratio_pattern_freq.get(key, 0) + 1
        
        # ── NEW: Extract field quadruples for MULT expressions ──
        # For rank(A/B)*rank(C/D), extracts normalized quadruples.
        # This is the most granular SC predictor: WQ SELF_CORRELATION checks
        # if the two ratio signals share overlapping field pairs.
        # Pair-family tracking is second-order; quadruple tracking is field-level.
        # NOTE: We don't store SC result here (ACTIVE alphas may or may not have SC data).
        # Instead, _extract_field_quadruples() is used in scoring to check overlap
        # with existing ACTIVE expressions' quadruples.
        for quad in _extract_field_quadruples(expr):
            quad_key = quad  # tuple of ((a,b), (c,d)) normalized pairs
            if quad_key not in active_quadruples:
                active_quadruples[quad_key] = []
            active_quadruples[quad_key].append(expr[:60])
    
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
        "ratio_pattern_freq": ratio_pattern_freq,
        "active_quadruples": active_quadruples,
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
    
    # ── Ratio pattern SELF_CORRELATION penalty (NEW) ──
    # SC considers signals from same pattern family correlated,
    # even with different fields. e.g. rev/ev, rev/cap, rev/equity
    # each adds to the "revenue-as-numerator" family in existing actives.
    candidate_patterns = _extract_ratio_patterns(expr)
    pattern_freq = ortho.get("ratio_pattern_freq", {})
    for (num_fam, den_fam) in candidate_patterns:
        fam_key = (num_fam, den_fam)
        usage = pattern_freq.get(fam_key, 0)
        if usage >= 1:
            # -3 for 1 existing, -6 for 2+, -10 for 3+
            penalty = -3 * min(usage, 3)
            novelty_score += penalty
    
    # Also penalize numerator-family overlap: even if denominator differs,
    # signals sharing the same numerator family tend to be correlated.
    candidate_nums = set()
    for (num_fam, _) in candidate_patterns:
        candidate_nums.add(num_fam)
    for existing_num in pattern_freq:
        if existing_num[0] in candidate_nums and existing_num[0] not in _NUM_TO_FAMILY:
            continue
    # Simpler: check if any numerator family appears in >1 active
    for num_fam in _NUM_TO_FAMILY.values():
        count_in_family = sum(1 for (nf, df), c in pattern_freq.items() if nf == num_fam and c > 0)
        if count_in_family > 1:
            novelty_score -= 2  # Cross-field numerator family collision
    
    # ── Field quadruple overlap penalty for MULT expressions ──
    # The most granular SC predictor: for rank(A/B)*rank(C/D), WQ SELF_CORRELATION
    # checks if the two ratio signals overlap in field pairs.
    # If a candidate's quadruple shares a pair with any ACTIVE expression,
    # the two signals are more likely correlated → lower SC score.
    # This is field-level (not family-level), making it the most specific predictor.
    candidate_quads = _extract_field_quadruples(expr)
    active_quads = ortho.get("active_quadruples", {})
    for cand_quad in candidate_quads:
        # cand_quad is a tuple of two sorted pair tuples: ((a,b), (c,d))
        pair1, pair2 = cand_quad
        # Check if either of candidate's pairs overlaps with any ACTIVE expression's pair
        for active_quad_key, active_expr_snippets in active_quads.items():
            for active_pair in active_quad_key:
                # If candidate shares ANY field pair with an existing ACTIVE's pair,
                # reduce orthogonality score — signals will be correlated
                if pair1 == active_pair or pair2 == active_pair:
                    # -5 for exact pair overlap (same A/B or same C/D)
                    # -2 for shared numerator field in different pair (partial overlap)
                    novelty_score -= 5
                    break  # One overlap per active quad is enough
                # Partial overlap: if numerator fields overlap
                c1_fields = set(pair1)
                c2_fields = set(pair2)
                a1_fields = set(active_pair)
                if c1_fields & a1_fields or c2_fields & a1_fields:
                    novelty_score -= 2  # Partial field overlap
        # Check if this exact quadruple already exists in ACTIVE
        if cand_quad in active_quads:
            novelty_score -= 8  # Exact quadruple reuse → high correlation risk
    
    # ── AST structure collision penalty (revised: reverse incentive) ──
    # Instead of penalizing dominant skeletons, REWARD rare ones
    # to break lock-in. Rare skeletons get bonus, dominant get small penalty.
    mult_pattern = re.compile(r'rank\([^)]+\)\*rank\([^)]+\)\+')
    sub_pattern = re.compile(r'rank\([^)]+\)\s*-\s*rank\(')
    
    has_mult = bool(mult_pattern.search(expr))
    has_sub = bool(sub_pattern.search(expr))
    
    mult_count = ortho.get("multiplication_count", 0)
    sub_count = ortho.get("subtraction_count", 0)
    total_actives = mult_count + sub_count + ortho.get("add_count", 0) + ortho.get("group_count", 0)
    
    # Actual count of true MULT skeletons (ratio*ratio+ pattern)
    true_mult = sum(1 for s in ortho.get("structures", [])
                    if s["type"] == "multiplication_ratio")
    true_sub = sum(1 for s in ortho.get("structures", [])
                   if s["type"] in ("subtraction", "direct_sub"))
    
    # Reverse incentive: rare skeletons get bonus, dominant get small penalty
    if has_mult and true_mult <= max(1, total_actives // 3):
        novelty_score += 2  # Reward underrepresented MULT
    elif has_mult and true_mult > total_actives * 2 // 3:
        novelty_score -= 2  # MULT already dominant
    
    if has_sub and true_sub <= max(1, total_actives // 3):
        novelty_score += 2  # Reward underrepresented SUB
    elif has_sub and true_sub > total_actives * 2 // 3:
        novelty_score -= 2  # SUB already dominant
    
    # Also reward rare skeleton types (ind_neut, pure_mult, direct_rank, etc.)
    for s in ortho.get("structures", []):
        stype = s["type"]
        if stype not in ("mult_ratio", "subtraction", "direct_sub", "direct_add"):
            existing_count = sum(1 for s2 in ortho.get("structures", []) if s2["type"] == stype)
            # If candidate is this rare type, give bonus
            if stype in ("ind_neutral",) and "ind_neutral" in expr:
                novelty_score += 3
            elif stype == "pure_mult" and "*" in expr and "+" not in expr and "/" in expr:
                novelty_score += 1
    
    # ── Historical SC pass rate penalty (v3.17 regression model) ──
    # Apply data-driven penalty: if a quadruple has poor SC history,
    # reduce orthogonality score proportionally.
    for cand_quad in candidate_quads:
        quad_key = _normalize_quad_key(cand_quad)
        if quad_key:
            adjusted, penalty = _wqdb.get_quad_sc_penalty(quad_key, 0.0)
            if penalty > 0:
                novelty_score -= penalty  # Scale penalty to full score space
    
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


# ═══ Task 1: Conditional Gating for Cross-Domain Mixing ═══

def _is_temporal_operator(field_expr: str) -> bool:
    """Check if a string is wrapped in a temporal operator that smooths/transforms coverage.
    
    Temporal operators provide time-series alignment that bridges daily/fundamental frequency gaps.
    """
    temporal_ops = ["ts_delta(", "ts_zscore(", "ts_rank(", "ts_std(", "ts_mean(", "ts_corr(", "ts_min(", "ts_max("]
    for op in temporal_ops:
        if field_expr.startswith(op):
            return True
    return False


def _build_cross_domain_ratio_pool(ortho: dict, skip_zero_occupancy: bool = False) -> list:
    """Build cross-domain ratio pairs bridging PV1 (price/volume, daily) and FUND (fundamental, quarterly).
    
    Conditional gating rule: at least one side MUST be wrapped in a temporal operator.
    This provides time-series alignment that reduces coverage mismatch:
      - rank(ts_delta(close,5) / enterprise_value)       — PV1 numerator temporally smoothed → fund denom
      - rank(revenue / ts_delta(close,10))               — fund numerator → PV1 denominator temporally smoothed
      - rank(ts_zscore(volume,20) / operating_income)    — volume volatility → revenue scale
    
    Returns format: list of (expr_str, name) compatible with existing ratio pool.
    """
    field_usage = ortho["fields_used"]
    used_pairs = ortho["field_pairs_used"]
    zero_usage = {"ebitda", "cash", "sales"}
    
    pool = []
    seen = set()
    
    # Cross-domain pairs: (temporal_pv1_field, fund_field) and (fund_field, temporal_pv1_field)
    # Temporal wrapper + PV1 field → fundamental denominator
    pv1_fields = list(PV1_FIELDS)
    fund_fields = list(FUND_FIELDS)
    
    for temporal_op in ["ts_delta", "ts_zscore", "ts_mean", "ts_std", "ts_rank"]:
        for period in [3, 5, 7, 10, 15, 20]:
            for pv1_field in pv1_fields:
                if pv1_field == "close":  # close used too broadly
                    continue
                # Direction 1: temporal(PV1) / FUND
                for fund_field in fund_fields:
                    if skip_zero_occupancy and fund_field in zero_usage:
                        continue
                    key = f"{temporal_op}_{pv1_field}_{period}_{fund_field}"
                    if key in seen:
                        continue
                    
                    expr_1 = f"rank({temporal_op}({pv1_field},{period})/{fund_field})"
                    # Validate it doesn't contain already-used raw pair
                    raw_fields = set(FIELD_PATTERN.findall(expr_1))
                    if len(raw_fields) >= 2:
                        rp = frozenset(list(raw_fields)[:2])
                        if rp in used_pairs:
                            continue
                    
                    seen.add(key)
                    pool.append((expr_1, f"cd_{temporal_op}_{pv1_field}_{fund_field}_p{period}"[:40]))
                
                # Direction 2: FUND / temporal(PV1)
                for fund_field in fund_fields:
                    if skip_zero_occupancy and fund_field in zero_usage:
                        continue
                    key = f"{temporal_op}_rev_{fund_field}_{pv1_field}_{period}"
                    if key in seen:
                        continue
                    
                    expr_2 = f"rank({fund_field}/{temporal_op}({pv1_field},{period}))"
                    raw_fields = set(FIELD_PATTERN.findall(expr_2))
                    if len(raw_fields) >= 2:
                        rp = frozenset(list(raw_fields)[:2])
                        if rp in used_pairs:
                            continue
                    
                    seen.add(key)
                    pool.append((expr_2, f"cd_{temporal_op}_rev_{fund_field}_{pv1_field}_p{period}"[:40]))
    
    return pool


def _generate_cross_domain_candidates(ratio_pool: list, ortho: dict, active_exprs: list) -> list:
    """Generate candidates from cross-domain ratio pool using the standard MULT skeleton.
    
    These candidates combine cross-domain ratios with standard momentum terms,
    producing expressions like:
      rank(ts_delta(close,5)/enterprise_value)*rank(debt/equity)+0.7*rank(ts_mean(adv20,5))
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
    
    # Build templates from cross-domain pool
    templates = []
    template_seen = set()
    for (r1_str, r1_name) in ratio_pool[:8]:  # More pool size for cross-domain
        r1_fields = set(FIELD_PATTERN.findall(r1_str))
        for (r2_str, r2_name) in ratio_pool[:8]:
            if r1_str == r2_str:
                continue
            r2_fields = set(FIELD_PATTERN.findall(r2_str))
            # Allow some overlap for cross-domain (different field groups by design)
            all_groups = {_get_field_group(f) for f in (r1_fields | r2_fields)}
            # For cross-domain, we need at least some structural diversity
            if len(all_groups) <= 1:
                continue  # Same domain — let regular pool handle it
            
            for mom_str, mom_name in momentums[:4]:
                tkey = (r1_str, r2_str, mom_str)
                if tkey in template_seen:
                    continue
                template_seen.add(tkey)
                median_expr = f"{r1_str}*{r2_str}+0.5*rank({mom_str})"
                score = score_candidate_orthogonality(median_expr, ortho, active_exprs)
                templates.append({
                    "r1_str": r1_str, "r1_name": r1_name,
                    "r2_str": r2_str, "r2_name": r2_name,
                    "mom_str": mom_str, "mom_name": mom_name,
                    "score": score,
                })
    
    templates.sort(key=lambda t: -t["score"])
    
    for tmpl in templates[:20]:  # Limit to top 20 templates
        for w in [0.3, 0.5, 0.7]:
            expr = f"{tmpl['r1_str']}*{tmpl['r2_str']}+{w}*rank({tmpl['mom_str']})"
            if expr in seen:
                continue
            seen.add(expr)
            name = f"CD_{tmpl['r1_name']}_{tmpl['r2_name']}_w{int(w*10)}"[:40]
            name = name.replace("-", "_").replace(" ", "")
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": tmpl["score"],
                "skeleton": SKELETON_CROSS_GATE,  # New skeleton type for cross-gate
                "weight": w,
            })
    
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_temporal_wrap_candidates(ortho: dict, active_exprs: list) -> list:
    """Generate candidates by wrapping verified fundamental ratios in high-order temporal operators.
    
    This is a pure cross-domain approach: take proven fund ratios and wrap them in
    ts_*, sign(), or residual operations to create temporal signatures.
    
    Examples:
      ts_delta(rank(revenue/enterprise_value), 5)
      sign(ts_delta(revenue/enterprise_value, 3)) * rank(ts_mean(returns, 5))
      ts_zscore(rank(debt/equity), 10)
    """
    candidates = []
    seen = set()
    
    # Use only fundamental ratio pairs (same domain, no mixing)
    for num, den in VERIFIED_NUM_DEN_PAIRS:
        if num in {"ebitda", "cash", "sales"} or den in {"ebitda", "cash", "sales"}:
            continue
        
        ratio_expr = f"rank({num}/{den})"
        
        # Topology A: ts_delta of ratio → captures fundamental change rate
        for period in [3, 5, 10]:
            expr = f"ts_delta({ratio_expr}, {period})"
            if expr not in seen:
                seen.add(expr)
                score = score_candidate_orthogonality(expr, ortho, active_exprs)
                candidates.append({
                    "name": f"TWA_delta_{num[:3]}{den[:3]}_p{period}"[:40],
                    "expr": expr,
                    "orthogonality_score": score,
                    "skeleton": SKELETON_NONLINEAR_BREAKER,
                    "weight": 1.0,
                })
        
        # Topology B: ts_zscore of ratio → captures extreme fundamental deviation
        for period in [10, 20]:
            expr = f"ts_zscore({ratio_expr}, {period})"
            if expr not in seen:
                seen.add(expr)
                score = score_candidate_orthogonality(expr, ortho, active_exprs)
                candidates.append({
                    "name": f"TWA_zscore_{num[:3]}{den[:3]}_p{period}"[:40],
                    "expr": expr,
                    "orthogonality_score": score,
                    "skeleton": SKELETON_DEEP_CASCADE,
                    "weight": 1.0,
                })
        
        # Topology C: sign(ts_delta(ratio)) * rank(pv1_momentum) — cross-domain interaction
        for period in [3, 5]:
            for mom_expr, mom_name in [("ts_mean(volume,5)", "vol_mom"), 
                                         ("ts_mean(adv20,5)", "adv_mom"),
                                         ("ts_std(returns,5)", "ret_vol")]:
                expr = f"sign(ts_delta({ratio_expr}, {period})) * rank({mom_expr})"
                if expr not in seen:
                    seen.add(expr)
                    score = score_candidate_orthogonality(expr, ortho, active_exprs)
                    candidates.append({
                        "name": f"TWA_sign_{num[:3]}{den[:3]}_{mom_name}_p{period}"[:40],
                        "expr": expr,
                        "orthogonality_score": score,
                        "skeleton": SKELETON_SIGN_SWITCH,
                        "weight": 1.0,
                    })
    
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_cross_gate_candidates(ortho: dict, active_exprs: list) -> list:
    """Pattern A: rank(Price_Field) * sign(ts_delta(Fund_Field, N)) — 跨域条件门控。
    
    严格遵循 prompt 要求：rank(pv1) 直接作为截面算子，与 sign(ts_delta(fund, N)) 相乘。
    这是最直接的跨域交互因子形式，同时满足 S≠None 要求（ts_delta 提供时序性）。
    """
    candidates = []
    seen = set()
    
    for pv1_field in list(PV1_FIELDS):
        if pv1_field in ("close",):  # close used too broadly
            continue
        for fund_field in list(FUND_FIELDS):
            if fund_field in ("ebitda", "cash", "sales"):
                continue
            for n in [3, 5, 7, 10]:
                # rank(PV1) * sign(ts_delta(FUND, N)) — 核心 pattern
                expr = f"rank({pv1_field}) * sign(ts_delta({fund_field}, {n}))"
                if expr not in seen:
                    seen.add(expr)
                    score = score_candidate_orthogonality(expr, ortho, active_exprs)
                    candidates.append({
                        "name": f"CG_{pv1_field}_{fund_field}_p{n}"[:40],
                        "expr": expr,
                        "orthogonality_score": score,
                        "skeleton": SKELETON_CROSS_GATE,
                        "weight": 1.0,
                    })
                # 反转方向：rank(FUND) * sign(ts_delta(PV1, N))
                expr2 = f"rank({fund_field}) * sign(ts_delta({pv1_field}, {n}))"
                if expr2 not in seen:
                    seen.add(expr2)
                    score = score_candidate_orthogonality(expr2, ortho, active_exprs)
                    candidates.append({
                        "name": f"CG_{fund_field}_rev_{pv1_field}_p{n}"[:40],
                        "expr": expr2,
                        "orthogonality_score": score,
                        "skeleton": SKELETON_CROSS_GATE,
                        "weight": 1.0,
                    })
    
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


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
            # Allow limited field overlap: same numerator but different denominator
            # is fine because different denominators create different normalization.
            # Only reject if ratios are identical (which already handled above)
            # or if they share BOTH fields (which means they're the same ratio).
            overlap = r1_fields & r2_fields
            if overlap and r1_fields == r2_fields:
                continue  # Identical field sets — same ratio family, skip
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
    gap_fill: direct_rank — rank(A) +/- W*rank(ts_*(B,N))
    Direct field rank with at least one time-series operator on every expression.
    Pure cross-section (no ts_*) always returns S=None in WQ.
    
    Patterns:
      - fund + ts_delta(pv1):  rank(fund) - W*rank(ts_delta(close,5))
      - ts_rank(fund) +/- rank(pv1):  rank(ts_rank(fund,250)) +/- W*rank(pv1)
      - cross-domain:  rank(fund) - W*rank(returns)  (returns is natively time-series)
    """
    candidates = []
    # Use fund fields + pv1 fields with time-series wrapping
    fund_fields = ["revenue", "debt", "operating_income", "cap", "enterprise_value", "equity"]
    pv1_fields = ["returns", "volume", "adv20", "high", "low", "open", "close", "vwap"]

    # Base combos: (left, right, op, base_weight, suffix, extra_weights)
    # extra_weights allows generating additional weight variants beyond the base
    combos = [
        # ── Pattern 1: ts_delta wrapper on pv1 side (lowest operator count) ──
        ("debt", "ts_delta(close,5)", "subtract", 1.0, "debt_dcl5", [0.5, 0.7]),
        ("revenue", "ts_delta(close,5)", "subtract", 1.0, "rev_dcl5", [0.5, 0.7]),
        ("cap", "ts_delta(close,5)", "subtract", 1.0, "cap_dcl5", [0.5, 0.7]),
        ("enterprise_value", "ts_delta(close,5)", "subtract", 1.0, "ev_dcl5", [0.5, 0.7]),
        ("operating_income", "ts_delta(close,5)", "subtract", 1.0, "oi_dcl5", [0.5, 0.7]),
        ("equity", "ts_delta(close,5)", "subtract", 1.0, "eq_dcl5", [0.5, 0.7]),

        ("debt", "ts_delta(high,5)", "subtract", 1.0, "debt_dhi5", [0.5, 0.7]),
        ("revenue", "ts_delta(high,5)", "subtract", 1.0, "rev_dhi5", [0.5, 0.7]),

        # ── Pattern 2: ts_mean momentum on pv1 side ──
        ("debt", "ts_mean(returns,5)", "subtract", 1.0, "debt_mret5", [0.5, 0.7]),
        ("revenue", "ts_mean(returns,5)", "subtract", 1.0, "rev_mret5", [0.5, 0.7]),
        ("cap", "ts_mean(returns,5)", "subtract", 1.0, "cap_mret5", [0.5, 0.7]),
        ("equity", "ts_mean(returns,5)", "subtract", 1.0, "eq_mret5", [0.5, 0.7]),
        ("enterprise_value", "ts_mean(returns,5)", "subtract", 1.0, "ev_mret5", [0.5, 0.7]),
        ("operating_income", "ts_mean(volume,10)", "subtract", 1.0, "oi_mvol10", [0.5, 0.7]),

        # ── Pattern 3: ts_rank wrapping on fundamental side ──
        ("ts_rank(debt,250)", "returns", "add", 1.0, "tsr_debt_ret", [0.5, 0.7]),
        ("ts_rank(revenue,250)", "returns", "add", 1.0, "tsr_rev_ret", [0.5, 0.7]),
        ("ts_rank(cap,250)", "returns", "add", 1.0, "tsr_cap_ret", [0.5, 0.7]),
        ("ts_rank(equity,250)", "returns", "subtract", 1.0, "tsr_eq_ret_sub", [0.5, 0.7]),
        ("ts_rank(enterprise_value,250)", "returns", "subtract", 1.0, "tsr_ev_ret_sub", [0.5, 0.7]),
        ("ts_rank(operating_income,250)", "volume", "subtract", 1.0, "tsr_oi_vol", [0.5, 0.7]),

        # ── Pattern 4: cross-domain (fund + native-ts pv1, proven working) ──
        ("debt", "returns", "subtract", 2.0, "debt_ret_sub2", []),
        ("revenue", "returns", "subtract", 1.0, "rev_ret_sub", [0.3, 0.5, 0.7, 0.9]),
        ("cap", "returns", "add", 1.0, "cap_ret_add", [0.3, 0.5, 0.7, 0.9]),
        ("enterprise_value", "returns", "subtract", 1.0, "ev_ret_sub", [0.3, 0.5, 0.7, 0.9]),
        ("equity", "returns", "subtract", 1.0, "eq_ret_sub", [0.3, 0.5, 0.7, 0.9]),
        ("operating_income", "returns", "subtract", 1.0, "oi_ret_sub", [0.3, 0.5, 0.7, 0.9]),

        # ── Pattern 5: fund + ts_corr(close, volume, N) — cross-correlation signal ──
        ("debt", "ts_corr(close,volume,10)", "add", 1.0, "debt_cv10", [0.3, 0.5]),
        ("revenue", "ts_corr(close,volume,10)", "add", 1.0, "rev_cv10", [0.3, 0.5]),
        ("enterprise_value", "ts_corr(close,volume,10)", "add", 1.0, "ev_cv10", [0.3, 0.5]),
        ("operating_income", "ts_corr(close,volume,10)", "add", 1.0, "oi_cv10", [0.3, 0.5]),

        # ── Pattern 6: fund + ts_zscore(pv1) — zscore momentum ──
        ("debt", "ts_zscore(close,20)", "add", 1.0, "debt_zs20", [0.3, 0.5, 0.7]),
        ("revenue", "ts_zscore(close,20)", "add", 1.0, "rev_zs20", [0.3, 0.5, 0.7]),
        ("enterprise_value", "ts_zscore(close,20)", "add", 1.0, "ev_zs20", [0.3, 0.5, 0.7]),
        ("equity", "ts_zscore(close,20)", "add", 1.0, "eq_zs20", [0.3, 0.5, 0.7]),
        ("operating_income", "ts_zscore(close,20)", "add", 1.0, "oi_zs20", [0.3, 0.5, 0.7]),

        # ── Pattern 7: fund + ts_rank(pv1, N) — rank momentum ──
        ("debt", "ts_rank(close,20)", "subtract", 1.0, "debt_rcl20", [0.3, 0.5]),
        ("revenue", "ts_rank(close,20)", "subtract", 1.0, "rev_rcl20", [0.3, 0.5]),
        ("enterprise_value", "ts_rank(close,20)", "subtract", 1.0, "ev_rcl20", [0.3, 0.5]),
        ("operating_income", "ts_rank(close,20)", "subtract", 1.0, "oi_rcl20", [0.3, 0.5]),

        # ── Pattern 8: ts_mean(returns, 20) — longer momentum window ──
        ("debt", "ts_mean(returns,20)", "subtract", 1.0, "debt_mret20", [0.3, 0.5, 0.7]),
        ("revenue", "ts_mean(returns,20)", "subtract", 1.0, "rev_mret20", [0.3, 0.5, 0.7]),
        ("enterprise_value", "ts_mean(returns,20)", "subtract", 1.0, "ev_mret20", [0.3, 0.5, 0.7]),
        ("operating_income", "ts_mean(returns,20)", "subtract", 1.0, "oi_mret20", [0.3, 0.5, 0.7]),
        ("equity", "ts_mean(returns,20)", "subtract", 1.0, "eq_mret20", [0.3, 0.5, 0.7]),

        # ── Pattern 9: ts_mean(volume, 20) — volume momentum ──
        ("debt", "ts_mean(volume,20)", "subtract", 1.0, "debt_mvol20", [0.3, 0.5, 0.7]),
        ("revenue", "ts_mean(volume,20)", "subtract", 1.0, "rev_mvol20", [0.3, 0.5, 0.7]),
        ("enterprise_value", "ts_mean(volume,20)", "subtract", 1.0, "ev_mvol20", [0.3, 0.5, 0.7]),
        ("operating_income", "ts_mean(volume,20)", "subtract", 1.0, "oi_mvol20", [0.3, 0.5, 0.7]),
    ]

    seen = set()
    for left, right, op, base_w, suffix, extra_ws in combos:
        # Always generate base weight variant
        weights_to_try = [base_w]
        # Also generate extra weight variants (different S/F combos)
        for ew in extra_ws:
            if ew != base_w:
                weights_to_try.append(ew)
        
        for w in weights_to_try:
            if op == "add":
                expr = f"rank({left})+{w}*rank({right})"
            else:
                expr = f"rank({left})-{w}*rank({right})"
            if expr in seen or expr in active_exprs:
                continue
            seen.add(expr)
            score = score_candidate_orthogonality(expr, ortho, active_exprs)
            name = f"DR_{suffix}_w{int(w*10)}"[:40]
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": score,
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


# ═══ v3.19 NEW ADVANCED SKELETON GENERATORS ═══════════════
# These implement 4 of the 7 advanced skeletons defined as constants
# but never generated: sign_switch, vol_adj, deep_cascade, cross_gate.
# Each has at least one ts_* operator (S≠None guarantee).
# Each uses only proven field pairs (no ebitda/cash/sales ratios).


def _generate_sign_switch_candidates(ortho: dict, active_exprs: list) -> list:
    """Pattern C: sign_switch — sign(ts_delta(close,N)) * rank(fund_ratio)
    
    Captures: directional price change * fundamental value.
    sign(ts_delta) provides binary +1/-1 switch for price momentum direction.
    Multiplying by a fundamental ratio ranks creates a conditional value signal.
    ts_delta provides the time-series component → S≠None guaranteed.
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
    # ts_delta windows: short (5d), medium (10d), long (20d)
    delta_windows = [
        ("ts_delta(close,5)", "dcl5"),
        ("ts_delta(close,10)", "dcl10"),
        ("ts_delta(close,20)", "dcl20"),
        ("-1*ts_delta(close,5)", "neg_dcl5"),
        ("-1*ts_delta(close,10)", "neg_dcl10"),
        ("ts_delta(high,5)", "dhi5"),
        ("ts_delta(volume,5)", "dvol5"),
    ]
    seen = set()
    for (ratio_str, ratio_name) in fund_ratios:
        for (delta_str, delta_name) in delta_windows:
            # sign + ts_delta = ts_ operator present → S≠None
            expr = f"sign({delta_str})*rank({ratio_str})"
            if expr in seen or expr in active_exprs:
                continue
            seen.add(expr)
            score = score_candidate_orthogonality(expr, ortho, active_exprs)
            name = f"SS_{delta_name}_{ratio_name}"[:40]
            name = name.replace("-","_").replace(" ","")
            candidates.append({
                "name": name, "expr": expr,
                "orthogonality_score": score,
                "skeleton": SKELETON_SIGN_SWITCH,
            })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_vol_adj_candidates(ortho: dict, active_exprs: list) -> list:
    """Pattern: vol_adj — rank(ts_corr(X,Y,N)) + W*rank(fund_ratio)
    
    Volatility-adjusted signal: price-volume correlation + fundamental ratio.
    ts_corr provides the time-series component. The correlation itself captures
    market regime (trending vs choppy), while the ratio adds fundamental value.
    No actual division by ts_std (which risks S=None), so the name reflects
    that this is a volatility-aware structural pattern.
    """
    candidates = []
    # Correlation signals: price-volume, price-volatility
    corr_signals = [
        ("ts_corr(close,volume,10)", "cv10"),
        ("ts_corr(close,volume,20)", "cv20"),
        ("ts_corr(close,volume,40)", "cv40"),
        ("ts_corr(close,returns,10)", "cr10"),
        ("ts_corr(close,returns,20)", "cr20"),
        ("ts_corr(volume,returns,10)", "vr10"),
        ("ts_corr(close,adv20,20)", "ca20"),
    ]
    fund_ratios = [
        ("revenue/enterprise_value", "rev_ev"),
        ("debt/equity", "de"),
        ("revenue/cap", "rev_cap"),
        ("operating_income/cap", "oi_cap"),
        ("revenue/equity", "rev_eq"),
    ]
    seen = set()
    for (corr_str, corr_name) in corr_signals:
        for (ratio_str, ratio_name) in fund_ratios:
            for w in [0.5, 0.7]:
                expr = f"rank({corr_str})+{w}*rank({ratio_str})"
                if expr in seen or expr in active_exprs:
                    continue
                seen.add(expr)
                score = score_candidate_orthogonality(expr, ortho, active_exprs)
                name = f"VA_{corr_name}_{ratio_name}_w{int(w*10)}"[:40]
                name = name.replace("-","_").replace(" ","")
                candidates.append({
                    "name": name, "expr": expr,
                    "orthogonality_score": score,
                    "skeleton": SKELETON_VOL_ADJ,
                    "weight": w,
                })
    candidates.sort(key=lambda x: -x["orthogonality_score"])
    return candidates


def _generate_deep_cascade_candidates(ortho: dict, active_exprs: list) -> list:
    """Pattern B: deep_cascade — ts_rank(ts_corr(rank(fund), rank(pv1), N1), N2)
    
    Deep nested signal: rank a long-term correlation between fundamental
    ranking and price signal. Minimal field usage (2 fields).
    No ratio pair → zero S=None risk.
    Pattern: ts_rank(ts_corr(rank({{fund}}), rank({{pv1}}), {{window}}), {{rank_window}})
    """
    candidates = []
    fund_fields = ["revenue", "debt", "cap", "enterprise_value", "equity", "operating_income"]
    pv1_fields_signal = ["returns", "volume", "adv20", "close"]
    # Correlation windows: medium and long
    corr_windows = [20, 40, 60, 120]
    rank_windows = [60, 120, 250]
    seen = set()
    for fund in fund_fields:
        for pv1 in pv1_fields_signal:
            if pv1 == "returns" and fund == "cap":
                # Special case: duplicate of existing DIRECT_RANK variants
                # but the wrapper structure is different
                pass  # include it — structure differs from DR
            for cw in corr_windows:
                for rw in rank_windows:
                    expr = f"ts_rank(ts_corr(rank({fund}),rank({pv1}),{cw}),{rw})"
                    if expr in seen or expr in active_exprs:
                        continue
                    seen.add(expr)
                    score = score_candidate_orthogonality(expr, ortho, active_exprs)
                    name = f"DC_{fund[:3]}_{pv1[:3]}_c{cw}_r{rw}"[:40]
                    name = name.replace("-","_").replace(" ","")
                    candidates.append({
                        "name": name, "expr": expr,
                        "orthogonality_score": score,
                        "skeleton": SKELETON_DEEP_CASCADE,
                        "corr_window": cw,
                        "rank_window": rw,
                    })
    # Dedup by expression and sort
    seen_exprs = set()
    deduped = []
    for c in candidates:
        if c["expr"] in seen_exprs:
            continue
        seen_exprs.add(c["expr"])
        deduped.append(c)
    deduped.sort(key=lambda x: -x["orthogonality_score"])
    return deduped


def _generate_cross_gate_candidates(ortho: dict, active_exprs: list) -> list:
    """Pattern A: cross_gate — rank(ts_delta(pv1,N)) + sign(ts_delta(fund_ratio,N))
    
    Cross-domain conditional gating: price momentum + fundamental change direction.
    ts_delta on price side provides the magnitude signal.
    sign(ts_delta(fund_ratio)) provides the fundamental direction gate.
    Two ts_ operators guarantee S≠None.
    """
    candidates = []
    # Price signals (magnitude)
    price_signals = [
        ("ts_delta(close,5)", "dcl5"),
        ("ts_delta(close,10)", "dcl10"),
        ("ts_delta(close,20)", "dcl20"),
        ("ts_mean(returns,5)", "mret5"),
        ("ts_mean(returns,10)", "mret10"),
        ("ts_delta(volume,5)", "dvol5"),
    ]
    # Fundamental ratios (for sign(gate))
    fund_ratios = [
        ("revenue/enterprise_value", "rev_ev"),
        ("debt/equity", "de"),
        ("revenue/cap", "rev_cap"),
        ("operating_income/cap", "oi_cap"),
        ("debt/enterprise_value", "de_ev"),
    ]
    # Gate windows for fundamental delta
    gate_periods = [5, 10, 20]
    seen = set()
    for (psig_str, psig_name) in price_signals:
        for (ratio_str, ratio_name) in fund_ratios:
            for gp in gate_periods:
                # Gate: sign(ts_delta(fund_ratio, N)) → binary +1/-1 direction
                expr = f"rank({psig_str})+sign(ts_delta({ratio_str},{gp}))"
                if expr in seen or expr in active_exprs:
                    continue
                seen.add(expr)
                score = score_candidate_orthogonality(expr, ortho, active_exprs)
                name = f"CG_{psig_name}_{ratio_name}_g{gp}"[:40]
                name = name.replace("-","_").replace(" ","")
                candidates.append({
                    "name": name, "expr": expr,
                    "orthogonality_score": score,
                    "skeleton": SKELETON_CROSS_GATE,
                    "gate_period": gp,
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

    # PURE_ADD removed: rank(A/B)+rank(C/D) has zero time-series component,
    # causing WQ to return S=None for every expression (cross-section only → no trading signal).
    # Use THREE_TERM (which adds a ts_* term) or DIRECT_RANK with ts_* operators instead.

    pure_mult = _generate_pure_mult_candidates(ortho, active_exprs)
    if pure_mult:
        log(f"  ✖️ Adding {len(pure_mult)} PURE_MULT candidates")
        all_candidates.extend(pure_mult)

    direct_rank = _generate_direct_rank_candidates(ortho, active_exprs)
    if direct_rank:
        log(f"  📊 Adding {len(direct_rank)} DIRECT_RANK candidates (all with ts component)")
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

    # ── Advanced skeleton generators (v3.19 + v4 Task 1) ──
    # cross_gate, sign_switch, vol_adj, deep_cascade — re-enabled in v4
    
    # v4 Task 1: Cross-domain conditional gating — rank(PV1) * sign(ts_delta(FUND, N))
    # This is the direct implementation of the prompt's core pattern.
    cross_gate = _generate_cross_gate_candidates(ortho, active_exprs)
    if cross_gate:
        log(f"  🌐 Adding {len(cross_gate)} cross-gate candidates (rank(PV1)*sign(ts_delta(FUND,N)))")
        all_candidates.extend(cross_gate)
    
    # v4 Task 1: Cross-domain ratio pool → MULT skeleton
    cross_pool = _build_cross_domain_ratio_pool(ortho, skip_zero_occupancy=(stuck_batches >= 2))
    if cross_pool:
        log(f"  🌐 Cross-domain pool: {len(cross_pool)} ratio pairs (temporal gating enabled)")
        cross_candidates = _generate_cross_domain_candidates(cross_pool, ortho, active_exprs)
        log(f"  🌐 Adding {len(cross_candidates)} cross-domain MULT candidates")
        all_candidates.extend(cross_candidates)
    
    # v4 Task 1: Temporal wrap candidates — fund ratios + ts_*/sign wrappers
    tw_candidates = _generate_temporal_wrap_candidates(ortho, active_exprs)
    if tw_candidates:
        log(f"  ⏳ Adding {len(tw_candidates)} temporal-wrap candidates (ts_delta/zscore/sign)")
        all_candidates.extend(tw_candidates)
    
    # ── v4 Task 2: DSB Dynamic Skeleton Builder — AST Topology Mutation ──
    # generate_topology_candidates was defined but never integrated.
    # Now called after cross-domain pools to add diverse AST-topology candidates.
    dsb = DynamicSkeletonBuilder()
    top_candidates = dsb.generate_topology_candidates(ratio_pool, ortho, active_exprs, max_count=15)
    if top_candidates:
        log(f"  🧬 Adding {len(top_candidates)} DSB topology-mutated candidates")
        all_candidates.extend(top_candidates)

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
    
    # ── StructuralDistanceMatrix for scoring (P2 + P7: topological distance in scoring) ──
    sdm = StructuralDistanceMatrix()
    # Pre-compute features for all known expressions (failed + active)
    known_for_dist = set(seen_exprs) | set(active_exprs)
    for _e in list(known_for_dist):
        if _e:
            sdm.extract_features(_e)

    # ── Skeleton success/failure tracking (P1) ──
    # Track skeleton-level win rates from failed_exprs
    skeleton_stats = {}
    if failed_exprs:
        for _fe in failed_exprs:
            _sk = _classify_v3_skeleton(_fe)
            skeleton_stats[_sk] = skeleton_stats.get(_sk, 0) + 1

    # ── Field usage decay score (P6: temporal diversity decay) ──
    # Penalize field combos that are heavily used recently
    field_decay = ortho.get("fields_used", {})
    # Also use operator frequency as a proxy for diversity
    op_freq = {}
    for _e in known_for_dist:
        for _op in ['rank', 'ts_mean', 'ts_delta', 'ts_corr', 'ts_rank', 'ts_std', 'sign', 'log', 'ind_neutral']:
            _cnt = len(re.findall(r'\b' + _op + r'\(', _e))
            if _cnt:
                op_freq[_op] = op_freq.get(_op, 0) + _cnt
    total_ops = max(sum(op_freq.values()), 1)
    for _op in op_freq:
        op_freq[_op] /= total_ops

    def _decay_score(c):
        """P6: Score penalty for over-used fields/operators. Lower = more decayed."""
        expr = c["expr"]
        penalty = 0.0
        # Field decay: fields used in >3 active alphas get penalized
        for _f in FIELD_PATTERN.findall(expr):
            usage = field_decay.get(_f, 0)
            if usage > 3:
                penalty += 0.15 * (usage - 3)
            elif usage > 1:
                penalty += 0.05
        # Operator decay: ts_* ops in high frequency in active set
        for _op, _freq in op_freq.items():
            if _op + '(' in expr and _freq > 0.15:
                penalty += 0.1 * _freq
        return penalty

    def _topo_distance_score(c):
        """P7: Bonus for structural diversity. Higher = more topologically different."""
        expr = c["expr"]
        min_sim = 0.0
        for _e in list(known_for_dist):
            if _e and len(_e) > 10:
                sim = sdm.structural_similarity(expr, _e)
                if sim > min_sim:
                    min_sim = sim
        # Higher min distance = more novel structure → bonus
        # min_sim ranges from 0 (completely different) to ~0.9 (very similar)
        # We want to reward expressions with min_sim < 0.4
        if min_sim < 0.3:
            return 5.0  # High novelty bonus
        elif min_sim < 0.45:
            return 2.5
        elif min_sim < 0.6:
            return 1.0
        else:
            return 0.0  # Too similar to existing expressions

    # ── Enhanced composite score ──
    for c in deduped:
        base_score = c.get("orthogonality_score", 0)
        # Apply P1: skeleton failure rate penalty
        sk = c.get("skeleton", "unknown")
        fail_count = skeleton_stats.get(sk, 0)
        if fail_count > 5:
            base_score -= 1.5  # Heavy penalty on failed skeletons
        elif fail_count > 2:
            base_score -= 0.5
        # Apply P6: temporal decay penalty
        decay = _decay_score(c)
        base_score -= decay
        # Apply P7: topological distance bonus
        topo = _topo_distance_score(c)
        base_score += topo
        # Update the composite score
        c["composite_score"] = round(base_score, 2)
        c["decay_penalty"] = decay
        c["topo_bonus"] = topo

    def _sort_key(c):
        return -c.get("composite_score", c.get("orthogonality_score", 0))

    deduped.sort(key=_sort_key)
    failed_skeleton_counts = {
        SKELETON_MULT: 0,
        SKELETON_DIRECT_RANK: 0,
        SKELETON_THREE_TERM: 0,
        SKELETON_IND_NEUT: 0,
        SKELETON_PURE_MULT: 0,
        SKELETON_SUB: 0,
        SKELETON_SINGLE: 0,
        SKELETON_CROSS_GATE: 0,
        SKELETON_SIGN_SWITCH: 0,
        SKELETON_NONLINEAR_BREAKER: 0,
        SKELETON_TSRANK_CORR: 0,
        SKELETON_TREND_BREAK: 0,
        SKELETON_VOL_ADJ: 0,
        SKELETON_RESIDUAL: 0,
        SKELETON_DEEP_CASCADE: 0,
        "other": 0,
    }
    if failed_exprs:
        for fe in failed_exprs:
            sk = _classify_v3_skeleton(fe)
            if sk in failed_skeleton_counts:
                failed_skeleton_counts[sk] += 1
            else:
                failed_skeleton_counts["other"] += 1
    
    log(f"  📊 Failed pool skeleton distribution: {dict((k, v) for k, v in failed_skeleton_counts.items() if v > 0)}")
    
    # Split candidates by skeleton type for targeted selection
    skeleton_groups = {}
    for c in deduped:
        sk = c.get("skeleton", "unknown")
        skeleton_groups.setdefault(sk, []).append(c)
    
    def sorted_group(sk):
        """Get a skeleton group sorted by orthogonality score."""
        g = skeleton_groups.get(sk, [])
        g.sort(key=_sort_key)
        return g
    
    # ── MULT exhaustion detection ──
    mult_pool = sorted_group(SKELETON_MULT)
    mult_exhausted = False
    if failed_exprs and mult_pool:
        MULT_WEIGHTS = [0.3, 0.5, 0.7, 0.9]
        seen_templates = set()
        exhausted_count = 0
        total_templates = 0
        for c in mult_pool:
            tkey = re.sub(r'\+[0-9.]+', '+W*', c["expr"])

            if tkey in seen_templates:
                continue
            seen_templates.add(tkey)
            total_templates += 1
            all_tested = all(
                re.sub(r'\+[0-9.]+', f'+{w}', c["expr"]) in failed_exprs

                for w in MULT_WEIGHTS
            )
            if all_tested:
                exhausted_count += 1
        if total_templates > 0 and exhausted_count / total_templates >= 0.5:
            mult_exhausted = True
            log(f"  🔄 MULT exhausted: {exhausted_count}/{total_templates} templates fully tested, skipping")
    
    # v3.19 Enhanced Skeleton Rotation (P4: 7-group rotation)
    # Extended from 3-phase to 7-skeleton groups with adaptive phase shifting

    # Merge v3 classifier results into the existing comprehensive dict
    # (Preserves the 15-key dictionary built above instead of rebuilding from scratch)
    if failed_exprs:
        for fe in failed_exprs:
            sk = _classify_v3_skeleton(fe)
            if sk not in failed_skeleton_counts:
                # v3 returned a type not in our predefined list — add it
                failed_skeleton_counts[sk] = failed_skeleton_counts.get(sk, 0) + 1
    total_failed = sum(failed_skeleton_counts.values())
    
    # Adaptive rotation: shift phase if any skeleton dominates the failed pool
    rotation_phase = stuck_batches % 7  # 0-6 for 7 skeleton groups
    rotation_override = False
    
    # Check for dominance and force rotation
    for sk, cnt in failed_skeleton_counts.items():
        if cnt > total_failed * 2 // 3 and total_failed >= 3:
            # This skeleton is overused → skip to the next unexplored group
            # Map ALL skeleton types to rotation phases for dominance override
            phase_map = {
                SKELETON_MULT: 0,
                SKELETON_DIRECT_RANK: 1,
                SKELETON_THREE_TERM: 2,
                SKELETON_IND_NEUT: 3,
                SKELETON_PURE_MULT: 4,
                SKELETON_SUB: 5,
                SKELETON_CROSS_GATE: 0,    # cross_gate treated as mult exploration
                SKELETON_SIGN_SWITCH: 1,   # sign_switch → direct_rank
                SKELETON_NONLINEAR_BREAKER: 2,
                SKELETON_TSRANK_CORR: 2,
                SKELETON_TREND_BREAK: 2,
                SKELETON_VOL_ADJ: 3,
                SKELETON_DEEP_CASCADE: 3,
                SKELETON_RESIDUAL: 4,
                SKELETON_SINGLE: 5,
                "other": 6,
            }
            current_sk_phase = phase_map.get(sk, 6)
            rotation_phase = (current_sk_phase + 1) % 6
            rotation_override = True
            log(f"  🔄 Skeleton dominance: {sk}={cnt}/{total_failed} → rotate to phase {rotation_phase}")
            break
    
    log(f"  🔄 Rotation phase: {rotation_phase} (stuck_batches={stuck_batches}, override={rotation_override})")
    
    # ── v3.19 Selection with Intra-Batch Diversity (P5) ──
    # Instead of taking n consecutive candidates from one skeleton group,
    # use a round-robin approach across skeleton types to ensure diversity.
    
    # Phase mapping: each phase has a primary skeleton + secondary skeletons.
    # Phase mapping includes all active generators (CROSS_GATE, SIGN_SWITCH, VOL_ADJ, DEEP_CASCADE enabled in v4).
    # 7 phases (0-6) for 7-group rotation; phase 6 = fallback to residual/deep exploration.
    phase_map = {
        0: (SKELETON_MULT, [SKELETON_DIRECT_RANK, SKELETON_THREE_TERM]),
        1: (SKELETON_DIRECT_RANK, [SKELETON_THREE_TERM, SKELETON_SUB]),
        2: (SKELETON_THREE_TERM, [SKELETON_IND_NEUT, SKELETON_PURE_MULT]),
        3: (SKELETON_IND_NEUT, [SKELETON_PURE_MULT, SKELETON_SINGLE]),
        4: (SKELETON_PURE_MULT, [SKELETON_SUB, SKELETON_RESIDUAL]),
        5: (SKELETON_SUB, [SKELETON_SINGLE]),
        6: (SKELETON_RESIDUAL, [SKELETON_CROSS_GATE, SKELETON_NONLINEAR_BREAKER]),
    }
    
    primary_sk, secondary_sks = phase_map.get(rotation_phase, phase_map[0])
    
    result = []
    seen_skeletons_in_batch = set()
    
    # Round-robin selection: pick one from primary, then secondary, cycling for diversity
    def pick_next(skeleton_type, min_count=1):
        """Pick one candidate from a skeleton group, skipping ones already in batch."""
        group = sorted_group(skeleton_type)
        for c in group:
            if c not in result:
                result.append(c)
                seen_skeletons_in_batch.add(skeleton_type)
    
    # Phase 0/4: primary exploration
    if (rotation_phase in (0, 4)) and sorted_group(primary_sk):
        # MULT exhaustion check for phase 0
        if rotation_phase == 0 and mult_exhausted:
            pass  # skip primary, go to secondary
        else:
            # Pick up to n//2 from primary
            group = sorted_group(primary_sk)
            for c in group[:n//2]:
                if c not in result and len(result) < n:
                    result.append(c)
                    seen_skeletons_in_batch.add(primary_sk)
    
    # Phase 1/5: DIRECT_RANK or SUB primary
    if rotation_phase in (1, 5):
        group = sorted_group(primary_sk)
        for c in group[:n//2]:
            if c not in result and len(result) < n:
                result.append(c)
                seen_skeletons_in_batch.add(primary_sk)
    
    # Phase 2/3: THREE_TERM or IND_NEUT primary
    if rotation_phase in (2, 3):
        group = sorted_group(primary_sk)
        for c in group[:n//2]:
            if c not in result and len(result) < n:
                result.append(c)
                seen_skeletons_in_batch.add(primary_sk)
    
    # Fill remaining slots from secondary skeleton groups
    for sk in secondary_sks:
        group = sorted_group(sk)
        for c in group:
            if c not in result and len(result) < n:
                result.append(c)
                seen_skeletons_in_batch.add(sk)
    
    # Final fallback: top candidates from any remaining groups
    if len(result) < n:
        for c in deduped:
            if c not in result and len(result) < n:
                result.append(c)
    
    result = result[:n]
    
    log(f"  🎯 v3.19 selection: {len(result)} candidates, skeleton diversity: {len(seen_skeletons_in_batch)} types")
    for sk_type in seen_skeletons_in_batch:
        cnt = sum(1 for c in result if c.get("skeleton") == sk_type)
        log(f"     {sk_type}: {cnt}")
    for c in result:
        log(f"  🎯 [{c.get('skeleton','?')[:4].upper()}] {c['name']}")
        log(f"        expr: {c['expr']}")
        log(f"        ortho_score: {c.get('orthogonality_score', 0):.1f} | composite: {c.get('composite_score', 0):.1f} | decay: {c.get('decay_penalty', 0):.2f} | topo: {c.get('topo_bonus', 0):.1f}")
    
    return result

def _strip_last_term(expr: str) -> str:
    """Strip the last +/-W*{momentum} term from an expression.
    
    Uses reverse scan with paren-depth tracking to handle nested parens
    like ts_corr(close,volume,10) — regex can't handle this correctly.
    
    Examples:
        rank(A/B)*rank(C/D)+0.7*rank(ts_mean(volume,5))
            → rank(A/B)*rank(C/D)
        rank(debt)-1.0*rank(returns)
            → rank(debt)
        rank(A/B)+rank(C/D)-0.5*rank(ts_corr(close,volume,10))
            → rank(A/B)+rank(C/D)
    """
    depth = 0
    for i in range(len(expr) - 1, -1, -1):
        if expr[i] == ')':
            depth += 1
        elif expr[i] == '(':
            depth -= 1
        elif depth == 0 and expr[i] in '+-':
            # Found the last top-level +/- operator
            return expr[:i].strip()
    return expr


# ═══ STRUCTURAL DISTANCE MATRIX ═══════════════════
# Direction D: 主动熵增调度 — 结构距离矩阵驱动的骨架探索

_CLASSIFIER_PATTERNS = [
    (re.compile(r'rank\([^)]+/\)[^)]*\*[^)]*rank\([^)]+/\)'), SKELETON_CROSS_GATE, "cross_gate"),
    (re.compile(r'ts_rank\s*\(\s*ts_corr'), SKELETON_TSRANK_CORR, "tsrank_corr"),
    (re.compile(r'\bsign\s*\(\s*ts_delta'), SKELETON_SIGN_SWITCH, "sign_switch"),
    (re.compile(r'ts_argmax[^)]*ts_argmin|ts_argmin[^)]*ts_argmax'), SKELETON_TREND_BREAK, "trend_break"),
    (re.compile(r'\bts_argmax\('), SKELETON_NONLINEAR_BREAKER, "nonlinear_breaker"),
    (re.compile(r'\bts_argmin\('), SKELETON_NONLINEAR_BREAKER, "nonlinear_breaker"),
    (re.compile(r'rank\s*\([^)]+\)\s*/\s*ts_std'), SKELETON_VOL_ADJ, "vol_adj"),
    (re.compile(r'ts_corr\s*\(\s*rank'), SKELETON_DEEP_CASCADE, "deep_cascade"),
]

def _classify_v3_skeleton(expr: str) -> str:
    """v3: Classify expression into skeleton type using v3 pattern set."""
    for pat, skeleton, short in _CLASSIFIER_PATTERNS:
        if pat.search(expr):
            return short
    return _get_skeleton_type(expr)


class StructuralDistanceMatrix:
    """骨架结构距离矩阵 — 衡量两个表达式的 AST 拓扑相似度。
    相似度 > threshold 的骨架被硬裁剪，防止探索陷入局部拓扑陷阱。
    """

    def __init__(self):
        self._cache: Dict[str, dict] = {}

    def extract_features(self, expr: str) -> dict:
        """从表达式提取结构化特征向量。"""
        if expr in self._cache:
            return self._cache[expr]
        feats: Dict[str, Any] = {}
        ops = ['rank', 'ts_mean', 'ts_sum', 'ts_std', 'ts_corr', 'ts_rank',
               'ts_min', 'ts_max', 'ts_argmin', 'ts_argmax', 'ts_zscore',
               'ts_delta', 'ts_trend', 'ts_percentile', 'log', 'sign', 'abs',
               'ind_neutral', 'ts_cov']
        feats['op_counts'] = {op: len(re.findall(r'\b' + op + r'\(', expr)) for op in ops}
        feats['total_ops'] = sum(feats['op_counts'].values())
        depth = max_depth = 0
        for ch in expr:
            if ch == '(':
                depth += 1
                max_depth = max(max_depth, depth)
            elif ch == ')':
                depth -= 1
        feats['max_nesting'] = max_depth
        n_ts = sum(1 for op in ops if op.startswith('ts_') and op + '(' in expr)
        feats['ts_ratio'] = n_ts / max(feats['total_ops'], 1)
        fields = set(FIELD_PATTERN.findall(expr))
        feats['has_pv1'] = bool(fields & PV1_FIELDS)
        feats['has_fund'] = bool(fields & FUND_FIELDS)
        feats['cross_domain'] = feats['has_pv1'] and feats['has_fund']
        feats['has_sign'] = bool(re.search(r'\bsign\(', expr))
        feats['has_abs'] = bool(re.search(r'\babs\(', expr))
        feats['has_argmax'] = 'ts_argmax(' in expr
        feats['has_argmin'] = 'ts_argmin(' in expr
        feats['has_corr'] = 'ts_corr(' in expr
        feats['has_cov'] = 'ts_cov(' in expr
        feats['ratio_count'] = len(RATIO_PATTERN_STRICT.findall(expr))
        feats['mul_count'] = expr.count('*')
        feats['n_rank'] = feats['op_counts']['rank']
        self._cache[expr] = feats
        return feats

    def structural_similarity(self, expr1: str, expr2: str) -> float:
        """计算结构相似度 [0, 1]。0=完全不同, 1=完全相同结构。"""
        f1 = self.extract_features(expr1)
        f2 = self.extract_features(expr2)
        sims = []
        s1 = {op for op, c in f1['op_counts'].items() if c > 0}
        s2 = {op for op, c in f2['op_counts'].items() if c > 0}
        if s1 or s2:
            sims.append(len(s1 & s2) / len(s1 | s2))
        else:
            sims.append(1.0)
        md1, md2 = max(f1['max_nesting'], 1), max(f2['max_nesting'], 1)
        sims.append(1 - abs(f1['max_nesting'] - f2['max_nesting']) / max(md1, md2))
        sims.append(1 - abs(f1['ts_ratio'] - f2['ts_ratio']))
        rc1, rc2 = max(f1['ratio_count'], 1), max(f2['ratio_count'], 1)
        sims.append(1 - abs(f1['ratio_count'] - f2['ratio_count']) / max(rc1, rc2))
        mc1, mc2 = max(f1['mul_count'], 1), max(f2['mul_count'], 1)
        sims.append(1 - abs(f1['mul_count'] - f2['mul_count']) / max(mc1, mc2))
        sims.append(1.0 if f1['cross_domain'] == f2['cross_domain'] else 0.0)
        nl_keys = ['has_sign', 'has_abs', 'has_argmax', 'has_argmin', 'has_corr', 'has_cov']
        nl_s = sum(1 for k in nl_keys if f1[k] == f2[k])
        sims.append(nl_s / len(nl_keys))
        return sum(sims) / len(sims)

    def is_too_similar(self, expr: str, known_exprs: List[str], threshold: float = 0.45) -> bool:
        """检查新表达式是否和已有表达式结构太相似。"""
        for existing in known_exprs:
            if self.structural_similarity(expr, existing) > threshold:
                return True
        return False

    def get_diversity_score(self, exprs: List[str]) -> float:
        """计算表达式集合的整体多样性分数 [0, 1]。"""
        if len(exprs) < 2:
            return 1.0
        avg_sim = 0.0
        count = 0
        for i in range(len(exprs)):
            for j in range(i + 1, len(exprs)):
                avg_sim += self.structural_similarity(exprs[i], exprs[j])
                count += 1
        if count == 0:
            return 1.0
        return 1.0 - (avg_sim / count)


# ═══ ADAPTIVE POLLING ════════════════════════════
def adaptive_poll(session, url: str, poll_name: str,
                  success_condition, max_wait: int = 1800,
                   initial_interval: float = 10,
                   fallback_interval: float = 60,
                   stuck_threshold: int = 0) -> Tuple[Optional[Any], requests.Session]:
    """
    Adaptive polling: fast at first, slow down over time.
    stuck_threshold: if > 0 and progress stays at 0 for this many secs, abort.
    Returns (value from success_condition when met, or None) and the session object
    (potentially refreshed if SSL/connection errors were encountered).
    """
    start = time.time()
    interval = initial_interval
    last_slowdown = start
    last_progress = 0
    stuck_since = None
    refresh_tried = False  # prevent infinite loop on auth failure
    
    log(f"⏳ Polling {poll_name} (max {max_wait}s, start every {initial_interval}s)")
    
    while time.time() - start < max_wait:
        elapsed = time.time() - start
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 401 and not refresh_tried:
                log(f"⚠️ 401 on {poll_name} ({elapsed:.0f}s), refreshing token...", "warn")
                new_s = fresh_session()
                _last_auth_time = time.time()
                session = new_s  # reuse the local var (polls same session obj)
                refresh_tried = True
                time.sleep(2)  # let proxy settle
                continue
            if r.status_code == 200:
                data = r.json()
                result = success_condition(data)
                if result is not None:
                    log(f"✅ {poll_name}: resolved in {elapsed:.0f}s")
                    return result, session
                
                # Log progress if available
                pct = data.get("progress", 0)
                if isinstance(pct, (int, float)) and pct < 1.0:
                    pct_pct = pct * 100
                else:
                    pct_pct = None
                
                if pct_pct is not None and time.time() - last_slowdown > 30:
                    log(f"⏳ {poll_name}: {pct_pct:.0f}% ({elapsed:.0f}s)")
                
                # Stuck detection: if progress hasn't changed for stuck_threshold seconds, abort
                # Works at ANY progress level (0%, 35%, 15%) not just 0%
                if stuck_threshold > 0 and isinstance(pct, (int, float)):
                    current_progress = pct
                    if current_progress == last_progress and elapsed > 30:
                        if stuck_since is None:
                            stuck_since = time.time()
                        elif time.time() - stuck_since > stuck_threshold:
                            log(f"❌ {poll_name}: stuck at {current_progress*100:.0f}% for {stuck_threshold}s, aborting", "error")
                            return None, session
                    else:
                        stuck_since = None
                        last_progress = current_progress
            elif r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 60))
                # Add jitter to avoid thundering herd, cap at 300s to avoid excessive waits
                retry = min(retry, 300)
                log(f"⚠️ 429: waiting {retry}s (Retry-After: {int(r.headers.get('Retry-After', 60))})")
                time.sleep(retry)
                continue
        except Exception as e:
            error_msg = str(e)
            log(f"⚠️ Poll error: {e}")
            
            # Auto-recover from SSL/Connection errors by refreshing session
            if ("SSLError" in error_msg or "ConnectionError" in error_msg or "SSLEOFError" in error_msg):
                if not refresh_tried:
                    log("🔄 SSL/Connection error detected, refreshing session...", "warn")
                    try:
                        new_s = fresh_session()
                        _last_auth_time = time.time()
                        # Note: we can't update the passed-in session object,
                        # but the caller should use the returned session next time
                    except Exception as refresh_err:
                        log(f"❌ Session refresh failed: {refresh_err}", "error")
                    refresh_tried = True
                    time.sleep(3)  # Let proxy settle
                    continue
                else:
                    log("⚠️ Session already refreshed, retrying connection...", "warn")
                    time.sleep(10)  # Longer delay after refresh
                    continue
            else:
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
    return None, session


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


# ═══ Task 2: Dynamic Skeleton Builder — AST Topology Mutation Engine ═══

class DynamicSkeletonBuilder:
    """AST拓扑变异引擎 — 动态组合截面算子与时序破坏算子，打破固定骨架瓶颈。
    
    核心设计：
    1. 不再写死 rank(A/B)*rank(C/D)+W*rank(M) 等模板
    2. 动态随机组合"截面算子"与"时序破坏算子（破坏平滑性）"
    3. 每个候选必须有至少一个 ts_* 算子（零 S=None 风险）
    4. 支持拓扑变异：对已有表达式进行 AST 级结构变异
    
    拓扑模板：
    - cross_gate: rank(pv1_signal) * sign(ts_delta(fund_ratio, N))
    - nested_tsrank_corr: ts_rank(ts_corr(rank(A), rank(B), N1), N2)
    - volume_ratio_breaker: ts_argmax(volume, N) / ts_argmax(volume, 2N) * rank(A/B)
    - dual_delta_cross: ts_delta(rank(fund1), N) * ts_delta(rank(fund2), M)
    - residual_rank: ts_rank(ts_residual(close, returns, N), M)
    """
    
    # 高级时序算子工厂 — 返回表达式字符串
    TS_OPERATORS = [
        # 时序差分 — 破坏平滑性，捕获一阶变化
        lambda f, n: f"ts_delta({f}, {n})",
        # 时序z-score — 捕获极端偏离
        lambda f, n: f"ts_zscore({f}, {n})",
        # 时序排名 — 将绝对值转为相对排名
        lambda f, n: f"ts_rank({f}, {n})",
        # 时序波动率 — 捕获波动变化
        lambda f, n: f"ts_std({f}, {n})",
        # 时序相关性 — 捕获共动性
        lambda f, n: f"ts_corr(close, {f}, {n})",
        # 时序均值 — 平滑但保留时序性
        lambda f, n: f"ts_mean({f}, {n})",
        # 时序极值 — 捕获极值突破
        lambda f, n: f"ts_argmax({f}, {n})",
        # 时序残差 — 捕获回归残差
        lambda f, n: f"ts_residual({f}, returns, {n})",
    ]
    
    # 截面算子 — 提供截面排序信号
    CROSS_SECTION_OPS = [
        lambda a, b: f"rank({a}/{b})",       # 比率排名
        lambda a, b: f"rank({a})/{b}",        # 不推荐 — 混合类型
    ]
    
    # 时序窗口周期
    PERIODS = [3, 5, 7, 10, 15, 20]
    
    def __init__(self, seed=None):
        """初始化构建器，可选随机种子用于可复现性。"""
        self._seed = seed
    
    def generate_topology_candidates(self, ratio_pool, ortho, active_exprs, max_count=30):
        """从 ratio pool 生成拓扑变异的候选表达式。
        
        对 pool 中的每个 ratio pair，应用 5 种拓扑模板，
        每个模板随机选取周期和截面算子组合。
        
        Returns: list of candidate dicts with expr, name, orthogonality_score, skeleton
        """
        candidates = []
        seen = set()
        
        for ratio_str, ratio_name in ratio_pool[:10]:
            # Topology 1: cross_gate — rank(PV1_signal) * sign(ts_delta(fund_ratio, N))
            for period in self.PERIODS:
                # 从 ratio 中提取字段，找 PV1 字段
                pv1_fields = [f for f in FIELD_PATTERN.findall(ratio_str) if f in PV1_FIELDS]
                fund_fields = [f for f in FIELD_PATTERN.findall(ratio_str) if f in FUND_FIELDS]
                
                for pv1_f in pv1_fields[:2]:
                    for fund_r in [ratio_str] if ratio_name.startswith("cd_") else fund_fields[:1]:
                        # 表达式：sign(ts_delta(fund_ratio, N)) * rank(ts_delta(pv1, M))
                        temp_op = self.TS_OPERATORS[0]  # ts_delta
                        expr = f"sign({temp_op(fund_r, period)}) * rank({temp_op(pv1_f, 5)})"
                        if expr not in seen and len(expr) < 200:
                            seen.add(expr)
                            score = score_candidate_orthogonality(expr, ortho, active_exprs)
                            candidates.append({
                                "name": f"DSB_gate_{ratio_name[:12]}_p{period}"[:40],
                                "expr": expr,
                                "orthogonality_score": score,
                                "skeleton": SKELETON_CROSS_GATE,
                                "weight": 1.0,
                            })
            
            # Topology 2: dual_delta_cross — ts_delta(rank(A/B), N) * ts_delta(rank(C/D), M)
            # 利用同一骨架的两个比率做交叉差分
            fund_fields_in_ratio = [f for f in FIELD_PATTERN.findall(ratio_str) if f in FUND_FIELDS]
            if len(fund_fields_in_ratio) >= 2:
                for p1 in [3, 5]:
                    for p2 in [7, 10]:
                        expr = f"ts_delta({ratio_str}, {p1}) + ts_delta(rank({fund_fields_in_ratio[0]}), {p2})"
                        if expr not in seen and len(expr) < 200:
                            seen.add(expr)
                            score = score_candidate_orthogonality(expr, ortho, active_exprs)
                            candidates.append({
                                "name": f"DSB_dual_{ratio_name[:8]}_p{p1}{p2}"[:40],
                                "expr": expr,
                                "orthogonality_score": score,
                                "skeleton": SKELETON_DEEP_CASCADE,
                                "weight": 1.0,
                            })
            
            # Topology 3: residual_rank — ts_rank(ts_residual(ratio, returns, N), M)
            for n in [10, 20]:
                for m in [5, 10]:
                    expr = f"ts_rank(ts_residual({ratio_str}, returns, {n}), {m})"
                    if expr not in seen and len(expr) < 200:
                        seen.add(expr)
                        score = score_candidate_orthogonality(expr, ortho, active_exprs)
                        candidates.append({
                            "name": f"DSB_residual_{ratio_name[:8]}_n{n}_m{m}"[:40],
                            "expr": expr,
                            "orthogonality_score": score,
                            "skeleton": SKELETON_RESIDUAL,
                            "weight": 1.0,
                        })
        
        # Topology 4: nested_tsrank_corr — ts_rank(ts_corr(rank(A/B), rank(C/D), N1), N2)
        # 只对有足够比率对的场景生成
        if len(ratio_pool) >= 4:
            for i in range(min(3, len(ratio_pool) - 1)):
                for j in range(i + 1, min(4, len(ratio_pool))):
                    r1 = ratio_pool[i][0]
                    r2 = ratio_pool[j][0]
                    f1_fields = FIELD_PATTERN.findall(r1)
                    f2_fields = FIELD_PATTERN.findall(r2)
                    if not (f1_fields and f2_fields):
                        continue
                    # 确保两个比率至少有一个字段不同
                    if set(f1_fields) & set(f2_fields):
                        # 有重叠字段，跳过避免完全相关
                        continue
                    for n1 in [10, 15]:
                        for n2 in [5, 10]:
                            expr = f"ts_rank(ts_corr({r1}, {r2}, {n1}), {n2})"
                            if expr not in seen and len(expr) < 250:
                                seen.add(expr)
                                score = score_candidate_orthogonality(expr, ortho, active_exprs)
                                candidates.append({
                                    "name": f"DSB_nested_{ratio_pool[i][1][:6]}_{ratio_pool[j][1][:6]}"[:40],
                                    "expr": expr,
                                    "orthogonality_score": score,
                                    "skeleton": SKELETON_TSRANK_CORR,
                                    "weight": 1.0,
                                })
        
        # Topology 5: zscore_of_ratio — ts_zscore(rank(A/B), N) — 基本面偏离度
        for ratio_str, ratio_name in ratio_pool[:10]:
            for period in [10, 20, 30]:
                expr = f"ts_zscore({ratio_str}, {period})"
                if expr not in seen and len(expr) < 200:
                    seen.add(expr)
                    score = score_candidate_orthogonality(expr, ortho, active_exprs)
                    candidates.append({
                        "name": f"DSB_zscore_{ratio_name[:10]}_p{period}"[:40],
                        "expr": expr,
                        "orthogonality_score": score,
                        "skeleton": SKELETON_NONLINEAR_BREAKER,
                        "weight": 1.0,
                    })
        
        candidates.sort(key=lambda x: -x["orthogonality_score"])
        return candidates[:max_count]
    
    def mutate_expr_topology(self, expr, ortho, active_exprs, max_variants=10):
        """对已有表达式进行 AST 级拓扑变异，打破自相关性。
        
        变异策略：
        1. 在外层包裹 ts_delta — 将 Level 信号转为 Delta 信号
        2. 在外层包裹 ts_zscore — 将 Level 信号转为 Extreme 信号
        3. 在外层包裹 ts_rank — 将 Level 信号转为 Rank 信号
        4. 替换最外层的 ts_mean 为 ts_delta — 破坏平滑性
        5. 在最外层加 ind_neutral — 剥离行业暴露
        
        Returns: list of mutated candidate dicts
        """
        mutations = []
        seen = set()
        
        # Mutation 1: ts_delta(expr, N)
        for n in [3, 5, 10]:
            mut = f"ts_delta({expr}, {n})"
            if mut not in seen:
                seen.add(mut)
                mutations.append({
                    "name": f"mut_delta_{n}",
                    "expr": mut,
                    "orthogonality_score": ortho.get("_last_score", 0),
                    "skeleton": SKELETON_NONLINEAR_BREAKER,
                })
        
        # Mutation 2: ts_zscore(expr, N)
        for n in [10, 20]:
            mut = f"ts_zscore({expr}, {n})"
            if mut not in seen:
                seen.add(mut)
                mutations.append({
                    "name": f"mut_zscore_{n}",
                    "expr": mut,
                    "orthogonality_score": ortho.get("_last_score", 0),
                    "skeleton": SKELETON_DEEP_CASCADE,
                })
        
        # Mutation 3: ts_rank(expr, N)
        for n in [5, 10, 20]:
            mut = f"ts_rank({expr}, {n})"
            if mut not in seen:
                seen.add(mut)
                mutations.append({
                    "name": f"mut_rank_{n}",
                    "expr": mut,
                    "orthogonality_score": ortho.get("_last_score", 0),
                    "skeleton": SKELETON_TSRANK_CORR,
                })
        
        # Mutation 4: ts_residual(expr, returns, N)
        for n in [10, 20]:
            mut = f"ts_residual({expr}, returns, {n})"
            if mut not in seen:
                seen.add(mut)
                mutations.append({
                    "name": f"mut_residual_{n}",
                    "expr": mut,
                    "orthogonality_score": ortho.get("_last_score", 0),
                    "skeleton": SKELETON_RESIDUAL,
                })
        
        # Mutation 5: ind_neutral(expr, IndClass.subindustry)
        mut = f"ind_neutral({expr}, IndClass.subindustry)"
        if mut not in seen:
            seen.add(mut)
            mutations.append({
                "name": "mut_ind_neut",
                "expr": mut,
                "orthogonality_score": ortho.get("_last_score", 0) + 3,
                "skeleton": SKELETON_IND_NEUT,
            })
        
        # Mutation 6: expr - ts_mean(expr, 5) (residual differencing)
        mut = f"{expr} - ts_mean({expr}, 5)"
        if mut not in seen and len(mut) < 250:
            seen.add(mut)
            mutations.append({
                "name": "mut_diff_mean5",
                "expr": mut,
                "orthogonality_score": ortho.get("_last_score", 0),
                "skeleton": SKELETON_RESIDUAL,
            })
        
        mutations.sort(key=lambda x: -x["orthogonality_score"])
        return mutations[:max_variants]


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
            
            # 2.5. Apply skeleton popularity decay (P1)
            self._apply_skeleton_decay()
            
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
                
                # ── RECORD: Generated ──
                _wqdb.record_alpha_event(
                    name=cand["name"], expr=cand["expr"],
                    event_type="generated",
                    phase="generate"
                )
                
                self.state["batch_idx"] = idx
                self.state["phase"] = "quick_test"
                self.save_checkpoint()
                
                # ── 4a. QUICK TEST — fast 1-year filter ──
                quick_pass = self._quick_test(cand)
                if quick_pass == "skip":
                    log(f"⏩ {cand['name']}: S=None detected, skip (dead pair)")
                    self._track_skeleton_outcome(cand, "quick_skip")
                    # ── RECORD: dead pair failure ──
                    _wqdb.record_alpha_event(
                        name=cand["name"], expr=cand["expr"],
                        event_type="failed",
                        is_status="S=None",
                        phase="quick_test",
                        notes="Dead pair: S=None"
                    )
                    # Immediately register failed expression so it's skipped next batch
                    failed_list = self.state.setdefault("failed_expressions", [])
                    expr = cand.get("expr", "")
                    if expr and expr not in failed_list:
                        failed_list.append(expr)
                        if len(failed_list) > 50:
                            self.state["failed_expressions"] = failed_list[-50:]
                        log(f"  📝 Registered dead pair ({len(failed_list)} total)")
                    self.state["batch_progress"] = idx + 1
                    self.save_checkpoint()
                    continue
                if not quick_pass:
                    log(f"⏩ {cand['name']}: quick test failed, skip (S<1.0)")
                    self._track_skeleton_outcome(cand, "quick_fail")
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
                        # ── RECORD: IS final failure ──
                        _wqdb.record_alpha_event(
                            name=cand["name"], expr=cand.get("expr", ""),
                            event_type="failed",
                            alpha_id=cand.get("alpha_id"),
                            sharpe=cand.get("sharpe"),
                            is_status="IS_FAIL",
                            phase="full_sim",
                            notes="All IS variations failed"
                        )
                        # ── RECORD: IS failure skeleton ──
                        self._track_skeleton_outcome(cand, "is_fail", cand.get("sharpe"))
                        # Register the base expression to prevent regeneration
                        failed_list = self.state.setdefault("failed_expressions", [])
                        base_expr = cand.get("expr", "")
                        if base_expr and base_expr not in failed_list:
                            failed_list.append(base_expr)
                            log(f"  📝 Registered failed base expr ({len(failed_list)} total): {base_expr[:60]}")
                            if len(failed_list) > 100:
                                self.state["failed_expressions"] = failed_list[-100:]
                        self.state["batch_progress"] = idx + 1
                        self.save_checkpoint()
                        notify(f"候选失败 ✖️ {cand['name']} IS {cand.get('sharpe','?')}/{cand.get('fitness','?')}，调参重试后仍失败",
                               emoji="⚠️", dedup_key=f"cand_fail_{cand.get('alpha_id','')}")
                        continue
                elif cand.get("is_status") == "TUNE":
                    log(f"🔧 {cand['name']}: IS TUNE (metrics strong, checks borderline), routing to tune")
                    success = self._tune_and_retry(cand, ortho, "is")
                    if not success:
                        log(f"✖️ {cand['name']}: tune also couldn't fix checks, skip")
                        # Register the base expression
                        failed_list = self.state.setdefault("failed_expressions", [])
                        base_expr = cand.get("expr", "")
                        if base_expr and base_expr not in failed_list:
                            failed_list.append(base_expr)
                            log(f"  📝 Registered failed base expr ({len(failed_list)} total): {base_expr[:60]}")
                            if len(failed_list) > 100:
                                self.state["failed_expressions"] = failed_list[-100:]
                        self.state["batch_progress"] = idx + 1
                        self.save_checkpoint()
                        notify(f"调参未修复 ⚠️ {cand['name']} IS {cand.get('sharpe','?')} 调参后仍无法通过check",
                               emoji="⚠️", dedup_key=f"tune_fail_{cand.get('alpha_id','')}")
                        continue
                
                # ── Skeleton tracking: IS PASS ──
                self._track_skeleton_outcome(cand, "is_pass", cand.get("sharpe"))
                
                # ── 4c. SC SUBMIT FIRST (priority over IS optimization) ──
                # Rationale: IS PASS alpha MUST be tested by SC before any optimization.
                # Tuning first risks losing the original IS PASS alpha if all variations fail.
                self.state["phase"] = "sc_submit"
                self.save_checkpoint()
                success = self._run_sc(cand)
                if not success:
                    log(f"❌ {cand['name']}: SC failed ({cand.get('sc_value', '?')})")
                    log(f"   Trying SC tune (different fields)...")
                    success = self._tune_and_retry(cand, ortho, "sc")
                    if not success:
                        log(f"✖️ {cand['name']}: all SC variations failed, skip")
                        # ── RECORD: SC final failure ──
                        _wqdb.record_alpha_event(
                            name=cand["name"], expr=cand.get("expr", ""),
                            event_type="sc_fail",
                            alpha_id=cand.get("alpha_id"),
                            sharpe=cand.get("sharpe"),
                            sc_value=cand.get("sc_value"),
                            is_status="SC_FAIL",
                            phase="sc_submit",
                            notes="All SC variations failed"
                        )
                        # ── RECORD: SC failure skeleton ──
                        self._track_skeleton_outcome(cand, "sc_fail", cand.get("sharpe"), cand.get("sc_value"))
                        self.state["batch_progress"] = idx + 1
                        self.save_checkpoint()
                        notify(f"SC耗尽 ✖️ {cand['name']}\nSC={cand.get('sc_value','?')}，换字段调参后仍失败",
                               emoji="⚠️", dedup_key=f"sc_fail_{cand.get('alpha_id','')}")
                        continue

                # ── 4d. IS OPTIMIZATION (post-SC-pass tune) ──
                # Only optimize AFTER SC passes — the alpha is already secured as ACTIVE.
                # Tuning now can only improve, never lose (the original SC-passed alpha stays ACTIVE).
                is_sharpe = cand.get("sharpe", 0) or 0
                is_fitness = cand.get("fitness", 0) or 0
                if cand.get("is_status") == "PASS" and self._should_optimize(is_sharpe, is_fitness):
                    strategy = self._get_optimization_strategy(is_sharpe, is_fitness)
                    # ── Strategy dispatch ──
                    log(f"📈 SC PASS + IS OPTIMIZATION S={is_sharpe:.2f} F={is_fitness:.2f}")
                    log(f"   {strategy['description']}")
                    log(f"   Grid: {strategy['strategy_desc']}")
                    log(f"   ⚠️ Original alpha already SC-PASS and ACTIVE — tuning is safe/improvement-only")
                    improved = self._tune_and_retry(cand, ortho, "is", is_optimization=True, opt_strategy=strategy)
                    if improved:
                        log(f"✅ Optimization improved S! Will re-test SC with optimized variant")
                        # After IS optimization, re-submit SC for the improved variant
                        self.state["phase"] = "sc_submit"
                        self.save_checkpoint()
                        success = self._run_sc(cand)
                        if not success:
                            log(f"❌ Optimized alpha SC failed, falling back to original SC-passed alpha")
                            # Keep original SC-passed alpha as ACTIVE (it was never removed)
                            log(f"   Original SC-passed alpha retained as ACTIVE")
                        # If improved alpha SC passes, it replaces original in active set
                    else:
                        log(f"ℹ️ No improvement from optimization, keeping SC-passed original")
                
                # ── 4e. SUBMIT ──
                self._track_skeleton_outcome(cand, "sc_pass", cand.get("sharpe"), cand.get("sc_value"))
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
            # Only count as stuck if at least one candidate reached full_sim (not quick_test skipped)
            reached_full_sim = any(
                c.get("sim_id") or c.get("alpha_id") or c.get("sharpe") is not None
                for c in candidates
            )
            if reached_full_sim:
                # All candidates that passed quick_test failed in full_sim/tune
                self.state["stuck_batches"] = self.state.get("stuck_batches", 0) + 1
                # Register failed expressions for dead-end detection
                failed_list = self.state.setdefault("failed_expressions", [])
                for c in candidates:
                    expr = c.get("expr", "")
                    if expr and expr not in failed_list:
                        failed_list.append(expr)
                        log(f"  📝 Registered failed expr ({len(failed_list)} total): {expr[:60]}")
                # Keep list bounded
                if len(failed_list) > 100:
                    self.state["failed_expressions"] = failed_list[-100:]
                if self.state["stuck_batches"] >= 3:
                    log(f"⚠️  {self.state['stuck_batches']} consecutive batches with 0 passes. "
                        f"Switching to stuck mode (skip zero-occupancy fields).",
                        "warn")
            else:
                # All candidates were quick_test skipped (S<1.0 or S=None)
                # This means the generated pool is weak — still register and count
                log(f"  ⚠️ Batch: all candidates quick_test skipped (weak signal pool), counting as stuck")
                self.state["stuck_batches"] = self.state.get("stuck_batches", 0) + 1
                failed_list = self.state.setdefault("failed_expressions", [])
                for c in candidates:
                    expr = c.get("expr", "")
                    if expr and expr not in failed_list:
                        failed_list.append(expr)
                        log(f"  📝 Registered weak expr ({len(failed_list)} total): {expr[:60]}")
                if len(failed_list) > 100:
                    self.state["failed_expressions"] = failed_list[-100:]
                if self.state["stuck_batches"] >= 3:
                    log(f"⚠️  {self.state['stuck_batches']} consecutive batches with 0 passes. "
                        f"Switching to stuck mode (skip zero-occupancy fields).",
                        "warn")

        # ── Track meta-optimization counters ──
        self.state["batches_since_optimization"] = self.state.get("batches_since_optimization", 0) + 1

        self.save_checkpoint()
        
        log(f"\n🔄 Batch complete. Current: {self.state['active_count']}/{TARGET_ACTIVE}")
        log("Restarting orthogonality analysis for next batch...")
    
    def _quick_test(self, cand: dict):
        """Quick 1-year sim to filter weak signals before full sim.
        Returns: True (proceed), False (weak/invalid), or "skip" (S=None/dead pair).
        
        Conservative design: any failure in quick_test → conservative fail.
        Full sim will still run for candidates that pass quick_test.
        On transient errors (401/retry failed), return False to avoid wasting full sim time.
        """
        payload = {"type": "REGULAR", "regular": cand["expr"], "settings": QUICK_SETTINGS}
        try:
            r = self.s.post(f"{API}/simulations", json=payload, timeout=60)
        except Exception as e:
            log(f"⏩ Quick test POST failed: {e}", "error")
            return False  # conservative: don't waste full sim time on unreachable
        if r.status_code == 401:
            log("⚠️ 401 on quick test POST, refreshing session...", "warn")
            self.s = fresh_session()
            _last_auth_time = time.time()
            try:
                r = self.s.post(f"{API}/simulations", json=payload, timeout=60)
            except Exception as e:
                log(f"⏩ Quick test retry POST failed: {e}", "error")
                return False  # conservative
        if r.status_code != 201:
            log(f"⏩ Quick test: HTTP {r.status_code}", "error")
            return False  # conservative
        sim_id = r.headers.get("Location", "").split("/")[-1]

        def quick_ready(data):
            return data.get("alpha") if data.get("alpha") else None

        alpha_id, self.s = adaptive_poll(
            self.s, f"{API}/simulations/{sim_id}",
            f"Quick {cand['name']}",
            quick_ready, max_wait=600,
            initial_interval=10, fallback_interval=30,
        )
        if not alpha_id:
            log(f"⏩ Quick test: timeout, conservatively skip")
            return False
        # Fetch IS stats
        r2 = self.s.get(f"{API}/alphas/{alpha_id}", timeout=30)
        if r2.status_code != 200:
            return True
        body = r2.json()
        stats = body.get("is", {}) if isinstance(body.get("is"), dict) else {}
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

        # Auto-refresh on 401
        if r.status_code == 401:
            log("⚠️ 401 on sim POST, refreshing session...", "warn")
            self.s = fresh_session()
            _last_auth_time = time.time()
            try:
                r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
            except Exception as e:
                log(f"❌ Sim retry POST failed: {e}", "error")
                return False

        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", 900))
            # Cap at 120s to avoid excessive waits
            wait = min(retry, 120)
            log(f"⚠️ 429: waiting {wait}s (Retry-After: {retry})")
            time.sleep(wait)
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

        alpha_id, self.s = adaptive_poll(
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
        stats = ad.get("is", {}) if isinstance(ad.get("is"), dict) else {}

        cand["sharpe"] = stats.get("sharpe")
        cand["fitness"] = stats.get("fitness")

        passes = sum(1 for c in checks if c.get("result") == "PASS")
        fails = sum(1 for c in checks if c.get("result") == "FAIL")

        sharpe_val = stats.get("sharpe")
        fitness_val = stats.get("fitness")

        # P1: S=None means dead pair — don't treat as PASS even if checks look good
        is_pass = (sharpe_val is not None and fails <= 1 and passes >= 6)
        # Soft pass: S strong or F strong with decent S → route to tuning
        soft_pass = (sharpe_val is not None and fails <= 2 and passes >= 4
                     and not is_pass
                     and (sharpe_val >= 1.25
                          or (sharpe_val >= 1.0 and fitness_val is not None and fitness_val >= 0.8)))

        if is_pass:
            cand["is_status"] = "PASS"
        elif soft_pass:
            cand["is_status"] = "TUNE"
            log(f"📊 IS: S={sharpe_val:.2f} F={fitness_val} | {passes}P/{fails}F | scoring strong but checks miss, routing to tune")
        else:
            cand["is_status"] = "FAIL"

        log(f"📊 IS: S={cand['sharpe']} F={cand['fitness']} | {passes}P/{fails}F | {cand['is_status']}")

        # ── RECORD: IS pass/fail ──
        _wqdb.record_alpha_event(
            name=cand.get("name", ""), expr=cand.get("expr", ""),
            event_type="is_pass" if is_pass else ("is_tune" if soft_pass else "is_fail"),
            alpha_id=alpha_id,
            sharpe=cand.get("sharpe"),
            fitness=cand.get("fitness"),
            is_status=cand["is_status"],
            phase="full_sim"
        )

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
        
        # ── Pre-batch health probe (Directive 3) ──
        # Skip probe on re-submissions (tune retries) — only probe on first SC attempt
        if cand.get("_sc_attempt", 1) == 1:
            probe = self.probe_wq_queue_health()
            congestion = probe.get("congestion", "moderate")
            delay = probe.get("recommended_delay_sec", 120)
            if delay > 0:
                log(f"⏸️ SC queue {congestion}, delaying {delay}s before submit", "warn")
                time.sleep(delay)
            else:
                log(f"✅ SC queue healthy, proceeding immediately")
        
        try:
            r = self.s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
        except Exception as e:
            log(f"❌ SC submit: {e}", "error")
            return False
        
        # Auto-refresh on 401
        if r.status_code == 401:
            log("⚠️ 401 on SC submit, refreshing session...", "warn")
            self.s = fresh_session()
            _last_auth_time = time.time()
            try:
                r = self.s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
            except Exception as e:
                log(f"❌ SC submit retry failed: {e}", "error")
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
        
        sc_result, self.s = adaptive_poll(
            self.s, f"{API}/alphas/{alpha_id}",
            f"SC {cand['name']}",
            sc_ready, max_wait=7200,  # 2h — SC can take 30-60+ min on congested queues
            initial_interval=30, fallback_interval=120,
            stuck_threshold=5400  # abort only if stuck at same % for 90 min (SC is slow)
        )
        
        # Handle early abort from stuck detection
        if sc_result is None:
            # Distinguish timeout vs stuck: check if progress ever moved
            # conservative: treat as TIMEOUT_PENDING (non-fatal)
            log(f"⏸️ SC for {cand['name']} aborted/stuck, marking as SC_TIMEOUT_PENDING", "warn")
            cand["sc_result"] = "SC_TIMEOUT_PENDING"
            _wqdb.record_alpha_event(
                name=cand.get("name", ""), expr=cand.get("expr", ""),
                event_type="sc_timeout_pending",
                alpha_id=alpha_id,
                sharpe=cand.get("sharpe"),
                fitness=cand.get("fitness"),
                sc_result="SC_TIMEOUT_PENDING",
                phase="sc_submit"
            )
            notify(f"SC卡住延期 ⏸️ {cand['name']} (排队拥堵/进度停滞，2h后重试)\nS={cand.get('sharpe')} SC=pending",
                   emoji="⏸️", dedup_key=f"sc_pending_{alpha_id}")
            return False  # graceful, don't crash main loop
        
        if not sc_result:
            # Try 403 probe as fallback — probe the alpha to get SC result
            try:
                r3 = self.s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
                if r3.status_code == 401:
                    log("⚠️ 401 on SC probe, refreshing session...", "warn")
                    self.s = fresh_session()
                    _last_auth_time = time.time()
                    r3 = self.s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
                if r3.status_code == 403:
                    body = r3.json()
                    checks = body.get("is", {}).get("checks", []) if isinstance(body.get("is"), dict) else []
                    sc = next((c for c in checks if c["name"] == "SELF_CORRELATION"), None)
                    if sc and sc.get("result") != "PENDING":
                        sc_result = sc
                    else:
                        log(f"⚠️ 403 probe: SC still pending or no SC found")
                else:
                    log(f"⚠️ 403 probe: got HTTP {r3.status_code}, expected 403")
            except Exception as e:
                log(f"⚠️ 403 probe error: {e}")
        
        if not sc_result:
            cand["sc_result"] = "TIMEOUT"
            return False
        
        cand["sc_value"] = sc_result.get("value")
        cand["sc_result"] = sc_result.get("result")
        is_pass = sc_result.get("result") == "PASS"
        
        log(f"📊 SC={cand['sc_value']} result={cand['sc_result']}")
        
        # ── RECORD: SC pass/fail ──
        _wqdb.record_alpha_event(
            name=cand.get("name", ""), expr=cand.get("expr", ""),
            event_type="sc_pass" if is_pass else "sc_fail",
            alpha_id=alpha_id,
            sharpe=cand.get("sharpe"),
            fitness=cand.get("fitness"),
            sc_value=cand.get("sc_value"),
            sc_result=cand.get("sc_result"),
            phase="sc_submit"
        )
        
        # ── RECORD: quadruple SC regression data (v3.17) ──
        # Extract quadruples from this expression and record SC outcome
        # Only for MULT-style expressions that have quadruples
        try:
            quads = _extract_field_quadruples(cand.get("expr", ""))
            for quad in quads:
                qk = _normalize_quad_key(quad)
                if qk:
                    _wqdb.record_quadruple_sc(qk, is_pass)
                    log(f"    📈 quad {qk} SC={'PASS' if is_pass else 'FAIL'} (regression record)")
        except:
            pass  # Non-MULT expression, no quadruples to record
        
        if is_pass:
            notify(f"SC通过 ✅ {cand['name']}\nSC={cand['sc_value']}\n{cand['expr'][:60]}",
                   emoji="✅", dedup_key=f"sc_{cand.get('alpha_id','')}")
        return is_pass
    
    def probe_wq_queue_health(self, max_tries: int = 3) -> dict:
        """
        Pre-SC-submission health probe: checks WQ SC queue congestion state.
        
        Strategy: submit a tiny sim (1-day backtest period) to measure how long
        the sim itself takes to resolve. Fast resolution = queue healthy.
        Slow resolution = SC queue likely congested.
        
        Returns dict with keys:
            - congestion: "healthy" | "moderate" | "severe"
            - sim_resolution_sec: float or None
            - recommended_delay_sec: int
        """
        log("🔍 Pre-SC health probe: checking WQ queue state...")
        
        probe_payload = {
            "type": "REGULAR",
            "regular": "rank(ts_delta(close, 1)) / ts_mean(volume, 5)",  # trivial expr
            "settings": {
                "backtest": {"start": "2025-01-01", "end": "2025-01-02"},  # 1 day
                "universe": "MID_CAP_US_1000",
                "long_only": False
            }
        }
        
        start = time.time()
        for attempt in range(1, max_tries + 1):
            try:
                r = self.s.post(f"{API}/simulations", json=probe_payload, timeout=90)
                if r.status_code == 401:
                    log("⚠️ 401 on probe, refreshing session...", "warn")
                    self.s = fresh_session()
                    _last_auth_time = time.time()
                    continue
                
                if r.status_code in (200, 201, 202):
                    sim_id = r.headers.get("Location", "").split("/")[-1]
                    if not sim_id:
                        # Parse from response body as fallback
                        try:
                            sim_id = r.json().get("id", "")
                        except:
                            pass
                    
                    if sim_id:
                        # Poll for sim resolution
                        def probe_ready(data):
                            return data.get("alpha") if data.get("alpha") else None
                        
                        result, self.s = adaptive_poll(
                            self.s, f"{API}/simulations/{sim_id}",
                            "Probe sim",
                            probe_ready, max_wait=300,  # 5 min max for probe
                            initial_interval=5, fallback_interval=15,
                            stuck_threshold=60  # abort if stuck > 60s
                        )
                        resolution_time = time.time() - start
                        
                        if result:
                            # Sim resolved — infer queue state
                            if resolution_time < 30:
                                congestion = "healthy"
                                delay = 0
                            elif resolution_time < 120:
                                congestion = "moderate"
                                delay = 120
                            else:
                                congestion = "severe"
                                delay = 600
                            
                            log(f"🔍 Probe resolved in {resolution_time:.0f}s → {congestion} (delay={delay}s)")
                            return {
                                "congestion": congestion,
                                "sim_resolution_sec": resolution_time,
                                "recommended_delay_sec": delay,
                                "sim_id": sim_id,
                                "alpha_id": result
                            }
                        else:
                            log(f"⚠️ Probe sim timed out ({resolution_time:.0f}s), queue likely severe")
                            return {
                                "congestion": "severe",
                                "sim_resolution_sec": resolution_time,
                                "recommended_delay_sec": 600,
                                "sim_id": sim_id,
                                "alpha_id": None
                            }
                
                elif r.status_code == 429:
                    retry = int(r.headers.get("Retry-After", 60))
                    wait = min(retry, 120)
                    log(f"⚠️ 429 on probe, waiting {wait}s (Retry-After: {retry})", "warn")
                    time.sleep(wait)
                    continue
                
                else:
                    log(f"⚠️ Probe HTTP {r.status_code}, retry {attempt}/{max_tries}")
                    time.sleep(10 * attempt)
                    
            except Exception as e:
                log(f"⚠️ Probe attempt {attempt}/{max_tries} error: {e}", "warn")
                if attempt < max_tries:
                    time.sleep(10 * attempt)
                else:
                    log(f"❌ Probe failed after {max_tries} attempts, defaulting to moderate", "error")
                    return {
                        "congestion": "moderate",
                        "sim_resolution_sec": None,
                        "recommended_delay_sec": 120,
                        "sim_id": None,
                        "alpha_id": None
                    }
        
        return {
            "congestion": "moderate",
            "sim_resolution_sec": None,
            "recommended_delay_sec": 120,
            "sim_id": None,
            "alpha_id": None
        }
    
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
        
        # Auto-refresh on 401
        if r.status_code == 401:
            log("⚠️ 401 on submit, refreshing session...", "warn")
            self.s = fresh_session()
            _last_auth_time = time.time()
            try:
                r = self.s.post(f"{API}/alphas/{alpha_id}/submit", json={}, timeout=30)
            except Exception as e:
                log(f"❌ Submit retry failed: {e}", "error")
                return
        
        if r.status_code in (200, 201, 202):
            log(f"✅ Submitted! status={r.status_code}")
            cand["submitted"] = True
            
            # ── RECORD: Submitted ──
            _wqdb.record_alpha_event(
                name=cand["name"], expr=cand["expr"],
                event_type="submitted",
                alpha_id=alpha_id,
                sharpe=cand.get("sharpe"),
                fitness=cand.get("fitness"),
                sc_value=cand.get("sc_value"),
                phase="submit"
            )
            
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
    
    def _run_single_sim_and_sc(self, var_name: str, payload: dict,
                                cand: dict, failed_phase: str,
                                max_tune_attempts: int,
                                is_optimization: bool) -> bool:
        """
        Run a single simulation with custom settings, then run SC.
        Used by SC neutralization degradation: same expr, different neutralization dim.
        
        Returns True if IS pass AND SC pass, False otherwise.
        """
        try:
            r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
        except Exception as e:
            log(f"    ❌ POST: {e}")
            return False
        
        if r.status_code == 401:
            log("    ⚠️ 401 on sim POST, refreshing...", "warn")
            self.s = fresh_session()
            _last_auth_time = time.time()
            try:
                r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
            except Exception as e:
                log(f"    ❌ Sim retry POST failed: {e}")
                return False
        
        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", 60))
            wait = min(retry, 60)
            log(f"    ⚠️ 429: wait {wait}s (Retry-After: {retry})")
            time.sleep(wait)
            try:
                r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
            except:
                return False
        
        if r.status_code != 201:
            log(f"    ❌ HTTP {r.status_code}")
            return False
        
        sim_id = r.headers.get("Location", "").split("/")[-1]
        
        def is_ready(data):
            return data.get("alpha") if data.get("alpha") else None
        
        alpha_id, self.s = adaptive_poll(
            self.s, f"{API}/simulations/{sim_id}",
            f"Tune {var_name}",
            is_ready, max_wait=3600,
            initial_interval=15, fallback_interval=60,
            stuck_threshold=300
        )
        
        if not alpha_id:
            log(f"    ❌ IS timeout")
            return False
        
        # Fetch IS details
        r2 = self.s.get(f"{API}/alphas/{alpha_id}", timeout=30)
        if r2.status_code != 200:
            return False
        
        ad = r2.json()
        checks = ad.get("is", {}).get("checks", []) if isinstance(ad.get("is"), dict) else []
        stats = ad.get("is", {}) if isinstance(ad.get("is"), dict) else {}
        
        sharpe_val = stats.get("sharpe")
        fitness_val = stats.get("fitness")
        passes = sum(1 for c in checks if c.get("result") == "PASS")
        fails = sum(1 for c in checks if c.get("result") == "FAIL")
        
        is_pass = (sharpe_val is not None and fails <= 1 and passes >= 6)
        soft_pass = (sharpe_val is not None and fails <= 2 and passes >= 4
                     and not is_pass
                     and (sharpe_val >= 1.25
                          or (sharpe_val >= 1.0 and fitness_val is not None and fitness_val >= 0.8)))
        
        neutral = ad.get("settings", {}).get("neutralization", "?")
        log(f"    IS: S={sharpe_val:.2f} F={fitness_val} | {passes}P/{fails}F | {neutral}")
        
        if not (is_pass or soft_pass):
            log(f"    ❌ IS failed")
            return False
        
        # Patch alpha name/tags
        try:
            self.s.patch(f"{API}/alphas/{alpha_id}",
                json={"name": var_name, "color": "GREEN",
                      "category": "FUNDAMENTAL", "tags": ["workflow-v2-tune", f"neut_{neutral}"]}, timeout=15)
        except: pass
        
        # IS pass → run SC
        var = {"alpha_id": alpha_id, "name": var_name, "expr": payload["regular"],
               "sharpe": sharpe_val, "fitness": fitness_val,
               "_sc_attempt": 1}
        sc_pass = self._run_sc(var)
        
        if sc_pass:
            log(f"    ✅ SC passed! ({var.get('sc_value')})")
            # Copy back to cand
            cand["alpha_id"] = alpha_id
            cand["sharpe"] = sharpe_val
            cand["fitness"] = fitness_val
            cand["is_status"] = "PASS"
            cand["sc_value"] = var.get("sc_value")
            cand["sc_result"] = "PASS"
            cand["expr"] = payload["regular"]
            cand["name"] = var_name
            self.state["candidates_passed_is"] = self.state.get("candidates_passed_is", 0) + 1
            self.state["candidates_passed_sc"] = self.state.get("candidates_passed_sc", 0) + 1
            self.save_checkpoint()
            return True
        
        log(f"    ❌ SC failed for {var_name}: {var.get('sc_value', '?')}")
        return False
    
    # ── v3.19 Skeleton Popularity Tracking ─────────────────
    
    def _track_skeleton_outcome(self, cand: dict, outcome: str,
                                 sharpe: float = None, sc_value: float = None):
        """Track skeleton type success rates for popularity-based selection.
        
        outcome: 'quick_skip', 'quick_fail', 'is_fail', 'is_pass',
                 'sc_fail', 'sc_pass', 'tune_fail', 'tune_pass', 'submitted'
        """
        sk = cand.get("skeleton", "other")
        state = self.state
        pop = state.setdefault("skeleton_popularity", {})
        sk_data = pop.setdefault(sk, {
            "attempts": 0, "is_pass": 0, "sc_pass": 0,
            "is_pass_rate": 0.0, "sc_pass_rate": 0.0,
            "avg_sharpe": 0.0, "sharpe_sum": 0.0,
            "weighted_score": 0.0,
        })
        sk_data["attempts"] += 1
        if sharpe is not None and sharpe > 0:
            sk_data["sharpe_sum"] = sk_data.get("sharpe_sum", 0) + sharpe
            sk_data["avg_sharpe"] = sk_data["sharpe_sum"] / max(sk_data["attempts"], 1)
        if outcome in ("is_pass", "tune_pass"):
            sk_data["is_pass"] += 1
        if outcome in ("sc_pass",):
            sk_data["sc_pass"] += 1
            sk_data["sc_pass_rate"] = sk_data["sc_pass"] / max(sk_data["attempts"], 1)
        sk_data["is_pass_rate"] = sk_data["is_pass"] / max(sk_data["attempts"], 1)
        # Weighted score: pass_rate * avg_sharpe * sc_bonus
        sc_bonus = 1.0 + sk_data.get("sc_pass_rate", 0) * 2
        sk_data["weighted_score"] = sk_data["is_pass_rate"] * sk_data["avg_sharpe"] * sc_bonus
        # Write immediate backup to JSON file for crash recovery
        try:
            import json, os
            backup_path = os.path.expanduser("~/.wq_skeleton_popularity.json")
            try:
                existing = json.load(open(backup_path))
            except:
                existing = {}
            existing[sk] = sk_data
            with open(backup_path, 'w') as f:
                json.dump(existing, f)
        except:
            pass  # Don't let backup failure break the main flow
    
    def _apply_skeleton_decay(self):
        """Apply recency decay to skeleton popularity each batch."""
        state = self.state
        pop = state.get("skeleton_popularity", {})
        decay = state.get("skeleton_popularity_decay", 1.0)
        if not pop or decay >= 1.0:
            return
        for sk, data in pop.items():
            data["attempts"] = max(1, int(data["attempts"] * decay))
            data["is_pass"] = max(0, int(data["is_pass"] * decay))
            data["sc_pass"] = max(0, int(data["sc_pass"] * decay))
            data["sharpe_sum"] *= decay
            if data["attempts"] > 0:
                data["avg_sharpe"] = data["sharpe_sum"] / data["attempts"]
                data["is_pass_rate"] = data["is_pass"] / data["attempts"]
                data["sc_pass_rate"] = data["sc_pass"] / max(data["attempts"], 1)
            sc_bonus = 1.0 + data.get("sc_pass_rate", 0) * 2
            data["weighted_score"] = data["is_pass_rate"] * data["avg_sharpe"] * sc_bonus
    
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
                         opt_strategy: dict = None,
                         settings_override: dict = None) -> bool:
        """
        Generate tuned variations of a candidate and retry.
        failed_phase: "is" or "sc"
        is_optimization: True = post-pass tuning (test all, pick best S > original)
        settings_override: dict — override default sim settings (e.g. neutralization dim).
                            If None, uses DEFAULT_SETTINGS.
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
                
                # Skeleton-aware prefix extraction (robust: handles nested parens)
                # Strip the last +/-W*{momentum} term from the expression
                # MULT:  rank(A/B)*rank(C/D)+W*rank(mom)    → prefix=rank(A/B)*rank(C/D)
                # DIRECT_RANK: rank(field)-W*rank(mom)       → prefix=rank(field)
                # THREE_TERM:  rank(A/B)+rank(C/D)-W*rank(X) → prefix=rank(A/B)+rank(C/D)
                # IND_NEUT: ind_neutral(...)+W*rank(field)   → prefix=ind_neutral(...)
                # Uses reverse scan with paren-depth tracking, regex can't handle nested parens
                expr_stripped = _strip_last_term(base_expr)
                # Only use regex prefix if it actually stripped something
                ratio_prefix = expr_stripped if expr_stripped != base_expr else base_expr
                
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
                
                # Extract the ratio prefix (everything before the last weight*momentum term)
                # Skeleton-aware: handles MULT (uses +), DIRECT_RANK (uses -), THREE_TERM (uses +...-)
                # Uses paren-depth reverse scan — regex can't handle nested parens like ts_corr
                expr_stripped = _strip_last_term(base_expr)
                ratio_prefix = expr_stripped if expr_stripped != base_expr else base_expr
                
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

        elif failed_phase == "sc":
            # ── SC fail: AST residual pruning (v4 — Task 3) ──
            # 核心思想：SC 失败不是字段问题，而是结构自相关太高。
            # 不要换字段，而是对原表达式做 AST 级残差化修剪，打破自相关模式。
            # 保留 IS 验证过的信号质量，只修改自相关结构。
            
            base_expr = cand.get("expr", "")
            base_name = cand.get("name", "orig")
            if not base_expr:
                log(f"  ⚠️ SC fail: no base expr, skipping", "warn")
            else:
                log(f"  🔬 SC AST residual pruning on '{base_name}': {base_expr[:80]}")
                
                # Phase 1: Neutralization dimension degradation (keep existing logic — proven effective)
                # 最细粒度的中性化可能消除伪相关
                log(f"  🔍 Phase 1: Neutralization degradation (SECTOR/SUBINDUSTRY)")
                for ndim in ["SECTOR", "SUBINDUSTRY"]:
                    if not self.running:
                        return False
                    var_name = f"{base_name}_neut_{ndim}"[:40]
                    log(f"    Attempt {ndim} neutralization...")
                    override = dict(DEFAULT_SETTINGS) if settings_override else dict(DEFAULT_SETTINGS)
                    override["neutralization"] = ndim
                    payload = {"type": "REGULAR", "regular": base_expr, "settings": override}
                    success = self._run_single_sim_and_sc(var_name, payload, cand, failed_phase, max_tune_attempts, is_optimization)
                    if success:
                        return True
                    else:
                        log(f"    {ndim} neutralization failed")
            
            # Phase 2: AST residual pruning — 对原表达式做拓扑变异，而非换字段
            # 这是关键创新：SC 失败是因为信号模式太"干净"，被 SC 检测为自相关
            # 通过残差化（差分/z-score/排名）破坏模式重复性，保留信号本质
            if base_expr:
                builder = DynamicSkeletonBuilder()
                ast_mutations = builder.mutate_expr_topology(base_expr, ortho, active_exprs, max_variants=8)
                if ast_mutations:
                    log(f"  🔧 Phase 2: AST residual pruning — {len(ast_mutations)} mutations generated")
                    for mut in ast_mutations:
                        if not self.running:
                            return False
                        var_name = f"{base_name}_mut_{mut['name']}"[:40]
                        log(f"    Mutation: {mut['name']} → {mut['expr'][:100]}")
                        
                        # 确保表达式长度合理
                        if len(mut["expr"]) > 300:
                            log(f"      ⚠️ Expr too long ({len(mut['expr'])} chars), skipping")
                            continue
                        
                        override = dict(DEFAULT_SETTINGS) if settings_override else dict(DEFAULT_SETTINGS)
                        payload = {"type": "REGULAR", "regular": mut["expr"], "settings": override}
                        success = self._run_single_sim_and_sc(var_name, payload, cand, failed_phase, max_tune_attempts, is_optimization)
                        if success:
                            log(f"  ✅ SC passed after AST mutation: {mut['name']}")
                            return True
                        else:
                            log(f"    Mutation {mut['name']} SC failed")
            
            # Phase 3: If AST pruning failed, fall back to legacy field pair swap
            # 保留原有逻辑作为兜底
            log(f"  ⚠️ Phase 3: AST pruning exhausted — falling back to field pair swap")
            field_usage = ortho["fields_used"]
            used_pairs = ortho.get("field_pairs_used", set())
            
            fund_denoms = ["cap", "enterprise_value", "equity"]
            pv1_denoms = ["close", "volume", "adv20", "vwap", "low", "high", "open"]
            denoms = [d for d in denoms if field_usage.get(d, 0) <= 2]
            
            fund_nums = ["revenue", "operating_income", "debt"]
            pv1_nums = ["returns", "volume", "low", "high"]
            nums = [n for n in fund_nums + pv1_nums if field_usage.get(n, 0) <= 1 and n not in ["close"]]
            
            mom_pool = [
                ("ts_mean(volume,5)", "vol_mom"),
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
                    g1 = "fund" if num in FUND_FIELDS else "pv1"
                    g2 = "fund" if den in FUND_FIELDS else "pv1"
                    if g1 != g2:
                        continue
                    
                    for num2 in nums[:6]:
                        if num2 == num:
                            continue
                        for den2 in denoms[:4]:
                            if den2 == den or num2 == den2:
                                continue
                            pair2 = frozenset([num2, den2])
                            if {num, den} & {num2, den2}:
                                continue
                            g1b = "fund" if num2 in FUND_FIELDS else "pv1"
                            g2b = "fund" if den2 in FUND_FIELDS else "pv1"
                            if g1b != g2b:
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
            
            # Auto-refresh on 401
            if r.status_code == 401:
                log("    ⚠️ 401 on tune sim POST, refreshing session...", "warn")
                self.s = fresh_session()
                _last_auth_time = time.time()
                try:
                    r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
                except Exception as e:
                    log(f"    ❌ Tune sim retry POST failed: {e}", "error")
                    continue
            
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 60))
                wait = min(retry, 60)
                log(f"    ⚠️ 429: wait {wait}s (Retry-After: {retry})")
                time.sleep(wait)
                try:
                    r = self.s.post(f"{API}/simulations", json=payload, timeout=90)
                except:
                    continue
            
            # Handle 409: sim already exists (same expression submitted recently)
            # Try to continue polling the existing sim rather than skipping
            if r.status_code == 409:
                existing_sim_id = None
                try:
                    err_body = r.json()
                    # WQ often includes the sim URL in a 'path' field or Location
                    if "path" in err_body:
                        existing_sim_id = err_body["path"].split("/")[-1]
                    elif "target" in err_body:
                        existing_sim_id = err_body["target"].split("/")[-1]
                except:
                    pass
                if existing_sim_id:
                    log(f"    ⚠️ 409: sim already exists (sim_id={existing_sim_id}), reusing")
                    var["sim_id"] = existing_sim_id
                    # Fall through to the polling section below
                else:
                    log(f"    ⚠️ 409: sim exists but couldn't extract sim_id, skipping")
                    continue
            
            elif r.status_code != 201:
                log(f"    ❌ HTTP {r.status_code}")
                continue
            
            if var.get("sim_id"):
                sim_id = var["sim_id"]
            else:
                sim_id = r.headers.get("Location", "").split("/")[-1]
                var["sim_id"] = sim_id
            
            # Adaptive IS poll
            def is_ready(data):
                aid = data.get("alpha")
                return aid if aid else None
            
            alpha_id, self.s = adaptive_poll(
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
            stats = ad.get("is", {}) if isinstance(ad.get("is"), dict) else {}
            
            var["sharpe"] = stats.get("sharpe")
            var["fitness"] = stats.get("fitness")
            passes = sum(1 for c in checks if c.get("result") == "PASS")
            fails = sum(1 for c in checks if c.get("result") == "FAIL")
            sharpe_val = stats.get("sharpe")
            # P1: S=None means dead pair — don't treat as PASS even if checks look good
            is_pass = (sharpe_val is not None and fails <= 1 and passes >= 6)
            # Soft pass in tune: S strong or F strong with decent S → still counts as success
            fitness_val = var.get("fitness")
            soft_pass = (sharpe_val is not None and fails <= 2 and passes >= 4
                         and not is_pass
                         and (sharpe_val >= 1.25
                              or (sharpe_val >= 1.0 and fitness_val is not None and fitness_val >= 0.8)))

            log(f"    IS: S={var['sharpe']} F={var['fitness']} | {passes}P/{fails}F")

            if not (is_pass or soft_pass):
                log(f"    ❌ IS failed")
                if var['sharpe'] is None:
                    log(f"    S=None (dead pair), continuing to next variation (not breaking)")
                continue

            if soft_pass:
                log(f"    ✅ Soft IS pass (S={sharpe_val:.2f}, {passes}P/{fails}F) — metrics strong, accepting as tune success")
            
            # Notify: 调参成功
            notify(f"调参成功 ✅ {var['name']}\nS={sharpe_val:.2f} F={var.get('fitness','?')}\n{var['expr'][:80]}",
                   emoji="✅", dedup_key=f"tune_success_{alpha_id}")
            
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
                    # ── RECORD: optimized variant ──
                    _wqdb.record_alpha_event(
                        name=var["name"], expr=var["expr"],
                        event_type="optimized",
                        alpha_id=alpha_id,
                        sharpe=var["sharpe"],
                        fitness=var["fitness"],
                        is_status="OPT_BEST",
                        phase="full_sim",
                        notes=f"Optimization: new best S={var_sharpe:.2f}"
                    )
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

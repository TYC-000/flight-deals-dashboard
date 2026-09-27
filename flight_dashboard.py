"""
✈️ YC's Flight Deal Dashboard — Asia Outer-Port → Spain (MAD/BCN)

A Streamlit dashboard for evaluating flight deals using Jev's three-criteria
verdict (connection failure risk, fatigue index, routing verdict).
"""
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# i18n helper
sys_path = Path(__file__).parent
import sys
sys.path.insert(0, str(sys_path))
from i18n import get as t, SEASONAL_DATA, DESTINATION_BEST_TIME, aircraft_comfort_score
from layout_detector import LAYOUT_LABELS, layout_options, is_likely_mobile
from dashboard_adapter import (
    safe_startswith as _safe_startswith,
    safe_in as _safe_in,
    compute_pref_score as _adapter_compute_pref_score,
)
from dashboard_view_model import (
    build_view as _vm_build_view,
    load_evidence_index as _vm_load_evidence_index,
    load_fx_evidence_index as _vm_load_fx_evidence_index,
    load_candidates as _vm_load_candidates,
    UNKNOWN as _VM_UNKNOWN,
    EVIDENCE_UNAVAILABLE as _VM_EVIDENCE_UNAVAILABLE,
)


def inject_layout_css(layout: str) -> None:
    """Inject CSS to adjust metric tile density based on layout choice."""
    if layout == "compact":
        css = """
        <style>
        [data-testid="stMetric"] { font-size: 1.05rem; padding: 8px 12px; }
        [data-testid="stMetric"] label { font-size: 0.85rem; opacity: 0.8; }
        [data-testid="stMetric"] [data-testid="stMetricValue"] { font-size: 1.4rem !important; }
        [data-testid="stMetric"] [data-testid="stMetricDelta"] { font-size: 0.9rem !important; }
        [data-testid="stTabs"] button { font-size: 0.95rem; padding: 10px 14px; }
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DATA_DIR = Path(__file__).parent / "data"
RESULTS_PATH = DATA_DIR / "flight_results.json"
SUMMARY_PATH = DATA_DIR / "flight_summary.md"
CANDIDATES_PATH = DATA_DIR / "flight_candidates.json"

TPE_BASELINE_TWD = 180_000  # baseline TPE-direct business class
PAGE_ICON = "✈️"


# ----------------------------------------------------------------------
# Data loaders (with caching)
# ----------------------------------------------------------------------
@st.cache_data(ttl=60)
def load_results() -> dict | None:
    if not RESULTS_PATH.exists():
        return None
    with RESULTS_PATH.open() as f:
        return json.load(f)


@st.cache_data(ttl=60)
def load_summary() -> str:
    if not SUMMARY_PATH.exists():
        return "_No summary available — run `python3 /Users/aib/.hermes/tools/eval_flight_yc.py` first_"
    return SUMMARY_PATH.read_text(encoding="utf-8")


def results_to_dataframe(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        ev = r.get("evaluation", {})
        rows.append({
            "id": r.get("id"),
            "label": r.get("label"),
            "origin": r.get("positioning", {}).get("from"),
            "outer_port": r.get("long_haul", {}).get("from"),
            "via_hub": r.get("long_haul", {}).get("via"),
            "carrier": r.get("long_haul", {}).get("carrier"),
            "destination": r.get("long_haul", {}).get("to"),
            "total_cost_twd": r.get("total_cost", 0),
            "savings_pct": r.get("savings_pct", 0),
            "savings_twd": TPE_BASELINE_TWD - r.get("total_cost", 0),
            "routing_verdict": ev.get("routing_verdict", "n/a"),
            "risk": ev.get("connection_failure_risk", 0),
            "fatigue": ev.get("fatigue_index", 0),
            "total_elapsed_h": round(r.get("total_elapsed_min", 0) / 60, 1),
            "same_pnr": bool(r.get("same_pnr", False)),
            "n_segments": len(r.get("segments", [])),
            "notes": str(r.get("notes", "") or ""),
        })
    df = pd.DataFrame(rows)
    # Ensure pyarrow-compatible dtypes: cast all object→string
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str)
    return df


def segments_for_route(option: dict) -> list[dict]:
    """Flatten segments for visualisation."""
    segs = option.get("segments", [])
    return [
        {
            "from": s.get("from"),
            "to": s.get("to"),
            "carrier": s.get("carrier"),
            "flight": s.get("flight"),
            "cabin": s.get("cabin"),
            "duration_min": s.get("duration_min"),
        }
        for s in segs
    ]


# ----------------------------------------------------------------------
# Page config
# ----------------------------------------------------------------------
# Default to English at config time; language picker below overrides via st.rerun
st.set_page_config(
    page_title="YC's Flight Deal Dashboard",
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)


# ----------------------------------------------------------------------
# Language picker — must come BEFORE any UI text so we can pick strings
# ----------------------------------------------------------------------
# Init default — overwrite possible values in priority order below
#
# Priority (highest first):
#   1. URL query string  ?lang=zh  (shareable — receives override)
#   2. Browser localStorage pref (sticky per-browser)
#   3. Hard fallback = "zh" (so first impression matches your main use case)
#
# localStorage note: streamlit only exposes Py→JS via components.html (iframe),
# which we already use elsewhere. For now we read URL query + persistent fallback.
DEFAULT_LANG = "zh"  # change to "en" if you want English-first

if "_lang" not in st.session_state:
    st.session_state["_lang"] = DEFAULT_LANG

# Priority 1: URL query override  (?lang=en or ?lang=zh)
_qp = st.query_params.get("lang")
if isinstance(_qp, list):
    _qp = _qp[0] if _qp else None
if _qp in ("en", "zh"):
    st.session_state["_lang"] = _qp
    try:
        st.query_params["lang"] = _qp  # make sticky in URL after first load
    except Exception:
        pass

# Reserve a placeholder for the sidebar's language radio
_LANG_PLACEHOLDER = st.sidebar.empty()


# ----------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------
with st.sidebar:
    # Language picker — first thing the user sees
    lang_choice = _LANG_PLACEHOLDER.radio(
        t("en", "lang_label"),
        options=["en", "zh"],
        format_func=lambda v: t(v, "lang_label").split(" ", 1)[1] if v == "zh" else "English",
        index=0 if st.session_state["_lang"] == "en" else 1,
        horizontal=True,
        key="_lang_radio",
    )
    if lang_choice != st.session_state["_lang"]:
        st.session_state["_lang"] = lang_choice
        st.rerun()
    L = st.session_state["_lang"]

    # Layout picker (responsive: spacious default; user can switch)
    if "_layout_user_set" not in st.session_state:
        # First visit — choose based on a hint
        # Streamlit doesn't expose User-Agent directly; we check ContextVia st_javascript? No.
        # Default to spacious, with a small prompt for mobile users
        st.session_state["_layout"] = "spacious"
        st.session_state["_layout_user_set"] = False
    layout_labels = layout_options(L)
    layout_idx = 0 if st.session_state.get("_layout", "spacious") == "spacious" else 1
    layout_choice_label = st.radio(
        t(L, "layout_label"),
        options=layout_labels,
        index=layout_idx,
        horizontal=True,
        key="_layout_radio",
    )
    layout_choice = "spacious" if layout_choice_label == layout_labels[0] else "compact"
    if layout_choice != st.session_state.get("_layout"):
        st.session_state["_layout"] = layout_choice
        st.session_state["_layout_user_set"] = True
    LAYOUT = layout_choice

    # Mobile hint when user hasn't manually toggled yet
    if not st.session_state["_layout_user_set"]:
        if L == "zh":
            st.caption("📱 手機/平板建議切到「精簡」，資訊密度較低")
        else:
            st.caption("📱 On mobile / tablet, switch to \"Compact\" for better density")

    st.title(f"{PAGE_ICON} {t(L, 'sidebar_title')}")
    st.caption(t(L, "sidebar_caption"))

    results = load_results()

    if results is None:
        st.error(t(L, "no_candidates_error"))
        st.code(t(L, "no_candidates_command"), language="bash")
        st.stop()

    filters = results.get("filters", {})
    # YC recommended thresholds — button to restore
    if st.button(t(L, "reset_filters_btn"), key="reset_filters", use_container_width=True):
        st.session_state["_max_risk_widget"] = 25
        st.session_state["_max_fatigue_widget"] = 7.5
        st.session_state["_min_savings_widget"] = 35
        st.session_state["_min_aircraft_widget"] = 4
        st.session_state["_verdict_filter_widget"] = ["prime_deal", "acceptable_economy"]
        st.session_state["_excluded_carriers_widget"] = ["LH", "BA", "AF", "KL"]
        st.session_state["_preferred_aircraft_widget"] = ["A380", "A350-900", "A350-1000", "B787-9", "B787-10"]
        st.rerun()
    st.caption(t(L, "filters_recommended_caption"))

    st.markdown(t(L, "filters_override"))

    max_risk = st.slider(
        t(L, "max_risk"),
        min_value=0, max_value=100,
        value=st.session_state.get("_max_risk_widget", 25),
        key="_max_risk_widget",
        help=t(L, "max_risk_help"),
    )
    min_aircraft = st.slider(
        t(L, "min_aircraft"),
        min_value=1, max_value=10,
        value=st.session_state.get("_min_aircraft_widget", 4),
        step=1,
        key="_min_aircraft_widget",
        help=t(L, "min_aircraft_help"),
    )
    max_fatigue = st.slider(
        t(L, "max_fatigue"),
        min_value=0.0, max_value=10.0,
        value=st.session_state.get("_max_fatigue_widget", 7.5),
        step=0.5,
        key="_max_fatigue_widget",
    )
    min_savings = st.slider(
        t(L, "min_savings"),
        min_value=0, max_value=100,
        value=st.session_state.get("_min_savings_widget", 35),
        key="_min_savings_widget",
    )
    verdict_filter = st.multiselect(
        t(L, "allowed_verdicts"),
        options=["prime_deal", "acceptable_economy", "avoid_exhausting"],
        default=st.session_state.get("_verdict_filter_widget", ["prime_deal", "acceptable_economy"]),
        key="_verdict_filter_widget",
    )

    # Travel companion's preferences (soft: warning + priority boost, not hard exclusion)
    st.markdown(t(L, "user_prefs_header"))
    excluded_carriers = st.multiselect(
        t(L, "excluded_carriers"),
        options=["LH", "BA", "AF", "KL", "MH", "EK", "QR", "EY", "TK", "SQ", "KE", "OZ", "JL", "NH"],
        default=st.session_state.get("_excluded_carriers_widget", ["LH", "BA", "AF", "KL"]),
        key="_excluded_carriers_widget",
        help=t(L, "excluded_carriers_help"),
    )
    preferred_aircraft = st.multiselect(
        t(L, "preferred_aircraft"),
        options=["A380", "A350-900", "A350-1000", "B787-9", "B787-10", "B777-300ER"],
        default=st.session_state.get("_preferred_aircraft_widget", ["A380", "A350-900", "A350-1000", "B787-9", "B787-10"]),
        key="_preferred_aircraft_widget",
        help=t(L, "preferred_aircraft_help"),
    )

    st.markdown("---")
    st.markdown(t(L, "yc_original_filters"))
    st.json(filters)

    st.markdown("---")
    st.caption(t(L, "evaluated_at", ts=results.get("evaluated_at", "n/a")))


# ----------------------------------------------------------------------
# Apply filters
# ----------------------------------------------------------------------
all_evaluated = results.get("all_evaluated", [])
df_all = results_to_dataframe(all_evaluated)

# Pull aircraft_comfort from raw all_evaluated (since df_all stripped it)
acf_by_id = {
    o["id"]: o.get("evaluation", {}).get("aircraft_comfort", 5.0)
    for o in all_evaluated
}
df_all["aircraft_comfort"] = df_all["id"].map(acf_by_id).fillna(5.0)

df_survived = df_all.copy()
df_survived = df_survived[
    (df_survived["risk"] <= max_risk / 100) &
    (df_survived["fatigue"] <= max_fatigue) &
    (df_survived["savings_pct"] >= min_savings) &
    (df_survived["aircraft_comfort"] >= min_aircraft) &
    (df_survived["routing_verdict"].isin(verdict_filter))
]

# Compute user-preference score:
#   - boost if long-haul segment uses preferred aircraft
#   - strong penalty if any segment uses excluded carrier
#
# v0.2 (Dashboard Runtime Repair): the underlying canonical evidence may
# have `aircraft_type = None` for any segment (current backend data shows
# 100% null). The original implementation called `.startswith()` on the
# raw value, which raised AttributeError. We now route the aircraft match
# through `dashboard_adapter.safe_startswith`, which returns False for
# non-string values instead of raising. The carrier membership test is
# routed through `safe_in` for symmetry and future-proofing. Semantics
# (boost -1 / penalty +3 / neutral 0) are preserved.
def _pref_score(opt_id: str) -> float:
    opt = opt_by_id_sort.get(opt_id, {})
    segs = opt.get("segments", [])
    score = 0.0
    if segs and preferred_aircraft:
        long_haul_seg = segs[1] if len(segs) >= 2 else segs[0]
        ac = long_haul_seg.get("aircraft_type")
        if _safe_startswith(ac, preferred_aircraft):
            score -= 1.0  # boost
    if segs and excluded_carriers:
        for s in segs:
            op = s.get("operating_carrier")
            mkt = s.get("carrier")
            if _safe_in(op, excluded_carriers) or _safe_in(mkt, excluded_carriers):
                score += 3.0  # strong penalty — outweighs fatigue gap
                break
    return score

# Downgrade verdict if carrier is excluded (visual + sort impact)
def _downgrade_verdict(opt_id: str, current_verdict: str) -> str:
    if current_verdict != "prime_deal":
        return current_verdict
    opt = opt_by_id_sort.get(opt_id, {})
    segs = opt.get("segments", [])
    for s in segs:
        op = s.get("operating_carrier")
        mkt = s.get("carrier")
        if _safe_in(op, excluded_carriers) or _safe_in(mkt, excluded_carriers):
            return "acceptable_economy"
    return current_verdict

opt_by_id_sort = {o["id"]: o for o in all_evaluated}
df_survived["_pref_score"] = df_survived["id"].map(_pref_score)
df_survived["routing_verdict"] = df_survived.apply(
    lambda r: _downgrade_verdict(r["id"], r["routing_verdict"]),
    axis=1,
)

# Sort by verdict priority then fatigue then risk then price
verdict_priority = {"prime_deal": 0, "acceptable_economy": 1, "avoid_exhausting": 2}
df_survived = df_survived.sort_values(
    by=["routing_verdict", "fatigue", "risk", "total_cost_twd", "_pref_score"],
    key=lambda col: col.map(lambda v: verdict_priority.get(v, 9)) if col.name == "routing_verdict" else col,
)
df_survived = df_survived.drop(columns=["_pref_score"])


# ----------------------------------------------------------------------
# Dashboard View Model (Dashboard Intelligence v0.2)
# ----------------------------------------------------------------------
# Load canonical evidence and build a per-candidate view object. This is
# presentation-only — it does NOT modify any canonical evidence and does NOT
# introduce any new arbitrage, ranking, or recommendation logic.
#
# The View Model joins evidence by candidate_id. When a candidate has no
# match (e.g., flight_results.json has 80 candidates but the L4.1 evidence
# files cover only 2), the corresponding *_view field is None and the UI
# displays "Evidence unavailable" — never fabricated.
@st.cache_data(ttl=60)
def _load_view_model() -> dict:
    """
    Load all canonical evidence files and build a View Model keyed by
    candidate_id. Returns:
      {
        "by_id": {candidate_id -> DashboardCandidateView.to_dict()},
        "summary": {arbitrage_state -> count, ...},
        "data_freshness": {"flight_results_at": ..., "evidence_files": {...}}
      }
    """
    DATA = Path(__file__).parent / "data"
    try:
        candidates = _vm_load_candidates(DATA / "flight_results.json")
    except Exception:
        candidates = []

    sched_idx = _vm_load_evidence_index(DATA / "schedule_evidence_v1_2_1.json")
    price_idx = _vm_load_evidence_index(DATA / "price_evidence.json")
    fx_idx = _vm_load_fx_evidence_index(DATA / "fx_evidence_v1_2_2.json")
    parity_idx = _vm_load_evidence_index(DATA / "passenger_parity_evidence_v1_2_3.json")
    base_idx = _vm_load_evidence_index(DATA / "baseline_evidence_v1_2_4.json")
    comp_idx = _vm_load_evidence_index(DATA / "comparison_evidence_v1_2_5.json")
    arb_idx = _vm_load_evidence_index(DATA / "arbitrage_evidence_l4.json")

    by_id: dict = {}
    summary: dict = {
        "candidates": len(candidates),
        "potential_opportunity": 0,
        "insufficient_evidence": 0,
        "not_comparable": 0,
        "not_arbitrage": 0,
        "refused": 0,
        "with_evidence": 0,
        "without_evidence": 0,
    }
    for c in candidates:
        v = _vm_build_view(c, sched_idx, price_idx, fx_idx, parity_idx, base_idx, comp_idx, arb_idx)
        cid = c.get("id")
        if isinstance(cid, str):
            by_id[cid] = v.to_dict()
        # Aggregate arbitrage state counts
        if v.arbitrage is None:
            summary["without_evidence"] += 1
        else:
            summary["with_evidence"] += 1
            st_name = v.arbitrage.arbitrage_state
            if st_name == "POTENTIAL_OPPORTUNITY":
                summary["potential_opportunity"] += 1
            elif st_name == "INSUFFICIENT_EVIDENCE":
                summary["insufficient_evidence"] += 1
            elif st_name == "NOT_COMPARABLE":
                summary["not_comparable"] += 1
            elif st_name == "NOT_ARBITRAGE":
                summary["not_arbitrage"] += 1
            elif st_name in ("REFUSED",):
                summary["refused"] += 1

    # Data freshness audit
    freshness = {"evidence_files": {}}
    try:
        if (DATA / "flight_results.json").exists():
            fr = json.loads((DATA / "flight_results.json").read_text())
            freshness["flight_results_at"] = fr.get("evaluated_at")
            freshness["flight_results_candidate_count"] = len(fr.get("all_evaluated", []))
    except Exception:
        pass
    for fn in ["schedule_evidence_v1_2_1.json", "price_evidence.json",
               "fx_evidence_v1_2_2.json", "passenger_parity_evidence_v1_2_3.json",
               "baseline_evidence_v1_2_4.json", "comparison_evidence_v1_2_5.json",
               "arbitrage_evidence_l4.json"]:
        p = DATA / fn
        if p.exists():
            try:
                d = json.loads(p.read_text())
                freshness["evidence_files"][fn] = {
                    "present": True,
                    "retrieved_at": d.get("trace_at") or d.get("retrieved_at"),
                    "evidence_count": d.get("n_evidences") or len(d.get("evidences", [])),
                }
            except Exception:
                freshness["evidence_files"][fn] = {"present": True, "parse_error": True}

    return {"by_id": by_id, "summary": summary, "data_freshness": freshness}


_VIEW_MODEL = _load_view_model()
_VM_BY_ID = _VIEW_MODEL["by_id"]
_VM_SUMMARY = _VIEW_MODEL["summary"]
_VM_FRESHNESS = _VIEW_MODEL["data_freshness"]


# ----------------------------------------------------------------------
# Evidence-aware presentation helpers (Dashboard Intelligence v0.2)
# ----------------------------------------------------------------------
def _vm_render_state_badge(state: str) -> str:
    """Return a neutral visual badge for an evidence state. NO ranking."""
    color_map = {
        "POTENTIAL_OPPORTUNITY": "🟡",
        "INSUFFICIENT_EVIDENCE": "⚪",
        "NOT_COMPARABLE": "⚪",
        "NOT_ARBITRAGE": "⚪",
        "EVIDENCE_VERIFIED": "🟢",
        "VERIFIED_OPPORTUNITY": "🟢",
    }
    icon = color_map.get(state, "⚪")
    return f"{icon} {state}"


def _vm_render_verification_badge(vs: str) -> str:
    """Return a neutral visual badge for a 5-tier verification status."""
    color_map = {
        "LIVE": "🟢",
        "VERIFIED": "🟢",
        "DATABASE": "🟡",
        "ESTIMATED": "🟡",
        "UNKNOWN": "⚪",
    }
    icon = color_map.get(vs, "⚪")
    return f"{icon} {vs}"


def _vm_render_evidence_card(view: dict) -> None:
    """Render a single candidate's evidence card using st.expander."""
    cid = view.get("identity", {}).get("candidate_id") or "—"
    label = view.get("identity", {}).get("label") or "—"
    route = view.get("identity", {}).get("route") or []
    st.markdown(f"**{label}**")
    st.caption(f"candidate_id: `{cid}` · route: {' → '.join(route) if route else '—'}")

    # Discovery
    discovery = view.get("discovery") or {}
    st.markdown("**Discovery**")
    c1, c2 = st.columns(2)
    with c1:
        st.write("discovery_reason:", discovery.get("discovery_reason") or _VM_UNKNOWN)
        st.write("candidate_family:", discovery.get("candidate_family") or _VM_UNKNOWN)
    with c2:
        st.write("route_structure:", discovery.get("route_structure") or _VM_UNKNOWN)

    # Schedule evidence
    sched = view.get("schedule")
    st.markdown("**Schedule evidence**")
    if sched:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("verification:", _vm_render_verification_badge(sched.get("verification_status") or _VM_UNKNOWN))
        with c2:
            st.write("provider:", sched.get("provider") or _VM_UNKNOWN)
        with c3:
            st.write("provider_mode:", sched.get("provider_mode") or _VM_UNKNOWN)
        st.write("schedule_status:", sched.get("schedule_status") or _VM_UNKNOWN)
    else:
        st.write(f"⚠ {_VM_EVIDENCE_UNAVAILABLE}")

    # Price evidence
    st.markdown("**Price evidence**")
    price = view.get("price") or {}
    providers = price.get("providers") or []
    if providers:
        for p in providers:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.write("provider:", p.get("provider") or _VM_UNKNOWN)
            with c2:
                st.write("mode:", p.get("provider_mode") or _VM_UNKNOWN)
            with c3:
                st.write("currency:", p.get("currency") or _VM_UNKNOWN)
            with c4:
                vs = p.get("verification_status") or _VM_UNKNOWN
                st.write("verification:", _vm_render_verification_badge(vs))
            # Pricing details
            price_val = p.get("price")
            st.write(f"  price: {price_val if price_val is not None else _VM_UNKNOWN}")
            retrieved = p.get("retrieved_at")
            if retrieved:
                st.caption(f"  retrieved_at: {retrieved}")
    else:
        st.write(f"⚠ {_VM_EVIDENCE_UNAVAILABLE}")

    # Legacy fields — clearly labeled
    legacy_twd = price.get("legacy_total_cost_twd")
    legacy_pct = price.get("legacy_savings_pct")
    if legacy_twd is not None or legacy_pct is not None:
        with st.expander("Legacy / derived fields (informational only)"):
            st.caption(
                "These fields are pre-computed at candidate-generation time "
                "and have no associated live provider or freshness. They are "
                "shown for backward compatibility only — they do NOT represent "
                "a live provider price."
            )
            if legacy_twd is not None:
                st.write(f"legacy_total_cost_twd: {legacy_twd:,}")
            if legacy_pct is not None:
                st.write(f"legacy_savings_pct: {legacy_pct}")

    # FX evidence
    st.markdown("**FX evidence**")
    fx = view.get("fx")
    if fx:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("state:", fx.get("fx_state") or _VM_UNKNOWN)
        with c2:
            base = fx.get("base_currency") or "?"
            quote = fx.get("quote_currency") or "?"
            st.write(f"pair: {base}→{quote}")
        with c3:
            rate = fx.get("rate")
            st.write(f"rate: {rate if rate is not None else _VM_UNKNOWN}")
        vs = fx.get("verification_status") or _VM_UNKNOWN
        st.write("verification:", _vm_render_verification_badge(vs))
        st.write(f"provider: {fx.get('provider') or _VM_UNKNOWN}")
        # Honest warning if FX is REFUSED/UNKNOWN
        if fx.get("fx_state") in ("REFUSED", "UNKNOWN"):
            st.caption("⚠ FX-converted prices cannot be displayed as 'real' when FX state is REFUSED or UNKNOWN.")
    else:
        st.write(f"⚠ {_VM_EVIDENCE_UNAVAILABLE}")

    # Baseline
    st.markdown("**Baseline**")
    base = view.get("baseline")
    if base:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("class:", base.get("baseline_class") or _VM_UNKNOWN)
        with c2:
            st.write("candidate_id:", base.get("baseline_candidate_id") or _VM_UNKNOWN)
        with c3:
            st.write("verification:", _vm_render_verification_badge(base.get("verification_status") or _VM_UNKNOWN))
    else:
        st.write(f"⚠ {_VM_EVIDENCE_UNAVAILABLE}")

    # Comparison
    st.markdown("**Comparison**")
    comp = view.get("comparison")
    if comp:
        c1, c2 = st.columns(2)
        with c1:
            st.write("comparability:", comp.get("comparability_status") or _VM_UNKNOWN)
            st.write("fx_state:", comp.get("fx_state") or _VM_UNKNOWN)
        with c2:
            delta = comp.get("delta")
            st.write(f"delta: {delta if delta is not None else _VM_UNKNOWN}")
            d_pct = comp.get("delta_percentage")
            st.write(f"delta_pct: {d_pct if d_pct is not None else _VM_UNKNOWN}")
        if comp.get("refusal_reasons"):
            st.caption(f"refusal_reasons: {comp['refusal_reasons']}")
        if comp.get("provider_disagreement") is True:
            st.caption("⚠ Provider disagreement (recorded as evidence, not as an error)")
    else:
        st.write(f"⚠ {_VM_EVIDENCE_UNAVAILABLE}")

    # Arbitrage state
    st.markdown("**Arbitrage state (L4)**")
    arb = view.get("arbitrage")
    if arb:
        st.write("state:", _vm_render_state_badge(arb.get("arbitrage_state") or _VM_UNKNOWN))
        st.write(f"evidence_maturity: {arb.get('evidence_maturity') or _VM_UNKNOWN}")
        if arb.get("arbitrage_reasons"):
            st.caption(f"reasons: {arb['arbitrage_reasons']}")
        if arb.get("insufficient_evidence_reasons"):
            st.caption(f"insufficient: {arb['insufficient_evidence_reasons']}")
        if arb.get("required_for_verification"):
            with st.expander("What remains unverified for VERIFIED"):
                for r in arb["required_for_verification"]:
                    st.write(f"• {r}")
    else:
        st.write(f"⚠ {_VM_EVIDENCE_UNAVAILABLE}")

    # Friction
    st.markdown("**Friction**")
    f = view.get("friction") or {}
    items = []
    for k in ["airport_change", "self_transfer", "multi_ticket", "positioning",
              "outer_port", "long_connection", "schedule_uncertainty",
              "baggage_uncertainty", "recheck_required", "overnight", "tight_connection"]:
        v = f.get(k)
        if v is True:
            items.append(f"⚠ {k}")
        elif v is False:
            items.append(f"✓ no {k}")
        elif v is None:
            items.append(f"? {k} unknown")
    if items:
        for it in items:
            st.write(it)
    else:
        st.write(_VM_UNKNOWN)

    # Missing / unverified
    st.markdown("**Missing / unverified**")
    missing = view.get("missing") or {}
    for k, v in missing.items():
        if v:
            st.write(f"⚠ {k}")


# ----------------------------------------------------------------------
# KPI row
# ----------------------------------------------------------------------
st.title(t(L, "title"))

# Dynamic subtitle built from current data (so adding ICN updates automatically)
# Identify unique outer ports in the data; sort for a stable label
ports = sorted(set(df_all["outer_port"].dropna())) if not df_all.empty else ["KUL", "CGK", "BKK"]
ports_label = " · ".join(ports)

route_arrow_en = "→"
route_arrow_zh = "→"
if L == "zh":
    st.markdown(f"**{ports_label} {route_arrow_zh} 中東轉機 {route_arrow_zh} 西班牙 (MAD/BCN)** · 全商務艙")
else:
    st.markdown(f"**{ports_label} {route_arrow_en} Middle East {route_arrow_en} Spain (MAD/BCN)** · All business class")

if df_survived.empty:
    st.warning(t(L, "no_data_warning"))
else:
    top_pick = df_survived.iloc[0]
    total_savings = int(df_survived["savings_twd"].sum())
    avg_savings_pct = round(df_survived["savings_pct"].mean(), 1)

    # Inject CSS based on layout choice
    inject_layout_css(LAYOUT)

    c1, c2, c3, c4 = (st.columns(2) if LAYOUT == "compact" else st.columns(4))
    with c1:
        st.metric(
            t(L, "kpi_top_pick"),
            f"NT$ {int(top_pick['total_cost_twd']):,}",
            f"{top_pick['savings_pct']}% {t(L, 'kpi_saved_suffix')}",
            delta_color="inverse",
        )
    with c2:
        st.metric(
            t(L, "kpi_avg_savings"),
            f"{avg_savings_pct}%",
            t(L, "kpi_avg_savings_sub", n=f"{TPE_BASELINE_TWD:,}"),
        )
    with c3:
        st.metric(
            t(L, "kpi_options_matched"),
            f"{len(df_survived)} / {len(df_all)}",
            f"{len(df_survived)} {t(L, 'kpi_options_matched_sub')}",
        )
    with c4:
        st.metric(
            t(L, "kpi_total_savings"),
            f"NT$ {total_savings:,}",
            f"{int(total_savings/1000)} {t(L, 'kpi_total_savings_unit')}" if total_savings > 1000 else None,
        )


# ----------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------
tab_kpi, tab_top3, tab_compare, tab_map, tab_table, tab_cal, tab_aircraft, tab_summary, tab_evidence = st.tabs([
    t(L, "tab_overview"),
    t(L, "tab_top3"),
    t(L, "tab_compare"),
    t(L, "tab_routes"),
    t(L, "tab_all"),
    t(L, "tab_calendar"),
    t(L, "tab_aircraft"),
    t(L, "tab_summary"),
    "Evidence (L0–L4.1)",
])


# === TAB 1: Overview charts ===
with tab_kpi:
    # Dashboard Intelligence v0.2: L4 evidence state counts (descriptive, not ranking).
    # These are honest counts of canonical L4 arbitrage states. They are NOT
    # recommendations and they do NOT imply which candidate is "best".
    s = _VM_SUMMARY
    if s.get("candidates", 0) > 0:
        st.markdown("##### L4 evidence overview")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            st.metric("Candidates", s.get("candidates", 0))
        with c2:
            st.metric("With evidence", s.get("with_evidence", 0))
        with c3:
            st.metric("Potential", s.get("potential_opportunity", 0))
        with c4:
            st.metric("Insufficient", s.get("insufficient_evidence", 0))
        with c5:
            st.metric("Not comparable", s.get("not_comparable", 0))
        with c6:
            st.metric("No evidence", s.get("without_evidence", 0))
        st.caption(
            "Descriptive state counts, NOT rankings. See the 'Evidence (L0–L4.1)' tab for details."
        )
        st.markdown("---")

    if df_survived.empty:
        st.info(t(L, "no_data_scatter"))
    else:
        # Layout-aware: compact stacks vertically (single column); spacious puts 2 charts side-by-side
        if LAYOUT == "compact":
            col_a = st.container()
            col_b = st.container()
        else:
            col_a, col_b = st.columns(2)

        # --- Scatter: risk vs fatigue ---
        with col_a:
            fig_scatter = px.scatter(
                df_survived,
                x="risk", y="fatigue",
                size="savings_pct", color="routing_verdict",
                hover_name="label",
                hover_data={
                    "id": True,
                    "origin": True,
                    "outer_port": True,
                    "via_hub": True,
                    "carrier": True,
                    "destination": True,
                    "total_cost_twd": ":,",
                    "savings_pct": True,
                    "risk": ":.0%",
                    "fatigue": ":.1f",
                    "total_elapsed_h": ":.1f",
                },
                size_max=60,
                color_discrete_map={
                    "prime_deal": "#16a34a",
                    "acceptable_economy": "#f59e0b",
                    "avoid_exhausting": "#dc2626",
                },
                title=t(L, "scatter_title"),
                labels={"risk": t(L, "scatter_x"), "fatigue": t(L, "scatter_y")},
            )
            fig_scatter.update_layout(height=450)
            fig_scatter.add_vline(x=0.25, line_dash="dash", line_color="red", opacity=0.5)
            fig_scatter.add_hline(y=7.5, line_dash="dash", line_color="red", opacity=0.5)
            fig_scatter.add_annotation(x=0.05, y=8.5,
                text=t(L, "high_risk_high_fatigue"), showarrow=False,
                font=dict(color="red", size=10), opacity=0.5)
            fig_scatter.add_annotation(x=0.05, y=1.5,
                text=t(L, "low_risk_low_fatigue"), showarrow=False,
                font=dict(color="green", size=10), opacity=0.5)
            st.plotly_chart(fig_scatter, use_container_width=True)

        # --- Bar: price comparison ---
        with col_b:
            df_plot = df_survived.sort_values("total_cost_twd", ascending=True)
            fig_bar = px.bar(
                df_plot,
                x="total_cost_twd", y="label",
                color="routing_verdict",
                orientation="h",
                hover_data=["savings_pct", "risk", "fatigue"],
                color_discrete_map={
                    "prime_deal": "#16a34a",
                    "acceptable_economy": "#f59e0b",
                    "avoid_exhausting": "#dc2626",
                },
                title=t(L, "bar_title"),
                labels={"total_cost_twd": t(L, "bar_xlabel"), "label": ""},
            )
            fig_bar.add_vline(x=TPE_BASELINE_TWD, line_dash="dash", line_color="red",
                annotation_text=t(L, "tpe_baseline_label", n=TPE_BASELINE_TWD),
                annotation_position="top right")
            fig_bar.update_layout(height=450, yaxis={"automargin": True})
            st.plotly_chart(fig_bar, use_container_width=True)

        # --- Savings + elapsed ---
        if LAYOUT == "compact":
            col_c = st.container()
            col_d = st.container()
        else:
            col_c, col_d = st.columns(2)
        with col_c:
            df_savings = df_survived.sort_values("savings_pct", ascending=False).head(10)
            fig_sav = px.bar(
                df_savings,
                x="savings_pct", y="label",
                orientation="h",
                color="routing_verdict",
                color_discrete_map={
                    "prime_deal": "#16a34a",
                    "acceptable_economy": "#f59e0b",
                    "avoid_exhausting": "#dc2626",
                },
                title=t(L, "savings_title"),
                labels={"savings_pct": t(L, "savings_xlabel")},
            )
            fig_sav.update_layout(height=400, yaxis={"automargin": True})
            st.plotly_chart(fig_sav, use_container_width=True)

        with col_d:
            df_ela = df_survived.sort_values("total_elapsed_h")
            fig_ela = px.bar(
                df_ela,
                x="total_elapsed_h", y="label",
                orientation="h",
                color="fatigue",
                color_continuous_scale="RdYlGn_r",
                title=t(L, "elapsed_title"),
                labels={"total_elapsed_h": t(L, "elapsed_xlabel")},
            )
            fig_ela.update_layout(height=400, yaxis={"automargin": True})
            st.plotly_chart(fig_ela, use_container_width=True)


# === TAB 2: Top 3 cards ===
with tab_top3:
    if df_survived.empty:
        st.info(t(L, "no_options_compare"))
    else:
        st.markdown(f"### {t(L, 'top3_title')}")
        st.caption(t(L, "top3_intro"))
        top3 = df_survived.head(3)
        opt_by_id = {o["id"]: o for o in all_evaluated}
        cols = st.columns(len(top3))
        medals = ["🥇", "🥈", "🥉"]
        for col, (_, row), medal in zip(cols, top3.iterrows(), medals):
            with col:
                verdict_color = {
                    "prime_deal": "🟢",
                    "acceptable_economy": "🟡",
                    "avoid_exhausting": "🔴",
                }.get(row["routing_verdict"], "⚪")

                st.markdown(f"### {medal} {verdict_color} {row['id']}")
                st.caption(row["label"])

                # Travel companion preference tags
                opt_for_tags = opt_by_id.get(row["id"], {})
                tags = []
                # Check excluded carriers
                for seg in opt_for_tags.get("segments", []):
                    op = seg.get("operating_carrier", "")
                    mkt = seg.get("carrier", "")
                    if (op and op in excluded_carriers) or (mkt and mkt in excluded_carriers):
                        tags.append(t(L, "tag_excluded"))
                        break
                # Check preferred aircraft (long-haul segment)
                segs = opt_for_tags.get("segments", [])
                if segs and preferred_aircraft:
                    long_haul_seg = segs[1] if len(segs) >= 2 else segs[0]
                    ac = long_haul_seg.get("aircraft_type")
                    if _safe_startswith(ac, preferred_aircraft):
                        tags.append(t(L, "tag_preferred"))
                # Check codeshare on any segment
                for seg in opt_for_tags.get("segments", []):
                    op = seg.get("operating_carrier", "")
                    mkt = seg.get("carrier", "")
                    if op and mkt and op.upper() != mkt.upper():
                        tags.append(t(L, "tag_codeshare"))
                        break
                if tags:
                    st.caption(" · ".join(tags))

                st.metric(
                    t(L, "metrics_total_cost"),
                    f"NT$ {int(row['total_cost_twd']):,}",
                    t(L, "top3_savings_pct", pct=row['savings_pct']),
                )

                # Aircraft info: show which long-haul aircraft is used, comfort rating, codeshare warnings
                opt_aircraft_lines = []
                for seg in opt_by_id.get(row["id"], {}).get("segments", []):
                    op = seg.get("operating_carrier", "—")
                    mkt = seg.get("carrier", "—")
                    ac = seg.get("aircraft_type", "—")
                    age = seg.get("aircraft_age_yr")
                    product = seg.get("cabin_product", "")
                    cs = "⚠️" if op.upper() != mkt.upper() else ""
                    comfort = aircraft_comfort_score(ac)
                    age_part = f"{age}年" if age is not None else "—"
                    prod_part = f" ({product})" if product else ""
                    opt_aircraft_lines.append(
                        f"  - {seg.get('from','?')}→{seg.get('to','?')}: "
                        f"`{mkt}`{' ' + cs + ' ' + op if cs else ''}  · "
                        f"**{ac}** ({age_part}) ★{comfort}{prod_part}"
                    )
                aircraft_summary = "\n".join(opt_aircraft_lines) if opt_aircraft_lines else "—"

                acf = opt_by_id.get(row["id"], {}).get("evaluation", {}).get("aircraft_comfort", "—")
                downgrade = "⚠downgraded" if opt_by_id.get(row["id"], {}).get("evaluation", {}).get("aircraft_auto_downgrade") else ""

                st.markdown(f"""
- **{t(L, 'metrics_origin')}**: {row['origin']}
- **{t(L, 'metrics_outer')}**: {row['outer_port']}
- **{t(L, 'metrics_hub')}**: {row['via_hub']}
- **{t(L, 'metrics_carrier')}**: {row['carrier']}
- **{t(L, 'metrics_destination')}**: {row['destination']}
- **{t(L, 'metrics_verdict')}**: {row['routing_verdict']}
- **{t(L, 'metrics_risk')}**: {row['risk']:.0%}
- **{t(L, 'metrics_fatigue')}**: {row['fatigue']:.1f} / 10
- **{t(L, 'metrics_aircraft_score')}**: {acf} / 10 {downgrade}
- **{t(L, 'metrics_elapsed')}**: {row['total_elapsed_h']}h
- **{t(L, 'metrics_same_pnr')}**: {row['same_pnr']}
- **{t(L, 'metrics_segments')}**: {row['n_segments']}

**{t(L, 'metrics_aircraft_breakdown')}**:
{aircraft_summary}
""")

                with st.expander(t(L, "metrics_notes"), expanded=False):
                    st.write(opt_by_id.get(row["id"], {}).get("notes", t(L, "metrics_no_notes")))

                with st.expander(t(L, "metrics_route"), expanded=False):
                    for seg in segments_for_route(opt_by_id.get(row["id"], {})):
                        st.write(f"  - **{seg['carrier']} {seg['flight']}**: "
                                  f"{seg['from']} → {seg['to']}  "
                                  f"({seg['duration_min']} min, {seg['cabin']})")


# === TAB 3: Side-by-side comparison ===
with tab_compare:
    if df_survived.empty:
        st.info(t(L, "no_options_compare"))
    else:
        st.markdown(f"### {t(L, 'compare_pick')}")
        compare_ids = st.multiselect(
            t(L, "compare_pick"),
            options=df_survived["id"].tolist(),
            default=df_survived.head(3)["id"].tolist(),
            max_selections=4,
        )
        if not compare_ids:
            st.info(t(L, "compare_select_one"))
        else:
            compare_df = df_survived[df_survived["id"].isin(compare_ids)].T
            compare_df.columns = compare_df.iloc[0]
            compare_df = compare_df[1:]

            st.dataframe(
                compare_df,
                use_container_width=True,
                column_config={
                    "total_cost_twd": st.column_config.ProgressColumn(
                        "Total cost (TWD)", format="NT$ %d", min_value=0, max_value=200000,
                    ),
                    "risk": st.column_config.ProgressColumn(
                        "Risk", format="%.0f%%", min_value=0, max_value=100,
                    ),
                    "fatigue": st.column_config.ProgressColumn(
                        "Fatigue", format="%.1f", min_value=0, max_value=10,
                    ),
                    "savings_pct": st.column_config.ProgressColumn(
                        "Savings %", format="%d%%", min_value=0, max_value=100,
                    ),
                },
            )

            opt_by_id = {o["id"]: o for o in all_evaluated}
            categories = t(L, "compare_categories")

            fig_radar = go.Figure()
            for cid in compare_ids:
                row = df_survived[df_survived["id"] == cid].iloc[0]
                opt = opt_by_id.get(cid, {})
                s_pct = row["savings_pct"] / 100
                low_risk = 1 - row["risk"]
                low_fatigue = 1 - (row["fatigue"] / 10)
                short_time = max(0, 1 - (row["total_elapsed_h"] / 30))
                same_pnr = 1.0 if opt.get("same_pnr") else 0.0

                fig_radar.add_trace(go.Scatterpolar(
                    r=[s_pct, low_risk, low_fatigue, short_time, same_pnr],
                    theta=categories,
                    fill="toself",
                    name=cid,
                ))
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                showlegend=True,
                height=500,
                title=t(L, "compare_radar_title"),
            )
            st.plotly_chart(fig_radar, use_container_width=True)


# === TAB 4: Route map ===
with tab_map:
    if df_survived.empty:
        st.info(t(L, "no_options_routes"))
    else:
        st.markdown(f"### {t(L, 'routes_intro')}")
        opt_by_id = {o["id"]: o for o in all_evaluated}
        for _, row in df_survived.iterrows():
            opt = opt_by_id.get(row["id"], {})
            with st.expander(f"**{row['id']}** — {row['label']}  ({row['total_cost_twd']:,} TWD)"):
                cols = st.columns([0.6, 0.4])
                with cols[0]:
                    st.markdown(t(L, "route_waypoints"))
                    for seg in segments_for_route(opt):
                        st.markdown(
                            f"- 🛫 **{seg['from']}** → 🛬 **{seg['to']}**  "
                            f"(`{seg['carrier']} {seg['flight']}`, "
                            f"{seg['duration_min']}min, {seg['cabin']})"
                        )
                with cols[1]:
                    st.markdown(f"""
**Stats:**
- Risk: {row['risk']:.0%}
- Fatigue: {row['fatigue']:.1f}/10
- Elapsed: {row['total_elapsed_h']}h
- Same PNR: {row['same_pnr']}
""")


# === TAB 5: Full table ===
with tab_table:
    st.markdown(f"### {t(L, 'table_title')}")
    st.caption(t(L, "table_caption", total=len(df_all), matched=len(df_survived)))

    df_display = df_all.copy()
    df_display["survives"] = df_display["id"].isin(df_survived["id"])

    st.dataframe(
        df_display.sort_values(["survives", "total_cost_twd"], ascending=[False, True]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.TextColumn(t(L, "table_col_id"), width="small"),
            "label": st.column_config.TextColumn(t(L, "table_col_label"), width="large"),
            "total_cost_twd": st.column_config.NumberColumn(
                t(L, "table_col_cost"), format="NT$ %d",
            ),
            "savings_pct": st.column_config.ProgressColumn(
                t(L, "table_col_save_pct"), format="%d%%", min_value=0, max_value=100,
            ),
            "savings_twd": st.column_config.NumberColumn(
                t(L, "table_col_save_twd"), format="NT$ %d",
            ),
            "risk": st.column_config.ProgressColumn(
                t(L, "table_col_risk"), format="%.0f%%", min_value=0, max_value=100,
            ),
            "fatigue": st.column_config.ProgressColumn(
                t(L, "table_col_fatigue"), format="%.1f", min_value=0, max_value=10,
            ),
            "survives": st.column_config.CheckboxColumn(t(L, "table_col_survives")),
            "same_pnr": st.column_config.CheckboxColumn(t(L, "table_col_pnr")),
        },
    )

    st.download_button(
        t(L, "download_csv"),
        df_survived.to_csv(index=False).encode("utf-8"),
        file_name=f"flight_deals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="dl_csv",
    )


# === TAB: Best booking calendar ===
with tab_cal:
    st.markdown(f"### 🗓️ {t(L, 'cal_title')}")
    st.caption(t(L, "cal_caption"))

    col_season, col_destination = st.columns(2)

    with col_season:
        st.markdown(f"#### 🌡️ {t(L, 'cal_season_header')}")
        for month, price, weather, dest_note in SEASONAL_DATA[L]:
            emoji = "🟢" if price == "cheap" else ("🔴" if price == "peak" else "🟡")
            label = t(L, "cal_cheap" if price == "cheap" else (
                      "cal_peak" if price == "peak" else "cal_moderate"))
            st.markdown(f"**{month}** {emoji} **{label}**  \n{weather}  \n{('→ ' + dest_note) if dest_note else ''}")

    with col_destination:
        st.markdown(f"#### 📍 {t(L, 'cal_dest_header')}")
        st.caption(t(L, "cal_dest_caption"))
        for dest, season_note in DESTINATION_BEST_TIME[L].items():
            st.markdown(f"- **{dest}** — {season_note}")

    st.markdown("---")
    st.markdown(f"### 💡 {t(L, 'cal_pro_tips_header')}")
    st.markdown(t(L, "cal_pro_tips_body"))


# === TAB: Aircraft info ===
with tab_aircraft:
    st.markdown(f"### ✈️ {t(L, 'acf_title')}")
    st.caption(t(L, "acf_caption"))

    if "aircraft_data" not in st.session_state or not st.session_state["aircraft_data"]:
        # Build fresh from current options — read RAW (not from df_all which strips segments)
        rows = []
        for opt in all_evaluated:
            for seg in opt.get("segments", []):
                ac = seg.get("aircraft_type", "—")
                op = seg.get("operating_carrier", "—")
                mkt = seg.get("carrier", "—")
                age = seg.get("aircraft_age_yr", None)
                product = seg.get("cabin_product", "")
                codeshare = op.upper() != mkt.upper() if op and mkt else False
                comfort = aircraft_comfort_score(ac)
                rows.append({
                    "候選ID": opt.get("id", "—"),
                    "航段": f"{seg.get('from','?')}→{seg.get('to','?')}",
                    "銷售航空": mkt,
                    "執飛航空": op,
                    "機型": ac,
                    "機齡(年)": age if age is not None else "—",
                    "艙等": product or "—",
                    "代碼共享": "⚠️ 是" if codeshare else "否",
                    "舒適度★": comfort,
                })
        st.session_state["aircraft_data"] = rows

    df_aircraft = pd.DataFrame(st.session_state["aircraft_data"])
    if not df_aircraft.empty:
        st.dataframe(
            df_aircraft.sort_values(by="舒適度★", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        # Warnings section
        codeshares = df_aircraft[df_aircraft["代碼共享"] == "⚠️ 是"]
        if not codeshares.empty:
            st.markdown(f"#### ⚠️ {t(L, 'acf_codeshare_warning_header')}")
            st.caption(t(L, "acf_codeshare_caption"))
            st.dataframe(codeshares, use_container_width=True, hide_index=True)

        # Show comfort legend
        st.markdown(f"#### 📖 {t(L, 'acf_legend_header')}")
        st.markdown(t(L, "acf_legend_body"))


# === TAB 6: Markdown summary ===
with tab_summary:
    st.markdown(f"### {t(L, 'summary_title')}")
    st.markdown(load_summary())

    with open(RESULTS_PATH) as f:
        raw_data = json.load(f)
    with st.expander(t(L, "raw_json_expander"), expanded=False):
        st.json(raw_data)


# === TAB 9: Evidence (L0–L4.1) — Dashboard Intelligence v0.2 ===
# Honest display of the existing L0–L4.1 evidence architecture.
# No ranking, no scoring, no recommendation. Counts only.
with tab_evidence:
    st.markdown("### Evidence (L0–L4.1)")
    st.caption(
        "Each row shows canonical L0–L4.1 evidence for one candidate, "
        "as recorded in `data/*.json`. Where evidence does not exist, "
        "the panel displays 'Evidence unavailable' — never fabricated."
    )

    # Honest data-freshness banner
    fr_at = _VM_FRESHNESS.get("flight_results_at", "n/a")
    fr_count = _VM_FRESHNESS.get("flight_results_candidate_count", "?")
    st.markdown("#### Data freshness")
    st.write(f"flight_results.json evaluated_at: **{fr_at}** · candidates: **{fr_count}**")
    with st.expander("Per-evidence-file timestamps (canonical)"):
        for fn, info in _VM_FRESHNESS.get("evidence_files", {}).items():
            st.write(f"• `{fn}` — present={info.get('present')}, "
                     f"retrieved_at={info.get('retrieved_at', 'n/a')}, "
                     f"count={info.get('evidence_count', 'n/a')}")

    # Overview state counts (L4 — descriptive, not ranking)
    st.markdown("#### Overview")
    s = _VM_SUMMARY
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("Candidates", s.get("candidates", 0))
    with c2:
        st.metric("With evidence", s.get("with_evidence", 0))
    with c3:
        st.metric("Potential", s.get("potential_opportunity", 0))
    with c4:
        st.metric("Insufficient", s.get("insufficient_evidence", 0))
    with c5:
        st.metric("Not comparable", s.get("not_comparable", 0))
    with c6:
        st.metric("No evidence", s.get("without_evidence", 0))
    st.caption(
        "These are descriptive state counts, NOT rankings. "
        "A 'Potential' count of 0 means no candidate currently has the "
        "evidence layers required to qualify as POTENTIAL_OPPORTUNITY."
    )

    # Honest data-coverage note
    if s.get("without_evidence", 0) > 0:
        st.info(
            f"{s['without_evidence']} of {s['candidates']} candidates have "
            "no L4.1 evidence join. This is the canonical interface mismatch: "
            "flight_results.json was generated by v0.2.1 Jev, while the L4.1 "
            "evidence files cover only 2 candidates from a different mission "
            "(`M-L41-INTEGRATION`). Per spec STEP 30, the View Model does not "
            "fabricate evidence for unmatched candidates."
        )

    # Per-candidate evidence cards
    st.markdown("#### Per-candidate evidence cards")
    st.caption(
        "Click a candidate below to see its full evidence card. "
        "When the L4.1 evidence layers are missing for a candidate, the "
        "panel displays 'Evidence unavailable' rather than guessing."
    )
    # Build candidate list (use the same survived DataFrame the rest of the
    # dashboard uses, so we honor sidebar filters for context).
    cand_list = df_survived["id"].tolist() if "id" in df_survived.columns else []
    if not cand_list:
        cand_list = list(_VM_BY_ID.keys())
    # Show first N candidates to keep the page manageable
    MAX_CARDS = 30
    shown = 0
    for cid in cand_list:
        if shown >= MAX_CARDS:
            st.caption(f"… and {len(cand_list) - MAX_CARDS} more candidates not shown "
                       f"(use the search/filter sidebar to narrow down).")
            break
        view = _VM_BY_ID.get(cid)
        if view is None:
            continue
        label = view.get("identity", {}).get("label") or cid
        with st.expander(f"{label}  ({cid})"):
            _vm_render_evidence_card(view)
        shown += 1

st.markdown("---")
st.caption(t(L, "footer_caption", n=len(all_evaluated)))

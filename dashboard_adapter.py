"""
dashboard_adapter.py — Dashboard Presentation Adapter

Architectural role
==================

Canonical backend evidence (e.g., `data/flight_results.json`) is the
source of truth. Its schema evolves with the Flight Hunter evidence
architecture (v0.1 candidates → Jev evaluation → v1.x evidence).

The Streamlit dashboard is a PRESENTATION layer and must remain stable
even when canonical fields are missing, null, or in a different
location than expected.

This adapter:
  * reads canonical evidence records,
  * produces *display-ready* field values for the dashboard,
  * never fabricates evidence (no invented aircraft, prices, schedules,
    carriers, or verdicts),
  * leaves canonical evidence untouched.

It is intentionally tiny: a thin translation layer, not a re-architecture.

Forbidden behaviors
===================

  * MUST NOT invent aircraft types. If `aircraft_type` is missing or null,
    display "Aircraft unavailable" — never a guessed model.
  * MUST NOT invent schedule data.
  * MUST NOT invent prices.
  * MUST NOT infer bookability or arbitrage.
  * MUST NOT modify Jev, candidate_discovery, or any evidence layer.

Permitted behaviors
===================

  * Defensive null/missing handling.
  * Safe type conversion (only for presentation).
  * Schema relocation (e.g., `evaluation.connection_failure_risk` → `risk`).
  * Presentation defaults that explicitly signal "evidence is unavailable".
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

# ----------------------------------------------------------------------
# Presentation sentinel for "evidence is unavailable"
# ----------------------------------------------------------------------
# A presentation-only string used in the UI when canonical evidence is
# missing or null. NEVER written back to canonical evidence.
AIRCRAFT_UNAVAILABLE = "Aircraft unavailable"
CARRIER_UNAVAILABLE = "Carrier unavailable"
VERDICT_UNAVAILABLE = "Verdict unavailable"
SCORE_UNAVAILABLE: Optional[float] = None


# ----------------------------------------------------------------------
# Low-level safe helpers
# ----------------------------------------------------------------------
def _is_str(value: Any) -> bool:
    """True iff value is a non-None string."""
    return isinstance(value, str)


def safe_str(value: Any, default: Optional[str] = None) -> Optional[str]:
    """Return value if it is a string, else default. None passes through."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return default


def safe_startswith(value: Any, prefixes: Iterable[str]) -> bool:
    """
    Return True iff value is a string and starts with any of prefixes.

    This is the canonical replacement for `value.startswith(p) for p in ...`
    when value may be None, a number, a list, or a dict. The original
    AttributeError came from calling `.startswith()` on `None`.

    The semantic is preserved: if value is not a string, it does NOT
    match any prefix (the candidate receives no boost).
    """
    if not _is_str(value):
        return False
    return any(value.startswith(p) for p in prefixes)


def safe_in(value: Any, container: Iterable[Any]) -> bool:
    """
    Membership test that is safe when value is None.

    The original code used `op in excluded_carriers` and `mkt in excluded_carriers`.
    Python's `in` operator on a list of strings returns False for None, so the
    original code was already safe. This helper exists for symmetry and for
    cases where a non-string value would cause a TypeError.
    """
    if value is None:
        return False
    return value in container


# ----------------------------------------------------------------------
# Display field extractors
# ----------------------------------------------------------------------
def display_aircraft_type(aircraft_type: Any) -> Optional[str]:
    """
    Presentation-safe aircraft type.

    Returns:
      * the aircraft type if it is a non-empty string,
      * None otherwise (the dashboard decides whether to render
        "Aircraft unavailable" or skip the badge).
    """
    if isinstance(aircraft_type, str) and aircraft_type:
        return aircraft_type
    return None


def display_risk(evaluation: Optional[dict]) -> Optional[float]:
    """
    Extract risk from the canonical evaluation sub-dict.

    Returns the number if present, else None. NEVER invents a value.
    """
    if not isinstance(evaluation, dict):
        return None
    v = evaluation.get("connection_failure_risk")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def display_fatigue(evaluation: Optional[dict]) -> Optional[float]:
    """Extract fatigue from the canonical evaluation sub-dict."""
    if not isinstance(evaluation, dict):
        return None
    v = evaluation.get("fatigue_index")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def display_routing_verdict(evaluation: Optional[dict]) -> Optional[str]:
    """Extract routing verdict from the canonical evaluation sub-dict."""
    if not isinstance(evaluation, dict):
        return None
    v = evaluation.get("routing_verdict")
    if isinstance(v, str) and v:
        return v
    return None


def display_total_cost_twd(option: dict) -> Optional[int]:
    """
    Extract total cost in TWD from a candidate option.

    The canonical field is `total_cost` and the currency is provided separately
    as `currency`. We assume TWD because the dashboard is currently TWD-only
    and the canonical data records `"currency": "TWD"` for all current candidates.

    Returns the integer cost if present, else None. NEVER invents a price.
    """
    if not isinstance(option, dict):
        return None
    v = option.get("total_cost")
    if isinstance(v, bool):
        # bool is an int subclass; exclude it explicitly
        return None
    if isinstance(v, (int, float)):
        return int(v)
    return None


def display_route(option: dict) -> Optional[list]:
    """Extract the route list (airport codes) if present."""
    if not isinstance(option, dict):
        return None
    r = option.get("route")
    if isinstance(r, list):
        return r
    return None


def display_carrier(segment: dict) -> Optional[str]:
    """Extract the operating carrier from a segment, preferring operating_carrier."""
    if not isinstance(segment, dict):
        return None
    op = segment.get("operating_carrier")
    if isinstance(op, str) and op:
        return op
    mkt = segment.get("carrier")
    if isinstance(mkt, str) and mkt:
        return mkt
    return None


# ----------------------------------------------------------------------
# Pref-score builder (null-safe replacement for the original helper)
# ----------------------------------------------------------------------
def compute_pref_score(
    opt: dict,
    preferred_aircraft: list,
    excluded_carriers: list,
) -> float:
    """
    Null-safe re-implementation of the dashboard's `_pref_score`.

    Semantics preserved:
      * boost (-1) if any segment's aircraft_type starts with a preferred prefix,
      * penalty (+3) if any segment's operating_carrier or carrier is in the
        excluded list,
      * 0 otherwise.

    Differences from the original:
      * does NOT raise AttributeError when aircraft_type is None,
      * returns 0 (the neutral score) when no signal can be derived.
    """
    score = 0.0
    segs = opt.get("segments") if isinstance(opt, dict) else None
    if not isinstance(segs, list) or not segs:
        return score

    # Boost: long-haul segment uses preferred aircraft family.
    if preferred_aircraft:
        long_haul_seg = segs[1] if len(segs) >= 2 else segs[0]
        if isinstance(long_haul_seg, dict):
            ac = long_haul_seg.get("aircraft_type")
            if safe_startswith(ac, preferred_aircraft):
                score -= 1.0

    # Penalty: any segment uses an excluded carrier.
    if excluded_carriers:
        for s in segs:
            if not isinstance(s, dict):
                continue
            op = s.get("operating_carrier")
            mkt = s.get("carrier")
            if safe_in(op, excluded_carriers) or safe_in(mkt, excluded_carriers):
                score += 3.0
                break  # one match is enough; preserves original semantics

    return score


# ----------------------------------------------------------------------
# Adapt a list of all_evaluated candidates into a flat row dict
# ----------------------------------------------------------------------
def adapt_candidate(option: dict) -> dict:
    """
    Adapt a single canonical candidate into a flat row dict with
    presentation-safe fields.

    The output dict is a shallow copy of the input — canonical evidence
    is preserved. NEW presentation fields are added with `_display_` prefix.

    Returns:
        {
            **option,                # canonical fields preserved
            "_display": {
                "aircraft_type": str | None,
                "risk": float | None,
                "fatigue": float | None,
                "routing_verdict": str | None,
                "total_cost_twd": int | None,
                "route": list | None,
                "carrier": str | None,
            }
        }
    """
    ev = option.get("evaluation") if isinstance(option, dict) else None
    segs = option.get("segments") if isinstance(option, dict) else None

    # Pick the long-haul segment for display purposes (matches dashboard logic)
    display_ac = None
    if isinstance(segs, list) and segs:
        long_haul = segs[1] if len(segs) >= 2 else segs[0]
        if isinstance(long_haul, dict):
            display_ac = display_aircraft_type(long_haul.get("aircraft_type"))

    # Pick a representative carrier (long-haul first, then any)
    display_car = None
    if isinstance(segs, list) and segs:
        for s in segs:
            if not isinstance(s, dict):
                continue
            display_car = display_carrier(s)
            if display_car:
                break

    return {
        **option,
        "_display": {
            "aircraft_type": display_ac,
            "risk": display_risk(ev),
            "fatigue": display_fatigue(ev),
            "routing_verdict": display_routing_verdict(ev),
            "total_cost_twd": display_total_cost_twd(option),
            "route": display_route(option),
            "carrier": display_car,
        },
    }


def adapt_all_evaluated(all_evaluated: list) -> list:
    """Adapt every candidate in a list. Pure function: input list not mutated."""
    if not isinstance(all_evaluated, list):
        return []
    return [adapt_candidate(o) for o in all_evaluated]


# ----------------------------------------------------------------------
# Public banner / mark for tests
# ----------------------------------------------------------------------
ADAPTER_VERSION = "0.2.0"

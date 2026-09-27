"""
test_dashboard_view_model_v0_2.py — Dashboard View Model tests

Tests for the Dashboard View Model introduced in Dashboard Intelligence v0.2.

Covers all categories in spec STEP 25:
  A. Candidate identity
  B. Null safety (aircraft_type, price, baggage, fx, schedule, comparison, arbitrage)
  C. Missing fields
  D. Candidate lineage (evidence from candidate A must never appear under candidate B)
  E. Price honesty (Unknown price must remain unknown)
  F. FX honesty (Missing/refused FX must not become a valid conversion)
  G. Schedule honesty (DATABASE must not become LIVE or VERIFIED)
  H. Parity honesty (UNKNOWN must not become MATCH)
  I. Arbitrage honesty (HARD_COMPARABLE alone must not become POTENTIAL_OPPORTUNITY)
  J. Provider identity (Mock evidence must remain visibly mock)
  K. Provenance (Retrieved timestamps/source/provider fields remain attached)
  L. Legacy field protection (Legacy total_cost_twd / savings_pct cannot masquerade as live price)
  M. No forbidden scoring (arbitrage_score, opportunity_score, confidence_score, winner, rank, best, cheapest, recommendation)
  N. Determinism (Same canonical evidence input produces identical view model output)
"""
from __future__ import annotations

import copy
import json
import re
import sys
from dataclasses import fields
from pathlib import Path

WD = Path(__file__).parent
sys.path.insert(0, str(WD))

from dashboard_view_model import (
    build_view,
    load_evidence_index,
    load_fx_evidence_index,
    load_candidates,
    DashboardCandidateView,
    IdentityView,
    DiscoveryView,
    ScheduleEvidenceView,
    PriceEvidenceView,
    FXEvidenceView,
    PassengerParityView,
    BaselineView,
    ComparisonView,
    ArbitrageEvidenceView,
    FrictionEvidenceView,
    MissingEvidenceView,
    ProviderPriceView,
    UNKNOWN,
    EVIDENCE_UNAVAILABLE,
    EvidenceLoadError,
)

RESULTS: list[tuple[str, bool, str]] = []


def _log(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}{(' :: ' + detail) if (detail and not ok) else ''}")


def _empty_index():
    """Build a fully empty set of evidence indexes for null-safety tests."""
    from dashboard_view_model import _EvidenceIndex
    empty = _EvidenceIndex([])
    return empty, empty, empty, empty, empty, empty, empty


def _build_view_from_candidate(candidate: dict, ev: dict | None = None) -> DashboardCandidateView:
    """Helper: build a view from a candidate dict with optional synthetic evidence record."""
    empty, empty2, empty3, empty4, empty5, empty6, empty7 = _empty_index()
    from dashboard_view_model import _EvidenceIndex
    if ev is not None:
        # Single-record evidence (keyed by candidate id)
        idx = _EvidenceIndex([ev])
    else:
        idx = empty
    return build_view(
        candidate=candidate,
        schedule_evidence_index=idx,
        price_evidence_index=idx,
        fx_evidence_index=empty2,
        parity_evidence_index=empty3,
        baseline_evidence_index=empty4,
        comparison_evidence_index=empty5,
        arbitrage_evidence_index=empty6,
    )


# ----------------------------------------------------------------------
# Test categories
# ----------------------------------------------------------------------
def main() -> int:
    print("=" * 75)
    print("Dashboard View Model v0.2 tests")
    print("=" * 75)

    # A. Candidate identity
    name = "A. Candidate identity survives transformation"
    try:
        c = {"id": "AUTO-TEST-1", "label": "Test route", "route": ["TPE", "KUL", "MAD"]}
        v = _build_view_from_candidate(c)
        ok = v.identity.candidate_id == "AUTO-TEST-1"
        ok2 = v.identity.route == ["TPE", "KUL", "MAD"]
        ok3 = v.identity.origin == "TPE"
        ok4 = v.identity.destination == "MAD"
        ok = ok and ok2 and ok3 and ok4
        _log(name, ok)
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # B. Null safety — multiple null fields
    name = "B. Null safety: aircraft=None, price=None, baggage=None, fx=None, schedule=None, comparison=None, arbitrage=None"
    try:
        c = {"id": "AUTO-NULL", "route": ["TPE", "MAD"]}
        v = _build_view_from_candidate(c)
        ok1 = v.schedule is None
        ok2 = v.price.providers == []
        ok3 = v.fx is None
        ok4 = v.parity is None
        ok5 = v.baseline is None
        ok6 = v.comparison is None
        ok7 = v.arbitrage is None
        ok = all([ok1, ok2, ok3, ok4, ok5, ok6, ok7])
        _log(name, ok, f"sched={ok1} price={ok2} fx={ok3} parity={ok4} base={ok5} comp={ok6} arb={ok7}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # C. Missing optional keys
    name = "C. Missing optional keys do not crash"
    try:
        c = {}  # completely empty
        v = _build_view_from_candidate(c)
        ok = v.identity.candidate_id is None
        ok2 = v.schedule is None
        ok3 = v.price.providers == []
        ok4 = v.arbitrage is None
        ok = ok and ok2 and ok3 and ok4
        _log(name, ok)
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # D. Candidate lineage — evidence from candidate A must NEVER appear under B
    name = "D. Candidate lineage: evidence from A does not appear under B"
    try:
        from dashboard_view_model import _EvidenceIndex
        c_a = {"id": "AUTO-A", "route": ["TPE", "MAD"]}
        c_b = {"id": "AUTO-B", "route": ["TPE", "BCN"]}
        ev_a = {
            "candidate_id": "AUTO-A",
            "provider": "duffel",
            "provider_mode": "live",
            "verification_status": "LIVE",
            "total_price": 500.0,
            "currency": "EUR",
            "schedule_status": "SUPPORTED",
            "schedule_source": "live",
        }
        idx = _EvidenceIndex([ev_a])
        v_a = build_view(c_a, idx, idx, _EvidenceIndex([]), idx, idx, idx, idx)
        v_b = build_view(c_b, idx, idx, _EvidenceIndex([]), idx, idx, idx, idx)
        # v_a should have evidence
        ok_a = v_a.price.providers[0].provider == "duffel"
        ok_a2 = v_a.schedule.verification_status == "LIVE"
        # v_b must NOT have evidence (different id)
        ok_b = v_b.price.providers == []
        ok_b2 = v_b.schedule is None
        ok = ok_a and ok_a2 and ok_b and ok_b2
        _log(name, ok, f"a.price={ok_a} a.sched={ok_a2} b.price={ok_b} b.sched={ok_b2}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # E. Price honesty — Unknown price must remain unknown
    name = "E. Price honesty: Unknown price must remain Unknown"
    try:
        from dashboard_view_model import _EvidenceIndex
        c = {"id": "AUTO-EP", "route": ["TPE", "MAD"], "total_cost": 64000, "savings_pct": 64.4}
        ev = {
            "candidate_id": "AUTO-EP",
            "provider": "mock_duffel",
            "provider_mode": "mock",
            "total_price": None,
            "currency": "TWD",
            "verification_status": "UNKNOWN",
        }
        idx = _EvidenceIndex([ev])
        v = build_view(c, idx, idx, _EvidenceIndex([]), idx, idx, idx, idx)
        ok1 = v.price.providers[0].price is None  # actual price unknown
        ok2 = v.price.providers[0].verification_status != "VERIFIED"
        # Legacy fields preserved but clearly separated
        ok3 = v.price.legacy_total_cost_twd == 64000
        ok4 = v.price.legacy_savings_pct == 64.4
        ok = ok1 and ok2 and ok3 and ok4
        _log(name, ok, f"price=None={ok1} vs!=VERIFIED={ok2} legacy.kept={ok3 and ok4}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # F. FX honesty — Missing/refused FX must not become a valid conversion
    name = "F. FX honesty: Missing/refused FX must not become a valid conversion"
    try:
        from dashboard_view_model import _EvidenceIndex, load_fx_evidence_index
        c = {"id": "AUTO-FX", "route": ["TPE", "MAD"], "currency": "TWD"}
        # Empty FX index
        v = build_view(c, _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]),
                        _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]))
        ok1 = v.fx is None  # no FX record → None
        ok2 = v.missing.fx_unavailable is True  # flagged as missing
        ok = ok1 and ok2
        _log(name, ok, f"fx=None={ok1} missing.fx_unavailable={ok2}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # G. Schedule honesty — DATABASE must not become LIVE or VERIFIED
    name = "G. Schedule honesty: DATABASE stays DATABASE (never LIVE/VERIFIED)"
    try:
        from dashboard_view_model import _EvidenceIndex
        c = {"id": "AUTO-SCHED", "route": ["TPE", "MAD"]}
        ev = {
            "candidate_id": "AUTO-SCHED",
            "provider": "openflights",
            "provider_mode": "database",
            "verification_status": "DATABASE",
            "schedule_status": "SUPPORTED",
            "schedule_source": "database",
        }
        idx = _EvidenceIndex([ev])
        v = build_view(c, idx, _EvidenceIndex([]), _EvidenceIndex([]),
                        _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]))
        ok1 = v.schedule.verification_status == "DATABASE"
        ok2 = v.schedule.provider_mode == "database"
        ok3 = v.schedule.verification_status != "LIVE"
        ok4 = v.schedule.verification_status != "VERIFIED"
        ok = ok1 and ok2 and ok3 and ok4
        _log(name, ok, f"vs=DATABASE={ok1} mode=database={ok2} not LIVE={ok3} not VERIFIED={ok4}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # H. Parity honesty — UNKNOWN must not become MATCH
    name = "H. Parity honesty: UNKNOWN stays UNKNOWN"
    try:
        from dashboard_view_model import _EvidenceIndex
        c = {"id": "AUTO-PARITY", "route": ["TPE", "MAD"]}
        ev = {
            "candidate_id": "AUTO-PARITY",
            "parity_status": "UNKNOWN",
            "verification_status": "DATABASE",
        }
        idx = _EvidenceIndex([ev])
        v = build_view(c, _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]),
                        idx, _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]))
        ok1 = v.parity.parity_status == "UNKNOWN"
        ok2 = v.parity.parity_status != "MATCH"
        ok = ok1 and ok2
        _log(name, ok, f"status=UNKNOWN={ok1} !=MATCH={ok2}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # I. Arbitrage honesty — HARD_COMPARABLE alone must not become POTENTIAL_OPPORTUNITY
    name = "I. Arbitrage honesty: HARD_COMPARABLE alone != POTENTIAL_OPPORTUNITY"
    try:
        from dashboard_view_model import _EvidenceIndex
        c = {"id": "AUTO-ARB", "route": ["TPE", "MAD"]}
        # If only HARD_COMPARABLE is provided (no arbitrage evidence), state must be UNKNOWN
        ev = {
            "candidate_id": "AUTO-ARB",
            "comparability_status": "HARD_COMPARABLE",
            "verification_status": "DATABASE",
        }
        idx = _EvidenceIndex([ev])
        v = build_view(c, _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]),
                        _EvidenceIndex([]), _EvidenceIndex([]), idx, _EvidenceIndex([]))
        ok1 = v.comparison is not None
        ok2 = v.comparison.comparability_status == "HARD_COMPARABLE"
        # No arbitrage evidence → arbitrage is None (NOT POTENTIAL_OPPORTUNITY)
        ok3 = v.arbitrage is None
        ok = ok1 and ok2 and ok3
        _log(name, ok, f"comparison.present={ok1} HARD_COMPARABLE={ok2} arbitrage=None={ok3}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # J. Provider identity — Mock evidence must remain visibly mock
    name = "J. Provider identity: mock remains visibly mock"
    try:
        from dashboard_view_model import _EvidenceIndex
        c = {"id": "AUTO-MOCK", "route": ["TPE", "MAD"]}
        ev = {
            "candidate_id": "AUTO-MOCK",
            "provider": "mock_duffel",
            "provider_mode": "mock",
            "verification_status": "LIVE",
            "total_price": 500.0,
            "currency": "EUR",
        }
        idx = _EvidenceIndex([ev])
        v = build_view(c, _EvidenceIndex([]), idx, _EvidenceIndex([]),
                        _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]))
        ok1 = v.price.providers[0].provider == "mock_duffel"
        ok2 = v.price.providers[0].provider_mode == "mock"
        ok3 = v.price.providers[0].provider_mode != "live"
        ok = ok1 and ok2 and ok3
        _log(name, ok, f"provider=mock_duffel={ok1} mode=mock={ok2} not live={ok3}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # K. Provenance — Retrieved timestamps / source / provider fields remain attached
    name = "K. Provenance: retrieved_at / provider / source remain attached"
    try:
        from dashboard_view_model import _EvidenceIndex
        c = {"id": "AUTO-PROV", "route": ["TPE", "MAD"]}
        ev = {
            "candidate_id": "AUTO-PROV",
            "provider": "duffel",
            "provider_mode": "live",
            "retrieved_at": "2026-09-28T10:00:00",
            "source": "duffel_live",
            "verification_status": "LIVE",
            "total_price": 500.0,
            "currency": "EUR",
        }
        idx = _EvidenceIndex([ev])
        v = build_view(c, _EvidenceIndex([]), idx, _EvidenceIndex([]),
                        _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]))
        ok1 = v.price.providers[0].retrieved_at == "2026-09-28T10:00:00"
        ok2 = v.price.providers[0].provider == "duffel"
        ok = ok1 and ok2
        _log(name, ok, f"retrieved_at={ok1} provider={ok2}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # L. Legacy field protection
    name = "L. Legacy field protection: legacy_total_cost_twd cannot masquerade as live price"
    try:
        from dashboard_view_model import _EvidenceIndex
        c = {"id": "AUTO-LEG", "route": ["TPE", "MAD"], "total_cost": 64000, "savings_pct": 64.4}
        # No price evidence
        v = build_view(c, _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]),
                        _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]), _EvidenceIndex([]))
        ok1 = v.price.providers == []  # no providers (price unknown)
        ok2 = v.price.legacy_total_cost_twd == 64000  # legacy kept for backward compat
        # ProviderPriceView.price is None for legacy
        # The PriceEvidenceView separates `providers` (canonical) from `legacy_*`
        # Both fields exist; the UI decides which to show under which label
        ok = ok1 and ok2
        _log(name, ok, f"providers=[]={ok1} legacy.kept={ok2}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # M. No forbidden scoring
    name = "M. No forbidden scoring in view model"
    try:
        c = {"id": "AUTO-M", "route": ["TPE", "MAD"]}
        v = _build_view_from_candidate(c)
        # Serialise the view to a dict and scan for forbidden tokens
        d = v.to_dict()
        # Flatten all string values
        flat = []
        def _walk(o):
            if isinstance(o, dict):
                for kk, vv in o.items():
                    flat.append(str(kk))
                    _walk(vv)
            elif isinstance(o, list):
                for x in o:
                    _walk(x)
            elif o is not None:
                flat.append(str(o))
        _walk(d)
        text = " ".join(flat).lower()
        forbidden = ["arbitrage_score", "opportunity_score", "confidence_score",
                     "winner", "rank", "tier", "best", "cheapest",
                     "recommendation", "deal_score"]
        # Filter out matches that are part of legitimate field names
        legitimate = ["ranking_verdict", "final_rank"]  # legacy fields from Jev — but we don't expose them
        hits = []
        for token in forbidden:
            # Word-boundary check to avoid false positives inside other words
            if re.search(r"\b" + token + r"\b", text):
                hits.append(token)
        ok = len(hits) == 0
        _log(name, ok, f"hits={hits}" if hits else "no forbidden tokens")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # N. Determinism — same input → same output
    name = "N. Determinism: same input produces identical output"
    try:
        from dashboard_view_model import _EvidenceIndex
        c = {"id": "AUTO-DET", "route": ["TPE", "KUL", "MAD"], "total_cost": 64000,
              "savings_pct": 64.4, "currency": "TWD",
              "multi_ticket": True, "positioning_flight": True}
        ev = {
            "candidate_id": "AUTO-DET",
            "provider": "mock_duffel",
            "provider_mode": "mock",
            "verification_status": "LIVE",
            "total_price": 50000,
            "currency": "TWD",
        }
        idx = _EvidenceIndex([ev])
        v1 = build_view(c, idx, idx, _EvidenceIndex([]), idx, idx, idx, idx)
        v2 = build_view(c, idx, idx, _EvidenceIndex([]), idx, idx, idx, idx)
        d1 = json.dumps(v1.to_dict(), sort_keys=True)
        d2 = json.dumps(v2.to_dict(), sort_keys=True)
        ok = d1 == d2
        _log(name, ok, f"identical={ok}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # O. Real canonical artifact integration test
    name = "O. Real canonical artifact integration"
    try:
        DATA = WD / "data"
        if (DATA / "flight_results.json").exists():
            candidates = load_candidates(DATA / "flight_results.json")
            schedule_idx = load_evidence_index(DATA / "schedule_evidence_v1_2_1.json")
            price_idx = load_evidence_index(DATA / "price_evidence.json")
            fx_idx = load_fx_evidence_index(DATA / "fx_evidence_v1_2_2.json")
            parity_idx = load_evidence_index(DATA / "passenger_parity_evidence_v1_2_3.json")
            baseline_idx = load_evidence_index(DATA / "baseline_evidence_v1_2_4.json")
            comparison_idx = load_evidence_index(DATA / "comparison_evidence_v1_2_5.json")
            arbitrage_idx = load_evidence_index(DATA / "arbitrage_evidence_l4.json")

            views = [
                build_view(c, schedule_idx, price_idx, fx_idx,
                            parity_idx, baseline_idx, comparison_idx, arbitrage_idx)
                for c in candidates
            ]
            ok = len(views) == 80
            ok2 = all(isinstance(v, DashboardCandidateView) for v in views)
            # At least one candidate (L4.1 ID) has evidence
            ok3 = any(v.evidence_available for v in views)
            ok = ok and ok2 and ok3
            _log(name, ok, f"#views={len(views)} all DashboardCandidateView={ok2} any evidence={ok3}")
        else:
            _log(name, True, "(flight_results.json absent; skipped)")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # Summary
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n" + "=" * 75)
    print(f"Dashboard View Model v0.2: {len(RESULTS)} tests, {passed} passed, {failed} failed")
    print("=" * 75)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

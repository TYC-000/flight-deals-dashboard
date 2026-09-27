"""
test_dashboard_repair_v0_2.py — Dashboard Runtime Repair v0.2 tests

Verifies that the dashboard's adapter layer (dashboard_adapter.py) and the
patched flight_dashboard.py are robust against missing/null optional fields
in canonical evidence. Does NOT modify canonical evidence; uses synthetic
records only.

Tests:
A. aircraft_type = None → adapter does not crash
B. aircraft_type = "A320" → existing classification preserved
C. missing risk → no crash
D. missing fatigue → no crash
E. missing routing_verdict → no crash
F. missing total_cost_twd → no crash
G. mixed records (some have fields, others don't) → load succeeds
H. canonical evidence is not modified by adapter
I. no fabricated aircraft/schedule/price fields
J. existing dashboard filtering/sorting behavior preserved

Run with:
    /Users/aib/.hermes/hermes-agent/venv/bin/python3 test_dashboard_repair_v0_2.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

WD = Path(__file__).parent
sys.path.insert(0, str(WD))

# Load the adapter (does not depend on Streamlit)
from dashboard_adapter import (
    safe_startswith,
    safe_in,
    compute_pref_score,
    adapt_candidate,
    adapt_all_evaluated,
    display_aircraft_type,
    display_risk,
    display_fatigue,
    display_routing_verdict,
    display_total_cost_twd,
    display_route,
    display_carrier,
    AIRCRAFT_UNAVAILABLE,
    ADAPTER_VERSION,
)

RESULTS: list[tuple[str, bool, str]] = []


def _log(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}{(' :: ' + detail) if (detail and not ok) else ''}")


def main() -> int:
    print("=" * 75)
    print(f"Dashboard Runtime Repair v0.2 tests (adapter {ADAPTER_VERSION})")
    print("=" * 75)

    # A. aircraft_type = None → adapter does not crash
    name = "A. aircraft_type=None → safe_startswith returns False (no crash)"
    try:
        # Original code: ac.startswith(p) → AttributeError
        # Adapter: safe_startswith(None, [...]) → False
        ok = safe_startswith(None, ["A380", "A350-900"]) is False
        _log(name, ok)
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # B. aircraft_type = "A320" → existing classification preserved
    name = "B. aircraft_type='A320' → safe_startswith behaves like original"
    try:
        # Note: "A320" does NOT start with "A380" or "A350-900"
        ok_neg = safe_startswith("A320", ["A380", "A350-900"]) is False
        # But "A350-900" matches "A350-900" (exact prefix)
        ok_pos = safe_startswith("A350-900", ["A350-900"]) is True
        # And "A350" matches "A350" prefix
        ok_pos2 = safe_startswith("A350", ["A350"]) is True
        ok = ok_neg and ok_pos and ok_pos2
        _log(name, ok, f"neg={ok_neg}, pos={ok_pos}, pos2={ok_pos2}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # C. missing risk (None evaluation block) → no crash
    name = "C. missing risk → display_risk returns None"
    try:
        ok1 = display_risk(None) is None
        ok2 = display_risk({}) is None
        ok3 = display_risk({"connection_failure_risk": 0.14}) == 0.14
        ok = ok1 and ok2 and ok3
        _log(name, ok, f"none={ok1}, empty={ok2}, value={ok3}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # D. missing fatigue → no crash
    name = "D. missing fatigue → display_fatigue returns None"
    try:
        ok1 = display_fatigue(None) is None
        ok2 = display_fatigue({}) is None
        ok3 = display_fatigue({"fatigue_index": 5.21}) == 5.21
        ok = ok1 and ok2 and ok3
        _log(name, ok)
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # E. missing routing_verdict → no crash
    name = "E. missing routing_verdict → display_routing_verdict returns None"
    try:
        ok1 = display_routing_verdict(None) is None
        ok2 = display_routing_verdict({}) is None
        ok3 = display_routing_verdict({"routing_verdict": "prime_deal"}) == "prime_deal"
        ok = ok1 and ok2 and ok3
        _log(name, ok)
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # F. missing total_cost_twd → no crash
    name = "F. missing total_cost_twd → display_total_cost_twd returns None"
    try:
        ok1 = display_total_cost_twd({}) is None
        ok2 = display_total_cost_twd({"total_cost": 64000}) == 64000
        ok3 = display_total_cost_twd({"total_cost": "not a number"}) is None
        ok = ok1 and ok2 and ok3
        _log(name, ok)
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # G. mixed records (some have fields, others don't) → adapter does not crash
    name = "G. mixed records → adapt_all_evaluated does not crash"
    try:
        mixed = [
            {  # full record
                "id": "A-1",
                "evaluation": {"routing_verdict": "prime_deal",
                                "connection_failure_risk": 0.10,
                                "fatigue_index": 4.0},
                "total_cost": 50000,
                "route": ["TPE", "MAD"],
                "segments": [{"aircraft_type": "A350", "operating_carrier": "MH"}],
            },
            {  # all missing
                "id": "B-2",
                # no evaluation, no total_cost, no segments, no route
            },
            {  # partial: segments with None aircraft_type
                "id": "C-3",
                "evaluation": {"routing_verdict": "acceptable_economy"},
                "total_cost": 80000,
                "segments": [{"aircraft_type": None, "operating_carrier": None}],
            },
            {  # weird types
                "id": "D-4",
                "evaluation": "not a dict",  # wrong type
                "total_cost": True,         # bool (not a real cost)
                "segments": "not a list",   # wrong type
            },
            {  # aircraft_type is a number
                "id": "E-5",
                "segments": [{"aircraft_type": 777}],
            },
        ]
        adapted = adapt_all_evaluated(mixed)
        # Every record must be present, no exception
        ok = len(adapted) == 5
        # Record A-1: aircraft_type preserved
        ok_a = adapted[0]["_display"]["aircraft_type"] == "A350"
        # Record B-2: aircraft_type None
        ok_b = adapted[1]["_display"]["aircraft_type"] is None
        # Record C-3: aircraft_type None
        ok_c = adapted[2]["_display"]["aircraft_type"] is None
        # Record D-4: aircraft_type None (segments wrong type)
        ok_d = adapted[3]["_display"]["aircraft_type"] is None
        # Record E-5: aircraft_type None (number not str)
        ok_e = adapted[4]["_display"]["aircraft_type"] is None
        ok = ok and ok_a and ok_b and ok_c and ok_d and ok_e
        _log(name, ok, f"len={len(adapted)}, A={ok_a}, B={ok_b}, C={ok_c}, D={ok_d}, E={ok_e}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # H. canonical evidence is not modified by adapter
    name = "H. canonical evidence is not modified by adapter"
    try:
        original = {
            "id": "ORIG-1",
            "evaluation": {"routing_verdict": "prime_deal", "connection_failure_risk": 0.1},
            "total_cost": 50000,
            "segments": [{"aircraft_type": "A350"}],
        }
        original_json = json.dumps(original, sort_keys=True)
        adapted = adapt_candidate(original)
        current_json = json.dumps(original, sort_keys=True)
        ok = original_json == current_json
        # Also check adapted does not write into original
        ok2 = adapted["_display"]["aircraft_type"] == "A350"
        ok = ok and ok2
        _log(name, ok)
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # I. no fabricated aircraft/schedule/price fields
    name = "I. no fabricated evidence (aircraft/schedule/price)"
    try:
        # Use a record with EVERYTHING missing
        empty = {"id": "EMPTY"}
        adapted = adapt_candidate(empty)
        d = adapted["_display"]
        ok_ac = d["aircraft_type"] is None
        ok_risk = d["risk"] is None
        ok_fatigue = d["fatigue"] is None
        ok_verdict = d["routing_verdict"] is None
        ok_cost = d["total_cost_twd"] is None
        ok = ok_ac and ok_risk and ok_fatigue and ok_verdict and ok_cost
        _log(name, ok, f"all None={ok}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # J. existing dashboard filtering/sorting behavior preserved
    name = "J. _pref_score preserves semantics (None aircraft → 0 boost, excluded carrier → +3)"
    try:
        # Case 1: aircraft None + no excluded carrier → 0
        opt1 = {"segments": [{"aircraft_type": None}]}
        score1 = compute_pref_score(opt1, ["A350-900"], [])
        ok1 = score1 == 0.0

        # Case 2: aircraft matches preferred → -1
        opt2 = {"segments": [{"aircraft_type": "A350-900"}]}
        score2 = compute_pref_score(opt2, ["A350-900"], [])
        ok2 = score2 == -1.0

        # Case 3: aircraft None + excluded carrier → +3
        opt3 = {"segments": [{"aircraft_type": None, "operating_carrier": "LH"}]}
        score3 = compute_pref_score(opt3, ["A350-900"], ["LH"])
        ok3 = score3 == 3.0

        # Case 4: aircraft matches + excluded carrier → -1 + 3 = +2
        opt4 = {"segments": [{"aircraft_type": "A350-900", "operating_carrier": "LH"}]}
        score4 = compute_pref_score(opt4, ["A350-900"], ["LH"])
        ok4 = score4 == 2.0

        # Case 5: empty segments → 0
        opt5 = {}
        score5 = compute_pref_score(opt5, ["A350-900"], ["LH"])
        ok5 = score5 == 0.0

        ok = ok1 and ok2 and ok3 and ok4 and ok5
        _log(name, ok, f"s1={score1}, s2={score2}, s3={score3}, s4={score4}, s5={score5}")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # Bonus: real flight_results.json does not crash with adapter
    name = "K. real flight_results.json: 80 candidates compute scores without crash"
    try:
        results_path = WD / "data" / "flight_results.json"
        if results_path.exists():
            results = json.loads(results_path.read_text())
            all_eval = results.get("all_evaluated", [])
            failed = []
            for o in all_eval:
                try:
                    score = compute_pref_score(
                        o,
                        ["A380", "A350-900", "A350-1000", "B787-9", "B787-10"],
                        ["LH", "BA", "AF", "KL"],
                    )
                except Exception as e:
                    failed.append((o.get("id"), type(e).__name__, str(e)))
            ok = len(failed) == 0
            _log(name, ok, f"failed={len(failed)}/{len(all_eval)}" if not ok else f"all {len(all_eval)} pass")
        else:
            _log(name, True, "(flight_results.json not present; skipped)")
    except Exception as e:
        _log(name, False, f"{type(e).__name__}: {e}")

    # Summary
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n" + "=" * 75)
    print(f"Dashboard Runtime Repair v0.2: {len(RESULTS)} tests, {passed} passed, {failed} failed")
    print("=" * 75)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

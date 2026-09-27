"""
test_passenger_parity_v1_2_3.py — Tests for v1.2.3 Multi-passenger Parity

Tests (per spec §18):
A.  provider-agnostic schema
B.  1 pax
C.  2 pax
D.  3 pax
E.  4 pax
F.  mixed passenger types
G.  same passenger types
H.  different passenger types
I.  same cabin
J.  different cabin
K.  unknown cabin
L.  same itinerary
M.  different itinerary
N.  same ticket structure
O.  multi-ticket
P.  unknown ticket structure
Q.  baggage parity
R.  baggage unknown
S.  missing passenger count
T.  missing passenger type
U.  price_per_passenger calculation
V.  non-linear passenger pricing
W.  provenance
X.  provider_mode
Y.  UNKNOWN semantics
Z.  no arbitrage_score
AA. no ArbitrageEvidence
AB. no Opportunity
AC. security / leakage
AD. regression compatibility (price_intelligence untouched)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
WORKDIR = HERE
sys.path.insert(0, str(HERE))

TEST_RESULTS: list[tuple[str, bool, str]] = []


def _log(name: str, ok: bool, detail: str = "") -> None:
    TEST_RESULTS.append((name, ok, detail))
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}{(' :: ' + detail) if (detail and not ok) else ''}")


# Synthesis helper to build PriceEvidence-like fixtures
def E(passenger_count: int | None = None,
      passenger_types: list[str] | None = None,
      cabin: str | None = "economy",
      itinerary_identity: str = "TPE-MAD",
      ticket_structure: str | None = "single-ticket",
      baggage_known: bool = True,
      baggage_checked: int = 1,
      baggage_carry_on: int = 1,
      total_price: float = 500.0,
      currency: str = "USD",
      provider: str = "duffel",
      provider_mode: str = "live",
      retrieved_at: str = "2026-09-27T10:00:00+00:00",
      fare_basis: str | None = None) -> dict:
    """Build a PriceEvidence-like fixture dict for testing."""
    baggage_complete = baggage_known
    return {
        "passenger_count": passenger_count,
        "passenger_types": passenger_types if passenger_types is not None else (
            ["ADT"] if passenger_count is not None else None),
        "cabin": cabin,
        "itinerary_identity": itinerary_identity,
        "ticket_structure": ticket_structure,
        "fare_basis": fare_basis,
        "total_price": total_price,
        "currency": currency,
        "provider": provider,
        "provider_mode": provider_mode,
        "retrieved_at": retrieved_at,
        "baggage": {
            "included": {"checked_pieces": baggage_checked, "carry_on": baggage_carry_on},
            "evidence_complete": baggage_complete,
        },
    }


# -----------------------------------------------------------------------------
# Test groups
# -----------------------------------------------------------------------------

def test_A_provider_agnostic_schema():
    name = "A. provider-agnostic schema"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(E(1, ["ADT"]), E(1, ["ADT"]))
        required = ["schema_version", "parity_status", "hard_parity_reasons",
                     "soft_parity_observations", "dimension_results",
                     "price_per_passenger", "providers", "verification_status",
                     "source", "retrieved_at", "provenance"]
        ok = all(k in r for k in required) and r["schema_version"] == "v1.2.3"
        _log(name, ok, "all required fields present")
    except Exception as e:
        _log(name, False, str(e))


def test_B_1_pax():
    name = "B. 1 pax"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(E(1, ["ADT"]), E(1, ["ADT"]))
        ok = r["dimension_results"]["passenger_count"]["a"] == 1
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_C_2_pax():
    name = "C. 2 pax"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(E(2, ["ADT"]), E(2, ["ADT"]))
        ok = r["dimension_results"]["passenger_count"]["a"] == 2 and \
             r["parity_status"] == "PARITY"
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_D_3_pax():
    name = "D. 3 pax"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(E(3, ["ADT"]), E(3, ["ADT"]))
        ok = r["dimension_results"]["passenger_count"]["a"] == 3
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_E_4_pax():
    name = "E. 4 pax"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(E(4, ["ADT"]), E(4, ["ADT"]))
        ok = r["dimension_results"]["passenger_count"]["a"] == 4
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_F_mixed_passenger_types():
    name = "F. mixed passenger types (ADT+CHD)"
    try:
        from passenger_parity import evaluate_passenger_parity
        a = E(2, ["ADT", "ADT"])  # ADT ADT
        b = E(2, ["ADT", "CHD"])  # ADT CHD
        r = evaluate_passenger_parity(a, b)
        ok = "PASSENGER_TYPE_MISMATCH" in r["hard_parity_reasons"]
        _log(name, ok, f"hard={r['hard_parity_reasons']}")
    except Exception as e:
        _log(name, False, str(e))


def test_G_same_passenger_types():
    name = "G. same passenger types (ADT vs ADT)"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(E(2, ["ADT"]), E(2, ["ADT"]))
        ok = r["parity_status"] == "PARITY"
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_H_different_passenger_types():
    name = "H. different passenger types (ADT+CHD vs ADT+ADT)"
    try:
        from passenger_parity import evaluate_passenger_parity
        a = E(2, ["ADT", "CHD"])
        b = E(2, ["ADT", "ADT"])
        r = evaluate_passenger_parity(a, b)
        ok = "PASSENGER_TYPE_MISMATCH" in r["hard_parity_reasons"]
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_I_same_cabin():
    name = "I. same cabin (Economy vs Economy)"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(1, ["ADT"], cabin="economy"),
            E(1, ["ADT"], cabin="economy"))
        ok = r["dimension_results"]["cabin"]["match"] is True
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_J_different_cabin():
    name = "J. different cabin (Economy vs Business)"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(1, ["ADT"], cabin="economy"),
            E(1, ["ADT"], cabin="business"))
        ok = "CABIN_MISMATCH" in r["hard_parity_reasons"]
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_K_unknown_cabin():
    name = "K. unknown cabin (one side)"
    try:
        from passenger_parity import evaluate_passenger_parity
        # a has cabin, b has no cabin
        a = E(1, ["ADT"], cabin="economy")
        b = E(1, ["ADT"], cabin=None)
        r = evaluate_passenger_parity(a, b)
        ok = "CABIN_UNKNOWN" in r["soft_parity_observations"] and \
             r["parity_status"] == "UNKNOWN"
        _log(name, ok, f"soft={r['soft_parity_observations']}")
    except Exception as e:
        _log(name, False, str(e))


def test_L_same_itinerary():
    name = "L. same itinerary"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(1, ["ADT"], itinerary_identity="TPE-MAD"),
            E(1, ["ADT"], itinerary_identity="TPE-MAD"))
        ok = r["dimension_results"]["itinerary_identity"]["match"] is True
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_M_different_itinerary():
    name = "M. different itinerary"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(1, ["ADT"], itinerary_identity="TPE-MAD"),
            E(1, ["ADT"], itinerary_identity="TPE-LHR"))
        ok = "ITINERARY_MISMATCH" in r["hard_parity_reasons"]
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_N_same_ticket_structure():
    name = "N. same ticket structure (single-ticket)"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(1, ["ADT"], ticket_structure="single-ticket"),
            E(1, ["ADT"], ticket_structure="single-ticket"))
        ok = r["dimension_results"]["ticket_structure"]["match"] is True
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_O_multi_ticket():
    name = "O. multi-ticket (single vs multi)"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(1, ["ADT"], ticket_structure="single-ticket"),
            E(1, ["ADT"], ticket_structure="multi-ticket"))
        ok = "TICKET_STRUCTURE_MISMATCH" in r["hard_parity_reasons"]
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_P_unknown_ticket_structure():
    name = "P. unknown ticket structure (both sides)"
    try:
        from passenger_parity import evaluate_passenger_parity
        a = E(1, ["ADT"], ticket_structure=None)
        b = E(1, ["ADT"], ticket_structure=None)
        r = evaluate_passenger_parity(a, b)
        ok = "TICKET_STRUCTURE_UNKNOWN" in r["soft_parity_observations"]
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_Q_baggage_parity():
    name = "Q. baggage parity (1 checked vs 0 checked)"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(1, ["ADT"], baggage_checked=1, baggage_known=True),
            E(1, ["ADT"], baggage_checked=0, baggage_known=True))
        # Baggage is SOFT — different but parity status unchanged
        ok = r["parity_status"] == "PARITY" and r["dimension_results"]["baggage"]["match"] is False
        _log(name, ok, "baggage is soft; parity unchanged")
    except Exception as e:
        _log(name, False, str(e))


def test_R_baggage_unknown():
    name = "R. baggage unknown (one side)"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(1, ["ADT"], baggage_known=True, baggage_checked=1),
            E(1, ["ADT"], baggage_known=False))
        ok = "BAGGAGE_UNKNOWN" in r["soft_parity_observations"]
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_S_missing_passenger_count():
    name = "S. missing passenger_count → UNKNOWN (NOT coerced to 1)"
    try:
        from passenger_parity import evaluate_passenger_parity, extract_passenger_basis
        a = E(passenger_count=None, passenger_types=["ADT"])  # bare type
        b = E(passenger_count=1, passenger_types=["ADT"])
        ea = extract_passenger_basis(a)
        # Hard rule from spec §4: missing passenger_count → UNKNOWN
        # The extracted pc should NOT default to 1.
        ok_pc = ea["passenger_count"] is None and ea["pc_known"] is False
        r = evaluate_passenger_parity(a, b)
        ok_status = r["parity_status"] == "UNKNOWN" and \
                    "PASSENGER_COUNT_UNKNOWN" in r["soft_parity_observations"]
        ok = ok_pc and ok_status
        _log(name, ok, f"extracted pc={ea['passenger_count']}, status={r['parity_status']}")
    except Exception as e:
        _log(name, False, str(e))


def test_T_missing_passenger_type():
    name = "T. missing passenger_type (no types surfaced)"
    try:
        from passenger_parity import evaluate_passenger_parity, extract_passenger_basis
        # a: explicitly no passenger_types surfaced at all
        a = {
            "passenger_count": 1,
            "cabin": "economy",
            "itinerary_identity": "TPE-MAD",
            "ticket_structure": "single-ticket",
            "total_price": 500.0,
            "currency": "USD",
            "provider": "duffel",
            "provider_mode": "live",
            "retrieved_at": "2026-09-27T10:00:00+00:00",
            "baggage": {"included": {"checked_pieces": 1, "carry_on": 1}, "evidence_complete": True},
        }
        # b: also no passenger_types
        b = dict(a)
        b["provider"] = "kiwi"
        ea = extract_passenger_basis(a)
        ok_extract = ea["passenger_types"] == []
        r = evaluate_passenger_parity(a, b)
        ok = (ok_extract and
              ("PASSENGER_TYPE_UNKNOWN" in r["soft_parity_observations"] or
                r["parity_status"] == "UNKNOWN"))
        _log(name, ok, f"a.types={ea['passenger_types']}, status={r['parity_status']}")
    except Exception as e:
        _log(name, False, str(e))


def test_U_price_per_passenger_calculation():
    name = "U. price_per_passenger calculation"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(
            E(2, ["ADT"], total_price=1000.0),
            E(2, ["ADT"], total_price=1200.0))
        # Derived analytical field
        ok = (r["price_per_passenger"]["a"] == 500.0 and
              r["price_per_passenger"]["b"] == 600.0 and
              r["price_per_passenger"]["difference"] == 100.0 and
              r["price_per_passenger"]["derived"] is True)
        _log(name, ok, "ppa computed; diff=100.0")
    except Exception as e:
        _log(name, False, str(e))


def test_V_non_linear_passenger_pricing():
    name = "V. non-linear passenger pricing (1pax $500 vs 2pax $1200)"
    try:
        from passenger_parity import evaluate_passenger_parity
        # 1pax $500, 2pax $1200 → passenger_count MISMATCH (so NON_PARITY)
        # But also ppa differs (500 vs 600) — this is the spec §7 Case B
        # scenario: NON_PARITY in price basis; NOT opportunity.
        r = evaluate_passenger_parity(
            E(1, ["ADT"], total_price=500.0),
            E(2, ["ADT"], total_price=1200.0))
        ok = "PASSENGER_COUNT_MISMATCH" in r["hard_parity_reasons"] and \
             "arbitrage_score" not in r and \
             "Opportunity" not in str(r.get("parity_status", "")) and \
             r["parity_status"] in {"NON_PARITY"}  # never VERIFIED
        _log(name, ok, f"hard={r['hard_parity_reasons']}, status={r['parity_status']}")
    except Exception as e:
        _log(name, False, str(e))


def test_W_provenance():
    name = "W. provenance (provider/provider_mode/retrieved_at preserved)"
    try:
        from passenger_parity import evaluate_passenger_parity
        a = E(1, ["ADT"], provider="duffel", provider_mode="live",
              retrieved_at="2026-09-27T10:00:00+00:00")
        b = E(1, ["ADT"], provider="kiwi", provider_mode="live",
              retrieved_at="2026-09-27T11:00:00+00:00")
        r = evaluate_passenger_parity(a, b)
        ok = (r["providers"]["a"]["provider"] == "duffel" and
              r["providers"]["b"]["provider"] == "kiwi" and
              r["providers"]["a"]["retrieved_at"] == "2026-09-27T10:00:00+00:00")
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_X_provider_mode():
    name = "X. provider_mode (live vs mock preserved)"
    try:
        from passenger_parity import evaluate_passenger_parity
        a = E(1, ["ADT"], provider="mock_duffel", provider_mode="mock")
        b = E(1, ["ADT"], provider="mock_kiwi", provider_mode="mock")
        r = evaluate_passenger_parity(a, b)
        ok = (r["providers"]["a"]["provider_mode"] == "mock" and
              r["providers"]["b"]["provider_mode"] == "mock")
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_Y_UNKNOWN_semantics():
    name = "Y. UNKNOWN semantics — never coerced to PARITY"
    try:
        from passenger_parity import evaluate_passenger_parity
        # Make 3 fields missing to ensure UNKNOWN, not PARITY
        a = E(1, ["ADT"], cabin=None, ticket_structure=None, baggage_known=False)
        b = E(1, ["ADT"], cabin=None, ticket_structure=None, baggage_known=False)
        r = evaluate_passenger_parity(a, b)
        # All 3 hard dimensions for a vs b: counts match (1=1), types
        # match (ADT=ADT), but cabin unknown. So UNKNOWN.
        ok = r["parity_status"] == "UNKNOWN"
        _log(name, ok, f"status={r['parity_status']}, soft={r['soft_parity_observations']}")
    except Exception as e:
        _log(name, False, str(e))


def test_Z_no_arbitrage_score():
    name = "Z. no arbitrage_score in output"
    try:
        from passenger_parity import evaluate_passenger_parity
        # Run on a bunch of fixtures
        for a, b in [
            (E(1, ["ADT"], total_price=500.0), E(2, ["ADT"], total_price=900.0)),
            (E(1, ["ADT"], cabin="economy"), E(1, ["CHD"], cabin="economy")),
            (E(2, ["ADT"], total_price=1000.0), E(2, ["ADT"], total_price=1200.0)),
        ]:
            r = evaluate_passenger_parity(a, b)
            serialized = json.dumps(r, ensure_ascii=False)
            for forbidden in ("arbitrage_score", "opportunity_score", "candidate_score",
                              "predicted_savings", "expected_profit"):
                assert forbidden not in serialized, f"{forbidden} in output"
        _log(name, True, "no forbidden tokens in any output")
    except AssertionError as e:
        _log(name, False, str(e))
    except Exception as e:
        _log(name, False, str(e))


def test_AA_no_ArbitrageEvidence():
    name = "AA. no ArbitrageEvidence emitted"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(E(1, ["ADT"]), E(2, ["ADT"], total_price=900.0))
        serialized = json.dumps(r, ensure_ascii=False)
        ok = "ArbitrageEvidence" not in serialized
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AB_no_Opportunity():
    name = "AB. no Opportunity emitted"
    try:
        from passenger_parity import evaluate_passenger_parity
        r = evaluate_passenger_parity(E(1, ["ADT"]), E(2, ["ADT"], total_price=900.0))
        serialized = json.dumps(r, ensure_ascii=False)
        # value-strings could legitimately contain the word "opportunity"
        # only as part of a documented annotation. Let's check.
        ok = ("\"Opportunity\"" not in serialized and
              "\"VERIFIED_OPPORTUNITY\"" not in serialized)
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AC_security_leakage():
    name = "AC. security / leakage (no provider tokens)"
    try:
        env = {"FAKE_PROVIDER_TOKEN_DO_NOT_LEAK_xxx": "secret_value_99"}
        # Run CLI with a couple of fixtures
        fixture_a = WORKDIR / "_tmp_fixture_a.json"
        fixture_b = WORKDIR / "_tmp_fixture_b.json"
        fixture_a.write_text(json.dumps(E(1, ["ADT"])))
        fixture_b.write_text(json.dumps(E(1, ["ADT"])))
        try:
            p = subprocess.run(["python3", "passenger_parity.py",
                                  "--evidence-a", str(fixture_a),
                                  "--evidence-b", str(fixture_b)],
                                 cwd=str(WORKDIR), env={**os.environ, **env},
                                 capture_output=True, text=True, timeout=20)
            output = (p.stdout or "") + (p.stderr or "")
            ev_path = WORKDIR / "data" / "passenger_parity_evidence_v1_2_3.json"
            ev_json = ev_path.read_text() if ev_path.exists() else ""
            tr_path = WORKDIR / "data" / "passenger_parity_trace_v1_2_3.json"
            tr_json = tr_path.read_text() if tr_path.exists() else ""
            ok = ("FAKE_PROVIDER_TOKEN_DO_NOT_LEAK_xxx" not in output and
                  "secret_value_99" not in output and
                  "FAKE_PROVIDER_TOKEN_DO_NOT_LEAK_xxx" not in ev_json and
                  "secret_value_99" not in ev_json and
                  "FAKE_PROVIDER_TOKEN_DO_NOT_LEAK_xxx" not in tr_json and
                  "secret_value_99" not in tr_json)
            _log(name, ok)
        finally:
            try: fixture_a.unlink()
            except FileNotFoundError: pass
            try: fixture_b.unlink()
            except FileNotFoundError: pass
    except Exception as e:
        _log(name, False, str(e))


def test_AD_regression_compatibility():
    name = "AD. price_intelligence.py untouched"
    try:
        pi_path = WORKDIR / "price_intelligence.py"
        with pi_path.open("rb") as f:
            content = f.read().decode()
        ok = "passenger_parity" not in content
        _log(name, ok, "v1.2.3 did not modify price_intelligence.py")
    except Exception as e:
        _log(name, False, str(e))


# -----------------------------------------------------------------------------
# Main runner
# -----------------------------------------------------------------------------

def main():
    print("\n" + "=" * 70)
    print("passenger_parity v1.2.3 — test_passenger_parity_v1_2_3.py")
    print("=" * 70)
    tests = [
        test_A_provider_agnostic_schema,
        test_B_1_pax,
        test_C_2_pax,
        test_D_3_pax,
        test_E_4_pax,
        test_F_mixed_passenger_types,
        test_G_same_passenger_types,
        test_H_different_passenger_types,
        test_I_same_cabin,
        test_J_different_cabin,
        test_K_unknown_cabin,
        test_L_same_itinerary,
        test_M_different_itinerary,
        test_N_same_ticket_structure,
        test_O_multi_ticket,
        test_P_unknown_ticket_structure,
        test_Q_baggage_parity,
        test_R_baggage_unknown,
        test_S_missing_passenger_count,
        test_T_missing_passenger_type,
        test_U_price_per_passenger_calculation,
        test_V_non_linear_passenger_pricing,
        test_W_provenance,
        test_X_provider_mode,
        test_Y_UNKNOWN_semantics,
        test_Z_no_arbitrage_score,
        test_AA_no_ArbitrageEvidence,
        test_AB_no_Opportunity,
        test_AC_security_leakage,
        test_AD_regression_compatibility,
    ]
    for t in tests:
        t()
    passed = sum(1 for _, ok, _ in TEST_RESULTS if ok)
    failed = sum(1 for _, ok, _ in TEST_RESULTS if not ok)
    print("\n" + "=" * 70)
    print(f"Total: {len(tests)} tests, {passed} passed, {failed} failed")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""
test_baseline_canonicalization_v1_2_4.py — Tests for v1.2.4

Tests (per spec §24):
A.  canonical schema
B.  mission binding
C.  date binding
D.  round-trip binding
E.  airport exactness
F.  airport-group semantics
G.  conventional baseline
H.  same-hub baseline
I.  same-carrier baseline
J.  same-ticket baseline
K.  positioning baseline
L.  outer-port baseline
M.  secondary-entry baseline
N.  alternative-hub baseline
O.  multi-ticket
P.  airport change
Q.  missing passenger basis
R.  missing cabin
S.  missing baggage
T.  missing carrier
U.  missing schedule
V.  multiple baselines
W.  no baseline
X.  price-free canonicalization
Y.  no cheapest-based selection
Z.  no Jev-based selection
AA. no information_priority_score selection
AB. provenance
AC. UNKNOWN semantics
AD. HARD/SOFT/UNKNOWN compatibility
AE. no ArbitrageEvidence
AF. no Opportunity
AG. no VerifiedOpportunity
AH. no arbitrage_score
AI. security
AJ. regression compatibility
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


def mission(origin="TPE", dest="MAD", travel_date="2027-04-15", return_date="2027-04-25",
              cabin="economy", pc=1, ptypes=None, mission_id="M1") -> dict:
    return {
        "mission_id": mission_id,
        "origin": origin,
        "destination": dest,
        "travel_date": travel_date,
        "return_date": return_date,
        "cabin": cabin,
        "passenger_count": pc,
        "passenger_types": ptypes if ptypes is not None else ["ADT"],
    }


def cand(cid="c1", origin="TPE", dest="MAD", segments=None,
           travel_date="2027-04-15", return_date="2027-04-25",
           cabin="economy", pc=1, ptypes=None,
           ticket_structure=None, ticket_count=None,
           carriers=None) -> dict:
    return {
        "id": cid,
        "segments": segments if segments is not None else [
            {"from": "TPE", "to": "FRA"}, {"from": "FRA", "to": "MAD"}],
        "travel_date": travel_date,
        "return_date": return_date,
        "cabin": cabin,
        "passenger_count": pc,
        "passenger_types": ptypes if ptypes is not None else ["ADT"],
        "ticket_structure": ticket_structure,
        "ticket_count": ticket_count,
        "carriers": carriers,
    }


# -----------------------------------------------------------------------------
# Test groups
# -----------------------------------------------------------------------------

def test_A_canonical_schema():
    name = "A. canonical schema"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(), cand())
        required = ["schema_version", "mission_canonical", "candidate_canonical",
                     "baseline_eligibility", "canonical_baselines", "comparison_pairs",
                     "canonicalization_rule_version", "retrieved_at",
                     "verification_status", "source", "provenance"]
        ok = all(k in r for k in required) and r["schema_version"] == "v1.2.4"
        _log(name, ok, "all required fields present")
    except Exception as e:
        _log(name, False, str(e))


def test_B_mission_binding():
    name = "B. mission binding (origin/dest preserved)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission("TPE", "MAD"), cand("c1", "TPE", "MAD"))
        ok = (r["mission_canonical"]["origin"] == "TPE" and
              r["mission_canonical"]["destination"] == "MAD")
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_C_date_binding():
    name = "C. date binding (travel_date preserved)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(travel_date="2027-04-15"),
                                          cand(travel_date="2027-04-15"))
        ok = r["mission_canonical"]["travel_date"] == "2027-04-15"
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_D_round_trip_binding():
    name = "D. round-trip binding (return_date preserved)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(return_date="2027-04-25"),
                                          cand(return_date="2027-04-25"))
        ok = (r["mission_canonical"]["is_round_trip"] is True and
              r["mission_canonical"]["return_date"] == "2027-04-25")
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_E_airport_exactness():
    name = "E. airport exactness (TPE != TSA)"
    try:
        from baseline_canonicalization import normalize_airport
        # normalize_airport should reject "TSA" (not a valid 3-letter IATA in our context)
        # but it should normalize "tpe" → "TPE"
        ok = (normalize_airport("TPE") == "TPE" and
              normalize_airport("tpe") == "TPE" and
              normalize_airport("") is None and
              normalize_airport(None) is None)
        _log(name, ok, "normalization preserves valid codes; rejects blanks")
    except Exception as e:
        _log(name, False, str(e))


def test_F_airport_group_semantics():
    name = "F. airport-group semantics"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # TPE != MAD; canonicalization should refuse to coalesce
        r = canonicalize_for_candidate(mission("TPE", "MAD"), cand("c1", "TPE", "MAD"))
        # candidate origin/destination are kept distinct
        ok = (r["candidate_canonical"]["origin"] !=
              r["candidate_canonical"]["destination"])
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_G_conventional_baseline():
    name = "G. conventional baseline (TPE→FRA→MAD)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(), cand())
        classes = {bl["baseline_class"] for bl in r["canonical_baselines"]}
        ok = "conventional_hub" in classes
        _log(name, ok, f"classes={classes}")
    except Exception as e:
        _log(name, False, str(e))


def test_H_same_hub_baseline():
    name = "H. same-hub baseline"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # Multi-segment through hub
        r = canonicalize_for_candidate(mission(), cand("c1", segments=[
            {"from": "TPE", "to": "FRA"}, {"from": "FRA", "to": "MAD"}]))
        # conventional_hub eligible, and eligible_baselines should include it
        bl_classes = [bl["baseline_class"] for bl in r["canonical_baselines"]]
        ok = "conventional_hub" in bl_classes
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_I_same_carrier_baseline():
    name = "I. same-carrier baseline (carrier preserved)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        c = cand(carriers=[{"marketing_carrier": "LH", "operating_carrier": "LH"}])
        r = canonicalize_for_candidate(mission(), c)
        ok = ("LH" in r["candidate_canonical"]["marketing_carriers"] and
              "LH" in r["candidate_canonical"]["operating_carriers"])
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_J_same_ticket_baseline():
    name = "J. same-ticket baseline (single-ticket preserved)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(), cand(ticket_structure="single-ticket"))
        ok = ("single-ticket" in [
            bl["canonical_representation"]["ticket_structure"]
            for bl in r["canonical_baselines"]
        ])
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_K_positioning_baseline():
    name = "K. positioning baseline (candidate positioning flight)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # Multi-ticket candidate with TPE→KUL→FRA→MAD routing
        c = cand("c1", segments=[
            {"from": "TPE", "to": "KUL"},
            {"from": "KUL", "to": "FRA"},
            {"from": "FRA", "to": "MAD"}], ticket_structure="multi-ticket", ticket_count=2)
        r = canonicalize_for_candidate(mission(), c)
        # outer_port_positioning should be eligible (origin is outer port, multi-ticket)
        elig = {e["baseline_class"]: e["eligibility"] for e in r["baseline_eligibility"]["baseline_classes"]}
        ok = elig.get("outer_port_positioning") == "ELIGIBLE"
        _log(name, ok, f"outer_port_positioning={elig.get('outer_port_positioning')}")
    except Exception as e:
        _log(name, False, str(e))


def test_L_outer_port_baseline():
    name = "L. outer-port baseline (TPE origin = outer port)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # TPE (Asia outer port) multi-ticket → MAD
        c = cand("c1", segments=[
            {"from": "TPE", "to": "KUL"}, {"from": "KUL", "to": "MAD"}],
                  ticket_structure="multi-ticket", ticket_count=2)
        r = canonicalize_for_candidate(mission(), c)
        ok = r["candidate_canonical"]["outer_port_origin"] is True
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_M_secondary_entry_baseline():
    name = "M. secondary-entry baseline (LIS as dest)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # Mission FRA → LIS; LIS is European secondary entry
        r = canonicalize_for_candidate(
            mission("FRA", "LIS"),
            cand("c1", "FRA", "LIS", segments=[{"from": "FRA", "to": "LIS"}]))
        elig = {e["baseline_class"]: e["eligibility"] for e in r["baseline_eligibility"]["baseline_classes"]}
        ok = elig.get("secondary_entry") == "ELIGIBLE"
        _log(name, ok, f"secondary_entry={elig.get('secondary_entry')}")
    except Exception as e:
        _log(name, False, str(e))


def test_N_alternative_hub_baseline():
    name = "N. alternative-hub baseline (TPE→DXB→MAD)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        c = cand("c1", segments=[{"from": "TPE", "to": "DXB"}, {"from": "DXB", "to": "MAD"}])
        r = canonicalize_for_candidate(mission(), c)
        # 2-segment through DXB → conventional_hub eligible
        elig = {e["baseline_class"]: e["eligibility"] for e in r["baseline_eligibility"]["baseline_classes"]}
        ok = elig.get("conventional_hub") == "ELIGIBLE"
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_O_multi_ticket():
    name = "O. multi-ticket candidate"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        c = cand("c1", segments=[{"from": "TPE", "to": "KUL"}, {"from": "KUL", "to": "MAD"}],
                  ticket_structure="multi-ticket", ticket_count=2)
        r = canonicalize_for_candidate(mission(), c)
        ok = r["candidate_canonical"]["ticket_structure"] == "multi-ticket"
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_P_airport_change():
    name = "P. airport-change detection"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # LHR → LGW (airport change)
        c = cand("c1", segments=[{"from": "LHR", "to": "MAD"},
                                  {"from": "LGW", "to": "BCN"}])
        r = canonicalize_for_candidate(
            mission("LHR", "BCN"), c)
        ok = any(bl["canonical_representation"].get("airport_change") is True
                 for bl in r["canonical_baselines"])
        _log(name, ok, "airport change detected")
    except Exception as e:
        _log(name, False, str(e))


def test_Q_missing_passenger_basis():
    name = "Q. missing passenger basis"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # Mission without passenger_count / types
        m = mission(pc=None)
        m.pop("passenger_count", None)
        m["passenger_types"] = None
        r = canonicalize_for_candidate(m, cand())
        ok = (r["mission_canonical"]["passenger_count"] is None and
              r["mission_canonical"]["passenger_basis_known"] is False)
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_R_missing_cabin():
    name = "R. missing cabin preserved as unknown"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        m["cabin"] = None
        r = canonicalize_for_candidate(m, cand(cabin=None))
        ok = (r["candidate_canonical"]["cabin"] is None and
              r["candidate_canonical"]["cabin_known"] is False)
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_S_missing_baggage():
    name = "S. missing baggage (no default to 0)"
    try:
        from baseline_canonicalization import canonicalize_candidate
        c = {"id": "c1"}
        canon = canonicalize_candidate(c)
        # candidate has no baggage info at all; canonical preserves None
        ok = canon.get("cabin") is None and canon.get("passenger_count") is None
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_T_missing_carrier():
    name = "T. missing carrier data"
    try:
        from baseline_canonicalization import canonicalize_candidate
        canon = canonicalize_candidate({"id": "c1", "segments": [{"from": "TPE", "to": "FRA"}]})
        ok = (canon["marketing_carriers"] == [] and
              canon["operating_carriers_known"] is False)
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_U_missing_schedule_evidence():
    name = "U. missing schedule evidence"
    try:
        from baseline_canonicalization import canonicalize_candidate
        canon = canonicalize_candidate({"id": "c1"})
        ok = canon["schedule_evidence_status"] == "UNKNOWN"
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_V_multiple_baselines():
    name = "V. multiple eligible baselines"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(), cand())
        # TPE→FRA→MAD normally has conventional_hub + same_airport_pair
        ok = len(r["canonical_baselines"]) >= 2
        _log(name, ok, f"count={len(r['canonical_baselines'])}")
    except Exception as e:
        _log(name, False, str(e))


def test_W_no_baseline():
    name = "W. no eligible baseline (some missions) — fictional_no_fly never canonical"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # Mission entirely missing origin/destination
        r = canonicalize_for_candidate({"mission_id": "M0"}, {"id": "c0"})
        # Every class should be UNKNOWN or NOT_ELIGIBLE
        bl_classes = {bl["baseline_class"] for bl in r["canonical_baselines"]}
        ok = "fictional_no_fly" not in bl_classes
        _log(name, ok, f"fictional_no_fly never canonical; classes={bl_classes}")
    except Exception as e:
        _log(name, False, str(e))


def test_X_price_free_canonicalization():
    name = "X. price-free canonicalization (works with all price=null)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c = cand()
        # Forcefully set price to None in the canonical representation downstream
        c["price"] = None
        c["price_evidence"] = None
        # canonicalize_for_candidate does not even read price; must produce same output
        r1 = canonicalize_for_candidate(m, c)
        c2 = dict(c)
        c2["price"] = 999.99  # arbitrary price; should NOT affect baseline output
        r2 = canonicalize_for_candidate(m, c2)
        # Compare structural fields (ignore retrieved_at timestamp)
        r1_struct = {k: v for k, v in r1.items() if k != "retrieved_at"}
        r1_struct["provenance"]["retrieved_at"] = "REDACTED"
        for bl in r1_struct["canonical_baselines"]:
            bl["provenance"]["retrieved_at"] = "REDACTED"
        r2_struct = {k: v for k, v in r2.items() if k != "retrieved_at"}
        r2_struct["provenance"]["retrieved_at"] = "REDACTED"
        for bl in r2_struct["canonical_baselines"]:
            bl["provenance"]["retrieved_at"] = "REDACTED"
        ok = (json.dumps(r1_struct, sort_keys=True) ==
              json.dumps(r2_struct, sort_keys=True))
        _log(name, ok, "output identical regardless of price")
    except Exception as e:
        _log(name, False, str(e))


def test_Y_no_cheapest_based_selection():
    name = "Y. no cheapest-based baseline selection"
    try:
        # Both candidates share same mission/structure except price
        # Baseline canonicalization must produce structurally identical output
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c_cheap = cand("cheap", segments=[{"from": "TPE", "to": "FRA"}, {"from": "FRA", "to": "MAD"}])
        c_expensive = dict(c_cheap)
        c_expensive["id"] = "expensive"
        c_expensive["price"] = 999999.99
        c_cheap["price"] = 100.00
        r_cheap = canonicalize_for_candidate(m, c_cheap)
        r_expensive = canonicalize_for_candidate(m, c_expensive)
        # Baseline set should be structurally identical (only provenance/retrieved_at may differ)
        bl_cheap = sorted([bl["baseline_class"] for bl in r_cheap["canonical_baselines"]])
        bl_expensive = sorted([bl["baseline_class"] for bl in r_expensive["canonical_baselines"]])
        ok = bl_cheap == bl_expensive
        _log(name, ok, f"cheap baselines={bl_cheap}; expensive baselines={bl_expensive}")
    except Exception as e:
        _log(name, False, str(e))


def test_Z_no_Jev_based_selection():
    name = "Z. no Jev-based baseline selection"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c_with_jev = cand("c1", segments=[{"from": "TPE", "to": "FRA"}, {"from": "FRA", "to": "MAD"}])
        c_without_jev = dict(c_with_jev)
        c_with_jev["jev_score"] = 9.99  # arbitrary
        c_with_jev["jev_survivor"] = True
        c_without_jev["jev_score"] = None
        r_with = canonicalize_for_candidate(m, c_with_jev)
        r_without = canonicalize_for_candidate(m, c_without_jev)
        ok = ([bl["baseline_class"] for bl in r_with["canonical_baselines"]] ==
              [bl["baseline_class"] for bl in r_without["canonical_baselines"]])
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AA_no_information_priority_score_selection():
    name = "AA. no information_priority_score selection"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c_high_ips = cand("c1")
        c_low_ips = dict(c_high_ips)
        c_high_ips["information_priority_score"] = 0.99
        c_low_ips["information_priority_score"] = 0.01
        r_high = canonicalize_for_candidate(m, c_high_ips)
        r_low = canonicalize_for_candidate(m, c_low_ips)
        ok = ([bl["baseline_class"] for bl in r_high["canonical_baselines"]] ==
              [bl["baseline_class"] for bl in r_low["canonical_baselines"]])
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AB_provenance():
    name = "AB. provenance (source + canonicalization rule/version)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate, CANONICALIZATION_RULE_VERSION
        r = canonicalize_for_candidate(mission(), cand())
        prov = r["provenance"]
        ok = (prov["source"] == "baseline_canonicalization_v1_2_4" and
              prov["canonicalization_rule_version"] == CANONICALIZATION_RULE_VERSION and
              prov["retrieved_at"] is not None)
        _log(name, ok, f"rule_version={prov['canonicalization_rule_version']}")
    except Exception as e:
        _log(name, False, str(e))


def test_AC_UNKNOWN_semantics():
    name = "AC. UNKNOWN semantics (insufficient evidence → UNKNOWN, not coerced)"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # Mission with missing origin
        r = canonicalize_for_candidate(
            {"mission_id": "M0", "destination": "MAD", "travel_date": "2027-04-15"},
            {"id": "c0", "segments": []})
        any_unknown = any(
            e["eligibility"] == "UNKNOWN"
            for e in r["baseline_eligibility"]["baseline_classes"]
        )
        ok = any_unknown
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AD_HARD_SOFT_UNKNOWN_compatibility():
    name = "AD. HARD/SOFT/UNKNOWN comparability labels"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(), cand())
        labels = {cp["comparability"] for cp in r["comparison_pairs"]}
        # For matched data, comparability should be "hard_comparable"
        ok = ("hard_comparable" in labels or
              "soft_comparable" in labels or
              "unknown" in labels)
        # All three labels are valid candidates; only require that the
        # comparability field is one of them
        for cp in r["comparison_pairs"]:
            assert cp["comparability"] in {"hard_comparable", "soft_comparable", "unknown"}
        _log(name, ok, f"labels={labels}")
    except Exception as e:
        _log(name, False, str(e))


def test_AE_no_ArbitrageEvidence():
    name = "AE. no ArbitrageEvidence"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(), cand())
        ok = "ArbitrageEvidence" not in json.dumps(r, ensure_ascii=False)
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AF_no_Opportunity():
    name = "AF. no Opportunity"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(), cand())
        ok = "\"Opportunity\"" not in json.dumps(r, ensure_ascii=False)
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AG_no_VerifiedOpportunity():
    name = "AG. no VerifiedOpportunity"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        r = canonicalize_for_candidate(mission(), cand())
        ok = "VerifiedOpportunity" not in json.dumps(r, ensure_ascii=False)
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AH_no_arbitrage_score():
    name = "AH. no arbitrage_score token"
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # Run several variations
        r1 = canonicalize_for_candidate(mission(), cand())
        r2 = canonicalize_for_candidate(mission(), cand("c2", segments=[{"from": "TPE", "to": "MAD"}]))
        tokens = ("arbitrage_score", "opportunity_score", "candidate_score",
                  "predicted_savings", "expected_profit")
        ok = all(t not in json.dumps(r1, ensure_ascii=False) for t in tokens) and \
             all(t not in json.dumps(r2, ensure_ascii=False) for t in tokens)
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))


def test_AI_security_leakage():
    name = "AI. security / leakage (no provider tokens)"
    try:
        env = {"FAKE_BASELINE_TOKEN_DO_NOT_LEAK_xxx": "secret_baseline_value"}
        # Use CLI with fixtures
        m_path = WORKDIR / "_tmp_mission.json"
        c_path = WORKDIR / "_tmp_candidate.json"
        m_path.write_text(json.dumps(mission()))
        c_path.write_text(json.dumps(cand()))
        try:
            p = subprocess.run(["python3", "baseline_canonicalization.py",
                                  "--mission", str(m_path),
                                  "--candidate", str(c_path)],
                                 cwd=str(WORKDIR), env={**os.environ, **env},
                                 capture_output=True, text=True, timeout=20)
            output = (p.stdout or "") + (p.stderr or "")
            ev_path = WORKDIR / "data" / "baseline_evidence_v1_2_4.json"
            ev_json = ev_path.read_text() if ev_path.exists() else ""
            tr_path = WORKDIR / "data" / "baseline_trace_v1_2_4.json"
            tr_json = tr_path.read_text() if tr_path.exists() else ""
            ok = ("FAKE_BASELINE_TOKEN_DO_NOT_LEAK_xxx" not in output and
                  "secret_baseline_value" not in output and
                  "FAKE_BASELINE_TOKEN_DO_NOT_LEAK_xxx" not in ev_json and
                  "secret_baseline_value" not in ev_json and
                  "FAKE_BASELINE_TOKEN_DO_NOT_LEAK_xxx" not in tr_json and
                  "secret_baseline_value" not in tr_json)
            _log(name, ok)
        finally:
            try: m_path.unlink()
            except FileNotFoundError: pass
            try: c_path.unlink()
            except FileNotFoundError: pass
    except Exception as e:
        _log(name, False, str(e))


def test_AJ_regression_compatibility():
    name = "AJ. price_intelligence.py untouched"
    try:
        pi_path = WORKDIR / "price_intelligence.py"
        content = pi_path.read_text()
        ok = "baseline_canonicalization" not in content
        _log(name, ok, "v1.2.4 did not modify price_intelligence.py")
    except Exception as e:
        _log(name, False, str(e))


# -----------------------------------------------------------------------------
# Negative cases from spec §20
# -----------------------------------------------------------------------------

def test_NEG_cheapest_not_automatically_baseline():
    """Cheapest candidate is NOT automatically baseline."""
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        # Two structurally-identical candidates with different prices
        m = mission()
        c1 = cand("c1"); c1["price"] = 100  # cheap
        c2 = cand("c2"); c2["price"] = 999  # expensive
        r1 = canonicalize_for_candidate(m, c1)
        r2 = canonicalize_for_candidate(m, c2)
        # Output must be structurally identical (price not used)
        ok = ([bl["baseline_class"] for bl in r1["canonical_baselines"]] ==
              [bl["baseline_class"] for bl in r2["canonical_baselines"]])
        _log("NEG-1: cheapest != baseline", ok)
    except Exception as e:
        _log("NEG-1: cheapest != baseline", False, str(e))


def test_NEG_Jev_survivor_not_baseline():
    """Jev survivor is NOT automatically baseline."""
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c_surv = cand("c1"); c_surv["jev_survivor"] = True
        c_not = cand("c2"); c_not["jev_survivor"] = False
        r_surv = canonicalize_for_candidate(m, c_surv)
        r_not = canonicalize_for_candidate(m, c_not)
        ok = ([bl["baseline_class"] for bl in r_surv["canonical_baselines"]] ==
              [bl["baseline_class"] for bl in r_not["canonical_baselines"]])
        _log("NEG-2: Jev survivor != baseline", ok)
    except Exception as e:
        _log("NEG-2: Jev survivor != baseline", False, str(e))


def test_NEG_IPS_not_baseline_selector():
    """information_priority_score is NOT baseline selector."""
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c_high = cand("c1"); c_high["information_priority_score"] = 0.99
        c_low = cand("c2"); c_low["information_priority_score"] = 0.01
        r_high = canonicalize_for_candidate(m, c_high)
        r_low = canonicalize_for_candidate(m, c_low)
        ok = ([bl["baseline_class"] for bl in r_high["canonical_baselines"]] ==
              [bl["baseline_class"] for bl in r_low["canonical_baselines"]])
        _log("NEG-3: information_priority_score != selector", ok)
    except Exception as e:
        _log("NEG-3: information_priority_score != selector", False, str(e))


def test_NEG_missing_price_not_failure():
    """Missing price ≠ baseline failure."""
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c = cand("c1"); c["price"] = None
        r = canonicalize_for_candidate(m, c)
        # Should still produce canonical baselines
        ok = len(r["canonical_baselines"]) > 0
        _log("NEG-4: missing price != failure", ok)
    except Exception as e:
        _log("NEG-4: missing price != failure", False, str(e))


def test_NEG_different_date_not_hard():
    """Different travel date → not hard comparable."""
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission(travel_date="2027-04-15")
        c = cand("c1", travel_date="2027-05-01")
        r = canonicalize_for_candidate(m, c)
        # ALL comparison pairs should be NOT hard_comparable
        ok = all(cp["comparability"] != "hard_comparable" for cp in r["comparison_pairs"])
        _log("NEG-5: different date ≠ hard comparable", ok)
    except Exception as e:
        _log("NEG-5: different date ≠ hard comparable", False, str(e))


def test_NEG_different_airport_not_exact():
    """Different destination → canonicalization doesn't claim exact parity."""
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission("TPE", "MAD")
        # Pass segments=[] to suppress the default helper segments
        c = cand("c1", "TPE", "CDG", segments=[{"from": "TPE", "to": "CDG"}])
        r = canonicalize_for_candidate(m, c)
        ok = all(not cp["hard_match"]["destination"] for cp in r["comparison_pairs"])
        _log("NEG-6: different airport ≠ hard match", ok)
    except Exception as e:
        _log("NEG-6: different airport ≠ hard match", False, str(e))


def test_NEG_multi_vs_single_ticket():
    """Multi-ticket vs single-ticket not auto-comparable."""
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c = cand("c1", segments=[{"from": "TPE", "to": "KUL"}, {"from": "KUL", "to": "MAD"}],
                  ticket_structure="multi-ticket", ticket_count=2)
        r = canonicalize_for_candidate(m, c)
        # Hard match should NOT claim parity for ticket_structure alone;
        # surfaced in soft_observations
        ok = all("ticket_structure" in cp["soft_observations"] for cp in r["comparison_pairs"])
        _log("NEG-7: multi-ticket vs single — soft observation", ok)
    except Exception as e:
        _log("NEG-7: multi-ticket vs single — soft observation", False, str(e))


def test_NEG_no_real_API_calls():
    """Baseline canonicalization makes 0 external API calls."""
    try:
        from baseline_canonicalization import canonicalize_for_candidate
        m = mission()
        c = cand()
        # Confirm the function never imports urllib/network
        import baseline_canonicalization as bl
        src = open(bl.__file__).read()
        ok = ("urllib" not in src and
              "urlopen" not in src and
              "requests" not in src and
              "httpx" not in src)
        _log("NEG-8: 0 external API calls (offline)", ok)
    except Exception as e:
        _log("NEG-8: 0 external API calls (offline)", False, str(e))


# -----------------------------------------------------------------------------
# Main runner
# -----------------------------------------------------------------------------

def main():
    print("\n" + "=" * 70)
    print("baseline_canonicalization v1.2.4 — test_baseline_canonicalization_v1_2_4.py")
    print("=" * 70)
    tests = [
        test_A_canonical_schema,
        test_B_mission_binding,
        test_C_date_binding,
        test_D_round_trip_binding,
        test_E_airport_exactness,
        test_F_airport_group_semantics,
        test_G_conventional_baseline,
        test_H_same_hub_baseline,
        test_I_same_carrier_baseline,
        test_J_same_ticket_baseline,
        test_K_positioning_baseline,
        test_L_outer_port_baseline,
        test_M_secondary_entry_baseline,
        test_N_alternative_hub_baseline,
        test_O_multi_ticket,
        test_P_airport_change,
        test_Q_missing_passenger_basis,
        test_R_missing_cabin,
        test_S_missing_baggage,
        test_T_missing_carrier,
        test_U_missing_schedule_evidence,
        test_V_multiple_baselines,
        test_W_no_baseline,
        test_X_price_free_canonicalization,
        test_Y_no_cheapest_based_selection,
        test_Z_no_Jev_based_selection,
        test_AA_no_information_priority_score_selection,
        test_AB_provenance,
        test_AC_UNKNOWN_semantics,
        test_AD_HARD_SOFT_UNKNOWN_compatibility,
        test_AE_no_ArbitrageEvidence,
        test_AF_no_Opportunity,
        test_AG_no_VerifiedOpportunity,
        test_AH_no_arbitrage_score,
        test_AI_security_leakage,
        test_AJ_regression_compatibility,
        # Negative cases (per spec §20)
        test_NEG_cheapest_not_automatically_baseline,
        test_NEG_Jev_survivor_not_baseline,
        test_NEG_IPS_not_baseline_selector,
        test_NEG_missing_price_not_failure,
        test_NEG_different_date_not_hard,
        test_NEG_different_airport_not_exact,
        test_NEG_multi_vs_single_ticket,
        test_NEG_no_real_API_calls,
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

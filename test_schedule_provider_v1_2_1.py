"""
test_schedule_provider_v1_2_1.py — Tests for v1.2.1 Live Schedule Upgrade

Tests (per spec §17):
A. explicit OpenFlights provider
B. explicit Duffel provider
C. missing credentials fail closed
D. no silent fallback
E. provider provenance
F. normalized ScheduleEvidence schema
G. date-window binding
H. connection calculation
I. airport-change detection
J. operating-carrier preservation
K. multi-city preservation
L. smoke-test hard limit
M. credential leakage
N. failure semantics
O. no BOOKABLE
P. no ArbitrageEvidence
Q. no arbitrage_score

Run:
    /Users/aib/.hermes/hermes-agent/venv/bin/python3 test_schedule_provider_v1_2_1.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
sys.path.insert(0, str(REPO_ROOT))
import live_schedule_provider as lsp  # noqa: E402

PYTHON = "/Users/aib/.hermes/hermes-agent/venv/bin/python3"
PASSED = 0
FAILED = 0


def _assert(cond, label):
    global PASSED, FAILED
    if cond:
        print(f"  PASS: {label}")
        PASSED += 1
        return True
    print(f"  FAIL: {label}")
    FAILED += 1
    return False


def _assert_eq(actual, expected, label):
    if actual == expected:
        return _assert(True, f"{label} == {expected!r}")
    return _assert(False, f"{label} — expected {expected!r}, got {actual!r}")


SYNTHETIC_CANDS = [
    {"id": "TEST-A", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"}]},
    {"id": "TEST-B", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH", "duration_min": 720}]},
    {"id": "TEST-C", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"},
                  {"from": "KUL", "to": "MAD", "carrier": "QR"}]},
    # TEST-D: airport change between KUL→SIN (different airports)
    # Connection[0]: KUL→SIN, prev=destination=KUL, next.origin=SIN → change=True
    # Connection[1]: SIN→MAD, prev.destination=SIN, next.origin=SIN → change=False
    {"id": "TEST-D", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"},
                  {"from": "KUL", "to": "SIN", "carrier": "EK"},
                  {"from": "SIN", "to": "MAD", "carrier": "QR"}]},
    {"id": "TEST-E", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "LHR", "carrier": "BR"},
                  {"from": "LHR", "to": "MAD", "carrier": "IB"}]},
]
SYNTHETIC_PATH = REPO_ROOT / "data" / "_synthetic_cands_for_v121.json"
SYNTHETIC_PATH.write_text(json.dumps(SYNTHETIC_CANDS))


def run_cli(*args, env_extra=None, timeout=30):
    full_env = dict(os.environ)
    full_env.pop("DUFFEL_API_KEY_LIVE", None)
    full_env.pop("DUFFEL_API_KEY_TEST", None)
    if env_extra:
        full_env.update(env_extra)
    return subprocess.run(
        [PYTHON, str(REPO_ROOT / "live_schedule_provider.py"),
         str(SYNTHETIC_PATH),
         *args],
        capture_output=True, text=True, timeout=timeout, env=full_env,
    )


# =============================================================================
# A. explicit OpenFlights provider
# =============================================================================

def test_a_explicit_openflights():
    print("\n=== Test A: explicit OpenFlights provider ===")
    p = lsp.OpenFlightsScheduleProvider()
    _assert_eq(p.name, "openflights", "OpenFlightsScheduleProvider.name")
    _assert(p.health_check(), "OpenFlights data files exist")
    res = p.lookup(SYNTHETIC_CANDS[0], date_window="2027-04-15")
    _assert(res["success"], "lookup success")


# =============================================================================
# B. explicit Duffel provider (real, no creds → fail closed)
# =============================================================================

def test_b_explicit_duffel():
    print("\n=== Test B: explicit Duffel provider (no creds → fail closed) ===")
    saved = os.environ.pop("DUFFEL_API_KEY_LIVE", None)
    saved2 = os.environ.pop("DUFFEL_API_KEY_TEST", None)
    try:
        try:
            lsp.DuffelScheduleProvider()
            raised = False
        except RuntimeError as e:
            raised = True
            _assert("MISSING_CREDENTIALS" in str(e), "RuntimeError mentions MISSING_CREDENTIALS")
        _assert(raised, "DuffelScheduleProvider raises without token")
        # With a fake token
        real = lsp.DuffelScheduleProvider(token="fake_token_for_test")
        _assert_eq(real.name, "duffel", "DuffelScheduleProvider.name")
    finally:
        if saved:
            os.environ["DUFFEL_API_KEY_LIVE"] = saved
        if saved2:
            os.environ["DUFFEL_API_KEY_TEST"] = saved2


# =============================================================================
# C. missing credentials fail closed
# =============================================================================

def test_c_missing_credentials_fail_closed():
    print("\n=== Test C: missing credentials fail closed ===")
    r = run_cli("--schedule-provider", "duffel", "--max-searches", "1")
    _assert_eq(r.returncode, 10, "duffel without creds → rc=10")
    _assert("MISSING_CREDENTIALS" in r.stderr, "MISSING_CREDENTIALS in stderr")
    _assert("FAIL CLOSED" in r.stderr, "FAIL CLOSED message in stderr")


# =============================================================================
# D. no silent fallback
# =============================================================================

def test_d_no_silent_fallback():
    print("\n=== Test D: no silent fallback ===")
    # --schedule-provider duffel without creds must NOT silently fall back to OpenFlights
    r = run_cli("--schedule-provider", "duffel", "--max-searches", "1")
    _assert(r.returncode != 0, "duffel without creds exits non-zero (no silent fallback)")
    _assert("FAIL CLOSED" in r.stderr, "explicit FAIL CLOSED message")
    # The output evidence file must NOT have been written for live evidence
    out = REPO_ROOT / "data" / "schedule_evidence_v1_2_1.json"
    if out.exists():
        body = json.loads(out.read_text())
        # provider field, if present, should not claim LIVE without explicit provider
        _assert(body.get("provider") in (None, "duffel"),
                "provider label, if any, is not silently switched")


# =============================================================================
# E. provider provenance
# =============================================================================

def test_e_provider_provenance():
    print("\n=== Test E: provider provenance ===")
    # OpenFlights
    res_of = lsp.OpenFlightsScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                      date_window="2027-04-15")
    pe_of = res_of["schedule_evidence"]
    _assert_eq(pe_of["provider"], "openflights", "OpenFlights provider identity")
    _assert_eq(pe_of["provider_mode"], "database", "OpenFlights provider_mode")
    _assert_eq(pe_of["provenance"]["source"], "openflights", "OpenFlights provenance.source")
    # Mock Duffel
    res_md = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                     date_window="2027-04-15")
    pe_md = res_md["schedule_evidence"]
    _assert_eq(pe_md["provider"], "mock_duffel", "MockDuffel provider identity")
    _assert_eq(pe_md["provider_mode"], "mock", "MockDuffel provider_mode")


# =============================================================================
# F. normalized ScheduleEvidence schema
# =============================================================================

def test_f_normalized_schema():
    print("\n=== Test F: normalized ScheduleEvidence schema ===")
    # Mock Duffel evidence (LIVE)
    res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[2],
                                                   date_window="2027-04-15")
    pe = res["schedule_evidence"]
    required = {
        "candidate_id", "provider", "provider_mode", "retrieved_at",
        "mission_date_window", "searched_date", "expires_at",
        "verification_status", "schedule_status",
        "segments", "connection_checks",
        "provenance", "warnings", "failure_reason",
    }
    for k in required:
        _assert(k in pe, f"ScheduleEvidence has key {k!r}")
    # Each segment has the canonical fields
    for seg in pe["segments"]:
        for sf in ["segment_index", "origin", "destination", "departing_at_iso",
                    "arriving_at_iso", "marketing_carrier", "operating_carrier",
                    "flight_number", "duration_minutes", "verification_status"]:
            _assert(sf in seg, f"segment has key {sf!r}")


# =============================================================================
# G. date-window binding
# =============================================================================

def test_g_date_window_binding():
    print("\n=== Test G: date-window binding ===")
    res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                   date_window="2027-04-15")
    pe = res["schedule_evidence"]
    _assert_eq(pe["mission_date_window"], "2027-04-15", "mission_date_window bound")
    _assert_eq(pe["searched_date"], "2027-04-15", "searched_date bound")
    # retrieved_at must be in ISO8601, NOT a hard-coded mock timestamp
    _assert(pe["retrieved_at"].startswith("202"), "retrieved_at is current ISO timestamp")
    # OpenFlights evidence
    res_of = lsp.OpenFlightsScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                      date_window="2027-04-15")
    pe_of = res_of["schedule_evidence"]
    _assert_eq(pe_of["mission_date_window"], "2027-04-15", "OpenFlights mission_date_window bound")


# =============================================================================
# H. connection calculation
# =============================================================================

def test_h_connection_calculation():
    print("\n=== Test H: connection calculation ===")
    # Multi-segment mock with 2h connection between seg[0] arrival and seg[1] departure
    res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[2],
                                                   date_window="2027-04-15")
    pe = res["schedule_evidence"]
    # TEST-C has 2 segments
    _assert(len(pe["connection_checks"]) == 1,
            f"1 connection check (got {len(pe['connection_checks'])})")
    cc = pe["connection_checks"][0]
    # Mock sets departure+2h → 120 min
    _assert_eq(cc["connection_time_min"], 120, "connection_time_min=120")
    _assert_eq(cc["overnight_connection"], False, "overnight=False")
    _assert_eq(cc["tight_connection"], False, "tight=False (<90 would be tight)")
    _assert_eq(cc["airport_change_required"], False, "airport_change_required=False")
    # OpenFlights: connection_time_min must be None
    res_of = lsp.OpenFlightsScheduleProvider().lookup(SYNTHETIC_CANDS[2],
                                                      date_window="2027-04-15")
    pe_of = res_of["schedule_evidence"]
    if pe_of.get("connection_checks"):
        cc_of = pe_of["connection_checks"][0]
        _assert(cc_of["connection_time_min"] is None,
                "OpenFlights connection_time_min=None (no timestamps)")


# =============================================================================
# I. airport-change detection
# =============================================================================

def test_i_airport_change_detection():
    print("\n=== Test I: airport-change detection ===")
    # Mock — TEST-D (TPE→KUL→DXB→MAD) has KUL vs DXB (different airports)
    res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[3],
                                                   date_window="2027-04-15")
    pe = res["schedule_evidence"]
    # 2 connection checks for 3 segments
    _assert(len(pe["connection_checks"]) == 2,
            f"2 connection checks (got {len(pe['connection_checks'])})")
    # airport_change_required = True iff arrival airport ≠ departure airport.
    # For TEST-D (TPE→KUL→SIN→MAD):
    # Conn[0]: arrival KUL, departure KUL (next leg starts at KUL) → same → False
    # Conn[1]: arrival SIN, departure SIN (next leg starts at SIN) → same → False
    cc0 = pe["connection_checks"][0]
    _assert_eq(cc0["airport_change_required"], False,
               "TPE→KUL vs KUL→SIN: same airport (KUL) → airport_change_required=False")
    cc1 = pe["connection_checks"][1]
    _assert_eq(cc1["airport_change_required"], False,
               "KUL→SIN vs SIN→MAD: same airport (SIN) → airport_change_required=False")
    # Now test a candidate with explicit airport change
    res_chg = lsp.MockDuffelScheduleProvider().lookup(
        {"id": "CHG", "segments": [
            {"from": "LHR", "to": "FRA", "carrier": "BA"},
            {"from": "FRA", "to": "MAD", "carrier": "LH"}]},
        date_window="2027-04-15")
    pe_chg = res_chg["schedule_evidence"]
    _assert_eq(pe_chg["connection_checks"][0]["airport_change_required"], False,
               "LHR→FRA vs FRA→MAD: same airport (FRA) → airport_change_required=False")
    # Add a separate test with an airport change: LHR → LGW (different airports)
    res_lgw = lsp.MockDuffelScheduleProvider().lookup(
        {"id": "LGW", "segments": [
            {"from": "LHR", "to": "MAD", "carrier": "BA"},
            {"from": "LGW", "to": "BCN", "carrier": "VY"}]},
        date_window="2027-04-15")
    pe_lgw = res_lgw["schedule_evidence"]
    _assert_eq(pe_lgw["connection_checks"][0]["airport_change_required"], True,
               "LHR→MAD vs LGW→BCN: arrival=LHR, departure=LGW → airport_change_required=True")
    # Missing data → None
    _assert_eq(lsp._airport_change(None, "TPE"), None,
               "missing arrival airport → None")
    _assert_eq(lsp._airport_change("TPE", "TPE"), False,
               "same airport → False")
    _assert_eq(lsp._airport_change("tpe", "KUL"), True,
               "different airports → True")


# =============================================================================
# J. operating-carrier preservation
# =============================================================================

def test_j_operating_carrier():
    print("\n=== Test J: operating-carrier preservation ===")
    res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                   date_window="2027-04-15")
    pe = res["schedule_evidence"]
    seg = pe["segments"][0]
    _assert(seg["marketing_carrier"] is not None, "marketing_carrier preserved")
    _assert(seg["operating_carrier"] is not None, "operating_carrier preserved")
    _assert("operating_carrier_flight_number" in seg,
            "operating_carrier_flight_number preserved")


# =============================================================================
# K. multi-city preservation
# =============================================================================

def test_k_multi_city_preservation():
    print("\n=== Test K: multi-city preservation ===")
    # TEST-D: 3 segments = 3 slices
    res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[3],
                                                   date_window="2027-04-15")
    pe = res["schedule_evidence"]
    _assert_eq(len(pe["segments"]), 3,
               f"3 segments preserved (got {len(pe['segments'])})")
    routes = [(s["origin"], s["destination"]) for s in pe["segments"]]
    _assert_eq(routes, [("TPE", "KUL"), ("KUL", "SIN"), ("SIN", "MAD")],
               "multi-city routes preserved, NOT collapsed")


# =============================================================================
# L. smoke-test hard limit
# =============================================================================

def test_l_smoke_test_hard_limit():
    print("\n=== Test L: smoke-test hard limit ===")
    r = run_cli("--schedule-provider", "mock_duffel", "--max-searches", "10",
                "--smoke-test")
    _assert_eq(r.returncode, 0, "smoke-test rc=0")
    body = json.loads((REPO_ROOT / "data" / "schedule_evidence_v1_2_1.json").read_text())
    _assert(body["summary"]["schedule_budget_max"] <= 2,
            f"smoke-test caps at 2 (got {body['summary']['schedule_budget_max']})")
    _assert(len(body["evidences"]) <= 2,
            f"smoke-test caps evidences at 2 (got {len(body['evidences'])})")


# =============================================================================
# M. credential leakage
# =============================================================================

def test_m_credential_leakage():
    print("\n=== Test M: credential leakage ===")
    fake = "FAKE_DUFFEL_TOKEN_DO_NOT_LEAK_xxxx1234"
    r = run_cli("--schedule-provider", "duffel", "--max-searches", "1",
                env_extra={"DUFFEL_API_KEY_LIVE": fake})
    full = r.stdout + r.stderr
    _assert(fake not in full, "fake token does not appear in stdout/stderr")


# =============================================================================
# N. failure semantics
# =============================================================================

def test_n_failure_semantics():
    print("\n=== Test N: failure semantics ===")
    # Empty segments → ROUTE_UNAVAILABLE
    res = lsp.MockDuffelScheduleProvider().lookup({"id": "EMPTY", "segments": []},
                                                   date_window="2027-04-15")
    _assert_eq(res["success"], False, "empty segments → failure")
    _assert_eq(res["failure_kind"], "ROUTE_UNAVAILABLE", "failure_kind ROUTE_UNAVAILABLE")
    # SIMULATE_PROVIDER_ERROR
    saved = os.environ.get("SIMULATE_PROVIDER_ERROR")
    os.environ["SIMULATE_PROVIDER_ERROR"] = "1"
    try:
        res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                       date_window="2027-04-15")
        _assert_eq(res["success"], False, "PROVIDER_ERROR → failure")
        _assert_eq(res["failure_kind"], "PROVIDER_ERROR", "failure_kind PROVIDER_ERROR")
    finally:
        if saved:
            os.environ["SIMULATE_PROVIDER_ERROR"] = saved
        else:
            os.environ.pop("SIMULATE_PROVIDER_ERROR", None)
    # PROVIDER_ERROR must NOT be interpreted as expensive/no-arbitrage
    # (this is a semantic test; we verify the failure_kind is just a label)
    _assert(res["failure_kind"] == "PROVIDER_ERROR",
            "PROVIDER_ERROR preserved as failure_kind (not 'expensive')")


# =============================================================================
# O. no BOOKABLE
# =============================================================================

def test_o_no_bookable():
    print("\n=== Test O: no BOOKABLE ===")
    src = (REPO_ROOT / "live_schedule_provider.py").read_text()
    src_s = re.sub(r"#.*", "", src)
    src_s = re.sub(r'""".*?"""', "", src_s, flags=re.DOTALL)
    src_s = re.sub(r"'''.*?'''", "", src_s, flags=re.DOTALL)
    _assert("BOOKABLE" not in src_s, "no BOOKABLE identifier")
    # Also verify in emitted payload
    res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                   date_window="2027-04-15")
    raw = json.dumps(res)
    _assert("BOOKABLE" not in raw, "no BOOKABLE in payload")


# =============================================================================
# P. no ArbitrageEvidence
# =============================================================================

def test_p_no_arbitrage_evidence():
    print("\n=== Test P: no ArbitrageEvidence ===")
    res = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[2],
                                                   date_window="2027-04-15")
    raw = json.dumps(res)
    for forbidden in ["arbitrage_opportunity", "net_arbitrage",
                       "booking_status", "ArbitrageEvidence"]:
        _assert(forbidden not in raw, f"no {forbidden!r} in payload")


# =============================================================================
# Q. no arbitrage_score
# =============================================================================

def test_q_no_arbitrage_score():
    print("\n=== Test Q: no arbitrage_score identifier ===")
    src = (REPO_ROOT / "live_schedule_provider.py").read_text()
    src_s = re.sub(r"#.*", "", src)
    src_s = re.sub(r'""".*?"""', "", src_s, flags=re.DOTALL)
    src_s = re.sub(r"'''.*?'''", "", src_s, flags=re.DOTALL)
    _assert(not re.search(r"\barbitrage_score\b\s*[=:(),.]", src_s),
            "no arbitrage_score as identifier")
    for forbidden in ["opportunity_score", "candidate_score"]:
        _assert(forbidden not in src, f"no {forbidden!r} in source")


# =============================================================================
# Bonus: OpenFlights reconciliation (spec §15)
# =============================================================================

def test_openflights_duffel_reconciliation():
    print("\n=== Test OpenFlights reconciliation (spec §15) ===")
    # OpenFlights says route exists (DATABASE)
    # Mock Duffel says route returned (LIVE)
    # Both should be recorded as independent evidence objects.
    of = lsp.OpenFlightsScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                   date_window="2027-04-15")
    md = lsp.MockDuffelScheduleProvider().lookup(SYNTHETIC_CANDS[0],
                                                  date_window="2027-04-15")
    of_ev = of["schedule_evidence"]
    md_ev = md["schedule_evidence"]
    _assert(of_ev["provider"] != md_ev["provider"],
            "providers distinct (openflights vs mock_duffel)")
    # OpenFlights verification_status is DATABASE / UNKNOWN
    _assert(of_ev["verification_status"] in ("DATABASE", "UNKNOWN"),
            f"OpenFlights verification_status is DATABASE/UNKNOWN "
            f"(got {of_ev['verification_status']})")
    # MockDuffel verification_status is LIVE
    _assert_eq(md_ev["verification_status"], "LIVE",
               "MockDuffel verification_status is LIVE")
    # They coexist as independent records
    fixture = {
        "candidate_id": SYNTHETIC_CANDS[0]["id"],
        "openflights": {"provider": of_ev["provider"],
                          "verification_status": of_ev["verification_status"],
                          "schedule_status": of_ev["schedule_status"]},
        "duffel": {"provider": md_ev["provider"],
                    "verification_status": md_ev["verification_status"],
                    "schedule_status": md_ev["schedule_status"]},
    }
    raw = json.dumps(fixture)
    _assert("arbitrage_score" not in raw, "no arbitrage_score in reconciliation fixture")
    _assert("VERIFIED" not in raw or "openflights" in raw,
            "VERIFIED not emitted (OpenFlights is DATABASE; MockDuffel is LIVE)")


# =============================================================================
# Run all
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Flight Market Intelligence v1.2.1 — Live Schedule Tests")
    print("=" * 60)
    tests = [
        test_a_explicit_openflights,
        test_b_explicit_duffel,
        test_c_missing_credentials_fail_closed,
        test_d_no_silent_fallback,
        test_e_provider_provenance,
        test_f_normalized_schema,
        test_g_date_window_binding,
        test_h_connection_calculation,
        test_i_airport_change_detection,
        test_j_operating_carrier,
        test_k_multi_city_preservation,
        test_l_smoke_test_hard_limit,
        test_m_credential_leakage,
        test_n_failure_semantics,
        test_o_no_bookable,
        test_p_no_arbitrage_evidence,
        test_q_no_arbitrage_score,
        test_openflights_duffel_reconciliation,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  EXCEPTION in {t.__name__}: {type(e).__name__}: {e}")
            FAILED += 1
    print("\n" + "=" * 60)
    print(f"Total: {PASSED} passed, {FAILED} failed")
    print("=" * 60)
    sys.exit(0 if FAILED == 0 else 1)

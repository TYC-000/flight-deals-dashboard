"""
test_price_intelligence_v1.py — Tests for Price Intelligence v1.1

All tests use mocked provider responses. No real API calls. No credentials required.

Tests (per spec §15):
A.  Provider interface
B.  Duffel response normalization
C.  PriceEvidence schema
D.  Provenance preservation
E.  Freshness calculation
F.  Stale price detection
G.  Currency unknown
H.  Baggage unknown
I.  Multi-ticket
J.  Incomplete multi-ticket
K.  Missing credentials
L.  Rate limiting
M.  Provider timeout
N.  Route unavailable
O.  No fake price
P.  Deterministic search key
Q.  Search budget
R.  Candidate selection
S.  Duplicate request prevention
T.  Trace completeness
U.  No BOOKABLE enum
V.  No ArbitrageEvidence output

Run:
    /Users/aib/.hermes/hermes-agent/venv/bin/python3 test_price_intelligence_v1.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure module importable
REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
sys.path.insert(0, str(REPO_ROOT))
import price_intelligence as pi  # noqa: E402

PYTHON = "/Users/aib/.hermes/hermes-agent/venv/bin/python3"
PASSED = 0
FAILED = 0


def _assert(cond: bool, label: str) -> bool:
    global PASSED, FAILED
    if cond:
        print(f"  PASS: {label}")
        PASSED += 1
        return True
    print(f"  FAIL: {label}")
    FAILED += 1
    return False


def _assert_eq(actual, expected, label: str) -> bool:
    if actual == expected:
        return _assert(True, f"{label} == {expected!r}")
    return _assert(False, f"{label} — expected {expected!r}, got {actual!r}")


def _mock_provider_payload() -> dict:
    """Synthetic Duffel response for tests."""
    return {
        "data": {
            "id": "off_mock_1",
            "expires_at": "2026-09-28T00:00:00Z",
            "type": "single_ticket",
            "total_amount": "1500.00",
            "total_currency": "USD",
            "base_amount": "1275.00",
            "tax_amount": "180.00",
            "owner": {"name": "Test Carrier"},
            "slices": [{
                "origin": "TPE", "destination": "MAD",
                "segments": [{
                    "origin": "TPE", "destination": "MAD",
                    "marketing_carrier": {"iata_code": "MH"},
                    "operating_carrier": {"iata_code": "MH"},
                    "marketing_carrier_flight_number": "MH-100",
                    "departing_at": "2027-04-15T08:00:00",
                    "arriving_at": "2027-04-15T20:00:00",
                    "duration": "PT12H0M",
                }],
                "passengers": [{"cabin": {"cabin_class": "economy"}, "bags": 1}],
            }],
            "passengers": [{"cabin": {"cabin_class": "economy"}, "bags": 1}],
        }
    }


def _mock_provider_no_baggage() -> dict:
    p = _mock_provider_payload()
    # remove 'bags' from passengers
    for s in p["data"]["slices"]:
        for pp in s.get("passengers") or []:
            pp.pop("bags", None)
    p["data"].pop("passengers", None)
    return p


# =============================================================================
# A. Provider interface
# =============================================================================

def test_a_provider_interface():
    print("\n=== Test A: Provider interface ===")
    mock = pi.MockDuffelProvider()
    _assert(hasattr(mock, "name"), "MockDuffelProvider has 'name'")
    _assert_eq(mock.name, "mock_duffel", "name == 'mock_duffel'")
    cap = mock.capabilities()
    _assert(cap.supports_split_ticket is True, "capabilities supports_split_ticket")
    _assert(cap.includes_baggage is True, "capabilities includes_baggage")
    _assert(cap.is_bookable_claim is False, "is_bookable_claim explicitly False (not a VERIFIED wrapper)")
    _assert(mock.health_check() is True, "health_check returns True")


# =============================================================================
# B. Duffel response normalization
# =============================================================================

def test_b_duffel_normalization():
    print("\n=== Test B: Duffel response normalization ===")
    retrieved_at = "2026-09-27T00:00:00Z"
    cand = {
        "id": "AUTO-TPE-MAD",
        "long_haul": {"cabin": "economy"},
        "segments": [
            {"from": "TPE", "to": "MAD", "carrier": "MH", "operating_carrier": "MH", "duration_min": 720}
        ],
    }
    pe = pi.normalize_duffel_response(_mock_provider_payload(), cand, retrieved_at)
    _assert(isinstance(pe, dict), "normalize returns dict")
    _assert_eq(pe["verification_status"], pi.VS_LIVE, "verification_status == LIVE")
    _assert_eq(pe["currency"], "TWD", "normalized to TWD")
    # 1500 USD * 31.85 = 47775 TWD
    _assert(pe["total_price"]["amount"] > 40000 and pe["total_price"]["amount"] < 50000, f"total_price TWD (got {pe['total_price']['amount']})")
    _assert_eq(pe["cabin"], "economy", "cabin detected")
    _assert_eq(pe["ticket_count"], 1, "single_ticket → ticket_count == 1")
    _assert_eq(pe["is_single_ticket"], True, "is_single_ticket True")
    _assert_eq(pe["separate_ticket_risk"], pi.RISK_NONE, "single_ticket → risk none")


# =============================================================================
# C. PriceEvidence schema
# =============================================================================

def test_c_priceevidence_schema():
    print("\n=== Test C: PriceEvidence schema ===")
    pe = pi.normalize_duffel_response(_mock_provider_payload(),
                                       {"id": "X", "long_haul": {"cabin": "economy"},
                                        "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]},
                                       "2026-09-27T00:00:00Z")
    _assert("candidate_id" in pe, "candidate_id present")
    _assert("currency" in pe, "currency present")
    _assert("total_price" in pe, "total_price present")
    _assert("ticket_groups" in pe, "ticket_groups present")
    _assert("verification_status" in pe, "verification_status present")
    fm = pe.get("freshness_min")
    _assert(fm is not None, "freshness_min present")


# =============================================================================
# D. Provenance preservation
# =============================================================================

def test_d_provenance_preservation():
    print("\n=== Test D: provenance preserved ===")
    pe = pi.normalize_duffel_response(_mock_provider_payload(),
                                       {"id": "X", "long_haul": {"cabin": "economy"},
                                        "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]},
                                       "2026-09-27T00:00:00Z")
    _assert("provenance" in pe, "provenance envelope present")
    prov = pe["provenance"]
    _assert("source" in prov, "provenance.source present")
    _assert_eq(prov["verification_status"], pi.VS_LIVE, "provenance.verification_status == LIVE")
    _assert("retrieved_at" in prov, "provenance.retrieved_at present")
    _assert("offer_id" in prov, "provenance.offer_id present")


# =============================================================================
# E. Freshness calculation
# =============================================================================

def test_e_freshness():
    print("\n=== Test E: freshness calculation ===")
    # Recent
    now = "2026-09-27T00:30:00Z"
    recent = "2026-09-27T00:00:00Z"
    f = pi.compute_freshness_min(recent, now=__import__("datetime").datetime.fromisoformat(now))
    _assert_eq(f, 30, "freshness_min for 30 min gap")
    _assert_eq(pi.freshness_bucket_from_min(5), pi.FreshnessBucket.RECENT, "5 min → RECENT")
    _assert_eq(pi.freshness_bucket_from_min(120), pi.FreshnessBucket.WARM, "120 min → WARM")
    _assert_eq(pi.freshness_bucket_from_min(500), pi.FreshnessBucket.COLD, "500 min → COLD")
    _assert_eq(pi.freshness_bucket_from_min(1500), pi.FreshnessBucket.EXPIRED, "1500 min → EXPIRED")
    _assert_eq(pi.freshness_bucket_from_min(-1), pi.FreshnessBucket.UNKNOWN, "negative → UNKNOWN")


# =============================================================================
# F. Stale price detection
# =============================================================================

def test_f_stale_price():
    print("\n=== Test F: stale price detection ===")
    # Force stale by setting retrieved_at 5 days ago
    mock = pi.MockDuffelProvider()
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}
    os.environ["SIMULATE_STALE_PRICE"] = "1"
    try:
        result = mock.quote(cand, date_window="2027-04-15")
        _assert(result.get("success"), "mock still returns success under STALE")
        pe = result["price_evidence"]
        # freshness_min should be ~5 days = 7200
        _assert(pe["freshness_min"] >= 24 * 60, f"stale freshness_min >= 1 day (got {pe['freshness_min']})")
        _assert_eq(pe["freshness_bucket"], pi.FreshnessBucket.EXPIRED, "stale → EXPIRED bucket")
        _assert(pi.FK_STALE_PRICE in pe["warnings"], "STALE_PRICE warning")
    finally:
        os.environ.pop("SIMULATE_STALE_PRICE", None)


# =============================================================================
# G. Currency unknown
# =============================================================================

def test_g_currency_unknown():
    print("\n=== Test G: CURRENCY_UNKNOWN ===")
    mock = pi.MockDuffelProvider()
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}
    os.environ["SIMULATE_CURRENCY_UNKNOWN"] = "1"
    try:
        result = mock.quote(cand, date_window="2027-04-15")
        _assert_eq(result.get("failure_kind"), pi.FK_CURRENCY_UNKNOWN, "failure_kind == CURRENCY_UNKNOWN")
        _assert(result.get("price_evidence") is None, "no price evidence on CURRENCY_UNKNOWN")
        _assert(pi.FK_CURRENCY_UNKNOWN in pi.FAILURE_KINDS_REFUSE_COMPARISON, "in refuse-comparison set")
    finally:
        os.environ.pop("SIMULATE_CURRENCY_UNKNOWN", None)


# =============================================================================
# H. Baggage unknown
# =============================================================================

def test_h_baggage_unknown():
    print("\n=== Test H: BAGGAGE_UNKNOWN ===")
    # Use the no-baggage payload directly
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}
    pe = pi.normalize_duffel_response(_mock_provider_no_baggage(), cand, "2026-09-27T00:00:00Z")
    _assert_eq(pe["verification_status"], pi.VS_LIVE, "still LIVE despite baggage unknown")
    _assert(pe.get("total_price", {}).get("amount") is not None, "price still emitted (warning, not block)")
    _assert(pi.CR_BAGGAGE_UNKNOWN in pe["confidence_reasons"], "BAGGAGE_UNKNOWN in confidence reasons")
    _assert(pi.FK_BAGGAGE_UNKNOWN in pe["warnings"], "BAGGAGE_UNKNOWN in warnings")


# =============================================================================
# I. Multi-ticket
# =============================================================================

def test_i_multi_ticket():
    print("\n=== Test I: multi-ticket ===")
    # Use a split_ticket Duffel response
    raw = {
        "data": {
            "id": "off_split_1", "type": "split_ticket",
            "expires_at": "2026-09-28T00:00:00Z",
            "total_amount": "2200.00", "total_currency": "USD",
            "base_amount": "1870.00", "tax_amount": "264.00",
            "slices": [
                {"origin": "TPE", "destination": "KUL",
                 "segments": [{"origin": "TPE", "destination": "KUL",
                               "marketing_carrier": {"iata_code": "D7"},
                               "operating_carrier": {"iata_code": "D7"},
                               "marketing_carrier_flight_number": "D7-371",
                               "departing_at": "2027-04-15T08:00:00",
                               "arriving_at": "2027-04-15T13:00:00",
                               "duration": "PT5H0M"}],
                 "passengers": [{"cabin": {"cabin_class": "economy"}, "bags": 1}]},
                {"origin": "KUL", "destination": "MAD",
                 "segments": [{"origin": "KUL", "destination": "MAD",
                               "marketing_carrier": {"iata_code": "QR"},
                               "operating_carrier": {"iata_code": "QR"},
                               "marketing_carrier_flight_number": "QR-149",
                               "departing_at": "2027-04-15T15:00:00",
                               "arriving_at": "2027-04-16T05:00:00",
                               "duration": "PT14H0M"}],
                 "passengers": [{"cabin": {"cabin_class": "economy"}, "bags": 1}]},
            ],
            "passengers": [{"cabin": {"cabin_class": "economy"}, "bags": 1}],
        }
    }
    cand = {"id": "AUTO-multi_ticket-TPE-KUL-MAD",
            "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"},
                         {"from": "KUL", "to": "MAD", "carrier": "QR"}]}
    pe = pi.normalize_duffel_response(raw, cand, "2026-09-27T00:00:00Z")
    _assert_eq(pe["ticket_count"], 2, "ticket_count == 2")
    _assert_eq(pe["is_single_ticket"], False, "is_single_ticket False")
    _assert_eq(len(pe["ticket_groups"]), 2, "ticket_groups has 2 entries")
    _assert_eq(pe["self_transfer"], False, "self_transfer False (same airport KUL)")
    _assert_eq(pe["separate_ticket_risk"], pi.RISK_ELEVATED, "split_ticket → elevated")


# =============================================================================
# J. Incomplete multi-ticket
# =============================================================================

def test_j_incomplete_multi_ticket():
    print("\n=== Test J: incomplete multi-ticket ===")
    mock = pi.MockDuffelProvider()
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"},
                         {"from": "KUL", "to": "MAD", "carrier": "QR"}]}
    os.environ["SIMULATE_MULTI_INCOMPLETE"] = "1"
    try:
        result = mock.quote(cand, date_window="2027-04-15")
        _assert(result.get("success"), "still emits evidence under MULTI_INCOMPLETE")
        pe = result["price_evidence"]
        _assert(pi.CR_MULTI_TICKET_PARTIAL in pe["confidence_reasons"], "MULTI_TICKET_PARTIAL in reasons")
        _assert(pi.FK_MULTI_TICKET_PRICE_INCOMPLETE in pe["warnings"], "warning emitted")
    finally:
        os.environ.pop("SIMULATE_MULTI_INCOMPLETE", None)


# =============================================================================
# K. Missing credentials
# =============================================================================

def test_k_missing_credentials():
    print("\n=== Test K: MISSING_CREDENTIALS ===")
    # Use MockDuffelProvider as a stand-in; simulate via env flag
    mock = pi.MockDuffelProvider()
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}
    # Real DuffelProvider: no env var set
    saved = os.environ.pop("DUFFEL_API_KEY_LIVE", None)
    os.environ.pop("DUFFEL_API_KEY_TEST", None)
    try:
        # Try to construct → should fail closed
        try:
            dp = pi.DuffelProvider()
            raised = False
        except RuntimeError as e:
            raised = True
            _assert_eq(str(e), pi.FK_MISSING_CREDENTIALS, "constructor raises MISSING_CREDENTIALS")
        _assert(raised, "DuffelProvider raises without credentials")
    finally:
        if saved:
            os.environ["DUFFEL_API_KEY_LIVE"] = saved
    _assert_eq(pi.FK_MISSING_CREDENTIALS, "MISSING_CREDENTIALS", "FK constant matches spec")
    _assert(pi.FK_MISSING_CREDENTIALS in pi.FAILURE_KINDS_REFUSE_COMPARISON, "in refuse set")


# =============================================================================
# L. Rate limiting
# =============================================================================

def test_l_rate_limiting():
    print("\n=== Test L: RATE_LIMITED ===")
    mock = pi.MockDuffelProvider()
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}
    os.environ["SIMULATE_RATE_LIMITED"] = "1"
    try:
        result = mock.quote(cand, date_window="2027-04-15")
        _assert_eq(result.get("failure_kind"), pi.FK_RATE_LIMITED, "failure_kind == RATE_LIMITED")
        _assert(result.get("price_evidence") is None, "no price on RATE_LIMITED")
        _assert(pi.FK_RATE_LIMITED in pi.FAILURE_KINDS_REFUSE_COMPARISON, "in refuse set")
    finally:
        os.environ.pop("SIMULATE_RATE_LIMITED", None)


# =============================================================================
# M. Provider timeout
# =============================================================================

def test_m_provider_timeout():
    print("\n=== Test M: PROVIDER_TIMEOUT ===")
    mock = pi.MockDuffelProvider()
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}
    os.environ["SIMULATE_PROVIDER_TIMEOUT"] = "1"
    try:
        result = mock.quote(cand, date_window="2027-04-15")
        _assert_eq(result.get("failure_kind"), pi.FK_PROVIDER_TIMEOUT, "failure_kind == PROVIDER_TIMEOUT")
    finally:
        os.environ.pop("SIMULATE_PROVIDER_TIMEOUT", None)


# =============================================================================
# N. Route unavailable
# =============================================================================

def test_n_route_unavailable():
    print("\n=== Test N: ROUTE_UNAVAILABLE ===")
    mock = pi.MockDuffelProvider()
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}
    os.environ["SIMULATE_ROUTE_UNAVAILABLE"] = "1"
    try:
        result = mock.quote(cand, date_window="2027-04-15")
        _assert_eq(result.get("failure_kind"), pi.FK_ROUTE_UNAVAILABLE, "failure_kind == ROUTE_UNAVAILABLE")
        _assert(pi.FK_ROUTE_UNAVAILABLE in pi.FAILURE_KINDS_REFUSE_COMPARISON, "in refuse set")
    finally:
        os.environ.pop("SIMULATE_ROUTE_UNAVAILABLE", None)


# =============================================================================
# O. No fake price
# =============================================================================

def test_o_no_fake_price():
    print("\n=== Test O: no fake price ===")
    # Empty segments → no fabrication
    result = pi.build_failure_result(pi.FK_PRICE_NOT_FOUND, "2026-09-27T00:00:00Z")
    _assert_eq(result.get("price_evidence"), None, "no price evidence in failure result")
    _assert_eq(result.get("success"), False, "failure result is not successful")


# =============================================================================
# P. Deterministic search key
# =============================================================================

def test_p_deterministic_search_key():
    print("\n=== Test P: deterministic search key ===")
    cand = {"id": "X", "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"}]}
    k1 = pi.make_search_key(cand, "2027-04-15", 1)
    k2 = pi.make_search_key(cand, "2027-04-15", 1)
    _assert_eq(k1, k2, "same input → same search key")
    k3 = pi.make_search_key(cand, "2027-04-16", 1)
    _assert(k1 != k3, "different date → different key")


# =============================================================================
# Q. Search budget
# =============================================================================

def test_q_search_budget():
    print("\n=== Test Q: search budget ===")
    budget = pi.SearchBudget(max_searches=3)
    _assert_eq(budget.budget_remaining(), 3, "initial budget")
    cand = {"id": "X"}
    for i in range(3):
        result = pi.build_failure_result(pi.FK_PRICE_NOT_FOUND, "2026-09-27T00:00:00Z")
        budget.record(pi.make_search_key(cand, "2027-04-15", 1), result, cand["id"])
    _assert_eq(budget.budget_remaining(), 0, "budget depleted after 3 queries")
    _assert(not budget.can_attempt(), "can_attempt False after budget")


# =============================================================================
# R. Candidate selection
# =============================================================================

def test_r_candidate_selection():
    print("\n=== Test R: candidate selection ===")
    cands = [
        {"id": "A", "segments": [{"from": "TPE", "to": "KUL"}],
         "schedule_intelligence": {"schedule_status": "SUPPORTED", "structural_signals": ["outer_port"]}},
        {"id": "B", "segments": [{"from": "TPE", "to": "MAD"}],
         "schedule_intelligence": {"schedule_status": "UNAVAILABLE", "structural_signals": []}},
        {"id": "C", "segments": [{"from": "TPE", "to": "KUL"}] * 4,
         "schedule_intelligence": {"schedule_status": "SUPPORTED", "structural_signals": ["multi_ticket"]}},
    ]
    lookup = lambda cid: {"A": cands[0]["schedule_intelligence"],
                          "B": cands[1]["schedule_intelligence"],
                          "C": cands[2]["schedule_intelligence"]}.get(cid, {})
    selected = pi.select_candidates(cands, max_searches=3, schedule_enrichment_lookup=lookup)
    _assert_eq(len(selected), 3, "all 3 selected")
    # A and C are tied in base signals; C wins because multi_ticket (+6) > outer_port (+4)
    # when both have 1 effective segment penalty. C has 4 segments though, so -1.5 penalty.
    # C total: 10 + 6 - 1.5 = 14.5, A total: 10 + 4 = 14. So C first.
    _assert_eq(selected[0]["id"], "C", "C is first (highest score: SUPPORTED + multi_ticket)")
    # B should be last (UNAVAILABLE)
    _assert_eq(selected[-1]["id"], "B", "B is last (UNAVAILABLE)")


# =============================================================================
# S. Duplicate request prevention (memoization)
# =============================================================================

def test_s_duplicate_request_prevention():
    print("\n=== Test S: duplicate request prevention ===")
    cands = [{"id": "A", "long_haul": {"cabin": "economy"},
              "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}]
    provider = pi.MockDuffelProvider()
    pi_evidences, summary, budget = pi.run_price_intelligence(
        candidates=cands, provider=provider,
        max_searches=10, date_window="2027-04-15", passengers=1,
        use_schedule_signals=False,
    )
    _assert_eq(summary["search_budget_used"], 1, "1 search used")
    _assert_eq(summary["candidates_with_evidence"], 1, "1 evidence")

    # Now try selecting same candidate twice via parallel selections
    cands2 = [cands[0], cands[0]]  # same id may dedup at selection? No — we pass both
    pi_evidences2, summary2, budget2 = pi.run_price_intelligence(
        candidates=cands2, provider=provider,
        max_searches=10, date_window="2027-04-15", passengers=1,
        use_schedule_signals=False,
    )
    _assert_eq(summary2["search_cache_hits"], 1, "second iteration is cache hit")


# =============================================================================
# T. Trace completeness
# =============================================================================

def test_t_trace_completeness():
    print("\n=== Test T: trace completeness ===")
    cands_path = REPO_ROOT / "data" / "flight_candidates.json"
    if not cands_path.exists():
        print(f"  SKIP: no flight_candidates.json")
        return
    cands = json.loads(cands_path.read_text())[:5]
    provider = pi.MockDuffelProvider()
    evidences, summary, budget = pi.run_price_intelligence(
        candidates=cands, provider=provider,
        max_searches=10, date_window="2027-04-15", passengers=1,
        use_schedule_signals=False,
    )
    candidates_by_id = {c.get("id"): c for c in cands}
    records = pi.build_trace_records(evidences, budget, candidates_by_id, provider.name)
    _assert(len(records) >= 1, "trace records produced")
    required_fields = ["candidate_id", "provider", "request_key", "request_time",
                       "response_time", "price_found", "price_status",
                       "verification_status", "retrieved_at", "expires_at",
                       "freshness", "ticket_count", "currency", "total_price",
                       "failure_reason", "warnings", "failure_kind"]
    rec = records[0]
    for f in required_fields:
        _assert(f in rec, f"trace field {f!r} present")
    # No secrets in trace
    raw = json.dumps(records)
    _assert("Bearer" not in raw and "DUFFEL_API" not in raw, "trace has no secrets")


# =============================================================================
# U. No BOOKABLE enum
# =============================================================================

def test_u_no_bookable_enum():
    print("\n=== Test U: no BOOKABLE enum ===")
    # All in pi.VERIFICATION_STATUSES
    _assert("BOOKABLE" not in pi.VERIFICATION_STATUSES, "BOOKABLE not in valid statuses")
    _assert("BOOKABLE" in pi.FORBIDDEN_VERIFICATION_VALUES, "BOOKABLE in forbidden set")
    # The set itself is opaque; the test is that BOOKABLE doesn't accidentally appear
    forbidden_in_set = "BOOKABLE" in {pi.VS_UNKNOWN, pi.VS_ESTIMATED, pi.VS_DATABASE, pi.VS_LIVE, pi.VS_VERIFIED}
    _assert(not forbidden_in_set, "BOOKABLE not accidentally wired into the constant set")


# =============================================================================
# V. No ArbitrageEvidence output
# =============================================================================

def test_v_no_arbitrage_output():
    print("\n=== Test V: no ArbitrageEvidence output ===")
    pe = pi.normalize_duffel_response(_mock_provider_payload(),
                                       {"id": "X", "long_haul": {"cabin": "economy"},
                                        "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]},
                                       "2026-09-27T00:00:00Z")
    raw = json.dumps(pe)
    _assert("arbitrage_score" not in raw, "no arbitrage_score in payload")
    _assert("arbitrage_opportunity" not in raw, "no arbitrage_opportunity in payload")
    _assert("net_arbitrage" not in raw, "no net_arbitrage in payload")
    _assert("booking_status" not in raw, "no booking_status in payload")


# =============================================================================
# Bonus test — comparison rules
# =============================================================================

def test_w_comparison_rules():
    print("\n=== Test W (bonus): comparison rules ===")
    a = {"currency": "TWD", "verification_status": pi.VS_LIVE,
         "freshness_min": 5, "total_price": {"amount": 1000.0},
         "ticket_count": 1, "failure_kind": None,
         "price_evidence": {"cabin": "economy"}}
    b = {"currency": "TWD", "verification_status": pi.VS_LIVE,
         "freshness_min": 7, "total_price": {"amount": 1100.0},
         "ticket_count": 1, "failure_kind": None,
         "price_evidence": {"cabin": "economy"}}
    res = pi.price_comparison(a, b)
    _assert(res.comparable, "two LIVE comparable prices are comparable")
    _assert_eq(res.a_less_than_b, True, "1000 < 1100")

    # Mismatched currency
    c = dict(b); c["currency"] = "USD"
    res2 = pi.price_comparison(a, c)
    _assert(not res2.comparable, "mismatched currency refuses comparison")

    # Mismatched ticket_count
    d = dict(b); d["ticket_count"] = 2
    res3 = pi.price_comparison(a, d)
    _assert(not res3.comparable, "mismatched ticket_count refuses direct compare")

    # One is UNKNOWN
    e = dict(a); e["verification_status"] = pi.VS_UNKNOWN
    res4 = pi.price_comparison(a, e)
    _assert(not res4.comparable, "UNKNOWN verification refuses comparison")


# =============================================================================
# Run all
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Flight Market Intelligence v1.1 — Price Intelligence Tests")
    print("=" * 60)
    tests = [
        test_a_provider_interface,
        test_b_duffel_normalization,
        test_c_priceevidence_schema,
        test_d_provenance_preservation,
        test_e_freshness,
        test_f_stale_price,
        test_g_currency_unknown,
        test_h_baggage_unknown,
        test_i_multi_ticket,
        test_j_incomplete_multi_ticket,
        test_k_missing_credentials,
        test_l_rate_limiting,
        test_m_provider_timeout,
        test_n_route_unavailable,
        test_o_no_fake_price,
        test_p_deterministic_search_key,
        test_q_search_budget,
        test_r_candidate_selection,
        test_s_duplicate_request_prevention,
        test_t_trace_completeness,
        test_u_no_bookable_enum,
        test_v_no_arbitrage_output,
        test_w_comparison_rules,
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

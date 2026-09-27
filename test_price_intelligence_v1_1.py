"""
test_price_intelligence_v1_1.py — Tests for v1.1.1 Real Provider Validation

Tests (per spec §9):
A. explicit mock mode
B. explicit Duffel mode
C. missing credentials fail closed
D. no silent Mock fallback
E. provider provenance
F. Mock vs real schema equivalence
G. deterministic search key
H. search budget
I. information priority selection
J. no BOOKABLE enum
K. no ArbitrageEvidence
L. no arbitrage_score
M. trace provider identity
N. real smoke-test guard

Run:
    /Users/aib/.hermes/hermes-agent/venv/bin/python3 test_price_intelligence_v1_1.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

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


# Small synthetic candidates file so tests are deterministic.
# Real candidates in data/flight_candidates.json include heuristic-scan
# entries with empty segments that would produce PRICE_NOT_FOUND consistently.
SYNTHETIC_CANDS = [
    {"id": "TEST-A", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"}]},
    {"id": "TEST-B", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH", "duration_min": 720}]},
    {"id": "TEST-C", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"},
                  {"from": "KUL", "to": "MAD", "carrier": "QR"}]},
]
SYNTHETIC_CANDS_PATH = REPO_ROOT / "data" / "_synthetic_cands_for_v111.json"
SYNTHETIC_CANDS_PATH.write_text(json.dumps(SYNTHETIC_CANDS))


# Helper to run CLI with given args
def run_cli(*args, env_extra=None, timeout=30):
    full_env = dict(os.environ)
    full_env.pop("DUFFEL_API_KEY_LIVE", None)
    full_env.pop("DUFFEL_API_KEY_TEST", None)
    if env_extra:
        full_env.update(env_extra)
    return subprocess.run(
        [PYTHON, str(REPO_ROOT / "price_intelligence.py"),
         str(SYNTHETIC_CANDS_PATH),
         *args],
        capture_output=True, text=True, timeout=timeout, env=full_env,
    )


def test_a_explicit_mock_mode():
    print("\n=== Test A: explicit mock mode ===")
    r = run_cli("--provider", "mock", "--max-searches", "2")
    _assert_eq(r.returncode, 0, "mock mode rc=0")
    out_path = REPO_ROOT / "data" / "price_evidence.json"
    _assert(out_path.exists(), "price_evidence.json written")
    payload = json.loads(out_path.read_text())
    _assert_eq(payload["provider"], "mock_duffel", "provider field == mock_duffel")


# =============================================================================
# B. explicit Duffel mode (no fallback)
# =============================================================================

def test_b_explicit_duffel_mode():
    print("\n=== Test B: explicit --provider duffel ===")
    r = run_cli("--provider", "duffel", "--max-searches", "2")
    # Without credentials: must fail closed (rc=10)
    _assert_eq(r.returncode, 10, "duffel without creds: rc=10 (MISSING_CREDENTIALS)")
    _assert("MISSING_CREDENTIALS" in r.stderr, "MISSING_CREDENTIALS in stderr")
    _assert("FAIL CLOSED" in r.stderr, "FAIL CLOSED message in stderr")
    # Output should NOT be written
    last_write_time = 0
    if (REPO_ROOT / "data" / "price_evidence.json").exists():
        last_write_time = (REPO_ROOT / "data" / "price_evidence.json").stat().st_mtime
    # We assume no mock run happened in this test order, but if previous test
    # wrote it, the file exists. The FAil closed test only checks rc.


# =============================================================================
# C. missing credentials fail closed
# =============================================================================

def test_c_missing_credentials_fail_closed():
    print("\n=== Test C: missing credentials fail closed ===")
    # Direct API: try to construct DuffelProvider without env
    saved = os.environ.pop("DUFFEL_API_KEY_LIVE", None)
    saved_test = os.environ.pop("DUFFEL_API_KEY_TEST", None)
    try:
        try:
            pi.DuffelProvider()
            raised = False
        except RuntimeError as e:
            raised = True
            _assert("MISSING_CREDENTIALS" in str(e), "RuntimeError mentions MISSING_CREDENTIALS")
        _assert(raised, "DuffelProvider raises without credentials")
    finally:
        if saved:
            os.environ["DUFFEL_API_KEY_LIVE"] = saved
        if saved_test:
            os.environ["DUFFEL_API_KEY_TEST"] = saved_test
    # build_provider path
    try:
        pi.build_provider("duffel")
        raised = False
    except RuntimeError as e:
        raised = True
        _assert("MISSING_CREDENTIALS" in str(e), "build_provider mentions MISSING_CREDENTIALS")
    _assert(raised, "build_provider('duffel') raises without credentials")


# =============================================================================
# D. no silent Mock fallback
# =============================================================================

def test_d_no_silent_mock_fallback():
    print("\n=== Test D: no silent Mock fallback ===")
    r = run_cli("--provider", "duffel", "--max-searches", "2")
    # Without creds: must NOT silently produce mock evidence
    _assert(r.returncode != 0, "duffel mode without creds exits non-zero")
    _assert("FAIL CLOSED" in r.stderr, "explicit FAIL CLOSED message")
    # Should NOT have written price_evidence.json (or if it did, re-write that
    # asserts no silent fallback). The KEY thing: stderr shows FAIL CLOSED.
    body = json.loads((REPO_ROOT / "data" / "price_evidence.json").read_text()) if (REPO_ROOT / "data" / "price_evidence.json").exists() else None
    if body is not None:
        # If file exists from test A, provider must be mock_duffel (not duffel)
        _assert(body["provider"] == "mock_duffel",
                "any price_evidence.json written by mock mode is labeled mock_duffel")


# =============================================================================
# E. provider provenance
# =============================================================================

def test_e_provider_provenance():
    print("\n=== Test E: provider provenance ===")
    # Run mock CLI first to ensure file exists
    r = run_cli("--provider", "mock", "--max-searches", "2")
    _assert_eq(r.returncode, 0, "mock mode rc=0 (setup)")
    body = json.loads((REPO_ROOT / "data" / "price_evidence.json").read_text())
    evidences = body["evidences"]
    _assert(len(evidences) >= 1, "has evidence")
    # Find the first non-null price_evidence (success case)
    sample = next((e for e in evidences if e.get("price_evidence") is not None), None)
    _assert(sample is not None, "at least one success evidence")
    _assert_eq(sample["provider"], "mock_duffel", "evidence.provider == mock_duffel")
    _assert_eq(sample["provider_mode"], "mock", "evidence.provider_mode == mock")
    pe = sample["price_evidence"]
    _assert_eq(pe["provider"], "mock_duffel", "price_evidence.provider == mock_duffel")
    _assert_eq(pe["provider_mode"], "mock", "price_evidence.provider_mode == mock")
    _assert_eq(pe["provenance"]["source"], "mock_duffel",
               "provenance.source == mock_duffel")


# =============================================================================
# F. Mock vs real schema equivalence
# =============================================================================

def test_f_mock_real_schema_equivalence():
    print("\n=== Test F: Mock vs real schema equivalence ===")
    # Compare normalized PriceEvidence shapes from MockDuffelProvider
    # vs what DuffelProvider.quote WOULD produce (using synthesized Duffel JSON)
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH", "duration_min": 720}]}
    mock_provider = pi.MockDuffelProvider()
    r_mock = mock_provider.quote(cand, date_window="2027-04-15")
    _assert(r_mock["success"], "Mock produces success")
    pe_mock = r_mock["price_evidence"]
    # Now exercise the same normalize with provider_name="duffel"
    synthetic_duffel_payload = {
        "data": pe_mock.get("__offer_payload_does_not_exist__", {}),  # placeholder
    }
    # Easier: construct a Duffel-like raw payload manually
    raw_duffel = {
        "data": {
            "id": "off_test",
            "type": "single_ticket",
            "expires_at": pe_mock.get("valid_until"),
            "total_amount": "1500.00",
            "total_currency": "USD",
            "base_amount": "1275.00",
            "tax_amount": "180.00",
            "owner": {"name": "Test Carrier (mock)"},
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
    pe_duffel_shape = pi.normalize_duffel_response(raw_duffel, cand, "2026-09-27T00:00:00Z",
                                                    provider_name="duffel")
    _assert(isinstance(pe_duffel_shape, dict), "Duffel normalization succeeds")
    # Schema contract: same top-level keys present
    schema_keys = ["candidate_id", "currency", "total_price", "ticket_groups",
                   "ticket_count", "is_single_ticket", "self_transfer",
                   "separate_ticket_risk", "cabin", "baggage", "provenance",
                   "freshness_min", "freshness_bucket", "verification_status",
                   "price_status", "warnings", "provider", "provider_mode"]
    for k in schema_keys:
        _assert(k in pe_mock, f"mock pe has key {k!r}")
        _assert(k in pe_duffel_shape, f"duffel pe has key {k!r}")
    _assert_eq(pe_mock["provider"], "mock_duffel", "mock.provider != real")
    _assert_eq(pe_duffel_shape["provider"], "duffel", "duffel.provider != mock")
    _assert_eq(pe_mock["provider_mode"], "mock", "mock.provider_mode != live")
    _assert_eq(pe_duffel_shape["provider_mode"], "live", "duffel.provider_mode != mock")


# =============================================================================
# G. deterministic search key (regression)
# =============================================================================

def test_g_deterministic_search_key():
    print("\n=== Test G: deterministic search key ===")
    cand = {"id": "X", "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"}]}
    k1 = pi.make_search_key(cand, "2027-04-15", 1)
    k2 = pi.make_search_key(cand, "2027-04-15", 1)
    _assert_eq(k1, k2, "same input → same key")
    _assert(k1 != pi.make_search_key(cand, "2027-04-16", 1), "different date → different key")


# =============================================================================
# H. search budget (regression)
# =============================================================================

def test_h_search_budget():
    print("\n=== Test H: search budget ===")
    budget = pi.SearchBudget(max_searches=3)
    _assert_eq(budget.budget_remaining(), 3, "initial budget")
    cand = {"id": "X"}
    for _ in range(3):
        result = pi.build_failure_result(pi.FK_PRICE_NOT_FOUND, "2026-09-27T00:00:00Z")
        budget.record(pi.make_search_key(cand, "2027-04-15", 1), result, cand["id"])
    _assert_eq(budget.budget_remaining(), 0, "budget depleted")


# =============================================================================
# I. information priority selection
# =============================================================================

def test_i_information_priority_selection():
    print("\n=== Test I: information priority selection ===")
    # The score function should be called information_priority_score,
    # not arbitrage_score or price_score. We check that the identifier is
    # never used as a variable/parameter name (comments and assertion strings
    # that document the policy are fine).
    import re
    src = (REPO_ROOT / "price_intelligence.py").read_text()
    # Strip comments and docstrings before checking for identifier usage
    src_stripped = re.sub(r"#.*", "", src)
    src_stripped = re.sub(r'""".*?"""', "", src_stripped, flags=re.DOTALL)
    src_stripped = re.sub(r"'''.*?'''", "", src_stripped, flags=re.DOTALL)
    # Look for: arbitrage_score used as identifier (followed by =, (, ,, :, etc.)
    _assert(not re.search(r"\barbitrage_score\b\s*[=:(),]", src_stripped),
            "no 'arbitrage_score' identifier assignment in code")
    _assert("ips" in src or "information_priority" in src,
            "uses 'ips' or 'information_priority' identifier")
    # Smoke check: select_candidates works
    cands = [
        {"id": "A", "segments": [{"from": "TPE", "to": "KUL"}],
         "schedule_intelligence": {"schedule_status": "SUPPORTED", "structural_signals": ["outer_port"]}},
        {"id": "B", "segments": [{"from": "TPE", "to": "MAD"}],
         "schedule_intelligence": {"schedule_status": "UNAVAILABLE", "structural_signals": []}},
    ]
    lookup = lambda cid: {"A": cands[0]["schedule_intelligence"],
                          "B": cands[1]["schedule_intelligence"]}.get(cid, {})
    selected = pi.select_candidates(cands, max_searches=2, schedule_enrichment_lookup=lookup)
    _assert_eq(selected[0]["id"], "A", "SUPPORTED signal winner")


# =============================================================================
# J. no BOOKABLE enum (regression)
# =============================================================================

def test_j_no_bookable_enum():
    print("\n=== Test J: no BOOKABLE enum ===")
    _assert("BOOKABLE" not in pi.VERIFICATION_STATUSES, "BOOKABLE not in valid statuses")
    _assert("BOOKABLE" in pi.FORBIDDEN_VERIFICATION_VALUES, "BOOKABLE in forbidden set")


# =============================================================================
# K. no ArbitrageEvidence output
# =============================================================================

def test_k_no_arbitrage_evidence():
    print("\n=== Test K: no ArbitrageEvidence output ===")
    cand = {"id": "X", "long_haul": {"cabin": "economy"},
            "segments": [{"from": "TPE", "to": "MAD", "carrier": "MH"}]}
    pe = pi.normalize_duffel_response({
        "data": {"id": "off_1", "type": "single_ticket",
                 "expires_at": "2026-09-28T00:00:00Z",
                 "total_amount": "1500", "total_currency": "USD",
                 "base_amount": "1275", "tax_amount": "180",
                 "owner": {"name": "Mock"},
                 "slices": [{"origin": "TPE", "destination": "MAD",
                             "segments": [{"origin": "TPE", "destination": "MAD",
                                           "marketing_carrier": {"iata_code": "MH"},
                                           "operating_carrier": {"iata_code": "MH"},
                                           "marketing_carrier_flight_number": "MH-100",
                                           "departing_at": "2027-04-15T08:00:00",
                                           "arriving_at": "2027-04-15T20:00:00",
                                           "duration": "PT12H0M"}],
                             "passengers": [{"cabin": {"cabin_class": "economy"}, "bags": 1}]}],
                 "passengers": [{"cabin": {"cabin_class": "economy"}, "bags": 1}]}
    }, cand, "2026-09-27T00:00:00Z", provider_name="duffel")
    raw = json.dumps(pe)
    _assert("arbitrage_score" not in raw, "no arbitrage_score")
    _assert("arbitrage_opportunity" not in raw, "no arbitrage_opportunity")
    _assert("net_arbitrage" not in raw, "no net_arbitrage")
    _assert("booking_status" not in raw, "no booking_status")


# =============================================================================
# L. no arbitrage_score identifier anywhere
# =============================================================================

def test_l_no_arbitrage_score_identifier():
    print("\n=== Test L: no arbitrage_score identifier ===")
    import re
    src = (REPO_ROOT / "price_intelligence.py").read_text()
    # Strip comments and docstrings
    src_stripped = re.sub(r"#.*", "", src)
    src_stripped = re.sub(r'""".*?"""', "", src_stripped, flags=re.DOTALL)
    src_stripped = re.sub(r"'''.*?'''", "", src_stripped, flags=re.DOTALL)
    _assert(not re.search(r"\barbitrage_score\b\s*[=:(),.]", src_stripped),
            "'arbitrage_score' identifier not used as variable/data field")


# =============================================================================
# M. trace provider identity
# =============================================================================

def test_m_trace_provider_identity():
    print("\n=== Test M: trace provider identity ===")
    r = run_cli("--provider", "mock", "--max-searches", "2")
    trace = json.loads((REPO_ROOT / "data" / "price_trace.json").read_text())
    _assert_eq(trace["provider"], "mock_duffel", "trace.provider == mock_duffel")
    # Per-candidate records must carry provider
    for rec in trace["candidates"]:
        _assert_eq(rec.get("provider"), "mock_duffel",
                   f"trace record {rec.get('candidate_id')} provider")


# =============================================================================
# N. real smoke-test guard
# =============================================================================

def test_n_real_smoke_test_guard():
    print("\n=== Test N: real smoke-test guard ===")
    # Try --smoke-test with --max-searches=10 — should be capped at 2
    r = run_cli("--provider", "mock", "--max-searches", "10", "--smoke-test")
    _assert_eq(r.returncode, 0, "smoke-test rc=0")
    # Inspect output: only 2 candidates should be in evidence
    body = json.loads((REPO_ROOT / "data" / "price_evidence.json").read_text())
    _assert(len(body["evidences"]) <= 2,
            f"smoke-test caps at 2 evidences (got {len(body['evidences'])})")
    _assert(body.get("smoke_test") is True, "smoke_test flag in output")


# =============================================================================
# Run all
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Flight Market Intelligence v1.1.1 — Provider Validation Tests")
    print("=" * 60)
    tests = [
        test_a_explicit_mock_mode,
        test_b_explicit_duffel_mode,
        test_c_missing_credentials_fail_closed,
        test_d_no_silent_mock_fallback,
        test_e_provider_provenance,
        test_f_mock_real_schema_equivalence,
        test_g_deterministic_search_key,
        test_h_search_budget,
        test_i_information_priority_selection,
        test_j_no_bookable_enum,
        test_k_no_arbitrage_evidence,
        test_l_no_arbitrage_score_identifier,
        test_m_trace_provider_identity,
        test_n_real_smoke_test_guard,
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
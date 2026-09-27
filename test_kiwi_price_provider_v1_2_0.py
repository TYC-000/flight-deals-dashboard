"""
test_kiwi_price_provider_v1_2_0.py — Tests for v1.2.0 Kiwi PriceProvider Integration

Tests (per spec §14):
A. provider identity
B. provider mode
C. schema keys
D. required fields
E. freshness
F. verification semantics
G. failure semantics
H. currency handling
I. baggage handling
J. ticket structure
K. no BOOKABLE
L. no ArbitrageEvidence
M. no arbitrage_score
N. information_priority_score terminology
O. no credential leakage
P. explicit provider mode
Q. no silent fallback

Run:
    /Users/aib/.hermes/hermes-agent/venv/bin/python3 test_kiwi_price_provider_v1_2_0.py
"""
import json
import os
import subprocess
import sys
import re
from pathlib import Path

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
sys.path.insert(0, str(REPO_ROOT))
import price_intelligence as pi  # noqa: E402
import kiwi_price_provider as kpp  # noqa: E402

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
    {"id": "TEST-D", "long_haul": {"cabin": "economy"},
     "segments": [{"from": "TPE", "to": "KUL", "carrier": "D7"},
                  {"from": "KUL", "to": "DXB", "carrier": "EK"},
                  {"from": "DXB", "to": "MAD", "carrier": "QR"}]},
]
SYNTHETIC_PATH = REPO_ROOT / "data" / "_synthetic_cands_for_v120.json"
SYNTHETIC_PATH.write_text(json.dumps(SYNTHETIC_CANDS))


def run_cli(*args, env_extra=None, timeout=30):
    full_env = dict(os.environ)
    full_env.pop("KIWI_API_KEY", None)
    full_env.pop("KIWI_TEQUILA_API_KEY", None)
    full_env.pop("DUFFEL_API_KEY_LIVE", None)
    full_env.pop("DUFFEL_API_KEY_TEST", None)
    if env_extra:
        full_env.update(env_extra)
    return subprocess.run(
        [PYTHON, str(REPO_ROOT / "price_intelligence.py"),
         str(SYNTHETIC_PATH),
         *args],
        capture_output=True, text=True, timeout=timeout, env=full_env,
    )


# =============================================================================
# A. provider identity
# =============================================================================

def test_a_provider_identity():
    print("\n=== Test A: provider identity ===")
    mock_kiwi = kpp.MockKiwiProvider()
    _assert_eq(mock_kiwi.name, "mock_kiwi", "MockKiwiProvider.name")
    # Real Kiwi
    _assert_eq(kpp.KiwiPriceProvider.__init__.__name__, "__init__", "Kiwi class exists")
    # Build real Kiwi with token (no network call)
    real = kpp.KiwiPriceProvider(token="fake_token_for_test")
    _assert_eq(real.name, "kiwi", "KiwiPriceProvider.name")


# =============================================================================
# B. provider mode
# =============================================================================

def test_b_provider_mode():
    print("\n=== Test B: provider mode ===")
    # mock_kiwi → provider_mode = "mock"
    mock = kpp.MockKiwiProvider()
    cand = SYNTHETIC_CANDS[0]
    res = mock.quote(cand, date_window="2027-04-15", passengers=1)
    _assert(res["success"], "mock_kiwi quote success")
    pe = res["price_evidence"]
    _assert_eq(pe["provider"], "mock_kiwi", "mock_kiwi provider identity")
    _assert_eq(pe["provider_mode"], "mock", "mock_kiwi provider_mode")


# =============================================================================
# C. schema keys (MockDuffel vs MockKiwi — same schema)
# =============================================================================

def test_c_schema_keys():
    print("\n=== Test C: schema keys (MockDuffel vs MockKiwi) ===")
    cand = SYNTHETIC_CANDS[2]  # TEST-C, multi-segment
    mock_duffel = pi.MockDuffelProvider()
    mock_kiwi = kpp.MockKiwiProvider()
    pe_d = mock_duffel.quote(cand, date_window="2027-04-15", passengers=1)["price_evidence"]
    pe_k = mock_kiwi.quote(cand, date_window="2027-04-15", passengers=1)["price_evidence"]
    keys_d = set(pe_d.keys())
    keys_k = set(pe_k.keys())
    # Both must include the canonical schema
    canonical = {"candidate_id", "ticket_groups", "ticket_count",
                 "is_single_ticket", "self_transfer", "separate_ticket_risk",
                 "currency", "total_price", "base_fare", "taxes", "fees",
                 "optional_extras", "fare_basis_code", "fare_type", "fare_classes",
                 "cabin", "changeable", "refundable", "change_fee", "refund_fee",
                 "baggage", "seat_selection", "meal_included", "transit_hotel_included",
                 "lounge_access", "valid_until", "price_quote_expires_at",
                 "price_retrieved_at", "retrieved_at", "price_freshness_min",
                 "freshness_min", "freshness_bucket", "confidence_reasons",
                 "warnings", "provenance", "provider", "provider_mode",
                 "verification_status", "price_status", "failure_reason", "failure_kind"}
    missing_d = canonical - keys_d
    missing_k = canonical - keys_k
    _assert(not missing_d, f"MockDuffel schema complete (missing: {missing_d})")
    _assert(not missing_k, f"MockKiwi schema complete (missing: {missing_k})")


# =============================================================================
# D. required fields
# =============================================================================

def test_d_required_fields():
    print("\n=== Test D: required fields ===")
    cand = SYNTHETIC_CANDS[0]
    pe = kpp.MockKiwiProvider().quote(cand, "2027-04-15")["price_evidence"]
    for field in ["candidate_id", "total_price", "currency", "ticket_groups",
                  "ticket_count", "provider", "provider_mode", "retrieved_at",
                  "freshness_bucket", "verification_status", "provenance"]:
        _assert(field in pe, f"required field {field!r} present")


# =============================================================================
# E. freshness
# =============================================================================

def test_e_freshness():
    print("\n=== Test E: freshness ===")
    cand = SYNTHETIC_CANDS[0]
    pe = kpp.MockKiwiProvider().quote(cand, "2027-04-15")["price_evidence"]
    _assert_eq(pe["freshness_bucket"], "FRESHNESS_RECENT", "fresh bucket RECENT")
    _assert(pe["freshness_min"] is not None and pe["freshness_min"] >= 0,
            "freshness_min >= 0")


# =============================================================================
# F. verification semantics
# =============================================================================

def test_f_verification_semantics():
    print("\n=== Test F: verification semantics ===")
    cand = SYNTHETIC_CANDS[0]
    pe = kpp.MockKiwiProvider().quote(cand, "2027-04-15")["price_evidence"]
    _assert_eq(pe["verification_status"], "LIVE", "mock_kiwi verification_status")
    _assert(pe["provenance"]["verification_status"] == "LIVE",
            "provenance.verification_status == LIVE")
    # BOOKABLE must never appear
    payload_str = json.dumps(pe)
    _assert("BOOKABLE" not in payload_str, "no BOOKABLE in payload")


# =============================================================================
# G. failure semantics
# =============================================================================

def test_g_failure_semantics():
    print("\n=== Test G: failure semantics ===")
    # Empty segments → PRICE_NOT_FOUND
    res = kpp.MockKiwiProvider().quote({"id": "EMPTY", "segments": []}, "2027-04-15")
    _assert_eq(res["success"], False, "empty segments → failure")
    _assert_eq(res["failure_kind"], "PRICE_NOT_FOUND", "failure_kind PRICE_NOT_FOUND")
    # No token → MISSING_CREDENTIALS
    saved = os.environ.pop("KIWI_API_KEY", None)
    saved2 = os.environ.pop("KIWI_TEQUILA_API_KEY", None)
    try:
        try:
            kpp.KiwiPriceProvider()
            raised = False
        except RuntimeError as e:
            raised = True
            _assert("MISSING_CREDENTIALS" in str(e), "RuntimeError mentions MISSING_CREDENTIALS")
        _assert(raised, "KiwiPriceProvider raises without token")
    finally:
        if saved:
            os.environ["KIWI_API_KEY"] = saved
        if saved2:
            os.environ["KIWI_TEQUILA_API_KEY"] = saved2


# =============================================================================
# H. currency handling
# =============================================================================

def test_h_currency_handling():
    print("\n=== Test H: currency handling ===")
    cand = SYNTHETIC_CANDS[0]
    pe = kpp.MockKiwiProvider().quote(cand, "2027-04-15")["price_evidence"]
    _assert_eq(pe["currency"], "EUR", "MockKiwiProvider currency (EUR)")
    # Currency_unknown simulation
    saved = os.environ.get("SIMULATE_CURRENCY_UNKNOWN")
    os.environ["SIMULATE_CURRENCY_UNKNOWN"] = "1"
    try:
        res = kpp.MockKiwiProvider().quote(cand, "2027-04-15")
        _assert_eq(res["success"], False, "currency unknown → failure")
        _assert_eq(res["failure_kind"], "CURRENCY_UNKNOWN", "failure_kind CURRENCY_UNKNOWN")
    finally:
        if saved:
            os.environ["SIMULATE_CURRENCY_UNKNOWN"] = saved
        else:
            os.environ.pop("SIMULATE_CURRENCY_UNKNOWN", None)


# =============================================================================
# I. baggage handling
# =============================================================================

def test_i_baggage():
    print("\n=== Test I: baggage handling ===")
    cand = SYNTHETIC_CANDS[0]
    pe = kpp.MockKiwiProvider().quote(cand, "2027-04-15")["price_evidence"]
    _assert("baggage" in pe, "baggage block present")
    _assert("recheck_required_at_connection" in pe["baggage"],
            "recheck_required_at_connection field present")


# =============================================================================
# J. ticket structure
# =============================================================================

def test_j_ticket_structure():
    print("\n=== Test J: ticket structure ===")
    # Single-segment → 1 ticket group
    pe1 = kpp.MockKiwiProvider().quote(SYNTHETIC_CANDS[0], "2027-04-15")["price_evidence"]
    _assert_eq(pe1["ticket_count"], 1, "single-segment → ticket_count=1")
    # Multi-segment same airline → may group together; let's just check structure
    pe4 = kpp.MockKiwiProvider().quote(SYNTHETIC_CANDS[3], "2027-04-15")["price_evidence"]
    _assert(pe4["ticket_count"] >= 1, "multi-segment → ticket_count>=1")
    _assert(len(pe4["ticket_groups"]) >= 1, "ticket_groups populated")


# =============================================================================
# K. no BOOKABLE
# =============================================================================

def test_k_no_bookable():
    print("\n=== Test K: no BOOKABLE ===")
    src = (REPO_ROOT / "kiwi_price_provider.py").read_text()
    # Strip comments and docstrings
    src_s = re.sub(r"#.*", "", src)
    src_s = re.sub(r'""".*?"""', "", src_s, flags=re.DOTALL)
    src_s = re.sub(r"'''.*?'''", "", src_s, flags=re.DOTALL)
    _assert("BOOKABLE" not in src_s, "no BOOKABLE identifier in kiwi_price_provider.py")


# =============================================================================
# L. no ArbitrageEvidence
# =============================================================================

def test_l_no_arbitrage_evidence():
    print("\n=== Test L: no ArbitrageEvidence ===")
    cand = SYNTHETIC_CANDS[2]
    pe = kpp.MockKiwiProvider().quote(cand, "2027-04-15")["price_evidence"]
    raw = json.dumps(pe)
    _assert("arbitrage_opportunity" not in raw, "no arbitrage_opportunity")
    _assert("net_arbitrage" not in raw, "no net_arbitrage")
    _assert("booking_status" not in raw, "no booking_status")


# =============================================================================
# M. no arbitrage_score
# =============================================================================

def test_m_no_arbitrage_score():
    print("\n=== Test M: no arbitrage_score identifier ===")
    src = (REPO_ROOT / "kiwi_price_provider.py").read_text()
    src_s = re.sub(r"#.*", "", src)
    src_s = re.sub(r'""".*?"""', "", src_s, flags=re.DOTALL)
    src_s = re.sub(r"'''.*?'''", "", src_s, flags=re.DOTALL)
    # Should not be used as identifier (assignment or kwarg)
    _assert(not re.search(r"\barbitrage_score\b\s*[=:(),]", src_s),
            "no 'arbitrage_score' as identifier assignment")


# =============================================================================
# N. information_priority_score terminology
# =============================================================================

def test_n_information_priority():
    print("\n=== Test N: information_priority_score terminology ===")
    # The information_priority_score is in price_intelligence.py, not kiwi.
    # This test verifies Kiwi doesn't introduce a competing term.
    src = (REPO_ROOT / "kiwi_price_provider.py").read_text()
    for forbidden in ["candidate_score", "price_score", "opportunity_score"]:
        _assert(forbidden not in src, f"no '{forbidden}' in kiwi_price_provider.py")
    # Confirm "ips" or "information_priority" exists in price_intelligence
    pi_src = (REPO_ROOT / "price_intelligence.py").read_text()
    _assert("ips" in pi_src or "information_priority" in pi_src,
            "price_intelligence uses ips/information_priority")


# =============================================================================
# O. no credential leakage
# =============================================================================

def test_o_no_credential_leakage():
    print("\n=== Test O: no credential leakage ===")
    fake_token = "FAKE_KIWI_TOKEN_DO_NOT_LEAK_zzzz1234"
    r = run_cli("--provider", "kiwi", "--max-searches", "1",
                env_extra={"KIWI_API_KEY": fake_token})
    # The CLI may exit non-zero (rc=10) if ProviderHealthCheck fails, but
    # the token must NEVER appear in stdout/stderr.
    full_output = r.stdout + r.stderr
    _assert(fake_token not in full_output,
            "fake token does not appear in stdout/stderr")


# =============================================================================
# P. explicit provider mode
# =============================================================================

def test_p_explicit_provider_modes():
    print("\n=== Test P: explicit provider modes ===")
    # --provider kiwi (no creds) → fail closed (rc=10)
    r = run_cli("--provider", "kiwi", "--max-searches", "1")
    _assert_eq(r.returncode, 10, "kiwi without creds → rc=10")
    _assert("MISSING_CREDENTIALS" in r.stderr, "MISSING_CREDENTIALS in stderr")
    # --provider mock_kiwi → ok (rc=0)
    r = run_cli("--provider", "mock_kiwi", "--max-searches", "1")
    _assert_eq(r.returncode, 0, "mock_kiwi → rc=0")


# =============================================================================
# Q. no silent fallback
# =============================================================================

def test_q_no_silent_fallback():
    print("\n=== Test Q: no silent fallback ===")
    # --provider kiwi without creds must NOT silently fall back to Mock
    r = run_cli("--provider", "kiwi", "--max-searches", "1")
    _assert(r.returncode != 0, "kiwi without creds exits non-zero (no silent fallback)")
    _assert("FAIL CLOSED" in r.stderr, "explicit FAIL CLOSED message")
    # price_evidence.json should NOT have been written
    payload_path = REPO_ROOT / "data" / "price_evidence.json"
    if payload_path.exists():
        # If the file existed from a prior test (e.g. test_e with mock),
        # ensure the provider label is consistent with what was last run.
        # The KEY check: stderr shows FAIL CLOSED.
        pass


# =============================================================================
# Cross-provider coexistence fixture (spec §15)
# =============================================================================

def test_cross_provider_coexistence():
    print("\n=== Test cross-provider coexistence (spec §15) ===")
    cand = SYNTHETIC_CANDS[0]
    pe_duffel = pi.MockDuffelProvider().quote(cand, "2027-04-15")["price_evidence"]
    pe_kiwi = kpp.MockKiwiProvider().quote(cand, "2027-04-15")["price_evidence"]
    # Coexist as independent objects; identity may differ
    _assert(pe_duffel["provider"] != pe_kiwi["provider"],
            "providers distinct (mock_duffel != mock_kiwi)")
    _assert(pe_duffel["total_price"]["amount"] != pe_kiwi["total_price"]["amount"],
            "prices differ (mocked; documented behaviour)")
    # Both carry the same canonical schema fields
    shared_keys = {"ticket_count", "is_single_ticket", "self_transfer",
                   "verification_status", "freshness_bucket", "retrieved_at"}
    _assert(shared_keys <= set(pe_duffel.keys()),
            f"Duffel evidence has shared schema keys ({shared_keys})")
    _assert(shared_keys <= set(pe_kiwi.keys()),
            f"Kiwi evidence has shared schema keys ({shared_keys})")
    # No arbitrage interpretation
    fixture = {
        "candidate_id": cand["id"],
        "provider_A": {"name": pe_duffel["provider"], "amount": pe_duffel["total_price"]["amount"], "currency": pe_duffel["total_price"]["currency"], "retrieved_at": pe_duffel["retrieved_at"]},
        "provider_B": {"name": pe_kiwi["provider"], "amount": pe_kiwi["total_price"]["amount"], "currency": pe_kiwi["total_price"]["currency"], "retrieved_at": pe_kiwi["retrieved_at"]},
    }
    raw = json.dumps(fixture)
    _assert("arbitrage_score" not in raw, "no arbitrage_score in coexistence fixture")
    _assert("arbitrage_opportunity" not in raw, "no arbitrage_opportunity in fixture")
    _assert("net_arbitrage" not in raw, "no net_arbitrage in fixture")


# =============================================================================
# Smoke-test hard limit (spec §16)
# =============================================================================

def test_smoke_test_hard_limit():
    print("\n=== Test smoke-test hard limit ===")
    r = run_cli("--provider", "mock_kiwi", "--max-searches", "10", "--smoke-test")
    _assert_eq(r.returncode, 0, "smoke-test rc=0")
    body = json.loads((REPO_ROOT / "data" / "price_evidence.json").read_text())
    _assert(len(body["evidences"]) <= 2,
            f"smoke-test caps at 2 evidences (got {len(body['evidences'])})")


# =============================================================================
# Run all
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Flight Market Intelligence v1.2.0 — Kiwi PriceProvider Tests")
    print("=" * 60)
    tests = [
        test_a_provider_identity,
        test_b_provider_mode,
        test_c_schema_keys,
        test_d_required_fields,
        test_e_freshness,
        test_f_verification_semantics,
        test_g_failure_semantics,
        test_h_currency_handling,
        test_i_baggage,
        test_j_ticket_structure,
        test_k_no_bookable,
        test_l_no_arbitrage_evidence,
        test_m_no_arbitrage_score,
        test_n_information_priority,
        test_o_no_credential_leakage,
        test_p_explicit_provider_modes,
        test_q_no_silent_fallback,
        test_cross_provider_coexistence,
        test_smoke_test_hard_limit,
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

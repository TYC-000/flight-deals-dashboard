"""
test_schedule_intelligence_v1.py — Tests for Schedule Intelligence v1.0

Tests (per spec §12):
A. OpenFlights lookup success
B. Unknown route remains UNKNOWN
C. provenance is preserved
D. no fake schedule generated
E. multi-segment connection calculation
F. overnight detection
G. airport-change detection
H. self-transfer detection
I. structural signals preserved
J. existing candidate schema remains compatible
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
SCHEDULE_INTEL = REPO_ROOT / "schedule_intelligence.py"
PYTHON = "/Users/aib/.hermes/hermes-agent/venv/bin/python3"

# Ensure module importable
sys.path.insert(0, str(REPO_ROOT))
import schedule_intelligence as si  # noqa: E402

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


def load_enriched() -> list[dict] | None:
    p = REPO_ROOT / "data" / "schedule_enriched_candidates.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def load_trace() -> dict:
    p = REPO_ROOT / "data" / "schedule_trace.json"
    return json.loads(p.read_text())


# =============================================================================
# Setup: run the CLI to populate data
# =============================================================================

def setup():
    print("\n=== SETUP: Running schedule_intelligence.py ===")
    # Run on the auto-generated candidates
    r = subprocess.run(
        [PYTHON, str(SCHEDULE_INTEL), str(REPO_ROOT / "data" / "flight_candidates_generated.json")],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        print(f"  FAIL: CLI rc={r.returncode}")
        print(r.stderr[-500:])
        sys.exit(1)
    print(f"  CLI rc={r.returncode}")


# =============================================================================
# Test A: OpenFlights lookup success
# =============================================================================

def test_a_openflights_lookup_success():
    """OpenFlights routes DB lookup returns DATABASE for known routes"""
    print("\n=== Test A: OpenFlights lookup success ===")
    routes = si.load_openflights_routes()
    # TPE → KUL (Malaysia Airlines flies this) is in OpenFlights DB
    _assert(("TPE", "KUL") in routes, "TPE→KUL in OpenFlights DB")
    _assert(("TPE", "ICN") in routes, "TPE→ICN (Korean Air / EVA) in OpenFlights DB")
    _assert(("KUL", "DXB") in routes, "KUL→DXB (Emirates) in OpenFlights DB")
    _assert(len(routes) > 1000, f"OpenFlights DB has >1000 routes (got {len(routes)})")


# =============================================================================
# Test B: Unknown route remains UNKNOWN
# =============================================================================

def test_b_unknown_route():
    """Route not in OpenFlights gets verification_status=UNKNOWN (no fabrication)"""
    print("\n=== Test B: Unknown route remains UNKNOWN ===")
    routes = si.load_openflights_routes()
    airports = si.load_openflights_airports()
    # Invent a fake route that definitely isn't in OpenFlights
    seg = {"from": "ZZZ", "to": "QQQ"}
    sched = si.build_segment_schedule(seg, routes, airports, "test-retrieved-at")
    _assert_eq(sched["verification_status"], si.VERIFICATION_UNKNOWN, "fake route verification_status")
    _assert_eq(sched["is_in_openflights_database"], False, "fake route in DB")
    _assert_eq(sched["departure"], None, "no fake departure")
    _assert_eq(sched["arrival"], None, "no fake arrival")
    _assert_eq(sched["duration_minutes"], None, "no fake duration")


# =============================================================================
# Test C: Provenance preserved
# =============================================================================

def test_c_provenance_preserved():
    """Provenance fields (source, retrieved_at, verification_status, confidence) present"""
    print("\n=== Test C: Provenance preserved ===")
    routes = si.load_openflights_routes()
    airports = si.load_openflights_airports()
    seg = {"from": "TPE", "to": "KUL"}
    sched = si.build_segment_schedule(seg, routes, airports, "test-retrieved")
    for field in ["source", "retrieved_at", "verification_status", "confidence"]:
        # v1.0 schema uses schedule_source instead of source
        if field == "source":
            _assert("schedule_source" in sched, "schedule_source field present")
            _assert(sched["schedule_source"] in ("openflights_database", "unknown"), f"schedule_source value: {sched['schedule_source']}")
        else:
            _assert(field in sched, f"field '{field}' present in schedule evidence")
    _assert(sched["retrieved_at"] == "test-retrieved", "retrieved_at preserved")
    _assert(isinstance(sched["confidence"], float), "confidence is float")
    _assert(0.0 <= sched["confidence"] <= 1.0, "confidence in [0, 1]")


# =============================================================================
# Test D: No fake schedule generated
# =============================================================================

def test_d_no_fake_schedule():
    """OpenFlights route existence does NOT fabricate departure/arrival/duration/carrier/aircraft"""
    print("\n=== Test D: No fake schedule generated ===")
    routes = si.load_openflights_routes()
    airports = si.load_openflights_airports()
    # TPE→KUL is in OpenFlights
    sched = si.build_segment_schedule({"from": "TPE", "to": "KUL"}, routes, airports, "now")
    _assert_eq(sched["verification_status"], si.VERIFICATION_DATABASE, "DATABASE status")
    # Per spec — NEVER fabricate
    _assert_eq(sched["departure"], None, "departure still None for DATABASE (no fabricated times)")
    _assert_eq(sched["arrival"], None, "arrival still None for DATABASE")
    _assert_eq(sched["duration_minutes"], None, "duration still None for DATABASE")
    _assert_eq(sched["operating_carrier"], None, "operating_carrier still None for DATABASE (no fabricated carrier)")
    # Schedule source should be openflights_database
    _assert_eq(sched["schedule_source"], "openflights_database", "schedule_source=openflights_database")


# =============================================================================
# Test E: Multi-segment connection calculation
# =============================================================================

def test_e_connection_calculation():
    """Multi-segment candidate gets connection check for each pair"""
    print("\n=== Test E: Multi-segment connection calculation ===")
    # Build a fake multi-segment candidate and check analyze_connection
    seg1 = {"from": "TPE", "to": "KUL"}
    seg2 = {"from": "KUL", "to": "MAD"}
    airports = si.load_openflights_airports()
    ck = si.analyze_connection(seg1, seg2, airports)
    _assert(ck["same_airport"] is True, "same_airport=True for KUL→KUL")
    _assert(ck["missing_schedule"] is False, "missing_schedule=False when airport is known")
    _assert("connection_time_min" in ck, "connection_time_min field present")
    _assert(ck["connection_time_min"] is None, "connection_time_min=None (not computable from OpenFlights)")


# =============================================================================
# Test F: Overnight detection
# =============================================================================

def test_f_overnight_detection():
    """overnight_connection is False by default (OpenFlights has no times)"""
    print("\n=== Test F: Overnight detection ===")
    seg1 = {"from": "TPE", "to": "KUL"}
    seg2 = {"from": "KUL", "to": "MAD"}
    airports = si.load_openflights_airports()
    ck = si.analyze_connection(seg1, seg2, airports)
    # OpenFlights lacks scheduled times → we mark overnight_connection=False (not computable)
    # The signal would later come from schedule intelligence (v1.1+)
    _assert_eq(ck["overnight_connection"], False, "overnight_connection=False (not guessable)")


# =============================================================================
# Test G: Airport-change detection
# =============================================================================

def test_g_airport_change_detection():
    """airport_change=True when connection airport not in OpenFlights DB"""
    print("\n=== Test G: Airport-change detection ===")
    airports = si.load_openflights_airports()
    seg1 = {"from": "TPE", "to": "XXX"}  # XXX not in OpenFlights
    seg2 = {"from": "XXX", "to": "MAD"}
    ck = si.analyze_connection(seg1, seg2, airports)
    _assert_eq(ck["same_airport"], True, "same IATA from/to")
    _assert_eq(ck["airport_change"], True, "airport_change=True when airport unknown")


# =============================================================================
# Test H: Self-transfer detection
# =============================================================================

def test_h_self_transfer_detection():
    """self_transfer=False for same-IATA connections (no airport change)"""
    print("\n=== Test H: Self-transfer detection ===")
    airports = si.load_openflights_airports()
    seg1 = {"from": "TPE", "to": "KUL"}
    seg2 = {"from": "KUL", "to": "MAD"}
    ck = si.analyze_connection(seg1, seg2, airports)
    _assert_eq(ck["self_transfer"], False, "self_transfer=False for same IATA")
    # Now non-contiguous (different airport) — should also not be self_transfer
    seg3 = {"from": "TPE", "to": "KUL"}
    seg4 = {"from": "SIN", "to": "MAD"}
    ck2 = si.analyze_connection(seg3, seg4, airports)
    _assert_eq(ck2["same_airport"], False, "non-contiguous same_airport=False")
    _assert_eq(ck2["missing_schedule"], True, "non-contiguous marked missing_schedule")


# =============================================================================
# Test I: Structural signals preserved
# =============================================================================

def test_i_structural_signals():
    """Structural signals detected from candidate_type + topology"""
    print("\n=== Test I: Structural signals detected ===")
    # Candidate with outer_port type
    cand = {
        "id": "AUTO-outer_port-TPE-KUL-DXB-BCN",
        "candidate_type": "outer_port_middle_east",
        "multi_ticket": False,
        "route": ["TPE", "KUL", "DXB", "BCN"],
        "segments": [
            {"from": "TPE", "to": "KUL"},
            {"from": "KUL", "to": "DXB"},
            {"from": "DXB", "to": "BCN"},
        ],
    }
    routes = si.load_openflights_routes()
    airports = si.load_openflights_airports()
    seg_scheds = [si.build_segment_schedule(s, routes, airports, "now") for s in cand["segments"]]
    conn_checks = [si.analyze_connection(cand["segments"][i], cand["segments"][i+1], airports)
                   for i in range(len(cand["segments"]) - 1)]
    signals = si.detect_structural_signals(cand, seg_scheds, conn_checks)
    _assert("outer_port" in signals, "outer_port in signals")
    _assert("alternative_hub" in signals, "alternative_hub in signals (DXB)")
    _assert("unusual_routing" in signals, "unusual_routing in signals (3-segment)")

    # Multi-ticket candidate
    cand2 = {
        "id": "AUTO-multi_ticket-TPE-KUL-MAD",
        "candidate_type": "multi_ticket_direct",
        "multi_ticket": True,
        "route": ["TPE", "KUL", "MAD"],
        "segments": [
            {"from": "TPE", "to": "KUL"},
            {"from": "KUL", "to": "MAD"},
        ],
    }
    seg_scheds2 = [si.build_segment_schedule(s, routes, airports, "now") for s in cand2["segments"]]
    conn_checks2 = [si.analyze_connection(cand2["segments"][i], cand2["segments"][i+1], airports)
                    for i in range(len(cand2["segments"]) - 1)]
    signals2 = si.detect_structural_signals(cand2, seg_scheds2, conn_checks2)
    _assert("multi_ticket" in signals2, "multi_ticket in signals")
    _assert("outer_port" in signals2, "outer_port in signals (KUL)")


# =============================================================================
# Test J: Existing candidate schema remains compatible
# =============================================================================

def test_j_schema_compat():
    """Enriched candidates preserve all original v0.2.1 fields"""
    print("\n=== Test J: Existing candidate schema remains compatible ===")
    enriched = load_enriched()
    _assert(enriched is not None, "enriched candidates file exists")
    _assert(len(enriched) == 80, f"80 candidates enriched (got {len(enriched)})")
    sample = enriched[0]
    # All original v0.2.1 fields preserved
    for field in ["id", "label", "currency", "total_cost", "segments", "candidate_type",
                  "discovery_source", "discovery_reason", "route"]:
        _assert(field in sample, f"original field '{field}' preserved")
    # New field added (not destructive)
    _assert("schedule_intelligence" in sample, "new schedule_intelligence field added")
    _assert("schedule_status" in sample["schedule_intelligence"], "schedule_status present")
    _assert("structural_signals" in sample["schedule_intelligence"], "structural_signals present")


# =============================================================================
# Test K: Trace schema matches spec §9
# =============================================================================

def test_k_trace_schema():
    """schedule_trace.json per-candidate record has required fields (spec §9)"""
    print("\n=== Test K: Trace schema matches spec §9 ===")
    trace = load_trace()
    _assert("candidates" in trace, "trace has candidates array")
    _assert(len(trace["candidates"]) == 80, "80 trace records")
    rec = trace["candidates"][0]
    required = ["candidate_id", "schedule_lookup_attempted", "schedule_source",
                "segments_checked", "segments_found", "segments_missing",
                "verification_status", "schedule_status", "connection_checks",
                "structural_signals", "failure_reason"]
    for f in required:
        _assert(f in rec, f"trace field '{f}' present")
    _assert_eq(rec["schedule_lookup_attempted"], True, "schedule_lookup_attempted=True")
    _assert_eq(rec["schedule_source"], "openflights", "schedule_source=openflights")


# =============================================================================
# Test L: Existing pipeline compatibility
# =============================================================================

def test_l_existing_pipeline():
    """Existing CLI commands still work unchanged"""
    print("\n=== Test L: Existing pipeline compatibility ===")
    # candidate_discovery.py CLI
    r1 = subprocess.run(
        [PYTHON, str(REPO_ROOT / "candidate_discovery.py"), str(REPO_ROOT / "examples" / "mission_tpe_spain.json")],
        capture_output=True, text=True, timeout=30,
    )
    _assert_eq(r1.returncode, 0, "candidate_discovery.py CLI rc=0")

    # eval_flight_yc.py CLI on manual candidates
    r2 = subprocess.run(
        [PYTHON, "/Users/aib/.hermes/tools/eval_flight_yc.py", str(REPO_ROOT / "data" / "flight_candidates.json")],
        capture_output=True, text=True, timeout=120,
    )
    _assert_eq(r2.returncode, 0, "eval_flight_yc.py CLI rc=0")

    # flight_results.json still readable
    frp = REPO_ROOT / "data" / "flight_results.json"
    _assert(frp.exists(), f"flight_results.json exists ({frp.stat().st_size} bytes)")


# =============================================================================
# Test M: Did NOT modify existing modules
# =============================================================================

def test_m_no_modify():
    """Schedule Intelligence does NOT modify candidate_discovery/run_pipeline/eval_flight_yc/flight_dashboard"""
    print("\n=== Test M: No existing files modified ===")
    import subprocess
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    modified_lines = [l for l in r.stdout.splitlines() if l.startswith(" M ")]
    forbidden = {"candidate_discovery.py", "run_pipeline.py", "flight_dashboard.py"}
    forbidden_modified = [l for l in modified_lines
                          if any(f in l for f in forbidden)]
    _assert(len(forbidden_modified) == 0, "no forbidden files modified")
    # Note: eval_flight_yc.py is external; we don't have a git status to check it.
    # We verify by running it.
    r2 = subprocess.run(
        [PYTHON, "/Users/aib/.hermes/tools/eval_flight_yc.py", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    _assert_eq(r2.returncode, 0, "eval_flight_yc.py still executable")


if __name__ == "__main__":
    print("=" * 60)
    print("Flight Market Intelligence v1.0 — Schedule Intelligence Tests")
    print("=" * 60)
    setup()
    tests = [
        test_a_openflights_lookup_success,
        test_b_unknown_route,
        test_c_provenance_preserved,
        test_d_no_fake_schedule,
        test_e_connection_calculation,
        test_f_overnight_detection,
        test_g_airport_change_detection,
        test_h_self_transfer_detection,
        test_i_structural_signals,
        test_j_schema_compat,
        test_k_trace_schema,
        test_l_existing_pipeline,
        test_m_no_modify,
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

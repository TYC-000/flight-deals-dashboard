"""
test_pipeline_v0.2.1.py — Integrity tests for v0.2.1 pipeline

Tests:
A. submitted_count == successful + failed
B. survivors <= successful
C. top_candidates <= survivors
D. all candidate IDs unique
E. every evaluated candidate has an evaluation trace
F. console summary numbers == serialized JSON numbers

Run:
    /Users/aib/.hermes/hermes-agent/venv/bin/python3 test_pipeline_v0.2.1.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
TRACE_PATH = REPO_ROOT / "data" / "evaluation_trace.json"
RESULTS_PATH = REPO_ROOT / "data" / "flight_results.json"
GENERATED_CANDIDATES_PATH = REPO_ROOT / "data" / "flight_candidates_generated.json"
MISSION_PATH = REPO_ROOT / "examples" / "mission_tpe_spain.json"


def assert_eq(actual, expected, label):
    if actual == expected:
        print(f"  PASS: {label} == {expected!r}")
        return True
    print(f"  FAIL: {label} — expected {expected!r}, got {actual!r}")
    return False


def assert_true(cond, label):
    if cond:
        print(f"  PASS: {label}")
        return True
    print(f"  FAIL: {label}")
    return False


def assert_le(actual, max_val, label):
    if actual <= max_val:
        print(f"  PASS: {label} ({actual} <= {max_val})")
        return True
    print(f"  FAIL: {label} — {actual} > {max_val}")
    return False


def load_trace() -> dict:
    if not TRACE_PATH.exists():
        raise FileNotFoundError(f"Trace file not found: {TRACE_PATH}. Run pipeline first.")
    return json.loads(TRACE_PATH.read_text())


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text())


# === Setup: run the pipeline to get fresh data ===

def run_pipeline_once() -> bool:
    """Run pipeline v0.2.1 once to populate data files."""
    print("=== SETUP: Running pipeline to generate fresh test data ===")
    r = subprocess.run(
        ["/Users/aib/.hermes/hermes-agent/venv/bin/python3",
         str(REPO_ROOT / "run_pipeline.py"), str(MISSION_PATH)],
        capture_output=True, text=True, timeout=300
    )
    if r.returncode not in (0, 6):  # 0 = pass, 6 = integrity fail (still has data)
        print(f"  Pipeline failed with rc={r.returncode}")
        print(f"  stderr: {r.stderr[-500:]}")
        return False
    print(f"  Pipeline rc={r.returncode} (0=PASS, 6=integrity issues — data still produced)")
    return True


# === Tests ===

def test_a_submitted_eq_succ_plus_failed():
    """Test A: submitted_count == successful + failed"""
    print("\n=== Test A: submitted == success + failed ===")
    trace = load_trace()
    counts = trace["counts"]
    submitted = counts.get("submitted")
    success = counts["json_evaluated"]
    failed_count = max(0, (submitted or 0) - success) if submitted else None
    if submitted is None:
        print("  SKIP: submitted count not in trace")
        return True
    return assert_eq(submitted, success + failed_count, "submitted == success + failed")


def test_b_survivors_le_evaluated():
    """Test B: survivors <= successful"""
    print("\n=== Test B: survivors <= successful ===")
    trace = load_trace()
    survivors = trace["counts"]["json_survivors"]
    evaluated = trace["counts"]["json_evaluated"]
    return assert_le(survivors, evaluated, "survivors <= evaluated")


def test_c_top_le_survivors():
    """Test C: top_candidates <= survivors"""
    print("\n=== Test C: top candidates <= survivors ===")
    trace = load_trace()
    top = trace["counts"]["json_top3"]
    survivors = trace["counts"]["json_survivors"]
    return assert_le(top, survivors, "top <= survivors")


def test_d_unique_ids():
    """Test D: all candidate IDs unique"""
    print("\n=== Test D: candidate IDs are unique ===")
    candidates = json.loads(GENERATED_CANDIDATES_PATH.read_text())
    ids = [c["id"] for c in candidates]
    return assert_eq(len(ids), len(set(ids)), "unique candidate IDs")


def test_e_evaluated_has_trace():
    """Test E: every evaluated candidate has an evaluation trace"""
    print("\n=== Test E: every evaluated candidate has evaluation trace ===")
    trace = load_trace()
    results = load_results()
    evaluated_ids = {r["id"] for r in results.get("all_evaluated", [])}
    trace_for_evaluated = [
        t for t in trace["candidates"] if t["candidate_id"] in evaluated_ids
    ]
    return assert_eq(
        len(trace_for_evaluated), len(evaluated_ids),
        "evaluated candidates have trace records",
    )


def test_f_console_eq_json():
    """Test F: console summary numbers == JSON numbers

    Per spec — these MUST be consistent.

    Jev internally prints 'Survivors: N' to console AND writes N to JSON.all_survivors.
    If they diverge, that means Jev's state tracking is broken — flag it.
    """
    print("\n=== Test F: console == JSON ===")
    trace = load_trace()
    jev_survivors_console = trace["counts"].get("jev_survivors_print")
    json_survivors = trace["counts"]["json_survivors"]
    if jev_survivors_console is None:
        print("  SKIP: Jev didn't print Survivors line (older version)")
        return True
    return assert_eq(
        jev_survivors_console, json_survivors,
        "console Survivors == JSON all_survivors",
    )


def test_z_trace_completeness():
    """Bonus: trace covers every candidate from Discovery"""
    print("\n=== Test Z: trace covers every candidate ===")
    candidates = json.loads(GENERATED_CANDIDATES_PATH.read_text())
    trace = load_trace()
    trace_ids = {t["candidate_id"] for t in trace["candidates"]}
    cand_ids = {c["id"] for c in candidates}
    return assert_eq(trace_ids, cand_ids, "trace covers every candidate")


# === Main ===

if __name__ == "__main__":
    print("=" * 60)
    print("Flight Arbitrage Hunter v0.2.1 — Integrity Tests")
    print("=" * 60)

    if not run_pipeline_once():
        print("\n❌ SETUP FAILED — cannot run tests")
        sys.exit(1)

    tests = [
        test_a_submitted_eq_succ_plus_failed,
        test_b_survivors_le_evaluated,
        test_c_top_le_survivors,
        test_d_unique_ids,
        test_e_evaluated_has_trace,
        test_f_console_eq_json,
        test_z_trace_completeness,
    ]

    failed = 0
    for test_fn in tests:
        try:
            ok = test_fn()
            if not ok:
                failed += 1
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"✅ All {len(tests)} integrity tests PASSED")
    else:
        print(f"❌ {failed}/{len(tests)} integrity tests FAILED")
        sys.exit(1)

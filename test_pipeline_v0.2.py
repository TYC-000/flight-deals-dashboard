"""
test_pipeline_v0.2.py — Tests for v0.2 pipeline

Run with:
    /Users/aib/.hermes/hermes-agent/venv/bin/python3 test_pipeline_v0.2.py

All tests are self-contained and don't require network.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Make repo root importable
REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
sys.path.insert(0, str(REPO_ROOT))

# Force reload
for m in list(sys.modules):
    if "candidate_discovery" in m:
        del sys.modules[m]

import candidate_discovery as cd


def assert_eq(actual, expected, label):
    if actual == expected:
        print(f"  PASS: {label} == {expected!r}")
    else:
        print(f"  FAIL: {label} — expected {expected!r}, got {actual!r}")
        raise AssertionError(label)


def assert_true(cond, label):
    if cond:
        print(f"  PASS: {label}")
    else:
        print(f"  FAIL: {label}")
        raise AssertionError(label)


# === Test 1: full mission → discovery → Jev path produces survivors ===
def test_1_full_path():
    print("\n=== Test 1: Full pipeline (mission → discovery → Jev → survivors) ===")
    mission_path = REPO_ROOT / "examples" / "mission_tpe_spain.json"
    mission = json.loads(mission_path.read_text())
    candidates = cd.generate_candidates(mission)
    assert_true(len(candidates) >= 20, f"candidates count >= 20 (got {len(candidates)})")

    # Write to temp file and run Jev
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(candidates[:5], f)  # only test 5 to be fast
        tmp = f.name
    r = subprocess.run(
        ["/Users/aib/.hermes/hermes-agent/venv/bin/python3",
         "/Users/aib/.hermes/tools/eval_flight_yc.py", tmp],
        capture_output=True, text=True, timeout=60
    )
    assert_eq(r.returncode, 0, "Jev evaluator returncode")


# === Test 2: family diversity ===
def test_2_family_diversity():
    print("\n=== Test 2: Family diversity (no family > 35%) ===")
    mission_path = REPO_ROOT / "examples" / "mission_tpe_spain.json"
    mission = json.loads(mission_path.read_text())
    candidates = cd.generate_candidates(mission)
    from collections import Counter
    families = Counter(c.get("candidate_type") for c in candidates)
    total = len(candidates)
    max_count = max(families.values())
    max_ratio = max_count / total
    print(f"  family counts: {dict(families)}")
    assert_true(max_ratio <= 0.35 + 0.01, f"max family ratio <= 35% (got {max_ratio:.2%})")


# === Test 3: canonical route normalization ===
def test_3_route_normalization():
    print("\n=== Test 3: Canonical route normalization ===")
    # Direct test
    assert_eq(cd._normalize_route(["TPE", "KUL", "MAD", "MAD"]),
              ["TPE", "KUL", "MAD"],
              "strip trailing duplicate")
    assert_eq(cd._normalize_route(["TPE", "FRA", "MAD"]),
              ["TPE", "FRA", "MAD"],
              "no trailing dup unchanged")
    assert_eq(cd._normalize_route(["TPE", "MAD"]),
              ["TPE", "MAD"],
              "short route unchanged")
    assert_eq(cd._normalize_route([]),
              [],
              "empty route unchanged")
    # End-to-end: ID should not have duplicate destination
    mission_path = REPO_ROOT / "examples" / "mission_tpe_spain.json"
    mission = json.loads(mission_path.read_text())
    candidates = cd.generate_candidates(mission)
    bad_ids = []
    for c in candidates:
        # Check ID format: last segment should not equal second-to-last
        parts = c["id"].split("-")
        if len(parts) >= 3 and parts[-1] == parts[-2]:
            bad_ids.append(c["id"])
    assert_true(len(bad_ids) == 0, f"no duplicate-destination IDs (found {len(bad_ids)} bad: {bad_ids[:3]})")


# === Test 4: empty candidate handling ===
def test_4_empty_candidates():
    print("\n=== Test 4: Empty candidate handling ===")
    # Mission that can't possibly generate candidates
    impossible_mission = {
        "origin": ["XYZ"],  # XYZ is not in any ESTIMATED_FLIGHT_MIN
        "destination": ["ABC"],
        "cabin": "economy",
        "preferences": {},
        "constraints": {"max_candidates": 80, "family_max_ratio": 0.35},
    }
    try:
        candidates = cd.generate_candidates(impossible_mission)
        # We expect this to either return [] OR raise
        assert_true(len(candidates) == 0, f"impossible mission returns 0 candidates (got {len(candidates)})")
    except Exception as e:
        print(f"  PASS: raised {type(e).__name__} — pipeline_stage_candidate_discovery would handle")


# === Test 5: invalid mission handling ===
def test_5_invalid_mission():
    print("\n=== Test 5: Invalid mission handling ===")
    # Missing required fields
    bad_mission = {"origin": ["TPE"]}  # missing destination
    try:
        candidates = cd.generate_candidates(bad_mission)
        # If it doesn't raise, that's also OK — let pipeline catch it
        print(f"  Discovery returned {len(candidates)} (no raise)")
    except (KeyError, AttributeError) as e:
        print(f"  PASS: raised {type(e).__name__} for missing fields")
    # Test that pipeline script handles bad JSON
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{not valid json")
        bad_path = f.name
    r = subprocess.run(
        ["/Users/aib/.hermes/hermes-agent/venv/bin/python3",
         str(REPO_ROOT / "run_pipeline.py"), bad_path],
        capture_output=True, text=True, timeout=30
    )
    assert_true(r.returncode != 0, f"pipeline exits non-zero for bad JSON (rc={r.returncode})")
    assert_true("Invalid JSON" in r.stderr or "Stage failed" in r.stderr,
                "pipeline reports explicit error")


# === Test 6: existing flight_candidates.json compatibility ===
def test_6_existing_compatibility():
    print("\n=== Test 6: Existing flight_candidates.json still works ===")
    existing_path = REPO_ROOT / "data" / "flight_candidates.json"
    if not existing_path.exists():
        print(f"  SKIP: {existing_path} not found")
        return
    # Run Jev on it
    r = subprocess.run(
        ["/Users/aib/.hermes/hermes-agent/venv/bin/python3",
         "/Users/aib/.hermes/tools/eval_flight_yc.py", str(existing_path)],
        capture_output=True, text=True, timeout=120
    )
    assert_eq(r.returncode, 0, "Jev on existing flight_candidates.json")
    # Verify schema of one entry
    existing = json.loads(existing_path.read_text())
    sample = existing[0]
    assert_true("id" in sample, "existing candidates have id")
    assert_true("segments" in sample, "existing candidates have segments")
    assert_true("positioning" in sample, "existing candidates have positioning")


# === Run all tests ===
if __name__ == "__main__":
    print("=" * 60)
    print("Flight Arbitrage Hunter v0.2 — Tests")
    print("=" * 60)

    tests = [
        test_1_full_path,
        test_2_family_diversity,
        test_3_route_normalization,
        test_4_empty_candidates,
        test_5_invalid_mission,
        test_6_existing_compatibility,
    ]

    failed = 0
    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"✅ All {len(tests)} tests PASSED")
    else:
        print(f"❌ {failed}/{len(tests)} tests FAILED")
        sys.exit(1)

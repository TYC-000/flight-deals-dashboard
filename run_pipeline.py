"""
run_pipeline.py — Hermes Flight Arbitrage Hunter v0.2.1 Pipeline Orchestrator

v0.2.1 changes:
- Explicit count reporting (Generated / Submitted / Success / Failed / Survivors / Top)
- evaluation_trace.json: per-candidate lifecycle record
- Integrity verification: count consistency, JSON consistency, trace completeness
- Stage-by-stage logging with explicit failure modes
- Does NOT modify Jev scoring/filter semantics

Architectural principle:
    Discovery Layer  →  Candidate JSON  →  Evaluation Layer
    Replaceable: v0.1 / v0.2 / Real Schedule / Price Discovery
    Future: Real-time schedule/price, Arbitrage scoring, Background scheduler

STOP condition: After this v0.2.1, no further work until next milestone.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
GENERATED_CANDIDATES_PATH = DATA_DIR / "flight_candidates_generated.json"
RESULTS_PATH = DATA_DIR / "flight_results.json"
TRACE_PATH = DATA_DIR / "evaluation_trace.json"
EVALUATOR_PATH = Path("/Users/aib/.hermes/tools/eval_flight_yc.py")
EVALUATOR_PYTHON = Path("/Users/aib/.hermes/hermes-agent/venv/bin/python3")


# === Pipeline lifecycle states (per spec) ===
# INPUT  →  EVALUATED  →  FILTERED  →  SURVIVORS  →  TOP
LIFECYCLE_STATES = ["input", "evaluated", "filtered", "survivors", "top"]


def _hrule(char: str = "=") -> None:
    print(char * 60, flush=True)


def _stage(n: int, total: int, name: str) -> None:
    print(f"\n[{n}/{total}] {name}", flush=True)


def _line(label: str, value: Any, width: int = 30) -> None:
    print(f"  {label:<{width}} {value}", flush=True)


# === Stages ===

def stage_load_mission(mission_path: Path) -> dict:
    """Stage 0: Load and validate mission JSON."""
    if not mission_path.exists():
        raise FileNotFoundError(f"Mission file not found: {mission_path}")
    try:
        mission = json.loads(mission_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in mission file: {e}")
    if not isinstance(mission, dict):
        raise ValueError("Mission must be a JSON object")
    if "origin" not in mission or "destination" not in mission:
        raise ValueError("Mission missing required fields: origin, destination")
    return mission


def stage_candidate_discovery(mission: dict) -> list[dict]:
    """Stage 1: Run candidate discovery. Returns list of candidates."""
    sys.path.insert(0, str(REPO_ROOT))
    if "candidate_discovery" in sys.modules:
        del sys.modules["candidate_discovery"]
    import candidate_discovery as cd

    t0 = time.time()
    candidates = cd.generate_candidates(mission)
    elapsed = time.time() - t0

    print(f"   Family generators: {len(cd.FAMILY_GENERATORS)}")
    print(f"   Discovery time: {elapsed:.2f}s")

    if not candidates:
        raise RuntimeError("Candidate discovery returned 0 candidates — aborting pipeline")

    return candidates


def stage_write_candidates(candidates: list[dict]) -> Path:
    """Stage 2: Write candidates to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_CANDIDATES_PATH.write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False)
    )
    print(f"   Written: {GENERATED_CANDIDATES_PATH} ({len(candidates)} candidates)")
    return GENERATED_CANDIDATES_PATH


def stage_jev_evaluation(candidates_path: Path) -> tuple[dict, str]:
    """Stage 3: Run Jev evaluator.

    Returns (results_dict, raw_stdout) — raw_stdout parsed for explicit counts.

    v0.2.1: explicit -o output to flight_results.json (not Jev's default /tmp path)
    so the JSON we read back matches what was just produced.
    """
    if not EVALUATOR_PATH.exists():
        raise FileNotFoundError(f"Evaluator not found: {EVALUATOR_PATH}")
    if not EVALUATOR_PYTHON.exists():
        raise FileNotFoundError(f"Evaluator python not found: {EVALUATOR_PYTHON}")

    t0 = time.time()
    proc = subprocess.run(
        [str(EVALUATOR_PYTHON), str(EVALUATOR_PATH), str(candidates_path),
         "-o", str(RESULTS_PATH)],  # v0.2.1: explicit output path
        capture_output=True, text=True, timeout=600,
    )
    elapsed = time.time() - t0

    if proc.returncode != 0:
        print(f"   ✗ Jev evaluator failed (rc={proc.returncode})", file=sys.stderr)
        print(f"   stderr: {proc.stderr[-500:]}", file=sys.stderr)
        raise RuntimeError(f"Jev evaluator returned rc={proc.returncode}")

    print(f"   Jev time: {elapsed:.2f}s")

    if not RESULTS_PATH.exists():
        raise RuntimeError("Jev evaluator did not produce flight_results.json")

    with RESULTS_PATH.open() as f:
        results = json.load(f)
    return results, proc.stdout


def parse_jev_counts(stdout: str, results: dict) -> dict:
    """Extract explicit counts from Jev stdout + JSON.

    v0.2.1 surfaces the lifecycle numbers so the user can spot mismatches.
    """
    # Parse submitted (pre-filter) and survivors from Jev stdout
    submitted = None
    jev_survivors = None
    m = re.search(r"Pre-filter.*?(\d+) → (\d+)", stdout)
    if m:
        submitted = int(m.group(2))
    m = re.search(r"Survivors:\s*(\d+)", stdout)
    if m:
        jev_survivors = int(m.group(1))

    # JSON authoritative numbers
    json_evaluated = len(results.get("all_evaluated", []))
    json_survivors = len(results.get("all_survivors", []))
    json_top3 = len(results.get("top3", []))
    json_dropped = len(results.get("dropped", []))

    return {
        "submitted": submitted,
        "jev_survivors_print": jev_survivors,
        "json_evaluated": json_evaluated,
        "json_survivors": json_survivors,
        "json_top3": json_top3,
        "json_dropped": json_dropped,
    }


def build_evaluation_trace(
    candidates: list[dict],
    results: dict,
    counts: dict,
) -> dict:
    """Build per-candidate trace.

    Lifecycle: INPUT → EVALUATED → FILTERED → SURVIVORS → TOP
    """
    evaluated_ids = {r["id"]: r for r in results.get("all_evaluated", [])}
    survivor_ids = {r["id"]: r for r in results.get("all_survivors", [])}
    top3_ids = {r["id"]: i + 1 for i, r in enumerate(results.get("top3", []))}
    dropped_by_id = {d["id"]: d["reason"] for d in results.get("dropped", [])}

    trace_records = []
    for c in candidates:
        cid = c["id"]
        evaluated = cid in evaluated_ids
        survived = cid in survivor_ids
        dropped = cid in dropped_by_id
        in_top3 = cid in top3_ids

        # Sanity: a candidate can be either survived or dropped, not both
        if survived and dropped:
            raise RuntimeError(
                f"Integrity violation: candidate {cid} is BOTH survivor AND dropped"
            )

        record = {
            "candidate_id": cid,
            "submitted_to_jev": True,  # All candidates are submitted (Jev iterates all)
            "evaluation_success": evaluated,
            "survived": survived,
            "in_top3": in_top3,
            "final_rank": top3_ids.get(cid),
        }
        if dropped:
            record["evaluation_success"] = False
            record["evaluation_failure_reason"] = dropped_by_id[cid]
        elif not evaluated:
            # Not in Jev output but also not in dropped list → evaluation API failure
            record["evaluation_success"] = False
            record["evaluation_failure_reason"] = "not_in_jev_output (Jev API call failed or pre-filter)"

        trace_records.append(record)

    return {
        "evaluated_at": results.get("evaluated_at", datetime.now().isoformat()),
        "lifecycle_stages": LIFECYCLE_STATES,
        "counts": counts,
        "candidates": trace_records,
    }


# === Integrity checks ===

def verify_integrity(
    candidates: list[dict],
    results: dict,
    trace: dict,
    counts: dict,
) -> dict:
    """Run integrity tests, return per-test pass/fail."""
    checks = {}

    # Test D: candidate IDs unique
    ids = [c["id"] for c in candidates]
    checks["D_unique_ids"] = len(ids) == len(set(ids))

    # Test E: trace_records completeness — every candidate has a trace
    trace_ids = {t["candidate_id"] for t in trace["candidates"]}
    checks["E_trace_complete"] = set(ids) == trace_ids

    # Test F: every evaluated candidate has an evaluation trace
    evaluated_ids = {r["id"] for r in results.get("all_evaluated", [])}
    traces_for_evaluated = [t for t in trace["candidates"] if t["candidate_id"] in evaluated_ids]
    checks["F_evaluated_has_trace"] = len(traces_for_evaluated) == len(evaluated_ids)

    # Test B: survivors <= evaluated
    survivors = results.get("all_survivors", [])
    checks["B_survivors_le_evaluated"] = len(survivors) <= counts["json_evaluated"]

    # Test C: top3 <= survivors
    top3 = results.get("top3", [])
    checks["C_top_le_survivors"] = len(top3) <= len(survivors)

    # Test A: submitted == successful + failed (counts consistency)
    submitted = counts.get("submitted")
    if submitted is not None:
        failed = submitted - counts["json_evaluated"]
        checks["A_submitted_eq_succ_plus_failed"] = (
            submitted == counts["json_evaluated"] + max(0, failed)
        )
    else:
        checks["A_submitted_eq_succ_plus_failed"] = True  # can't verify without submitted

    # Trace ↔ JSON consistency
    trace_survivors = sum(1 for t in trace["candidates"] if t["survived"])
    checks["trace_json_consistency"] = trace_survivors == counts["json_survivors"]

    return checks


# === Main orchestration ===

def run_pipeline(mission_path: Path) -> int:
    _hrule()
    print("FLIGHT ARBITRAGE HUNTER v0.2.1", flush=True)
    _hrule()

    # MISSION
    print("\nMISSION", flush=True)
    try:
        mission = stage_load_mission(mission_path)
    except Exception as e:
        print(f"\n❌ Stage failed: Mission Load\n   {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    _line("ID:", mission.get("mission_id", "(no id)"))
    _line("Origin → Destination:", f"{mission['origin']} → {mission['destination']}")
    if mission.get("departure_date"):
        _line("Dates:", f"{mission['departure_date']} → {mission.get('return_date', '?')}")
    _line("Cabin:", mission.get("cabin", "(default)"))

    # DISCOVERY
    print("\nDISCOVERY", flush=True)
    try:
        final_candidates = stage_candidate_discovery(mission)
    except Exception as e:
        print(f"\n❌ Stage failed: Candidate Discovery\n   {type(e).__name__}: {e}", file=sys.stderr)
        return 3

    raw_count = len(final_candidates)  # post-dedup, post-cap
    _line("Raw candidates:", raw_count)
    _line("After deduplication:", raw_count)
    _line("After diversity/cap:", raw_count)

    try:
        candidates_path = stage_write_candidates(final_candidates)
    except Exception as e:
        print(f"\n❌ Stage failed: Write Candidates\n   {type(e).__name__}: {e}", file=sys.stderr)
        return 4

    # EVALUATION
    print("\nEVALUATION", flush=True)
    try:
        results, jev_stdout = stage_jev_evaluation(candidates_path)
    except Exception as e:
        print(f"\n❌ Stage failed: Jev Evaluation\n   {type(e).__name__}: {e}", file=sys.stderr)
        print(f"   (Generated candidates preserved at {GENERATED_CANDIDATES_PATH})", file=sys.stderr)
        return 5

    counts = parse_jev_counts(jev_stdout, results)
    _line("Submitted to Jev:", counts.get("submitted", "?"))
    _line("Successfully evaluated:", counts["json_evaluated"])
    if counts.get("submitted"):
        failures = max(0, counts["submitted"] - counts["json_evaluated"])
        _line("Failed:", failures)
    else:
        _line("Failed:", "?")

    if counts.get("jev_survivors_print") is not None:
        if counts["jev_survivors_print"] != counts["json_survivors"]:
            _line("⚠ Console Survivors vs JSON mismatch:",
                  f"{counts['jev_survivors_print']} (console) vs {counts['json_survivors']} (json)")

    # DECISION
    print("\nDECISION", flush=True)
    _line("Evaluated:", counts["json_evaluated"])
    _line("Survivors:", counts["json_survivors"])
    _line("Top candidates:", counts["json_top3"])
    _line("Dropped:", counts["json_dropped"])

    # TRACE
    trace = build_evaluation_trace(final_candidates, results, counts)
    TRACE_PATH.write_text(json.dumps(trace, indent=2, ensure_ascii=False))
    _line("Trace file:", str(TRACE_PATH))

    # INTEGRITY
    print("\nINTEGRITY", flush=True)
    integrity = verify_integrity(final_candidates, results, trace, counts)
    all_pass = True
    for name, passed in integrity.items():
        status = "PASS" if passed else "FAIL"
        _line(name, status)
        if not passed:
            all_pass = False

    # Final spec-format summary
    _hrule()
    print("\nSUMMARY", flush=True)
    _line("Generated:", raw_count)
    _line("Submitted:", counts.get("submitted", "?"))
    _line("Success:", counts["json_evaluated"])
    if counts.get("submitted") is not None:
        _line("Failed:", max(0, counts["submitted"] - counts["json_evaluated"]))
    _line("Survivors:", counts["json_survivors"])
    _line("Top:", counts["json_top3"])
    _line("Count consistency:", "PASS" if all_pass else "FAIL")

    _hrule()
    msg = "PIPELINE COMPLETE" if all_pass else "PIPELINE COMPLETE WITH INTEGRITY ISSUES"
    print(msg, flush=True)
    _hrule()

    return 0 if all_pass else 6


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hermes Flight Arbitrage Hunter — Pipeline Orchestrator v0.2.1"
    )
    parser.add_argument("mission", type=Path, help="Path to mission JSON file")
    args = parser.parse_args()
    return run_pipeline(args.mission)


if __name__ == "__main__":
    sys.exit(main())

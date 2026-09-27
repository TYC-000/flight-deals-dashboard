"""
run_pipeline.py — Hermes Flight Arbitrage Hunter v0.2 Pipeline Orchestrator

Wires:
    mission.json
        ↓
    candidate_discovery.generate_candidates()
        ↓
    data/flight_candidates_generated.json
        ↓
    /Users/aib/.hermes/tools/eval_flight_yc.py (existing Jev pipeline)
        ↓
    data/flight_results.json

v0.2 changes from v0.1:
    + Stage-by-stage orchestration with explicit failure handling
    + Preserves intermediate artifacts (candidates + results)
    + Logging at each stage
    + Empty candidate / invalid JSON / missing file → explicit error
    + Does NOT touch Jev evaluator, does NOT modify dashboard

Architectural principle:
    Discovery Layer  →  Candidate JSON  →  Evaluation Layer
    These are independent and replaceable.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
GENERATED_CANDIDATES_PATH = DATA_DIR / "flight_candidates_generated.json"
RESULTS_PATH = DATA_DIR / "flight_results.json"
EVALUATOR_PATH = Path("/Users/aib/.hermes/tools/eval_flight_yc.py")
EVALUATOR_PYTHON = Path("/Users/aib/.hermes/hermes-agent/venv/bin/python3")


def _banner(msg: str) -> None:
    print(f"\n{'=' * 60}\n{msg}\n{'=' * 60}", flush=True)


def _stage(n: int, total: int, name: str) -> None:
    print(f"\n[{n}/{total}] {name}", flush=True)


def stage_load_mission(mission_path: Path) -> dict:
    """Stage 0: Load and validate mission JSON. Raises on error."""
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
    """Stage 1: Run candidate discovery. Raises on error or empty result."""
    # Local import to avoid circular
    sys.path.insert(0, str(REPO_ROOT))
    # Reload module fresh
    if "candidate_discovery" in sys.modules:
        del sys.modules["candidate_discovery"]
    import candidate_discovery as cd

    t0 = time.time()
    candidates = cd.generate_candidates(mission)
    elapsed = time.time() - t0

    print(f"   Raw families: {len(candidates)} candidates from {len(cd.FAMILY_GENERATORS)} family generators")
    print(f"   Discovery time: {elapsed:.2f}s")

    if not candidates:
        raise RuntimeError("Candidate discovery returned 0 candidates — aborting pipeline")

    return candidates


def stage_write_candidates(candidates: list[dict]) -> Path:
    """Stage 2: Write candidates to disk. Returns path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_CANDIDATES_PATH.write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False)
    )
    print(f"   Written: {GENERATED_CANDIDATES_PATH} ({len(candidates)} candidates)")
    return GENERATED_CANDIDATES_PATH


def stage_jev_evaluation(candidates_path: Path) -> dict:
    """Stage 3: Run Jev evaluator on candidates. Returns results dict.

    Does NOT raise on partial failure — surfaces stdout/stderr.
    """
    if not EVALUATOR_PATH.exists():
        raise FileNotFoundError(f"Evaluator not found: {EVALUATOR_PATH}")
    if not EVALUATOR_PYTHON.exists():
        raise FileNotFoundError(f"Evaluator python not found: {EVALUATOR_PYTHON}")

    t0 = time.time()
    proc = subprocess.run(
        [str(EVALUATOR_PYTHON), str(EVALUATOR_PATH), str(candidates_path)],
        capture_output=True, text=True, timeout=600,
    )
    elapsed = time.time() - t0

    if proc.returncode != 0:
        print(f"   ✗ Jev evaluator failed (rc={proc.returncode})", file=sys.stderr)
        print(f"   stderr: {proc.stderr[-500:]}", file=sys.stderr)
        raise RuntimeError(f"Jev evaluator returned rc={proc.returncode}")

    print(f"   Jev time: {elapsed:.2f}s")
    # Tail summary
    for line in proc.stdout.splitlines():
        if any(marker in line for marker in ["Survivors:", "TOP 3", "✅"]):
            print(f"   > {line.strip()}")

    # Load the results JSON to confirm
    if not RESULTS_PATH.exists():
        raise RuntimeError("Jev evaluator did not produce flight_results.json")

    with RESULTS_PATH.open() as f:
        results = json.load(f)
    return results


def stage_summary(mission: dict, candidates: list[dict], results: dict) -> dict:
    """Stage 4: Build summary report."""
    family_counts: dict[str, int] = {}
    for c in candidates:
        fam = c.get("candidate_type", "unknown")
        family_counts[fam] = family_counts.get(fam, 0) + 1

    survivors = results.get("all_survivors", [])
    evaluated = results.get("all_evaluated", [])
    top3 = results.get("top3", [])

    summary = {
        "mission_id": mission.get("mission_id", "(no id)"),
        "origin": mission.get("origin"),
        "destination": mission.get("destination"),
        "candidates_generated": len(candidates),
        "candidates_deduplicated": len(candidates),  # post-dedup, same as final
        "family_distribution": family_counts,
        "jev_evaluated": len(evaluated),
        "jev_survivors": len(survivors),
        "top3_count": len(top3),
        "outputs": {
            "candidates_json": str(GENERATED_CANDIDATES_PATH),
            "results_json": str(RESULTS_PATH),
        },
    }
    return summary


def run_pipeline(mission_path: Path) -> int:
    """Orchestrate the full pipeline. Returns exit code."""
    _banner("Flight Arbitrage Hunter v0.2")

    print(f"\nMission:")
    try:
        mission = stage_load_mission(mission_path)
        print(f"  ID:      {mission.get('mission_id', '(no id)')}")
        print(f"  Origin:  {mission['origin']}")
        print(f"  Dest:    {mission['destination']}")
        print(f"  Cabin:   {mission.get('cabin', '(default)')}")
        if mission.get("departure_date"):
            print(f"  Dates:   {mission['departure_date']} → {mission.get('return_date', '?')}")
    except Exception as e:
        print(f"\nStage failed: Mission Load\n  {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    _stage(1, 3, "Candidate Discovery")
    try:
        candidates = stage_candidate_discovery(mission)
        print(f"   Generated: {len(candidates)} candidates")
    except Exception as e:
        print(f"\nStage failed: Candidate Discovery\n  {type(e).__name__}: {e}", file=sys.stderr)
        return 3

    try:
        candidates_path = stage_write_candidates(candidates)
    except Exception as e:
        print(f"\nStage failed: Write Candidates\n  {type(e).__name__}: {e}", file=sys.stderr)
        return 4

    _stage(2, 3, "Jev Evaluation")
    try:
        results = stage_jev_evaluation(candidates_path)
    except Exception as e:
        print(f"\nStage failed: Jev Evaluation\n  {type(e).__name__}: {e}", file=sys.stderr)
        print(f"   (Generated candidates preserved at {GENERATED_CANDIDATES_PATH})", file=sys.stderr)
        return 5

    _stage(3, 3, "Output")
    summary = stage_summary(mission, candidates, results)
    print(f"\n   Candidates: {summary['candidates_generated']} → {summary['outputs']['candidates_json']}")
    print(f"   Results:    {summary['outputs']['results_json']}")
    print(f"   Jev:        {summary['jev_evaluated']} evaluated → {summary['jev_survivors']} survivors → {summary['top3_count']} Top 3")

    _banner("Pipeline complete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Flight Arbitrage Hunter — Pipeline Orchestrator v0.2")
    parser.add_argument("mission", type=Path, help="Path to mission JSON file")
    args = parser.parse_args()
    return run_pipeline(args.mission)


if __name__ == "__main__":
    sys.exit(main())

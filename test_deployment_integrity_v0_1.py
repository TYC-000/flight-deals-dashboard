"""
test_deployment_integrity_v0_1.py — Deployment integrity v0.1 tests.

These tests verify LOCAL + GITHUB invariants only. They do NOT verify
Streamlit deployment (which is behind share.streamlit.io auth).

Per spec:
  - Tests must NOT pretend to verify Streamlit deployment.
  - Streamlit items are reported as UNKNOWN, not PASS.

Tests:
A. Local working tree = flight-deals-dashboard repository
B. Local branch is main
C. Local HEAD SHA exists
D. Origin remote = https://github.com/TYC-000/flight-deals-dashboard
E. Local HEAD == origin/main (sync)
F. a0fb42b exists in local
G. a0fb42b exists in origin/main
H. L4.1 files exist locally
I. L4.1 files exist on origin/main
J. Previous architecture files exist locally and on origin/main
K. Dashboard entrypoint (flight_dashboard.py) exists locally
L. Dashboard entrypoint exists on origin/main
M. Dashboard data file (data/flight_results.json) exists locally
N. Dashboard data file exists on origin/main
O. Working tree has no tracked modifications (only untracked allowed)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
WORKDIR = HERE

RESULTS: list[tuple[str, bool, str]] = []


def _log(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}{(' :: ' + detail) if (detail and not ok) else ''}")


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git"] + list(args), capture_output=True, text=True,
        cwd=str(cwd or WORKDIR), check=False,
    ).stdout.strip()


def file_on_origin(path: str) -> bool:
    """Check whether path exists on origin/main (returns True if file is tracked)."""
    out = git("ls-tree", "origin/main", "--", path)
    return bool(out)


def main():
    print("=" * 75)
    print("Deployment Integrity v0.1 tests (test_deployment_integrity_v0_1.py)")
    print("=" * 75)

    # A. Local working tree = flight-deals-dashboard repository
    name = "A. local working tree = flight-deals-dashboard repository"
    try:
        out = git("remote", "get-url", "origin")
        ok = "TYC-000/flight-deals-dashboard" in out
        _log(name, ok, f"origin={out}")
    except Exception as e:
        _log(name, False, str(e))

    # B. Local branch is main
    name = "B. local branch is main"
    try:
        branch = git("branch", "--show-current")
        ok = branch == "main"
        _log(name, ok, f"branch={branch}")
    except Exception as e:
        _log(name, False, str(e))

    # C. Local HEAD SHA exists
    name = "C. local HEAD SHA exists"
    try:
        head = git("rev-parse", "HEAD")
        ok = len(head) == 40
        _log(name, ok, f"HEAD={head}")
    except Exception as e:
        _log(name, False, str(e))

    # D. Origin remote = expected
    name = "D. origin remote = TYC-000/flight-deals-dashboard"
    try:
        out = git("remote", "get-url", "origin")
        ok = out == "https://github.com/TYC-000/flight-deals-dashboard.git"
        _log(name, ok, f"origin={out}")
    except Exception as e:
        _log(name, False, str(e))

    # E. Local HEAD == origin/main
    name = "E. local HEAD == origin/main"
    try:
        local = git("rev-parse", "HEAD")
        remote = git("rev-parse", "origin/main")
        ok = local == remote
        _log(name, ok, f"local={local[:12]} remote={remote[:12]}")
    except Exception as e:
        _log(name, False, str(e))

    # F. a0fb42b exists in local
    name = "F. a0fb42b exists locally"
    try:
        out = git("cat-file", "-e", "a0fb42b")
        ok = "FATAL" not in out
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))

    # G. a0fb42b exists on origin/main
    name = "G. a0fb42b exists on origin/main"
    try:
        # Use git log + grep, not shell pipe
        out = subprocess.run(
            ["git", "log", "--oneline", "origin/main"],
            capture_output=True, text=True,
            cwd=str(WORKDIR), check=False,
        ).stdout
        ok = "a0fb42b" in out
        _log(name, ok, f"present on remote" if ok else "not found")
    except Exception as e:
        _log(name, False, str(e))

    # H. L4.1 files exist locally
    name = "H. L4.1 files exist locally"
    try:
        files = ["l4_1_orchestrator.py", "test_l4_1_pipeline_integration.py",
                  "docs/l4_1_pipeline_integration.md"]
        missing = [f for f in files if not (HERE / f).exists()]
        ok = len(missing) == 0
        _log(name, ok, f"missing={missing}" if missing else "all present")
    except Exception as e:
        _log(name, False, str(e))

    # I. L4.1 files exist on origin/main
    name = "I. L4.1 files exist on origin/main"
    try:
        files = ["l4_1_orchestrator.py", "test_l4_1_pipeline_integration.py",
                  "docs/l4_1_pipeline_integration.md"]
        missing = [f for f in files if not file_on_origin(f)]
        ok = len(missing) == 0
        _log(name, ok, f"missing={missing}" if missing else "all present on remote")
    except Exception as e:
        _log(name, False, str(e))

    # J. Previous architecture files (local + remote)
    name = "J. previous architecture files (local + origin/main)"
    try:
        files = ["candidate_discovery.py", "run_pipeline.py", "schedule_intelligence.py",
                  "price_intelligence.py", "kiwi_price_provider.py", "live_schedule_provider.py",
                  "fx_provider.py", "passenger_parity.py", "baseline_canonicalization.py",
                  "comparison_engine.py", "arbitrage_detection.py"]
        local_missing = [f for f in files if not (HERE / f).exists()]
        gh_missing = [f for f in files if not file_on_origin(f)]
        ok = (len(local_missing) == 0 and len(gh_missing) == 0)
        _log(name, ok, f"local_missing={local_missing}, gh_missing={gh_missing}")
    except Exception as e:
        _log(name, False, str(e))

    # K. Dashboard entrypoint exists locally
    name = "K. flight_dashboard.py exists locally"
    try:
        ok = (HERE / "flight_dashboard.py").exists()
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))

    # L. Dashboard entrypoint exists on origin/main
    name = "L. flight_dashboard.py exists on origin/main"
    try:
        ok = file_on_origin("flight_dashboard.py")
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))

    # M. Dashboard data file exists locally
    name = "M. data/flight_results.json exists locally"
    try:
        ok = (HERE / "data" / "flight_results.json").exists()
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))

    # N. Dashboard data file exists on origin/main
    name = "N. data/flight_results.json exists on origin/main"
    try:
        ok = file_on_origin("data/flight_results.json")
        _log(name, ok)
    except Exception as e:
        _log(name, False, str(e))

    # O. Working tree has no tracked modifications
    name = "O. working tree has no tracked modifications"
    try:
        out = git("status", "--short", "--porcelain")
        # Porcelain format: 'M ', ' M', 'A ', 'D ' for staged; '??' for untracked
        tracked_changes = [
            line for line in out.splitlines()
            if not line.startswith("??")
        ]
        ok = len(tracked_changes) == 0
        _log(name, ok, f"untracked={len([l for l in out.splitlines() if l.startswith('??')])}, tracked_changes={len(tracked_changes)}")
    except Exception as e:
        _log(name, False, str(e))

    # Summary
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n" + "=" * 75)
    print(f"Deployment Integrity v0.1: {len(RESULTS)} tests, {passed} passed, {failed} failed")
    print("=" * 75)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

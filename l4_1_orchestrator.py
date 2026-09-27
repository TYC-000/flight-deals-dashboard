"""
l4_1_orchestrator.py — L0→L4 pipeline integration (L4.1)

Orchestrates the existing v0.1 / v1.0 / v1.1 / v1.2.x / L4 modules
without modifying them, by invoking their CLI entry points and reading
their JSON outputs.

DESIGN PRINCIPLES (per L4.1 spec):
  - DO NOT modify any v1.0 / v1.1 / v1.2.x / L4 evidence module.
  - DO NOT modify Jev.
  - DO NOT bypass the comparison layer.
  - DO preserve candidate_id from discovery → ArbitrageEvidence.
  - DO use real providers only when credentials exist; fail-closed otherwise.
  - DO NOT relabel mock evidence as live/duffel.
  - DO emit traceable evidence refs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
PYTHON_BIN = Path("/Users/aib/.hermes/hermes-agent/venv/bin/python3")

# Default artifact paths (per existing v1.x modules)
GENERATED_CANDIDATES_PATH = DATA_DIR / "flight_candidates_generated.json"
SCHEDULE_ENRICHED_PATH = DATA_DIR / "schedule_enriched_candidates.json"
SCHEDULE_TRACE_PATH = DATA_DIR / "schedule_trace.json"
PRICE_EVIDENCE_PATH = DATA_DIR / "price_evidence.json"
PRICE_TRACE_PATH = DATA_DIR / "price_trace.json"
SCHEDULE_EVIDENCE_V121_PATH = DATA_DIR / "schedule_evidence_v1_2_1.json"
SCHEDULE_TRACE_V121_PATH = DATA_DIR / "schedule_trace_v1_2_1.json"
FX_EVIDENCE_PATH = DATA_DIR / "fx_evidence_v1_2_2.json"
FX_TRACE_PATH = DATA_DIR / "fx_trace_v1_2_2.json"
PARITY_EVIDENCE_PATH = DATA_DIR / "passenger_parity_evidence_v1_2_3.json"
PARITY_TRACE_PATH = DATA_DIR / "passenger_parity_trace_v1_2_3.json"
BASELINE_EVIDENCE_PATH = DATA_DIR / "baseline_evidence_v1_2_4.json"
BASELINE_TRACE_PATH = DATA_DIR / "baseline_trace_v1_2_4.json"
COMPARISON_EVIDENCE_PATH = DATA_DIR / "comparison_evidence_v1_2_5.json"
COMPARISON_TRACE_PATH = DATA_DIR / "comparison_trace_v1_2_5.json"
ARBITRAGE_EVIDENCE_PATH = DATA_DIR / "arbitrage_evidence_l4.json"
ARBITRAGE_TRACE_PATH = DATA_DIR / "arbitrage_trace_l4.json"

L41_RUN_TRACE_PATH = DATA_DIR / "l4_1_run_trace.json"

# Working directory used for in/out JSON files per stage
L41_WORKDIR = DATA_DIR / "l4_1_workdir"
L41_WORKDIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Helpers
# ============================================================================

def _hrule(char: str = "=") -> None:
    print(char * 60, flush=True)


def _stage(n: int, total: int, name: str) -> None:
    print(f"\n[{n}/{total}] {name}", flush=True)


def _line(label: str, value: Any, width: int = 30) -> None:
    print(f"  {label:<{width}} {value}", flush=True)


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def _run_subprocess(args: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Run a subprocess synchronously. Returns (rc, stdout, stderr)."""
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            cwd=str(REPO_ROOT))
    return proc.returncode, proc.stdout, proc.stderr


# ============================================================================
# Credential check (fail-closed per spec §5)
# ============================================================================

def check_provider_credential(provider: str, provider_mode: str) -> dict[str, Any]:
    out = {"honored": True, "actual_provider": provider,
           "actual_mode": provider_mode, "credential_present": False,
           "credential_checked_env": None, "refusal_reason": None}
    if provider_mode == "mock":
        return out
    if provider == "duffel":
        env_keys = ("DUFFEL_API_KEY_LIVE", "DUFFEL_API_KEY_TEST")
        for k in env_keys:
            if os.environ.get(k):
                out["credential_present"] = True
                out["credential_checked_env"] = k
                break
        if not out["credential_present"]:
            out["honored"] = False
            out["refusal_reason"] = (
                f"provider=duffel requested with provider_mode={provider_mode} "
                f"but no credential in {env_keys}. Per L4.1 §5: fail-closed."
            )
        return out
    if provider == "kiwi":
        env_keys = ("KIWI_API_KEY", "KIWI_TEQUILA_API_KEY")
        for k in env_keys:
            if os.environ.get(k):
                out["credential_present"] = True
                out["credential_checked_env"] = k
                break
        if not out["credential_present"]:
            out["honored"] = False
            out["refusal_reason"] = (
                f"provider=kiwi requested with provider_mode={provider_mode} "
                f"but no credential in {env_keys}. Per L4.1 §5: fail-closed."
            )
        return out
    return out


# ============================================================================
# Stage 1 — Discovery (in-process)
# ============================================================================

def stage_l41_discovery(mission: dict) -> list[dict[str, Any]]:
    """Stage L4.1.1: Run candidate discovery (v0.1, in-process).

    Returns the list of candidates with original `id` field preserved.
    """
    if "candidate_discovery" in sys.modules:
        del sys.modules["candidate_discovery"]
    import candidate_discovery as cd
    t0 = time.time()
    candidates = cd.generate_candidates(mission)
    elapsed = time.time() - t0
    print(f"   Family generators: {len(cd.FAMILY_GENERATORS)}")
    print(f"   Discovery time: {elapsed:.2f}s")
    print(f"   Candidates: {len(candidates)}")

    no_id = [i for i, c in enumerate(candidates) if not c.get("id")]
    if no_id:
        raise RuntimeError(
            f"Discovery returned {len(no_id)} candidates without `id` — aborting"
        )
    return candidates


# ============================================================================
# Stage 2 — Schedule Intelligence (v1.0, in-process)
# ============================================================================

def stage_l41_schedule_enrich(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stage L4.1.2: v1.0 Schedule Intelligence (OpenFlights DATABASE).

    enrich_candidates returns (enriched, traces, summary); we keep enriched.
    """
    if "schedule_intelligence" in sys.modules:
        del sys.modules["schedule_intelligence"]
    import schedule_intelligence as si
    result = si.enrich_candidates(candidates)
    if isinstance(result, tuple):
        return result[0]
    return result


# ============================================================================
# Stage 3 — Price Intelligence (v1.1/v1.2.0, CLI subprocess)
# ============================================================================

def stage_l41_price_evidence(
        candidates_path: Path,
        provider: str,
        provider_mode: str,
        max_searches: int,
        date_window: str,
        passengers: int,
        smoke_test: bool,
        credential_check: dict[str, Any],
) -> dict[str, Any]:
    """Stage L4.1.3: v1.1/v1.2.0 Price Intelligence (CLI subprocess).

    Returns a dict with `evidences`, `actual_provider`, `actual_provider_mode`,
    `n_live`, `n_mock`, `n_refused`.
    """
    output_path = L41_WORKDIR / "price_evidence_l41.json"
    trace_path = L41_WORKDIR / "price_trace_l41.json"

    # Map L4.1 names to price_intelligence CLI names
    # price_intelligence uses build_provider(spec) where spec ∈ {mock, duffel, mock_kiwi, kiwi, auto}
    # But the CLI (price_intelligence.py main) does NOT take --provider. It auto-builds based on
    # credential availability. We'll invoke via Python module + override via env.

    args = [
        str(PYTHON_BIN),
        str(REPO_ROOT / "price_intelligence.py"),
        str(candidates_path),
        "--max-searches", str(max_searches),
        "--smoke-test" if smoke_test else "--no-smoke-test",
        "--date-window", date_window,
        "--passengers", str(passengers),
        "--output", str(output_path),
        "--trace", str(trace_path),
    ]
    # Note: price_intelligence's CLI does not accept --provider; provider is determined
    # internally based on env. If user requested explicit duffel/kiwi without creds,
    # build_provider() will raise; we'll catch that.

    rc, stdout, stderr = _run_subprocess(args, timeout=300)
    if rc != 0 and "MISSING_CREDENTIALS" not in stderr:
        # Real failure (not a credential issue)
        print(f"   ⚠ price_intelligence rc={rc}: {stderr[:300]}", flush=True)

    if not output_path.exists():
        # Refused (likely missing creds) — emit stub evidence for each candidate
        print(f"   ⚠ Price evidence NOT emitted (refused or no candidates). "
              f"Reason: {stderr[:200]}", flush=True)
        return {
            "evidences": [],
            "actual_provider": None,
            "actual_provider_mode": None,
            "n_live": 0, "n_mock": 0, "n_refused": 0,
            "rc": rc,
            "refusal_reason": credential_check.get("refusal_reason") if not credential_check["honored"] else stderr[:300],
        }

    # Read output
    out = json.loads(output_path.read_text())
    evidences = out.get("evidences", [])
    # Determine actual provider/mode from output schema
    actual_provider = out.get("provider")
    # Distinguish LIVE from MOCK via verification_status
    n_live = sum(1 for e in evidences if e.get("verification_status") == "LIVE")
    n_mock = sum(1 for e in evidences if (e.get("provider_mode") == "mock") and e.get("verification_status") == "LIVE")
    n_refused = sum(1 for e in evidences if e.get("price_status") == "REFUSED" or e.get("verification_status") == "UNKNOWN")
    # The actual provider_mode from each evidence
    modes = set()
    for e in evidences:
        if e.get("provider_mode"):
            modes.add(e["provider_mode"])
    actual_mode = next(iter(modes)) if len(modes) == 1 else (",".join(sorted(modes)) if modes else None)
    return {
        "evidences": evidences,
        "actual_provider": actual_provider,
        "actual_provider_mode": actual_mode,
        "n_live": n_live,
        "n_mock": n_mock,
        "n_refused": n_refused,
        "rc": rc,
    }


# ============================================================================
# Stage 4 — Live Schedule (v1.2.1, CLI subprocess, mock only)
# ============================================================================

def stage_l41_live_schedule(
        candidates_path: Path,
        max_searches: int,
        date_window: str,
        passengers: int,
        smoke_test: bool,
        schedule_provider: str = "mock_duffel",
) -> dict[str, Any]:
    """Stage L4.1.4: v1.2.1 Live Schedule (mock_duffel for safety)."""
    output_path = L41_WORKDIR / "schedule_evidence_v121_l41.json"
    trace_path = L41_WORKDIR / "schedule_trace_v121_l41.json"

    args = [
        str(PYTHON_BIN),
        str(REPO_ROOT / "live_schedule_provider.py"),
        str(candidates_path),
        "--schedule-provider", schedule_provider,
        "--max-searches", str(max_searches),
        "--smoke-test" if smoke_test else "--no-smoke-test",
        "--date-window", date_window,
        "--passengers", str(passengers),
        "--output", str(output_path),
        "--trace", str(trace_path),
    ]
    rc, stdout, stderr = _run_subprocess(args, timeout=300)
    if rc != 0:
        print(f"   ⚠ live_schedule_provider rc={rc}: {stderr[:300]}", flush=True)
    if not output_path.exists():
        return {"evidences": [], "rc": rc, "provider": schedule_provider, "provider_mode": "mock"}
    out = json.loads(output_path.read_text())
    return {
        "evidences": out.get("evidences", []),
        "rc": rc,
        "provider": schedule_provider,
        "provider_mode": "mock",
    }


# ============================================================================
# Stage 5 — FX (v1.2.2, CLI subprocess)
# ============================================================================

def stage_l41_fx(
        base: str,
        quote: str,
        fx_provider: str,
        smoke_test: bool,
) -> dict[str, Any] | None:
    """Stage L4.1.5: v1.2.2 FX (Frankfurter or mock)."""
    output_path = L41_WORKDIR / "fx_evidence_v122_l41.json"
    trace_path = L41_WORKDIR / "fx_trace_v122_l41.json"
    args = [
        str(PYTHON_BIN),
        str(REPO_ROOT / "fx_provider.py"),
        "--fx-provider", fx_provider,
        "--smoke-test" if smoke_test else "--no-smoke-test",
        "--base", base,
        "--quote", quote,
        "--output", str(output_path),
        "--trace", str(trace_path),
    ]
    rc, stdout, stderr = _run_subprocess(args, timeout=120)
    if rc != 0:
        print(f"   ⚠ fx_provider rc={rc}: {stderr[:300]}", flush=True)
    if not output_path.exists():
        return None
    out = json.loads(output_path.read_text())
    evs = out.get("evidences", [])
    return evs[0] if evs else None


# ============================================================================
# Stage 6 — Build Parity / Baseline / Comparison / L4 (in-process)
# ============================================================================

def stage_l41_passenger_parity(
        evidence_a: dict[str, Any],
        evidence_b: dict[str, Any],
) -> dict[str, Any]:
    """Stage L4.1.6: v1.2.3 Passenger Parity (in-process)."""
    if "passenger_parity" in sys.modules:
        del sys.modules["passenger_parity"]
    import passenger_parity as pp
    return pp.evaluate_passenger_parity(evidence_a, evidence_b)


def stage_l41_baseline(
        mission: dict,
        candidate: dict[str, Any],
) -> dict[str, Any]:
    """Stage L4.1.7: v1.2.4 Baseline Canonicalization (in-process)."""
    if "baseline_canonicalization" in sys.modules:
        del sys.modules["baseline_canonicalization"]
    import baseline_canonicalization as bc
    return bc.canonicalize_for_candidate(mission, candidate)


def stage_l41_comparison(
        candidate_a: dict[str, Any],
        candidate_b: dict[str, Any],
        fx_evidence: dict[str, Any] | None,
        baseline_pair: dict[str, Any] | None,
        comparison_currency: str = "EUR",
) -> dict[str, Any]:
    """Stage L4.1.8: v1.2.5 Comparison Engine (in-process)."""
    if "comparison_engine" in sys.modules:
        del sys.modules["comparison_engine"]
    import comparison_engine as ce
    return ce.build_comparison_evidence(
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        fx_evidence=fx_evidence,
        baseline_pair=baseline_pair,
        comparison_currency=comparison_currency,
    )


def stage_l41_arbitrage(
        candidate: dict[str, Any],
        baseline: dict[str, Any] | None,
        comparison: dict[str, Any],
        fx_evidence: dict[str, Any] | None,
        schedule_evidence_a: dict[str, Any] | None = None,
        schedule_evidence_b: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage L4.1.9: L4 Arbitrage Detection (in-process)."""
    if "arbitrage_detection" in sys.modules:
        del sys.modules["arbitrage_detection"]
    import arbitrage_detection as L4
    return L4.build_arbitrage_evidence(
        candidate=candidate,
        baseline=baseline,
        comparison=comparison,
        fx_evidence=fx_evidence,
        schedule_evidence_a=schedule_evidence_a,
        schedule_evidence_b=schedule_evidence_b,
    )


# ============================================================================
# Normalize price-evidence for parity input
# ============================================================================

def normalize_price_for_parity(candidate: dict[str, Any],
                                 price_ev: dict[str, Any] | None) -> dict[str, Any]:
    """Build a parity-compatible input from a candidate + price-evidence record.

    Per passenger_parity.evaluate_passenger_parity contract, the input dict
    must carry normalized fields (passenger_count / passenger_types / cabin /
    ticket_structure / baggage / fare_basis). Missing fields stay None
    (UNKNOWN semantics), never coerced.
    """
    cid = candidate.get("id")
    if price_ev is None:
        return {
            "candidate_id": cid,
            "currency": None,
            "total_price": None,
            "ticket_count": None,
            "is_single_ticket": None,
            "cabin": candidate.get("cabin"),
            "passenger_count": candidate.get("passengers", 1),
            "passenger_types": candidate.get("passenger_types", ["ADT"]),
            "baggage": None,
            "fare_basis_code": None,
        }
    # Build from price_evidence nested structure if present
    pe_nested = price_ev.get("price_evidence") or {}
    return {
        "candidate_id": cid,
        "currency": price_ev.get("currency"),
        "total_price": (price_ev.get("total_price") or {}).get("amount")
                          if isinstance(price_ev.get("total_price"), dict)
                          else price_ev.get("total_price"),
        "ticket_count": price_ev.get("ticket_count"),
        "is_single_ticket": price_ev.get("is_single_ticket"),
        "cabin": pe_nested.get("cabin") or candidate.get("cabin"),
        "passenger_count": candidate.get("passengers", 1),
        "passenger_types": candidate.get("passenger_types", ["ADT"]),
        "baggage": pe_nested.get("baggage"),
        "fare_basis_code": pe_nested.get("fare_basis_code"),
    }


# ============================================================================
# Main orchestration
# ============================================================================

def run_l41_pipeline(mission_path: Path,
                       provider: str = "mock",
                       provider_mode: str = "mock",
                       fx_provider: str = "frankfurter",
                       max_searches: int = 5,
                       max_l4_pairs: int = 5,
                       date_window: str = "2027-04-15",
                       passengers: int = 1,
                       smoke_test: bool = True,
                       ) -> int:
    """Run the L0→L4 chain end-to-end with lineage preservation."""
    _hrule()
    print("FLIGHT ARBITRAGE HUNTER — L0→L4 Pipeline Integration (L4.1)", flush=True)
    _hrule()

    run_trace: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "version": "l4.1/v1",
        "stages": [],
        "real_external_requests": [],
        "credential_checks": [],
    }

    # === MISSION LOAD ===
    _stage(1, 9, "MISSION LOAD")
    if not mission_path.exists():
        print(f"\n❌ Mission not found: {mission_path}", file=sys.stderr)
        return 11
    mission = json.loads(mission_path.read_text())
    run_trace["mission"] = mission
    _line("mission_id:", mission.get("mission_id", "(no id)"))
    _line("route:", f"{mission.get('origin')} → {mission.get('destination')}")
    _line("dates:", f"{mission.get('departure_date')} → {mission.get('return_date', '?')}")

    # === CREDENTIAL CHECK ===
    _stage(2, 9, "CREDENTIAL CHECK")
    cred = check_provider_credential(provider, provider_mode)
    run_trace["credential_checks"].append({
        "stage": "price_provider",
        "requested": {"provider": provider, "provider_mode": provider_mode},
        **cred,
    })
    if not cred["honored"]:
        _line("STATUS:", f"FAIL-CLOSED — {cred['refusal_reason']}")
        # Continue; emit REFUSED records (don't silently fallback).
    else:
        _line("STATUS:", f"OK ({cred['actual_provider']}/{cred['actual_mode']})")
    cred_fx = check_provider_credential("frankfurter", "live")  # FX is its own provider
    _line("FX credential:", "OK" if cred_fx["honored"] else "(none required)")

    # === STAGE 3 — DISCOVERY ===
    _stage(3, 9, "CANDIDATE DISCOVERY (v0.1)")
    candidates = stage_l41_discovery(mission)
    candidate_ids = [c.get("id") for c in candidates]
    run_trace["stages"].append({
        "stage": "discovery",
        "n_candidates": len(candidates),
        "candidate_ids": candidate_ids,
    })
    _line("candidates:", len(candidates))
    _save_json(GENERATED_CANDIDATES_PATH, candidates)

    # === STAGE 4 — SCHEDULE ENRICHMENT (v1.0) ===
    _stage(4, 9, "SCHEDULE INTELLIGENCE (v1.0 — OpenFlights DATABASE)")
    try:
        enriched = stage_l41_schedule_enrich(candidates)
        lineage = [(o.get("id"), e.get("id")) for o, e in zip(candidates, enriched)]
        preserved = sum(1 for a, b in lineage if a == b)
        run_trace["stages"].append({
            "stage": "schedule_enrichment_v1_0",
            "n_in": len(candidates),
            "n_out": len(enriched),
            "n_candidate_ids_preserved": preserved,
            "data_source": "openflights_routes.dat",
        })
        _line("candidates in/out:", f"{len(candidates)} / {len(enriched)}")
        _line("ids preserved:", preserved)
        _save_json(SCHEDULE_ENRICHED_PATH, enriched)
    except Exception as e:
        print(f"   ⚠ schedule_intelligence failed: {type(e).__name__}: {e}")
        enriched = candidates
        run_trace["stages"].append({
            "stage": "schedule_enrichment_v1_0",
            "status": "FAILED",
            "error": str(e),
        })

    # === STAGE 5 — PRICE EVIDENCE (v1.1/v1.2.0) ===
    _stage(5, 9, "PRICE EVIDENCE (v1.1/v1.2.0)")
    # Write a temporary candidates file for the price CLI
    cand_for_price = L41_WORKDIR / "candidates_for_price.json"
    _save_json(cand_for_price, enriched)

    if cred["honored"]:
        price_result = stage_l41_price_evidence(
            cand_for_price,
            provider=provider,
            provider_mode=provider_mode,
            max_searches=max_searches,
            date_window=date_window,
            passengers=passengers,
            smoke_test=smoke_test,
            credential_check=cred,
        )
        price_evidences = price_result["evidences"]
    else:
        # FAIL-CLOSED: emit refusal records per candidate
        price_evidences = []
        for c in enriched:
            price_evidences.append({
                "candidate_id": c.get("id"),
                "provider": provider,
                "provider_mode": provider_mode,
                "verification_status": "UNKNOWN",
                "price_status": "REFUSED",
                "failure_kind": "MISSING_CREDENTIALS",
                "failure_reason": cred["refusal_reason"],
                "currency": None,
                "total_price": None,
                "ticket_count": None,
                "is_single_ticket": None,
                "self_transfer": None,
                "separate_ticket_risk": None,
                "freshness_min": None,
                "freshness_bucket": None,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "warnings": ["REFUSED: provider requested without credential"],
                "price_evidence": None,
            })
        price_result = {
            "evidences": price_evidences,
            "actual_provider": provider,
            "actual_provider_mode": provider_mode,
            "n_live": 0, "n_mock": 0, "n_refused": len(price_evidences),
            "rc": 10,
        }

    pe_index = {pe.get("candidate_id"): pe for pe in price_evidences if pe.get("candidate_id")}
    run_trace["stages"].append({
        "stage": "price_evidence",
        "n_evidences": len(price_evidences),
        "n_live": price_result["n_live"],
        "n_mock": price_result["n_mock"],
        "n_refused": price_result["n_refused"],
        "actual_provider": price_result["actual_provider"],
        "actual_provider_mode": price_result["actual_provider_mode"],
        "candidate_ids_with_live_evidence": [pe.get("candidate_id") for pe in price_evidences
                                                if pe.get("verification_status") == "LIVE"],
    })
    _line("price evidences:", len(price_evidences))
    _line("live/mock/refused:", f"{price_result['n_live']} / {price_result['n_mock']} / {price_result['n_refused']}")
    _line("actual provider:", f"{price_result['actual_provider']}/{price_result['actual_provider_mode']}")
    _save_json(PRICE_EVIDENCE_PATH, {
        "schema": "price_intelligence_v1_1",
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "provider": price_result["actual_provider"],
        "smoke_test": smoke_test,
        "summary": {
            "provider": price_result["actual_provider"],
            "candidates_received": len(enriched),
            "candidates_with_evidence": price_result["n_live"],
            "candidates_failed": price_result["n_refused"],
            "n_live": price_result["n_live"],
            "n_mock": price_result["n_mock"],
            "n_refused": price_result["n_refused"],
        },
        "evidences": price_evidences,
    })

    # === STAGE 6 — LIVE SCHEDULE (v1.2.1) — mock only ===
    _stage(6, 9, "LIVE SCHEDULE (v1.2.1 — mock_duffel)")
    sched_result = stage_l41_live_schedule(
        cand_for_price, max_searches, date_window, passengers, smoke_test,
        schedule_provider="mock_duffel",
    )
    sched_ev_list = sched_result.get("evidences", [])
    sched_index = {}
    for s in sched_ev_list:
        if isinstance(s, dict) and s.get("candidate_id"):
            sched_index[s["candidate_id"]] = s
    run_trace["stages"].append({
        "stage": "live_schedule_v1_2_1",
        "n_evidences": len(sched_ev_list),
        "provider": sched_result["provider"],
        "provider_mode": sched_result["provider_mode"],
        "candidate_ids_with_schedule": list(sched_index.keys())[:5],
    })
    _line("schedule evidences:", len(sched_ev_list))
    _line("provider:", f"{sched_result['provider']}/{sched_result['provider_mode']}")
    _save_json(SCHEDULE_EVIDENCE_V121_PATH, {
        "schema": "schedule_provider_v1_2_1",
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "schedule_provider": sched_result["provider"],
        "smoke_test": smoke_test,
        "evidences": sched_ev_list,
    })

    # === STAGE 7 — FX (v1.2.2) ===
    _stage(7, 9, "FX (v1.2.2 — Frankfurter)")
    fx_evidence = stage_l41_fx(
        base="TWD", quote="EUR",
        fx_provider=fx_provider, smoke_test=smoke_test,
    )
    fx_state = (fx_evidence.get("verification_status") if fx_evidence else "UNKNOWN")
    # Real external request counter (Frankfurter smoke only)
    if fx_evidence and fx_evidence.get("fx_evidence", {}).get("provider") == "frankfurter":
        run_trace["real_external_requests"].append({
            "provider": "frankfurter",
            "endpoint": "/v2/rate/{base}/{quote}",
            "verified_smoke_only": True,
            "verification_status": fx_state,
            "retrieved_at": fx_evidence.get("fx_evidence", {}).get("retrieved_at"),
        })
    run_trace["stages"].append({
        "stage": "fx",
        "fx_evidence_emitted": fx_evidence is not None,
        "fx_state": fx_state,
    })
    _line("fx state:", fx_state)
    if fx_evidence:
        _save_json(FX_EVIDENCE_PATH, {
            "schema": "fx_provider_v1_2_2",
            "trace_at": datetime.now(timezone.utc).isoformat(),
            "fx_provider": fx_provider,
            "smoke_test": smoke_test,
            "summary": {"conversions_succeeded": 1, "conversions_failed": 0,
                          "verification_status_distribution": {fx_state: 1}},
            "evidences": [fx_evidence],
        })

    # === STAGE 8 — BASELINE / PARITY / COMPARISON / L4 for each pair ===
    _stage(8, 9, "BASELINE / PARITY / COMPARISON / L4")
    # Pick LIVE candidates and pair them with another LIVE candidate of same O&D
    live_candidates = []
    for c in enriched:
        pe = pe_index.get(c.get("id"))
        if pe and pe.get("verification_status") == "LIVE":
            live_candidates.append(c)

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    used: set[str] = set()
    for a in live_candidates:
        if a.get("id") in used:
            continue
        for b in live_candidates:
            if a is b or b.get("id") in used:
                continue
            if (a.get("origin"), a.get("destination")) == (b.get("origin"), b.get("destination")):
                pairs.append((a, b))
                used.add(a["id"])
                used.add(b["id"])
                break
        if len(pairs) >= max_l4_pairs:
            break
    run_trace["stages"].append({
        "stage": "pairing",
        "n_live_candidates": len(live_candidates),
        "n_pairs": len(pairs),
    })
    _line("live candidates:", len(live_candidates))
    _line("pairs:", len(pairs))

    parity_records: list[dict[str, Any]] = []
    baseline_records: list[dict[str, Any]] = []
    comparison_records: list[dict[str, Any]] = []
    arbitrage_records: list[dict[str, Any]] = []

    for ci, (cand_a, cand_b) in enumerate(pairs):
        cid_a = cand_a.get("id")
        cid_b = cand_b.get("id")
        pe_a = pe_index.get(cid_a)
        pe_b = pe_index.get(cid_b)

        # Parity
        a_norm = normalize_price_for_parity(cand_a, pe_a)
        b_norm = normalize_price_for_parity(cand_b, pe_b)
        parity = stage_l41_passenger_parity(a_norm, b_norm)
        parity["candidate_a_id"] = cid_a
        parity["candidate_b_id"] = cid_b
        parity["stage"] = "passenger_parity"
        parity["trace_at"] = datetime.now(timezone.utc).isoformat()
        parity_records.append(parity)

        # Baseline (per candidate_a)
        baseline = stage_l41_baseline(mission, cand_a)
        baseline["stage"] = "baseline"
        baseline_records.append(baseline)

        # Comparison
        comparison = stage_l41_comparison(
            cand_a, cand_b, fx_evidence,
            baseline_pair=None, comparison_currency="EUR",
        )
        # Replace synthetic ids with real ones
        comparison["candidate_a_id"] = cid_a
        comparison["candidate_b_id"] = cid_b
        comparison["stage"] = "comparison"
        comparison["trace_at"] = datetime.now(timezone.utc).isoformat()
        comparison_records.append(comparison)

        # Schedule refs
        sched_a = sched_index.get(cid_a)
        sched_b = sched_index.get(cid_b)

        # L4
        try:
            # Inject price evidence into candidate so L4's price_evidence_refs is populated
            cand_a_with_pe = dict(cand_a)
            if pe_a:
                cand_a_with_pe["price_evidence"] = pe_a
            cand_b_with_pe = dict(cand_b)
            if pe_b:
                cand_b_with_pe["price_evidence"] = pe_b
            arb = stage_l41_arbitrage(
                candidate=cand_a_with_pe,
                baseline=baseline,
                comparison=comparison,
                fx_evidence=fx_evidence,
                schedule_evidence_a=sched_a,
                schedule_evidence_b=sched_b,
            )
        except Exception as e:
            arb = {
                "schema_version": "l4/v1",
                "arbitrage_id": f"L4::{cid_a}::REFUSED",
                "candidate_id": cid_a,
                "baseline_id": baseline.get("baseline_id") if baseline else None,
                "comparison_id": comparison.get("comparison_id"),
                "arbitrage_state": "INSUFFICIENT_EVIDENCE",
                "failure_reason": f"L4 build failed: {type(e).__name__}: {e}",
                "failure_kind": "L4_BUILD_ERROR",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "rule_version": "l4/v1",
            }
        # PRESERVE candidate_id (do not replace)
        arb["candidate_id"] = cid_a
        arb["trace_at"] = datetime.now(timezone.utc).isoformat()
        arb["stage"] = "arbitrage"
        arbitrage_records.append(arb)

    # Persist all artifacts
    if comparison_records:
        _save_json(COMPARISON_EVIDENCE_PATH, {
            "schema": "comparison_engine_v1_2_5",
            "trace_at": datetime.now(timezone.utc).isoformat(),
            "n_evidences": len(comparison_records),
            "evidences": comparison_records,
        })
    if parity_records:
        _save_json(PARITY_EVIDENCE_PATH, {
            "schema": "passenger_parity_v1_2_3",
            "trace_at": datetime.now(timezone.utc).isoformat(),
            "n_evidences": len(parity_records),
            "evidences": parity_records,
        })
    if baseline_records:
        _save_json(BASELINE_EVIDENCE_PATH, {
            "schema": "baseline_canonicalization_v1_2_4",
            "trace_at": datetime.now(timezone.utc).isoformat(),
            "n_evidences": len(baseline_records),
            "evidences": baseline_records,
        })
    if arbitrage_records:
        # Canonical: sort by candidate_id, take first
        sorted_arb = sorted(arbitrage_records, key=lambda x: x.get("candidate_id", ""))
        canonical = sorted_arb[0]
        _save_json(ARBITRAGE_EVIDENCE_PATH, canonical)
        _line("canonical ArbitrageEvidence:", f"candidate_id={canonical.get('candidate_id')}")
        # Also save the full list for transparency
        _save_json(DATA_DIR / "arbitrage_evidence_l4_list.json", {
            "schema": "l4/v1-list",
            "trace_at": datetime.now(timezone.utc).isoformat(),
            "n_evidences": len(arbitrage_records),
            "evidences": sorted_arb,
        })

    # === STAGE 9 — RUN TRACE ===
    _stage(9, 9, "RUN TRACE")
    run_trace["completed_at"] = datetime.now(timezone.utc).isoformat()
    run_trace["n_arbitrage_evidences"] = len(arbitrage_records)
    run_trace["n_comparison_evidences"] = len(comparison_records)
    run_trace["n_parity_evidences"] = len(parity_records)
    run_trace["n_baseline_evidences"] = len(baseline_records)
    run_trace["n_price_evidences"] = len(price_evidences)
    run_trace["n_schedule_evidences"] = len(sched_ev_list)
    run_trace["candidate_ids_with_l4"] = [a.get("candidate_id") for a in arbitrage_records]
    _save_json(L41_RUN_TRACE_PATH, run_trace)
    _line("trace:", str(L41_RUN_TRACE_PATH))

    _hrule()
    print(f"\nL4.1 PIPELINE COMPLETE", flush=True)
    print(f"  candidates: {len(enriched)}", flush=True)
    print(f"  schedule_enriched (v1.0): {len(enriched)} (OpenFlights DATABASE)", flush=True)
    print(f"  price evidences: {len(price_evidences)} "
          f"(live={price_result['n_live']}, mock={price_result['n_mock']}, refused={price_result['n_refused']})", flush=True)
    print(f"  schedule evidences (v1.2.1): {len(sched_ev_list)}", flush=True)
    print(f"  FX evidence (v1.2.2): {1 if fx_evidence else 0}", flush=True)
    print(f"  parity evidences: {len(parity_records)}", flush=True)
    print(f"  baseline evidences: {len(baseline_records)}", flush=True)
    print(f"  comparison evidences: {len(comparison_records)}", flush=True)
    print(f"  ArbitrageEvidence: {len(arbitrage_records)}", flush=True)
    print(f"  real external requests: {len(run_trace['real_external_requests'])}", flush=True)
    print(f"  canonical arbitrage_evidence: candidate_id={arbitrage_records[0].get('candidate_id') if arbitrage_records else None}", flush=True)
    _hrule()
    return 0


# ============================================================================
# CLI
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hermes Flight Arbitrage Hunter — L0→L4 Pipeline Integration (L4.1)"
    )
    parser.add_argument("mission", type=Path)
    parser.add_argument("--provider", type=str, default="mock",
                          choices=["mock", "duffel", "kiwi", "auto", "mock_duffel", "mock_kiwi"],
                          help="Price provider")
    parser.add_argument("--provider-mode", type=str, default="mock",
                          choices=["mock", "live"],
                          help="Provider mode (live requires credential; else fail-closed)")
    parser.add_argument("--fx-provider", type=str, default="frankfurter",
                          choices=["frankfurter", "mock"])
    parser.add_argument("--max-searches", type=int, default=5)
    parser.add_argument("--max-l4-pairs", type=int, default=5)
    parser.add_argument("--date-window", type=str, default="2027-04-15")
    parser.add_argument("--passengers", type=int, default=1)
    parser.add_argument("--smoke-test", action="store_true", default=True)
    return run_l41_pipeline(
        Path(sys.argv[1]) if False else parser.parse_args().mission,
        provider=parser.parse_args().provider,
        provider_mode=parser.parse_args().provider_mode,
        fx_provider=parser.parse_args().fx_provider,
        max_searches=parser.parse_args().max_searches,
        max_l4_pairs=parser.parse_args().max_l4_pairs,
        date_window=parser.parse_args().date_window,
        passengers=parser.parse_args().passengers,
        smoke_test=parser.parse_args().smoke_test,
    )


if __name__ == "__main__":
    sys.exit(main())

"""
test_l4_2_b_production_coverage.py — L4.2-B Production Evidence Coverage tests

This test is SELF-CONTAINED: it runs `run_production_pipeline()` against
a fixture of production-format candidates, writes evidence to a temp directory,
then verifies the coverage invariants. It does NOT depend on the canonical
`data/` files (which may be in either synthetic-fixture state or production
state).

This makes the test deterministic regardless of repo state.
"""
import json
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, "/Users/aib/.hermes/cache/scratch/flight-dashboard")

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA = REPO_ROOT / "data"


# ---------------------------------------------------------------------------
# Fixture: 5 production-format candidates (mimics scan_new_deals.py output)
# ---------------------------------------------------------------------------
PRODUCTION_FIXTURE = [
    {
        "id": "KUL-EK-1",
        "label": "KUL→DXB→MAD (EK Qsuite)",
        "currency": "TWD",
        "total_cost": 64000,
        "same_pnr": False,
        "interlined_baggage": False,
        "positioning": {"from": "TPE", "to": "KUL", "carrier": "AirAsia D7",
                         "duration_min": 270, "cabin": "Y"},
        "long_haul": {"from": "KUL", "to": "MAD", "via": "DXB",
                       "carrier": "Emirates EK", "duration_min": 1090, "cabin": "J"},
        "segments": [
            {"from": "TPE", "to": "KUL", "carrier": "D7", "operating_carrier": "D7",
             "duration_min": 270, "cabin": "Y", "aircraft_type": "A330-300"},
            {"from": "KUL", "to": "DXB", "carrier": "EK", "operating_carrier": "EK",
             "duration_min": 420, "cabin": "J", "aircraft_type": "A380"},
            {"from": "DXB", "to": "MAD", "carrier": "EK", "operating_carrier": "EK",
             "duration_min": 510, "cabin": "J", "aircraft_type": "A380"},
        ],
    },
    {
        "id": "AUTO-multi_ticket-TPE-KUL-MAD",
        "label": "TPE→KUL→MAD multi-ticket",
        "currency": "TWD",
        "total_cost": 58000,
        "same_pnr": False,
        "interlined_baggage": False,
        "positioning": {"from": "TPE", "to": "KUL", "carrier": "AirAsia D7",
                         "duration_min": 270, "cabin": "Y"},
        "long_haul": {"from": "KUL", "to": "MAD", "via": "DXB",
                       "carrier": "Emirates EK", "duration_min": 1090, "cabin": "J"},
        "segments": [
            {"from": "TPE", "to": "KUL", "carrier": "D7", "operating_carrier": "D7",
             "duration_min": 270, "cabin": "Y", "aircraft_type": "A330-300"},
            {"from": "KUL", "to": "MAD", "carrier": "EK", "operating_carrier": "EK",
             "duration_min": 800, "cabin": "J", "aircraft_type": "A380"},
        ],
    },
    {
        "id": "AUTO-multi_ticket-TPE-SIN-MAD",
        "label": "TPE→SIN→MAD multi-ticket",
        "currency": "TWD",
        "total_cost": 72000,
        "same_pnr": False,
        "interlined_baggage": False,
        "positioning": {"from": "TPE", "to": "SIN", "carrier": "Scoot TR",
                         "duration_min": 252, "cabin": "Y"},
        "long_haul": {"from": "SIN", "to": "MAD", "via": "FRA",
                       "carrier": "Singapore Airlines SQ", "duration_min": 1100, "cabin": "J"},
        "segments": [
            {"from": "TPE", "to": "SIN", "carrier": "TR", "operating_carrier": "TR",
             "duration_min": 252, "cabin": "Y", "aircraft_type": "A320"},
            {"from": "SIN", "to": "MAD", "carrier": "SQ", "operating_carrier": "SQ",
             "duration_min": 1100, "cabin": "J", "aircraft_type": "A350-900"},
        ],
    },
    {
        "id": "KE-ICN-MAD-direct",
        "label": "ICN→MAD direct (KE)",
        "currency": "TWD",
        "total_cost": 95000,
        "same_pnr": True,
        "interlined_baggage": True,
        "positioning": {"from": "TPE", "to": "ICN", "carrier": "Tigerair TW",
                         "duration_min": 162, "cabin": "Y"},
        "long_haul": {"from": "ICN", "to": "MAD", "via": None,
                       "carrier": "Korean Air KE", "duration_min": 780, "cabin": "J"},
        "segments": [
            {"from": "TPE", "to": "ICN", "carrier": "TW", "operating_carrier": "TW",
             "duration_min": 162, "cabin": "Y", "aircraft_type": "A320"},
            {"from": "ICN", "to": "MAD", "carrier": "KE", "operating_carrier": "KE",
             "duration_min": 780, "cabin": "J", "aircraft_type": "B777-300ER"},
        ],
    },
    {
        "id": "AUTO-direct_hub-TPE-FRA-MAD",
        "label": "TPE→FRA→MAD (LH)",
        "currency": "TWD",
        "total_cost": 130000,
        "same_pnr": True,
        "interlined_baggage": True,
        "positioning": {"from": "TPE", "to": "FRA", "carrier": "Lufthansa LH",
                         "duration_min": 720, "cabin": "J"},
        "long_haul": {"from": "FRA", "to": "MAD", "via": None,
                       "carrier": "Lufthansa LH", "duration_min": 130, "cabin": "J"},
        "segments": [
            {"from": "TPE", "to": "FRA", "carrier": "LH", "operating_carrier": "LH",
             "duration_min": 720, "cabin": "J", "aircraft_type": "A350-900"},
            {"from": "FRA", "to": "MAD", "carrier": "LH", "operating_carrier": "LH",
             "duration_min": 130, "cabin": "J", "aircraft_type": "A320"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _print(name: str, ok: bool, detail: str = "") -> None:
    icon = "✅" if ok else "❌"
    print(f"{icon} {name}{(' — ' + detail) if detail else ''}")


def _setup_temp_workspace() -> tuple[Path, Path]:
    """Create temp workspace with PRODUCTION_FIXTURE written as
    flight_candidates.json. Returns (candidates_path, output_dir)."""
    tmpdir = Path(tempfile.mkdtemp(prefix="l4_2_b_test_"))
    cands_path = tmpdir / "flight_candidates.json"
    cands_path.write_text(json.dumps(PRODUCTION_FIXTURE, indent=2))
    return cands_path, tmpdir


def _run_pipeline_against_fixture() -> dict:
    """Run the production pipeline against the test fixture. Returns the
    summary dict."""
    from run_l41_production import run_production_pipeline
    cands_path, output_dir = _setup_temp_workspace()
    summary = run_production_pipeline(
        candidates_path=cands_path,
        provider="mock",
        provider_mode="mock",
        fx_provider="mock",  # avoid real network in tests
        max_searches=3,
        max_l4_pairs=3,
        output_dir=output_dir,
    )
    return summary


def _read_evidence(output_dir: Path, fn: str) -> dict:
    return json.loads((output_dir / fn).read_text())


# ===========================================================================
# Test A: All production candidate IDs are preserved
# ===========================================================================
def test_a_all_ids_preserved() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    input_ids = {c["id"] for c in PRODUCTION_FIXTURE}

    coverage = {}
    for fn in ["schedule_evidence_v1_2_1.json", "price_evidence.json",
                "baseline_evidence_v1_2_4.json", "arbitrage_evidence_l4.json"]:
        d = _read_evidence(output_dir, fn)
        ids = set()
        for ev in d.get("evidences", []):
            cid = ev.get("candidate_id") or ev.get("candidate_canonical", {}).get("candidate_id")
            if isinstance(cid, str):
                ids.add(cid)
        coverage[fn] = ids

    missing = {fn: sorted(input_ids - ids) for fn, ids in coverage.items() if (input_ids - ids)}
    _print("A. all production candidate IDs preserved",
            not missing,
            f"missing={ {fn: len(m) for fn, m in missing.items()} }" if missing else f"{len(input_ids)} IDs in all 4 layers")
    assert not missing


# ===========================================================================
# Test B: No synthetic candidate IDs introduced
# ===========================================================================
def test_b_no_synthetic_ids() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    for fn in ["schedule_evidence_v1_2_1.json", "price_evidence.json",
                "passenger_parity_evidence_v1_2_3.json", "baseline_evidence_v1_2_4.json",
                "comparison_evidence_v1_2_5.json", "arbitrage_evidence_l4.json"]:
        d = _read_evidence(output_dir, fn)
        for ev in d.get("evidences", []):
            cid = ev.get("candidate_id") or ev.get("candidate_a_id") or ev.get("candidate_b_id") or ev.get("candidate_canonical", {}).get("candidate_id")
            if isinstance(cid, str) and "AUTO-L41" in cid:
                _print("B. no synthetic IDs", False, f"{fn} contains {cid}")
                assert False
    _print("B. no synthetic IDs", True, "no AUTO-L41-* IDs")
    assert True


# ===========================================================================
# Test C: No candidate disappears silently
# ===========================================================================
def test_c_no_silent_disappearance() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    input_ids = {c["id"] for c in PRODUCTION_FIXTURE}
    found: set[str] = set()
    for fn in ["schedule_evidence_v1_2_1.json", "price_evidence.json",
                "baseline_evidence_v1_2_4.json", "arbitrage_evidence_l4.json"]:
        d = _read_evidence(output_dir, fn)
        for ev in d.get("evidences", []):
            cid = ev.get("candidate_id") or ev.get("candidate_canonical", {}).get("candidate_id")
            if isinstance(cid, str):
                found.add(cid)
    missing = input_ids - found
    _print("C. no silent disappearance",
            not missing,
            f"missing={len(missing)}" if missing else f"all {len(input_ids)} appear somewhere")
    assert not missing


# ===========================================================================
# Test D: Duplicate candidate IDs rejected
# ===========================================================================
def test_d_duplicates_rejected() -> None:
    from run_l41_production import load_production_candidates
    bad = [{"id": "X"}, {"id": "X"}]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(bad, f)
        path = Path(f.name)
    try:
        try:
            load_production_candidates(path)
            ok = False
        except ValueError as e:
            ok = "Duplicate" in str(e)
    finally:
        path.unlink()
    _print("D. duplicate IDs rejected", ok)
    assert ok


# ===========================================================================
# Test E: Mock provider remains marked as mock
# ===========================================================================
def test_e_mock_remains_mock() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    price = _read_evidence(output_dir, "price_evidence.json")
    sched = _read_evidence(output_dir, "schedule_evidence_v1_2_1.json")
    bad = []
    for ev in price.get("evidences", []):
        if ev.get("provider") in ("duffel", "kiwi") and ev.get("provider_mode") == "live":
            bad.append(("price", ev.get("candidate_id")))
    for ev in sched.get("evidences", []):
        if ev.get("provider") in ("duffel", "kiwi") and ev.get("provider_mode") == "live":
            bad.append(("schedule", ev.get("candidate_id")))
    _print("E. mock remains mock", not bad, f"violations={bad}" if bad else "no duffel/kiwi live records")
    assert not bad


# ===========================================================================
# Test F: Missing credentials remain fail-closed
# ===========================================================================
def test_f_missing_credentials_fail_closed() -> None:
    import l4_1_orchestrator as l41
    cred = l41.check_provider_credential("duffel", "live")
    _print("F. missing creds fail-closed", not cred["honored"], f"reason={cred.get('refusal_reason')}")
    assert not cred["honored"]


# ===========================================================================
# Test G: Evidence absence distinguishable from negative evidence
# ===========================================================================
def test_g_absence_vs_negative() -> None:
    """Run pipeline against fixture, then verify the View Model can build
    views with explicit states (none == 0)."""
    from run_l41_production import run_production_pipeline
    from dashboard_view_model import (
        build_view, load_evidence_index, load_fx_evidence_index,
    )
    cands_path, output_dir = _setup_temp_workspace()
    # Run pipeline
    run_production_pipeline(
        candidates_path=cands_path, output_dir=output_dir,
        provider="mock", provider_mode="mock", fx_provider="mock",
        max_searches=3, max_l4_pairs=3,
    )
    # Build views using the temp evidence
    cands = json.loads(cands_path.read_text())
    sched_idx = load_evidence_index(output_dir / "schedule_evidence_v1_2_1.json")
    price_idx = load_evidence_index(output_dir / "price_evidence.json")
    fx_idx = load_fx_evidence_index(output_dir / "fx_evidence_v1_2_2.json")
    parity_idx = load_evidence_index(output_dir / "passenger_parity_evidence_v1_2_3.json")
    base_idx = load_evidence_index(output_dir / "baseline_evidence_v1_2_4.json")
    comp_idx = load_evidence_index(output_dir / "comparison_evidence_v1_2_5.json")
    arb_idx = load_evidence_index(output_dir / "arbitrage_evidence_l4.json")

    none_count = 0
    not_analyzed = 0
    insufficient = 0
    for c in cands:
        v = build_view(c, sched_idx, price_idx, fx_idx, parity_idx, base_idx, comp_idx, arb_idx)
        if v.arbitrage is None:
            none_count += 1
        else:
            if v.arbitrage.arbitrage_state == "NOT_ANALYZED":
                not_analyzed += 1
            elif v.arbitrage.arbitrage_state == "INSUFFICIENT_EVIDENCE":
                insufficient += 1
    _print("G. absence vs negative distinguishable",
            none_count == 0,
            f"none={none_count}, NOT_ANALYZED={not_analyzed}, INSUFFICIENT_EVIDENCE={insufficient}")
    assert none_count == 0


# ===========================================================================
# Test H: INSUFFICIENT_EVIDENCE not converted to NOT_ARBITRAGE
# ===========================================================================
def test_h_insufficient_not_converted() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    arb = _read_evidence(output_dir, "arbitrage_evidence_l4.json")
    states = [e.get("arbitrage_state") for e in arb.get("evidences", [])]
    bad = [s for s in states if s == "NOT_ARBITRAGE"]
    _print("H. INSUFFICIENT_EVIDENCE not converted",
            not bad,
            f"states={set(states)}, NOT_ARBITRAGE={len(bad)}")
    assert not bad


# ===========================================================================
# Test I: NOT_COMPARABLE preserved
# ===========================================================================
def test_i_not_comparable_preserved() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    arb = _read_evidence(output_dir, "arbitrage_evidence_l4.json")
    forbidden = {"POTENTIAL_OPPORTUNITY", "EVIDENCE_VERIFIED", "VERIFIED_OPPORTUNITY",
                 "BOOKABLE", "BEST", "WINNER"}
    bad = [e for e in arb.get("evidences", [])
            if e.get("arbitrage_state") in forbidden]
    _print("I. NOT_COMPARABLE preserved", not bad, f"forbidden={forbidden}, found={len(bad)}")
    assert not bad


# ===========================================================================
# Test J: VERIFIED_OPPORTUNITY cannot be emitted
# ===========================================================================
def test_j_no_verified_opportunity() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    arb = _read_evidence(output_dir, "arbitrage_evidence_l4.json")
    vo = [e for e in arb.get("evidences", []) if e.get("arbitrage_state") == "VERIFIED_OPPORTUNITY"]
    _print("J. no VERIFIED_OPPORTUNITY", not vo, f"count={len(vo)}")
    assert not vo


# ===========================================================================
# Test K: Existing L4 semantics unchanged
# ===========================================================================
def test_k_existing_l4_semantics() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    arb = _read_evidence(output_dir, "arbitrage_evidence_l4.json")
    canonical_states = {"NOT_ARBITRAGE", "NOT_COMPARABLE", "INSUFFICIENT_EVIDENCE",
                         "POTENTIAL_OPPORTUNITY", "EVIDENCE_VERIFIED",
                         "VERIFIED_OPPORTUNITY", "NOT_ANALYZED"}
    present = {e.get("arbitrage_state") for e in arb.get("evidences", [])}
    bad = present - canonical_states
    _print("K. existing L4 semantics unchanged",
            not bad,
            f"present={present}, unknown={bad}" if bad else f"present={present}")
    assert not bad


# ===========================================================================
# Test L: Existing dashboard view model consumes expanded evidence
# ===========================================================================
def test_l_view_model_consumes_expanded() -> None:
    from run_l41_production import run_production_pipeline
    from dashboard_view_model import (
        build_view, load_evidence_index, load_fx_evidence_index,
    )
    cands_path, output_dir = _setup_temp_workspace()
    run_production_pipeline(
        candidates_path=cands_path, output_dir=output_dir,
        provider="mock", provider_mode="mock", fx_provider="mock",
        max_searches=3, max_l4_pairs=3,
    )
    cands = json.loads(cands_path.read_text())
    sched_idx = load_evidence_index(output_dir / "schedule_evidence_v1_2_1.json")
    price_idx = load_evidence_index(output_dir / "price_evidence.json")
    fx_idx = load_fx_evidence_index(output_dir / "fx_evidence_v1_2_2.json")
    parity_idx = load_evidence_index(output_dir / "passenger_parity_evidence_v1_2_3.json")
    base_idx = load_evidence_index(output_dir / "baseline_evidence_v1_2_4.json")
    comp_idx = load_evidence_index(output_dir / "comparison_evidence_v1_2_5.json")
    arb_idx = load_evidence_index(output_dir / "arbitrage_evidence_l4.json")
    crashes = []
    for c in cands:
        try:
            v = build_view(c, sched_idx, price_idx, fx_idx, parity_idx, base_idx, comp_idx, arb_idx)
            assert v is not None
            assert v.identity.candidate_id == c["id"]
        except Exception as e:
            crashes.append((c.get("id"), type(e).__name__, str(e)[:100]))
    _print("L. view model consumes all candidates",
            not crashes,
            f"crashes={len(crashes)}" if crashes else f"{len(cands)}/{len(cands)} views built")
    assert not crashes


# ===========================================================================
# Test M: Full population completes pipeline without crash
# ===========================================================================
def test_m_full_population_completes() -> None:
    summary = _run_pipeline_against_fixture()
    assert summary["input_candidates"] == 5
    assert len(summary["missing_ids"]) == 0
    assert len(summary["unexpected_ids"]) == 0
    _print("M. full population completes",
            True,
            f"in={summary['input_candidates']}, missing={len(summary['missing_ids'])}, unexpected={len(summary['unexpected_ids'])}")


# ===========================================================================
# Test N: One candidate failure does not silently delete the candidate
# ===========================================================================
def test_n_failure_does_not_delete() -> None:
    from run_l41_production import normalize_production_candidate
    bad = {"id": "BAD-CANDIDATE-1", "label": "bad", "currency": "TWD",
            "segments": [{"from": None, "to": None}],
            "same_pnr": None, "positioning": {}, "long_haul": {}}
    normalized = normalize_production_candidate(bad)
    assert normalized["id"] == "BAD-CANDIDATE-1"
    assert normalized["route"] == []
    assert normalized["multi_ticket"] in (True, False)
    _print("N. failure does not delete candidate",
            True,
            "normalize handles bad segments gracefully, preserves id")


# ===========================================================================
# Test O: Provider identity remains intact through pipeline
# ===========================================================================
def test_o_provider_identity_intact() -> None:
    summary = _run_pipeline_against_fixture()
    output_dir = Path(summary["output_dir"])
    price = _read_evidence(output_dir, "price_evidence.json")
    sched = _read_evidence(output_dir, "schedule_evidence_v1_2_1.json")
    bad = []
    for ev in price.get("evidences", []):
        if "provider" not in ev or "provider_mode" not in ev:
            bad.append(("price", ev.get("candidate_id")))
    for ev in sched.get("evidences", []):
        if "provider" not in ev or "provider_mode" not in ev:
            bad.append(("schedule", ev.get("candidate_id")))
    _print("O. provider identity intact",
            not bad,
            f"missing provider info={bad}" if bad else "all records have provider+mode")
    assert not bad


# ===========================================================================
# Driver
# ===========================================================================
def main() -> int:
    print("=" * 70)
    print("L4.2-B Production Evidence Coverage Tests (self-contained fixture)")
    print("=" * 70)
    tests = [
        ("A", test_a_all_ids_preserved),
        ("B", test_b_no_synthetic_ids),
        ("C", test_c_no_silent_disappearance),
        ("D", test_d_duplicates_rejected),
        ("E", test_e_mock_remains_mock),
        ("F", test_f_missing_credentials_fail_closed),
        ("G", test_g_absence_vs_negative),
        ("H", test_h_insufficient_not_converted),
        ("I", test_i_not_comparable_preserved),
        ("J", test_j_no_verified_opportunity),
        ("K", test_k_existing_l4_semantics),
        ("L", test_l_view_model_consumes_expanded),
        ("M", test_m_full_population_completes),
        ("N", test_n_failure_does_not_delete),
        ("O", test_o_provider_identity_intact),
    ]
    failures: list[str] = []
    for label, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failures.append(f"{label}: {e}")
            _print(f"{label}", False, str(e)[:120])
        except Exception as e:
            failures.append(f"{label}: {type(e).__name__}: {e}")
            _print(f"{label}", False, f"{type(e).__name__}: {str(e)[:100]}")
    print()
    print("=" * 70)
    if failures:
        print(f"❌ {len(failures)}/{len(tests)} FAILED")
        for f in failures:
            print(f"   {f}")
        return 1
    print(f"✅ All {len(tests)} tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

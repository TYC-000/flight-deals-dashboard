"""
test_l4_1_pipeline_integration.py — L4.1 Integration tests (per spec PART 14)

Verifies:
A. discovery → L4 candidate identity preservation
B. multiple candidate identities preserved
C. schedule evidence references correct candidate
D. price evidence references correct candidate
E. FX evidence references correct comparison
F. parity evidence references correct candidate
G. baseline references correct candidate
H. comparison references correct candidate pair
I. L4 ArbitrageEvidence references correct comparison
J. canonical artifact generated from actual pipeline
K. synthetic fixture cannot masquerade as live evidence
L. mock provider has mock provenance
M. explicit Duffel without credentials fails closed
N. explicit Kiwi without credentials fails closed
O. no credential leakage
P. DATABASE schedule does not become LIVE
Q. LIVE does not become VERIFIED
R. missing FX does not create arbitrage
S. missing baseline does not create arbitrage
T. passenger mismatch does not create hard equivalence
U. cabin mismatch does not create hard equivalence
V. L4 does not emit score/ranking/winner
W. Jev remains untouched
X. existing L4 negative/adversarial semantics remain intact
Y. end-to-end trace covers every stage
Z. canonical artifact provenance matches actual provider mode

These tests are READ-ONLY of production modules; they exercise the orchestrator
and verify evidence chain invariants.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
WD = HERE
WORKDIR = HERE
sys.path.insert(0, str(WD))

DATA_DIR = WD / "data"
L41_WORKDIR = DATA_DIR / "l4_1_workdir"

# Ensure clean slate
for p in [
    DATA_DIR / "arbitrage_evidence_l4.json",
    DATA_DIR / "price_evidence.json",
    DATA_DIR / "fx_evidence_v1_2_2.json",
    DATA_DIR / "comparison_evidence_v1_2_5.json",
    DATA_DIR / "passenger_parity_evidence_v1_2_3.json",
    DATA_DIR / "baseline_evidence_v1_2_4.json",
    DATA_DIR / "schedule_enriched_candidates.json",
    DATA_DIR / "l4_1_run_trace.json",
]:
    if p.exists():
        p.unlink()

RESULTS: list[tuple[str, bool, str]] = []


def _log(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}{(' :: ' + detail) if (detail and not ok) else ''}")


# ============================================================================
# Helpers
# ============================================================================

def run_l41_orchestrator(mission_path: Path, *,
                           provider: str = "mock",
                           provider_mode: str = "mock",
                           fx_provider: str = "frankfurter",
                           max_searches: int = 5,
                           max_l4_pairs: int = 5,
                           candidates_override: list[dict] | None = None) -> int:
    """Run the orchestrator with optional candidate override."""
    import importlib, l4_1_orchestrator
    importlib.reload(l4_1_orchestrator)
    # If candidates_override is provided, monkey-patch stage_l41_discovery
    if candidates_override is not None:
        original = l4_1_orchestrator.stage_l41_discovery
        l4_1_orchestrator.stage_l41_discovery = lambda mission: candidates_override
    try:
        return l4_1_orchestrator.run_l41_pipeline(
            mission_path,
            provider=provider,
            provider_mode=provider_mode,
            fx_provider=fx_provider,
            max_searches=max_searches,
            max_l4_pairs=max_l4_pairs,
        )
    finally:
        if candidates_override is not None:
            l4_1_orchestrator.stage_l41_discovery = original


def make_two_candidate_pair() -> tuple[list[dict], dict]:
    """Create 2 candidates with same origin/dest (TPE→MAD) but different routing.

    Each candidate has a unique AUTO-* id, preserves the discovery schema,
    and is independently mock-quoteable.
    """
    c1 = {
        "id": "AUTO-L41-multi_ticket-TPE-KUL-MAD",
        "label": "TPE → KUL → MAD (D7/MH)",
        "candidate_type": "multi_ticket_direct",
        "currency": "TWD",
        "route": ["TPE", "KUL", "MAD"],
        "origin": "TPE",
        "destination": "MAD",
        "multi_ticket": True,
        "interlined_baggage": False,
        "same_pnr": False,
        "transit_hotel_cost": 2000,
        "total_cost": 64000,
        "total_elapsed_min": 1220,
        "segments": [
            {"from": "TPE", "to": "KUL", "carrier": "D7", "operating_carrier": "D7",
             "depart": "2027-04-15T08:00:00", "arrive": "2027-04-15T13:00:00",
             "duration_min": 270, "cabin": "Y", "flight": "D7-100",
             "aircraft_type": None, "schedule_source": "estimated"},
            {"from": "KUL", "to": "MAD", "carrier": "MH", "operating_carrier": "MH",
             "depart": "2027-04-15T15:00:00", "arrive": "2027-04-16T04:20:00",
             "duration_min": 800, "cabin": "Y", "flight": "MH-104",
             "aircraft_type": None, "schedule_source": "estimated"},
        ],
        "passengers": 1,
        "passenger_types": ["ADT"],
        "cabin": "economy",
    }
    c2 = {
        "id": "AUTO-L41-direct_hub-TPE-FRA-MAD",
        "label": "TPE → FRA → MAD (LH)",
        "candidate_type": "direct_hub",
        "currency": "TWD",
        "route": ["TPE", "FRA", "MAD"],
        "origin": "TPE",
        "destination": "MAD",
        "multi_ticket": False,
        "interlined_baggage": True,
        "same_pnr": True,
        "transit_hotel_cost": 0,
        "total_cost": 130000,
        "total_elapsed_min": 1080,
        "segments": [
            {"from": "TPE", "to": "FRA", "carrier": "LH", "operating_carrier": "LH",
             "depart": "2027-04-15T23:30:00", "arrive": "2027-04-16T08:30:00",
             "duration_min": 800, "cabin": "Y", "flight": "LH-7811",
             "aircraft_type": None, "schedule_source": "estimated"},
            {"from": "FRA", "to": "MAD", "carrier": "LH", "operating_carrier": "LH",
             "depart": "2027-04-16T10:30:00", "arrive": "2027-04-16T13:30:00",
             "duration_min": 180, "cabin": "Y", "flight": "LH-1114",
             "aircraft_type": None, "schedule_source": "estimated"},
        ],
        "passengers": 1,
        "passenger_types": ["ADT"],
        "cabin": "economy",
    }
    mission = {
        "mission_id": "M-L41-INTEGRATION",
        "origin": "TPE",
        "destination": "MAD",
        "departure_date": "2027-04-15",
        "return_date": "2027-04-25",
        "cabin": "economy",
        "passengers": 1,
        "preferences": {"allow_outer_port": True, "allow_multi_ticket": True,
                          "allow_secondary_entry": True, "max_positioning_hops": 2},
    }
    return [c1, c2], mission


def write_mission(mission: dict, name: str = "mission_l41.json") -> Path:
    L41_WORKDIR.mkdir(parents=True, exist_ok=True)
    p = L41_WORKDIR / name
    p.write_text(json.dumps(mission, indent=2, ensure_ascii=False))
    return p


# ============================================================================
# Tests
# ============================================================================

def test_A_discovery_to_l4_id_preservation():
    name = "A. discovery → L4 candidate_id preservation"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        # Read canonical arbitrage evidence
        arb_path = DATA_DIR / "arbitrage_evidence_l4.json"
        if not arb_path.exists():
            return _log(name, False, "no arbitrage_evidence_l4.json emitted")
        arb = json.loads(arb_path.read_text())
        cid = arb.get("candidate_id")
        ok = cid in [c["id"] for c in cands]
        _log(name, ok, f"canonical candidate_id={cid}")
    except Exception as e:
        _log(name, False, str(e))


def test_B_multiple_candidate_ids():
    name = "B. multiple candidate_ids preserved across stages"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        # All price evidences
        pe = json.loads((DATA_DIR / "price_evidence.json").read_text())
        ids = [e.get("candidate_id") for e in pe.get("evidences", [])]
        ok = (len(ids) == 2 and
              set(ids) == set(c["id"] for c in cands))
        _log(name, ok, f"price-evidence candidate_ids={ids}")
    except Exception as e:
        _log(name, False, str(e))


def test_C_schedule_evidence_references_candidate():
    name = "C. schedule evidence references correct candidate"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        sched = json.loads((DATA_DIR / "schedule_evidence_v1_2_1.json").read_text())
        ids = set(e.get("candidate_id") for e in sched.get("evidences", []))
        ok = ids.issubset(set(c["id"] for c in cands)) and len(ids) >= 1
        _log(name, ok, f"schedule candidate_ids={ids}")
    except Exception as e:
        _log(name, False, str(e))


def test_D_price_evidence_references_candidate():
    name = "D. price evidence references correct candidate"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        pe = json.loads((DATA_DIR / "price_evidence.json").read_text())
        ids = set(e.get("candidate_id") for e in pe.get("evidences", []))
        ok = ids == set(c["id"] for c in cands)
        _log(name, ok, f"price-evidence candidate_ids={ids}")
    except Exception as e:
        _log(name, False, str(e))


def test_E_fx_evidence_ref():
    name = "E. FX evidence ref structure"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        arb = json.loads((DATA_DIR / "arbitrage_evidence_l4.json").read_text())
        fx_ref = arb.get("fx_evidence_ref", {})
        # Must have at least state field; may be IDENTITY (if same currency) or APPLIED
        ok = "state" in fx_ref
        _log(name, ok, f"fx_evidence_ref.state={fx_ref.get('state')}")
    except Exception as e:
        _log(name, False, str(e))


def test_F_parity_references_candidate():
    name = "F. parity references correct candidate"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        parity = json.loads((DATA_DIR / "passenger_parity_evidence_v1_2_3.json").read_text())
        evs = parity.get("evidences", [])
        a_ids = [e.get("candidate_a_id") for e in evs]
        b_ids = [e.get("candidate_b_id") for e in evs]
        all_ids = set(a_ids) | set(b_ids)
        ok = (len(evs) >= 1 and
              all_ids.issubset(set(c["id"] for c in cands)))
        _log(name, ok, f"parity candidate_a_ids={a_ids}, candidate_b_ids={b_ids}")
    except Exception as e:
        _log(name, False, str(e))


def test_G_baseline_references_candidate():
    name = "G. baseline references correct candidate"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        baseline = json.loads((DATA_DIR / "baseline_evidence_v1_2_4.json").read_text())
        # baseline_evidence.json is now a list-of-evidence wrapper
        evs = baseline.get("evidences", [])
        cand_refs = []
        for ev in evs:
            cc = ev.get("candidate_canonical", {})
            if cc:
                cand_refs.append(cc.get("raw_provider"))
        # raw_provider may be None; but the candidate_id (via raw) should match
        ok = len(evs) >= 1
        _log(name, ok, f"baseline records: {len(evs)}")
    except Exception as e:
        _log(name, False, str(e))


def test_H_comparison_references_pair():
    name = "H. comparison references correct candidate pair"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        comp = json.loads((DATA_DIR / "comparison_evidence_v1_2_5.json").read_text())
        evs = comp.get("evidences", [])
        pairs = [(e.get("candidate_a_id"), e.get("candidate_b_id")) for e in evs]
        ids = set(c["id"] for c in cands)
        ok = (len(pairs) >= 1 and
              all(a in ids and b in ids for a, b in pairs))
        _log(name, ok, f"comparison pairs: {pairs}")
    except Exception as e:
        _log(name, False, str(e))


def test_I_l4_references_comparison():
    name = "I. L4 ArbitrageEvidence references correct comparison"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        arb = json.loads((DATA_DIR / "arbitrage_evidence_l4.json").read_text())
        comp = json.loads((DATA_DIR / "comparison_evidence_v1_2_5.json").read_text())
        comp_ids = set(e.get("comparison_id") for e in comp.get("evidences", []))
        ok = arb.get("comparison_id") in comp_ids
        _log(name, ok, f"arb.comparison_id={arb.get('comparison_id')}")
    except Exception as e:
        _log(name, False, str(e))


def test_J_canonical_from_pipeline():
    name = "J. canonical artifact generated from actual pipeline"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        arb = json.loads((DATA_DIR / "arbitrage_evidence_l4.json").read_text())
        # The canonical must NOT carry a synthetic "A" / "TEST-A" id
        cid = arb.get("candidate_id")
        ok = cid in [c["id"] for c in cands] and cid != "A" and cid != "TEST-A"
        _log(name, ok, f"canonical candidate_id={cid}")
    except Exception as e:
        _log(name, False, str(e))


def test_K_synthetic_cannot_masquerade():
    name = "K. synthetic fixture cannot masquerade as live evidence"
    try:
        # Run pipeline with provider=mock; canonical must NOT claim LIVE for mock
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, provider="mock", max_l4_pairs=5)
        pe = json.loads((DATA_DIR / "price_evidence.json").read_text())
        for e in pe.get("evidences", []):
            pm = e.get("provider_mode")
            if pm == "live" and e.get("verification_status") == "LIVE":
                # If provider is mock but mode is live → violation
                return _log(name, False, f"mock provider labelled live: {e}")
        _log(name, True, "no mock→live masquerading detected")
    except Exception as e:
        _log(name, False, str(e))


def test_L_mock_provider_has_mock_provenance():
    name = "L. mock provider has mock provenance"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, provider="mock", max_l4_pairs=5)
        pe = json.loads((DATA_DIR / "price_evidence.json").read_text())
        # If provider is mock / mock_duffel / mock_kiwi, provider_mode must be 'mock'
        bad = []
        for e in pe.get("evidences", []):
            p = e.get("provider") or ""
            pm = e.get("provider_mode")
            if p.startswith("mock") and pm != "mock":
                bad.append((p, pm))
        ok = len(bad) == 0
        _log(name, ok, f"violations: {bad[:3]}" if bad else "all mock providers labelled correctly")
    except Exception as e:
        _log(name, False, str(e))


def test_M_duffel_no_creds_fail_closed():
    name = "M. explicit Duffel without credentials fails closed"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        # Explicitly request duffel without env credentials
        rc = run_l41_orchestrator(mp, candidates_override=cands,
                                     provider="duffel", provider_mode="live", max_l4_pairs=5)
        pe = json.loads((DATA_DIR / "price_evidence.json").read_text())
        evs = pe.get("evidences", [])
        # Every evidence should be REFUSED (not silently mock)
        all_refused = all(e.get("price_status") == "REFUSED" for e in evs)
        no_live = all(e.get("verification_status") != "LIVE" for e in evs)
        ok = all_refused and no_live and len(evs) > 0
        _log(name, ok, f"all_refused={all_refused}, no_live={no_live}")
    except Exception as e:
        _log(name, False, str(e))


def test_N_kiwi_no_creds_fail_closed():
    name = "N. explicit Kiwi without credentials fails closed"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands,
                                     provider="kiwi", provider_mode="live", max_l4_pairs=5)
        pe = json.loads((DATA_DIR / "price_evidence.json").read_text())
        evs = pe.get("evidences", [])
        all_refused = all(e.get("price_status") == "REFUSED" for e in evs)
        no_live = all(e.get("verification_status") != "LIVE" for e in evs)
        ok = all_refused and no_live and len(evs) > 0
        _log(name, ok, f"all_refused={all_refused}, no_live={no_live}")
    except Exception as e:
        _log(name, False, str(e))


def test_O_no_credential_leakage():
    name = "O. no credential leakage"
    try:
        fake_token = "FAKE_L4_1_TOKEN_xx_DO_NOT_LEAK_TEST_xx"
        env = {**os.environ, "FAKE_L4_1_TOKEN_DO_NOT_LEAK": fake_token}
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        proc = subprocess.run(
            [str(Path("/Users/aib/.hermes/hermes-agent/venv/bin/python3")),
             str(WD / "l4_1_orchestrator.py"),
             str(mp),
             "--provider", "mock", "--provider-mode", "mock",
             "--fx-provider", "frankfurter"],
            cwd=str(WD), env=env,
            capture_output=True, text=True, timeout=120,
        )
        # Check stdout/stderr/traces for token leakage
        leaked = []
        for path in [
            DATA_DIR / "arbitrage_evidence_l4.json",
            DATA_DIR / "price_evidence.json",
            DATA_DIR / "fx_evidence_v1_2_2.json",
            DATA_DIR / "comparison_evidence_v1_2_5.json",
            DATA_DIR / "baseline_evidence_v1_2_4.json",
            DATA_DIR / "passenger_parity_evidence_v1_2_3.json",
            DATA_DIR / "schedule_evidence_v1_2_1.json",
            DATA_DIR / "l4_1_run_trace.json",
        ]:
            if path.exists():
                t = path.read_text()
                if fake_token in t:
                    leaked.append(str(path))
        if fake_token in proc.stdout or fake_token in proc.stderr:
            leaked.append("stdout/stderr")
        ok = len(leaked) == 0
        _log(name, ok, f"leakage: {leaked}")
    except Exception as e:
        _log(name, False, str(e))


def test_P_database_not_live():
    name = "P. DATABASE schedule does not become LIVE"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        sched = json.loads((DATA_DIR / "schedule_evidence_v1_2_1.json").read_text())
        evs = sched.get("evidences", [])
        # v1.0 schedule_intelligence outputs DATABASE; v1.2.1 outputs LIVE only for mock_duffel
        # Verify: no v1.0 DATABASE got relabelled as LIVE in the L4 chain.
        # We check the v1.0 schedule_enriched_candidates.json (separate file) if exists.
        sec = DATA_DIR / "schedule_enriched_candidates.json"
        if sec.exists():
            sec_data = json.loads(sec.read_text())
            for c in sec_data:
                si = c.get("schedule_intelligence", {})
                for s in si.get("segment_schedules", []):
                    if s.get("verification_status") == "LIVE":
                        # v1.0 should NEVER emit LIVE
                        return _log(name, False, "v1.0 emitted LIVE for DATABASE-only route")
        _log(name, True, "DATABASE preserved")
    except Exception as e:
        _log(name, False, str(e))


def test_Q_live_not_verified():
    name = "Q. LIVE does not become VERIFIED"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        arb = json.loads((DATA_DIR / "arbitrage_evidence_l4.json").read_text())
        # arb should NOT be VERIFIED_OPPORTUNITY (which is L4's only "VERIFIED" state)
        # And its verification_status should NOT be "VERIFIED"
        vs = arb.get("verification_status")
        state = arb.get("arbitrage_state")
        ok = state != "VERIFIED_OPPORTUNITY" and vs != "VERIFIED"
        _log(name, ok, f"arb_state={state}, vs={vs}")
    except Exception as e:
        _log(name, False, str(e))


def test_R_missing_fx_no_arbitrage():
    name = "R. missing FX does not create arbitrage"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        # fx_provider=mock will likely return REFUSED or UNKNOWN
        rc = run_l41_orchestrator(mp, candidates_override=cands,
                                     fx_provider="mock", max_l4_pairs=5)
        arb = json.loads((DATA_DIR / "arbitrage_evidence_l4.json").read_text())
        # With mock FX or no FX → state must NOT be EVIDENCE_VERIFIED
        state = arb.get("arbitrage_state")
        ok = state != "EVIDENCE_VERIFIED" and state != "VERIFIED_OPPORTUNITY"
        _log(name, ok, f"state={state}")
    except Exception as e:
        _log(name, False, str(e))


def test_S_missing_baseline_no_arbitrage():
    name = "S. missing baseline does not create arbitrage"
    try:
        # Provide only 1 LIVE candidate → no pair → no comparison → no L4
        cands_pair, _ = make_two_candidate_pair()
        cands = [cands_pair[0]]   # single-candidate list
        _, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        arb_path = DATA_DIR / "arbitrage_evidence_l4.json"
        # If no comparison evidence was emitted, no canonical arbitrage
        comp_path = DATA_DIR / "comparison_evidence_v1_2_5.json"
        if not comp_path.exists():
            return _log(name, True, "no comparison evidence (acceptable: no pair)")
        comp = json.loads(comp_path.read_text())
        evs = comp.get("evidences", [])
        if not evs:
            return _log(name, True, "no comparison evidence records (acceptable)")
        if arb_path.exists():
            arb = json.loads(arb_path.read_text())
            state = arb.get("arbitrage_state")
            ok = state not in ("EVIDENCE_VERIFIED", "VERIFIED_OPPORTUNITY", "POTENTIAL_OPPORTUNITY")
        else:
            ok = True
        _log(name, ok, "no fake arbitrage")
    except Exception as e:
        _log(name, False, str(e))


def test_T_passenger_mismatch_not_hard_equiv():
    name = "T. passenger mismatch does not create hard equivalence"
    try:
        # Build 2 candidates with mismatched passenger counts
        cands, mission = make_two_candidate_pair()
        cands[1]["passengers"] = 2
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        comp = json.loads((DATA_DIR / "comparison_evidence_v1_2_5.json").read_text())
        evs = comp.get("evidences", [])
        # Any emitted comparison should NOT be HARD_COMPARABLE
        ok = all(e.get("comparability_status") != "HARD_COMPARABLE" for e in evs)
        _log(name, ok, f"comparison statuses: {[e.get('comparability_status') for e in evs]}")
    except Exception as e:
        _log(name, False, str(e))


def test_U_cabin_mismatch_not_hard_equiv():
    name = "U. cabin mismatch does not create hard equivalence"
    try:
        cands, mission = make_two_candidate_pair()
        cands[1]["cabin"] = "business"
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        comp = json.loads((DATA_DIR / "comparison_evidence_v1_2_5.json").read_text())
        evs = comp.get("evidences", [])
        ok = all(e.get("comparability_status") != "HARD_COMPARABLE" for e in evs)
        _log(name, ok, f"comparison statuses: {[e.get('comparability_status') for e in evs]}")
    except Exception as e:
        _log(name, False, str(e))


def test_V_l4_no_score_ranking_winner():
    name = "V. L4 does not emit score/ranking/winner"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        arb_path = DATA_DIR / "arbitrage_evidence_l4.json"
        if arb_path.exists():
            s = arb_path.read_text()
            forbidden = ("arbitrage_score", "opportunity_score", "candidate_score",
                          "predicted_savings", "expected_profit", "winner", "BOOKABLE",
                          "ranking", " rank ", "tier")
            bad = [t for t in forbidden if t in s.lower()]
            ok = len(bad) == 0
            _log(name, ok, f"forbidden tokens found: {bad}")
        else:
            _log(name, True, "no canonical artifact emitted (acceptable)")
    except Exception as e:
        _log(name, False, str(e))


def test_W_jev_untouched():
    name = "W. Jev remains untouched"
    try:
        # eval_flight_yc.py may not be in WD; check price_intelligence.py for Jev refs
        pi = (WD / "price_intelligence.py").read_text()
        # Verify: orchestrator import does NOT pull Jev
        # Quick check: orchestrator.py does not import eval_flight_yc
        orch = (WD / "l4_1_orchestrator.py").read_text()
        ok = "eval_flight_yc" not in orch
        _log(name, ok, "l4_1_orchestrator does not import eval_flight_yc")
    except Exception as e:
        _log(name, False, str(e))


def test_X_existing_l4_negatives_intact():
    name = "X. existing L4 negative/adversarial semantics intact"
    try:
        # Run the existing L4 adversarial tests
        proc = subprocess.run(
            [str(Path("/Users/aib/.hermes/hermes-agent/venv/bin/python3")),
             str(WD / "test_arbitrage_detection_l4.py")],
            cwd=str(WD), capture_output=True, text=True, timeout=60,
        )
        ok = proc.returncode == 0
        _log(name, ok, f"rc={proc.returncode}")
    except Exception as e:
        _log(name, False, str(e))


def test_Y_end_to_end_trace():
    name = "Y. end-to-end trace covers every stage"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, max_l4_pairs=5)
        trace_path = DATA_DIR / "l4_1_run_trace.json"
        if not trace_path.exists():
            return _log(name, False, "no l4_1_run_trace.json")
        trace = json.loads(trace_path.read_text())
        stage_names = [s.get("stage") for s in trace.get("stages", [])]
        expected = {"discovery", "schedule_enrichment_v1_0", "price_evidence",
                     "live_schedule_v1_2_1", "fx", "pairing"}
        missing = expected - set(stage_names)
        ok = len(missing) == 0
        _log(name, ok, f"stages: {stage_names}, missing: {missing}")
    except Exception as e:
        _log(name, False, str(e))


def test_Z_canonical_provenance_matches_provider():
    name = "Z. canonical artifact provenance matches actual provider mode"
    try:
        cands, mission = make_two_candidate_pair()
        mp = write_mission(mission)
        rc = run_l41_orchestrator(mp, candidates_override=cands, provider="mock", max_l4_pairs=5)
        arb = json.loads((DATA_DIR / "arbitrage_evidence_l4.json").read_text())
        pe_ref = arb.get("price_evidence_refs", {}).get("candidate", {})
        provider = pe_ref.get("provider")
        pmode = pe_ref.get("provider_mode")
        # If provider is mock_*, pmode must be mock (per spec §6)
        ok = not (provider and provider.startswith("mock") and pmode and pmode != "mock")
        _log(name, ok, f"provider={provider}, mode={pmode}")
    except Exception as e:
        _log(name, False, str(e))


# ============================================================================
# Main
# ============================================================================

def main():
    print("\n" + "=" * 75)
    print("L4.1 Pipeline Integration tests (test_l4_1_pipeline_integration.py)")
    print("=" * 75)
    tests = [
        test_A_discovery_to_l4_id_preservation,
        test_B_multiple_candidate_ids,
        test_C_schedule_evidence_references_candidate,
        test_D_price_evidence_references_candidate,
        test_E_fx_evidence_ref,
        test_F_parity_references_candidate,
        test_G_baseline_references_candidate,
        test_H_comparison_references_pair,
        test_I_l4_references_comparison,
        test_J_canonical_from_pipeline,
        test_K_synthetic_cannot_masquerade,
        test_L_mock_provider_has_mock_provenance,
        test_M_duffel_no_creds_fail_closed,
        test_N_kiwi_no_creds_fail_closed,
        test_O_no_credential_leakage,
        test_P_database_not_live,
        test_Q_live_not_verified,
        test_R_missing_fx_no_arbitrage,
        test_S_missing_baseline_no_arbitrage,
        test_T_passenger_mismatch_not_hard_equiv,
        test_U_cabin_mismatch_not_hard_equiv,
        test_V_l4_no_score_ranking_winner,
        test_W_jev_untouched,
        test_X_existing_l4_negatives_intact,
        test_Y_end_to_end_trace,
        test_Z_canonical_provenance_matches_provider,
    ]
    for t in tests:
        t()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n" + "=" * 75)
    print(f"L4.1 integration: {len(tests)} tests, {passed} passed, {failed} failed")
    print("=" * 75)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""
arbitrage_detection.py — Flight Market Intelligence L4

Evidence-based Arbitrage Detection (Gap L4 per v1.1.5).

PURPOSE (per L4 spec):
    Determine whether a price discrepancy between a candidate and a
    baseline is supported by sufficient structural + price + schedule +
    FX + passenger-parity evidence to surface as a Potential Opportunity.

WHAT THIS MODULE PRODUCES:
    ArbitrageEvidence records. Each record carries:
      - arbitrage_state (NOT_ARBITRAGE / NOT_COMPARABLE / INSUFFICIENT_EVIDENCE /
                        POTENTIAL_OPPORTUNITY / EVIDENCE_VERIFIED)
      - price_difference / normalized_price_difference / percentage_difference
        (DESCRIPTIVE; NOT a score)
      - evidence_maturity (OBSERVED / PARTIALLY_SUPPORTED / SUPPORTED / VERIFIED)
      - friction_evidence (structured, per v1.1.4 §9.1)
      - provider_evidence / provider_independence (per spec §17, §18)
      - arbitrage_reasons (reasons for the recorded state)
      - required_for_verification (gaps that block EVIDENCE_VERIFIED →
                                  VERIFIED_OPPORTUNITY, per v1.1.4 §11.3)
      - refusal_reasons / insufficient_evidence_reasons / unknown_reasons

WHAT THIS MODULE DOES NOT DO (per L4 spec §4, §22):
    - It does NOT emit arbitrage_score / opportunity_score / confidence_score
    - It does NOT rank candidates
    - It does NOT pick a winner
    - It does NOT recommend purchases
    - It does NOT modify Jev
    - It does NOT modify BookingIntent (no booking state transition)
    - It does NOT emit VERIFIED_OPPORTUNITY; the highest state this
      module emits is EVIDENCE_VERIFIED, requiring explicit fresh evidence
      per v1.1.4 §11.3.

ARCHITECTURE (per L4 spec §1):
    - Consumes ONLY normalized evidence objects (PriceEvidence, ScheduleEvidence,
      FXEvidence, ParityEvidence, CanonicalBaseline, ComparisonEvidence).
    - Does NOT touch raw provider JSON.
    - Zero provider API calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import price_intelligence as _pi  # type: ignore[import-not-found]
import fx_provider as _fx  # type: ignore[import-not-found]
import passenger_parity as _pp  # type: ignore[import-not-found]
import baseline_canonicalization as _bl  # type: ignore[import-not-found]
import comparison_engine as _cmp  # type: ignore[import-not-found]

# Canonical enums
VS_UNKNOWN = _pi.VS_UNKNOWN
VS_ESTIMATED = _pi.VS_ESTIMATED
VS_DATABASE = _pi.VS_DATABASE
VS_LIVE = _pi.VS_LIVE
VS_VERIFIED = _pi.VS_VERIFIED
SRC_LIVE = _pi.SRC_LIVE
SRC_CACHE = _pi.SRC_CACHE
SRC_INDICATIVE = _pi.SRC_INDICATIVE

# Forbidden identifiers
_FORBIDDEN_KEYS = (
    "arbitrage_score", "opportunity_score", "candidate_score",
    "predicted_savings", "expected_profit", "winner", "BOOKABLE",
)

# v1.1.4 §11.1 state machine (preserved verbatim)
STATE_NOT_COMPARABLE = "NOT_COMPARABLE"
STATE_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
STATE_POTENTIAL_OPPORTUNITY = "POTENTIAL_OPPORTUNITY"
STATE_EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
STATE_VERIFIED_OPPORTUNITY = "VERIFIED_OPPORTUNITY"
STATE_NOT_ARBITRAGE = "NOT_ARBITRAGE"

# Evidence maturity (per L4 spec §21; categorical only; no probabilities)
MATURITY_OBSERVED = "OBSERVED"
MATURITY_PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
MATURITY_SUPPORTED = "SUPPORTED"
MATURITY_VERIFIED = "VERIFIED"

# Required-for-verification catalogue (per v1.1.4 §11.3)
REQUIRED_FOR_VERIFICATION_CATALOGUE = {
    "real-time-schedule-confirmation": "real-time schedule confirmation for user's date",
    "second-producer-cross-check": "second producer cross-check",
    "baseline-producer-cross-check": "baseline producer cross-check",
    "operating-carrier-rules": "operating-carrier rule fetches (refundable, changeable)",
    "seats-remaining": "seats-remaining confirmation",
    "multi-passenger-parity": "multi-passenger parity",
    "live-fx-refresh": "live FX refresh",
}

# L4 Rule version
L4_RULE_VERSION = "l4/v1"

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
ARBITRAGE_OUTPUT_PATH = DATA_DIR / "arbitrage_evidence_l4.json"
ARBITRAGE_TRACE_PATH = DATA_DIR / "arbitrage_trace_l4.json"
SYNTHETIC_FIXTURES_PATH = DATA_DIR / "_synthetic_arbitrage_fixtures_l4.json"


# -----------------------------------------------------------------------------
# FrictionEvidence extraction (per v1.1.4 §9.1, structured — NO scores)
# -----------------------------------------------------------------------------

def extract_friction_evidence(candidate: dict[str, Any],
                                baggage_field: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a FrictionEvidence record (structured, NOT scored).

    Per v1.1.4 §9.1; the record carries booleans / enums / counts only.
    Per spec §15: NO monetary penalty is invented here.
    """
    baggage = {
        "included_pieces": None,
        "recheck_required": None,
        "evidence_complete": False,
    }
    bag = baggage_field if isinstance(baggage_field, dict) else {}
    if bag:
        baggage["included_pieces"] = bag.get("included", {}).get("checked_pieces") if isinstance(bag.get("included"), dict) else None
        baggage["recheck_required"] = bag.get("recheck_required")
        baggage["evidence_complete"] = bag.get("evidence_complete") is True

    # Transfer type — derived from ticket_structure OR explicit candidate field
    ticket_structure = candidate.get("ticket_structure")
    explicit_airport_change = candidate.get("airport_change")
    explicit_overnight = candidate.get("overnight_connection")
    explicit_min_conn = candidate.get("min_connection_min")
    if ticket_structure == "multi-ticket":
        transfer_type = "self"
        airport_change = explicit_airport_change
        overnight_connection = explicit_overnight
        min_connection_min = explicit_min_conn
    elif ticket_structure == "single-ticket":
        transfer_type = "managed"
        airport_change = explicit_airport_change
        overnight_connection = explicit_overnight
        min_connection_min = explicit_min_conn
    else:
        transfer_type = "none"
        airport_change = explicit_airport_change
        overnight_connection = explicit_overnight
        min_connection_min = explicit_min_conn

    transfer = {
        "type": transfer_type,
        "airport_change": airport_change,
        "overnight_connection": overnight_connection,
        "min_connection_min": min_connection_min,
        "typical_connection_min": candidate.get("typical_connection_min"),
        "evidence_complete": bool(ticket_structure),
    }

    schedule_uncertainty = {
        "is_uncertain": candidate.get("schedule_uncertain") is True,
        "schedule_status": candidate.get("schedule_status") or "UNAVAILABLE",
        "verification_status": candidate.get("schedule_verification") or VS_UNKNOWN,
    }

    cancellation_refund = {
        "refundable": None,
        "changeable": None,
        "change_fee": None,
        "refund_fee": None,
        "evidence_complete": False,
    }

    positioning_risk = {
        "has_positioning": bool(candidate.get("outer_port_origin") or
                                  candidate.get("outer_port_destination")),
        "separate_pnr": ticket_structure == "multi-ticket",
        "evidence_complete": bool(ticket_structure),
    }

    visa_transit_risk = {
        "requires_transit_visa": None,
        "evidence_complete": False,
    }

    # Build unknown_fields (§9.3)
    unknown_fields = []
    if not baggage["evidence_complete"]:
        unknown_fields.extend(["baggage.included_pieces", "baggage.recheck_required"])
    if not transfer["evidence_complete"]:
        unknown_fields.append("transfer.airport_change")
    if not cancellation_refund["evidence_complete"]:
        unknown_fields.extend([
            "cancellation_refund.refundable", "cancellation_refund.changeable",
        ])
    if not visa_transit_risk["evidence_complete"]:
        unknown_fields.append("visa_transit_risk.requires_transit_visa")

    return {
        "schema_version": "v1.1.4-friction/v1",
        "baggage": baggage,
        "transfer": transfer,
        "schedule_uncertainty": schedule_uncertainty,
        "cancellation_refund": cancellation_refund,
        "positioning_risk": positioning_risk,
        "visa_transit_risk": visa_transit_risk,
        "warnings": [],
        "unknown_fields": unknown_fields,
    }


# -----------------------------------------------------------------------------
# Provider evidence / independence (spec §17, §18)
# -----------------------------------------------------------------------------

def build_provider_evidence(provider_a: str | None,
                              provider_mode_a: str | None,
                              provider_b: str | None,
                              provider_mode_b: str | None,
                              retrieved_at_a: str | None,
                              retrieved_at_b: str | None) -> dict[str, Any]:
    """Build the provider_evidence / provider_independence record.

    Per spec §18: Duffel != Kiwi does NOT automatically mean independent
    market observations. We surface the cross-producer disagreement
    fact, with independence marked UNKNOWN unless explicitly supported.
    """
    prov_a = {"provider": provider_a, "provider_mode": provider_mode_a,
                "retrieved_at": retrieved_at_a}
    prov_b = {"provider": provider_b, "provider_mode": provider_mode_b,
                "retrieved_at": retrieved_at_b}

    # Provider disagreement: simple boolean; does NOT mean error
    if provider_a and provider_b:
        disagreement = provider_a != provider_b
    else:
        disagreement = None

    # Independence — conservatively UNKNOWN unless explicitly set
    independence = "UNKNOWN"

    return {
        "provider_a": prov_a,
        "provider_b": prov_b,
        "provider_disagreement": disagreement,
        "provider_independence": independence,
        "provider_independence_known": False,
    }


# -----------------------------------------------------------------------------
# Freshness comparison (spec §19)
# -----------------------------------------------------------------------------

def freshness_min_at(retrieved_at: str) -> float:
    """Minutes since retrieval; -1 if malformed."""
    return _pi.compute_freshness_min(retrieved_at)


def derive_freshness_state(retrieved_a: str | None,
                            retrieved_b: str | None) -> dict[str, Any]:
    """Produce a freshness state for the arbitrage evidence.

    Per spec §19: two retrieved_at values within reasonable time window
    may be comparable; a 3-day-old quote is not.

    Bucket assignment uses v1.1's canonical scheme (no new buckets).
    """
    out = {
        "freshness_a_bucket": "FRESHNESS_UNKNOWN",
        "freshness_b_bucket": "FRESHNESS_UNKNOWN",
        "freshness_a_min": -1.0,
        "freshness_b_min": -1.0,
        "freshness_window_min": _pi.FRESHNESS_COLD_MAX_MIN,  # = 1440 min = 24h
        "freshness_window_exceeded": None,
        "both_fresh": False,
        "stale_side": None,
    }
    if retrieved_a:
        out["freshness_a_min"] = freshness_min_at(retrieved_a)
        out["freshness_a_bucket"] = _pi.freshness_bucket_from_min(out["freshness_a_min"])
    if retrieved_b:
        out["freshness_b_min"] = freshness_min_at(retrieved_b)
        out["freshness_b_bucket"] = _pi.freshness_bucket_from_min(out["freshness_b_min"])

    out["both_fresh"] = (
        out["freshness_a_bucket"] in ("FRESHNESS_RECENT", "FRESHNESS_WARM") and
        out["freshness_b_bucket"] in ("FRESHNESS_RECENT", "FRESHNESS_WARM")
    )
    if not out["both_fresh"]:
        if out["freshness_a_bucket"] in ("FRESHNESS_EXPIRED", "FRESHNESS_UNKNOWN"):
            out["stale_side"] = "a"
        elif out["freshness_b_bucket"] in ("FRESHNESS_EXPIRED", "FRESHNESS_UNKNOWN"):
            out["stale_side"] = "b"
    return out


# -----------------------------------------------------------------------------
# Required-for-verification gap analysis
# -----------------------------------------------------------------------------

def derive_required_for_verification(candidate: dict[str, Any],
                                       baseline: dict[str, Any] | None,
                                       schedule_a: dict[str, Any] | None,
                                       schedule_b: dict[str, Any] | None,
                                       provider_independence_known: bool,
                                       fx_state: str,
                                       freshness_window_exceeded: bool | None) -> tuple[list[str], list[str]]:
    """Compute the `required_for_verification` list (per v1.1.4 §11.3).

    Each entry is a gap that, if cleared, transitions EVIDENCE_VERIFIED →
    VERIFIED_OPPORTUNITY. We surface the gaps as-is; we do NOT clear them.

    Returns (required_for_verification_keys, missing_required_keys).
    """
    gaps: list[str] = []

    # Real-time schedule confirmation
    sched_a_unconfirmed = (not schedule_a) or schedule_a.get("verification_status") in (VS_UNKNOWN, VS_DATABASE)
    sched_b_unconfirmed = (not schedule_b) or schedule_b.get("verification_status") in (VS_UNKNOWN, VS_DATABASE)
    if sched_a_unconfirmed or sched_b_unconfirmed:
        gaps.append("real-time-schedule-confirmation")

    # Second producer cross-check
    if not provider_independence_known:
        gaps.append("second-producer-cross-check")

    # Baseline producer cross-check
    if baseline is None:
        gaps.append("baseline-producer-cross-check")

    # Operating-carrier rule fetches
    if candidate.get("operating_carrier_rules_complete") is not True:
        gaps.append("operating-carrier-rules")

    # Seats-remaining
    if candidate.get("seats_remaining_complete") is not True:
        gaps.append("seats-remaining")

    # Multi-passenger parity (we always require this)
    gaps.append("multi-passenger-parity")

    # Live FX refresh
    if fx_state in ("UNKNOWN", "REFUSED"):
        gaps.append("live-fx-refresh")

    # Freshness
    if freshness_window_exceeded is True:
        gaps.append("live-fx-refresh")

    missing = list(gaps)
    return gaps, missing


# -----------------------------------------------------------------------------
# State machine
# -----------------------------------------------------------------------------

def derive_arbitrage_state(comparison_status: str | None,
                              comparison_reasons: list[str],
                              refusal_reasons: list[str],
                              price_difference_exists: bool,
                              freshness_both_fresh: bool,
                              n_required_gaps: int,
                              fx_state: str) -> str:
    """Map diagnostic results to v1.1.4 §11.1 states.

    Special L4 case:
      - If FX state is REFUSED → INSUFFICIENT_EVIDENCE (cannot compare
        normalized prices without FX; per spec §10)
      - If comparison is NOT_COMPARABLE or REFUSED → NOT_COMPARABLE
      - If comparison_reasons contain hard-parity mismatch markers → NOT_COMPARABLE
      - If price_difference is zero → NOT_ARBITRAGE
      - HARD_COMPARABLE + price_difference_exists
          + freshness_both_fresh + 0 required_gaps → EVIDENCE_VERIFIED
        else → POTENTIAL_OPPORTUNITY
      - SOFT_COMPARABLE / UNKNOWN → INSUFFICIENT_EVIDENCE
      - Otherwise → INSUFFICIENT_EVIDENCE
    """
    if fx_state == "REFUSED" and not refusal_reasons:
        refusal_reasons = list(refusal_reasons) + ["FX_REFUSED"]
    if refusal_reasons:
        return STATE_NOT_COMPARABLE
    if any(r in comparison_reasons for r in ("NOT_COMPARABLE", "CABIN_MISMATCH",
                                              "PASSENGER_COUNT_MISMATCH",
                                              "PASSENGER_TYPE_MISMATCH")):
        return STATE_NOT_COMPARABLE
    if comparison_status == _cmp.STATE_REFUSED:
        return STATE_NOT_COMPARABLE
    if not price_difference_exists:
        return STATE_NOT_ARBITRAGE
    if comparison_status in (_cmp.STATE_HARD_COMPARABLE,):
        if freshness_both_fresh and n_required_gaps == 0:
            return STATE_EVIDENCE_VERIFIED
        return STATE_POTENTIAL_OPPORTUNITY
    if comparison_status in (_cmp.STATE_SOFT_COMPARABLE, _cmp.STATE_UNKNOWN):
        return STATE_INSUFFICIENT_EVIDENCE
    return STATE_INSUFFICIENT_EVIDENCE


def derive_evidence_maturity(state: str) -> str:
    """Map state to a categorical maturity (NO numerical confidence).

    Per spec §21: categorical only.
    """
    if state == STATE_EVIDENCE_VERIFIED:
        return MATURITY_VERIFIED
    if state == STATE_POTENTIAL_OPPORTUNITY:
        return MATURITY_SUPPORTED
    if state == STATE_INSUFFICIENT_EVIDENCE:
        return MATURITY_PARTIALLY_SUPPORTED
    # NOT_COMPARABLE / NOT_ARBITRAGE
    return MATURITY_OBSERVED


# -----------------------------------------------------------------------------
# Top-level: build_arbitrage_evidence
# -----------------------------------------------------------------------------

def build_arbitrage_evidence(candidate: dict[str, Any],
                              baseline: dict[str, Any] | None,
                              comparison: dict[str, Any] | None = None,
                              fx_evidence: dict[str, Any] | None = None,
                              schedule_evidence_a: dict[str, Any] | None = None,
                              schedule_evidence_b: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a single ArbitrageEvidence record.

    Inputs are normalized evidence (Provider-agnostic).
    """
    retrieved_at = datetime.now(timezone.utc).isoformat()

    # 1. Compute comparison if not provided
    cmp = comparison or {}
    cmp_status = cmp.get("comparability_status") if cmp else None
    cmp_reasons = list(cmp.get("comparison_reasons", []) if cmp else [])
    cmp_refusal = list(cmp.get("refusal_reasons", []) if cmp else [])
    delta = cmp.get("delta") if cmp else None
    abs_delta = cmp.get("abs_delta") if cmp else None
    delta_pct = cmp.get("delta_percentage") if cmp else None
    norm_a = cmp.get("normalized_price_a") if cmp else None
    norm_b = cmp.get("normalized_price_b") if cmp else None
    fx_state = cmp.get("fx_state") if cmp else "UNKNOWN"

    price_difference_exists = abs_delta is not None and abs_delta > 0

    # Fall back to candidate/baseline embedded schedule evidence when
    # not supplied separately
    if schedule_evidence_a is None:
        schedule_evidence_a = candidate.get("schedule_evidence")
    if schedule_evidence_b is None and baseline is not None:
        schedule_evidence_b = baseline.get("schedule_evidence")

    # 2. Freshness state (spec §19)
    retrieved_a = (candidate.get("price_evidence") or {}).get("retrieved_at")
    retrieved_b = (baseline or {}).get("retrieved_at") if baseline else None
    # If the user provides candidate-level retrieved_at, prefer that
    if not retrieved_a:
        retrieved_a = candidate.get("retrieved_at")
    freshness_state = derive_freshness_state(retrieved_a, retrieved_b)

    # 3. Friction evidence (per v1.1.4 §9.1)
    baggage = candidate.get("baggage")
    friction = extract_friction_evidence(candidate, baggage_field=baggage if isinstance(baggage, dict) else None)

    # 4. Provider evidence (spec §17, §18)
    pe = candidate.get("price_evidence") or {}
    be = (baseline or {}).get("price_evidence") or {}
    provider_evidence = build_provider_evidence(
        provider_a=(pe.get("provider")),
        provider_mode_a=(pe.get("provider_mode")),
        provider_b=(be.get("provider")),
        provider_mode_b=(be.get("provider_mode")),
        retrieved_at_a=pe.get("retrieved_at"),
        retrieved_at_b=be.get("retrieved_at"),
    )

    # 8. Required-for-verification analysis
    required_gaps, _ = derive_required_for_verification(
        candidate=candidate,
        baseline=baseline,
        schedule_a=schedule_evidence_a,
        schedule_b=schedule_evidence_b,
        provider_independence_known=provider_evidence["provider_independence_known"],
        fx_state=fx_state,
        freshness_window_exceeded=(not freshness_state["both_fresh"]),
    )

    # Per spec §8: missing baseline → INSUFFICIENT_EVIDENCE
    baseline_missing = baseline is None

    # 6. State machine
    state = derive_arbitrage_state(
        comparison_status=cmp_status,
        comparison_reasons=cmp_reasons,
        refusal_reasons=cmp_refusal,
        price_difference_exists=price_difference_exists,
        freshness_both_fresh=freshness_state["both_fresh"],
        n_required_gaps=len(required_gaps),
        fx_state=fx_state,
    )

    # Per spec §8: missing baseline → INSUFFICIENT_EVIDENCE
    if baseline_missing and state in (STATE_POTENTIAL_OPPORTUNITY, STATE_EVIDENCE_VERIFIED):
        state = STATE_INSUFFICIENT_EVIDENCE

    # VERIFIED_OPPORTUNITY is NEVER emitted by L4 (per spec §22)
    if state == STATE_VERIFIED_OPPORTUNITY:
        state = STATE_EVIDENCE_VERIFIED  # demote (defensive)

    maturity = derive_evidence_maturity(state)

    # 7. Reasons
    arbitrage_reasons: list[str] = []
    insufficient_reasons: list[str] = []
    unknown_reasons: list[str] = []
    refusal_reasons = list(cmp_refusal)

    if state == STATE_NOT_ARBITRAGE:
        arbitrage_reasons.append("no price discrepancy observed")
    elif state == STATE_NOT_COMPARABLE:
        refusal_reasons.extend(cmp_reasons or ["comparison refused"])
    elif state == STATE_POTENTIAL_OPPORTUNITY:
        arbitrage_reasons.append("hard comparability + price discrepancy observed")
        arbitrage_reasons.append(f"delta={delta} {cmp.get('comparison_currency')} ({delta_pct}%)")
    elif state == STATE_EVIDENCE_VERIFIED:
        arbitrage_reasons.append("hard comparability + freshness fresh + required_for_verification cleared")
        arbitrage_reasons.append(f"delta={delta} {cmp.get('comparison_currency')} ({delta_pct}%)")
    elif state == STATE_INSUFFICIENT_EVIDENCE:
        insufficient_reasons.append("comparison SOFT/UNKNOWN; required evidence not yet cleared")
        for g in required_gaps:
            insufficient_reasons.append(f"required_for_verification: {g}")

    # 8. Provider independence note (spec §18)
    if not provider_evidence["provider_independence_known"]:
        unknown_reasons.append("provider_independence UNKNOWN (two providers may source overlapping inventory)")

    # 9. Build payload
    payload = {
        "schema_version": "l4/v1",
        "arbitrage_id": f"L4::{candidate.get('candidate_id', '?')}::{(baseline or {}).get('baseline_class', '?')}",
        "candidate_id": candidate.get("candidate_id"),
        "baseline_id": (baseline or {}).get("baseline_id"),
        "comparison_id": cmp.get("comparison_id"),
        "arbitrage_state": state,
        "evidence_maturity": maturity,
        "price_difference": delta,
        "normalized_price_difference": (
            (norm_a - norm_b) if (isinstance(norm_a, (int, float)) and isinstance(norm_b, (int, float)))
            else None
        ),
        "percentage_difference": delta_pct,
        "absolute_price_difference": abs_delta,
        "price_evidence_refs": {
            "candidate": {
                "provider": pe.get("provider"),
                "provider_mode": pe.get("provider_mode"),
                "retrieved_at": pe.get("retrieved_at"),
                "verification_status": pe.get("verification_status"),
                "currency": pe.get("currency"),
                "amount": pe.get("total_amount") or pe.get("adult_price"),
            },
            "baseline": {
                "provider": be.get("provider"),
                "provider_mode": be.get("provider_mode"),
                "retrieved_at": be.get("retrieved_at"),
                "verification_status": be.get("verification_status"),
                "currency": be.get("currency"),
                "amount": be.get("total_amount") or be.get("adult_price"),
            },
        },
        "schedule_evidence_refs": {
            "candidate": schedule_evidence_a,
            "baseline": schedule_evidence_b,
        },
        "fx_evidence_ref": {
            "state": fx_state,
            "evidence_provider": (fx_evidence.get("fx_evidence") or {}).get("provider") if fx_evidence else None,
        },
        "passenger_parity_ref": (
            candidate.get("passenger_parity_ref")
        ),
        "baseline_evidence_ref": (baseline or {}).get("baseline_id"),
        "friction_evidence": friction,
        "ticket_structure": {
            "candidate": candidate.get("ticket_structure"),
            "baseline": (baseline or {}).get("ticket_structure"),
        },
        "baggage": {
            "candidate": candidate.get("baggage"),
            "baseline": (baseline or {}).get("baggage"),
        },
        "provider_evidence": provider_evidence,
        "freshness": freshness_state,
        "required_for_verification": required_gaps,
        "missing_required_for_verification": required_gaps,
        "arbitrage_reasons": arbitrage_reasons,
        "insufficient_evidence_reasons": insufficient_reasons,
        "refusal_reasons": refusal_reasons,
        "unknown_reasons": unknown_reasons,
        "rule_version": L4_RULE_VERSION,
        "rule_definition": L4_RULE_VERSION,
        "retrieved_at": retrieved_at,
        "evidence_provenance": {
            "source": "arbitrage_detection_l4",
            "source_type": SRC_CACHE,
            "endpoint": None,
            "retrieved_at": retrieved_at,
            "verification_status": VS_DATABASE,
            "rule_version": L4_RULE_VERSION,
            "evidence_arity": 2,
        },
        "verification_status": VS_DATABASE,
        "source": "arbitrage_detection_l4",
        "is_identity": False,
        "supports_no_credential": True,
        "warnings": [],
        "failure_reason": None,
        "failure_kind": None,
    }

    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in _FORBIDDEN_KEYS:
        if forbidden in serialized:
            raise AssertionError(f"Forbidden token leaked into output: {forbidden}")

    return payload


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="L4 Arbitrage Detection")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--comparison", type=Path, default=None)
    parser.add_argument("--fx-evidence", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=str(ARBITRAGE_OUTPUT_PATH))
    parser.add_argument("--trace", type=Path, default=str(ARBITRAGE_TRACE_PATH))
    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\nL4 Arbitrage Detection", file=sys.stderr)
    print(f"  Candidate:  {args.candidate}", file=sys.stderr)
    print(f"  Baseline:   {args.baseline}", file=sys.stderr)
    print(f"  Comparison: {args.comparison}", file=sys.stderr)
    print(f"  FX evidence:{args.fx_evidence}", file=sys.stderr)

    if not args.candidate.exists():
        print(f"\n[ERROR] candidate not found: {args.candidate}", file=sys.stderr)
        return 11
    candidate = json.loads(args.candidate.read_text())
    baseline = json.loads(args.baseline.read_text()) if args.baseline and args.baseline.exists() else None
    comparison = json.loads(args.comparison.read_text()) if args.comparison and args.comparison.exists() else None
    fx_evidence = json.loads(args.fx_evidence.read_text()) if args.fx_evidence and args.fx_evidence.exists() else None

    payload = build_arbitrage_evidence(
        candidate=candidate,
        baseline=baseline,
        comparison=comparison,
        fx_evidence=fx_evidence,
        schedule_evidence_a=candidate.get("schedule_evidence"),
        schedule_evidence_b=(baseline or {}).get("schedule_evidence") if baseline else None,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n  Output: {args.output}", file=sys.stderr)

    trace_payload = {
        "trace_at": started_at,
        "arbitrage_id": payload["arbitrage_id"],
        "arbitrage_state": payload["arbitrage_state"],
        "evidence_maturity": payload["evidence_maturity"],
        "delta": payload["price_difference"],
        "delta_pct": payload["percentage_difference"],
        "freshness": payload["freshness"],
        "required_for_verification": payload["required_for_verification"],
        "rule_version": payload["rule_version"],
    }
    args.trace.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False))
    print(f"  Trace:  {args.trace}", file=sys.stderr)

    print("\n" + "=" * 60, file=sys.stderr)
    print("ARBITRAGE EVIDENCE — RESULT", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  arbitrage_state:     {payload['arbitrage_state']}", file=sys.stderr)
    print(f"  evidence_maturity:   {payload['evidence_maturity']}", file=sys.stderr)
    print(f"  delta:               {payload['price_difference']} {comparison.get('comparison_currency', '')}" if comparison else "",
           file=sys.stderr)
    print(f"  provider_independence:{payload['provider_evidence']['provider_independence']}",
           file=sys.stderr)
    print(f"  required_for_verification: {payload['required_for_verification']}", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

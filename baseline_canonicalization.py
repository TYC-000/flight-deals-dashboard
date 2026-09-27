"""
baseline_canonicalization.py — Flight Market Intelligence v1.2.4

Baseline Canonicalization Layer (Gap F per v1.1.5).

PURPOSE:
    Answer the question: "What should this candidate be compared against?"
    A baseline is a *comparability reference*, NOT a price winner.

WHAT THIS MODULE PRODUCES:
    CanonicalBaseline records: provider-agnostic representation of a
    candidate's eligible baselines. A CanonicalBaseline is *not* a
    produced search result; it is a structural description of what
    kind of baseline the candidate could be compared against, IF such
    a baseline were available.

WHAT THIS MODULE DOES NOT DO (per spec §1, §4, §18):
    - It does NOT use price to choose a baseline.
    - It does NOT use Jev score, information_priority_score, or any
      ranking to choose a baseline.
    - It does NOT emit ArbitrageEvidence, Opportunity, or
      VerifiedOpportunity.
    - It does NOT modify Jev semantics.
    - It does NOT compare two prices.

BASELINE TAXONOMY (from v1.1.4 §3.1, preserved verbatim):
    canonical_direct         single non-stop on same carrier/alliance
    conventional_hub         single-connection through primary alliance hub
    secondary_entry          two-connection through European secondary entry
    outer_port_positioning   two-ticket with positioning flight
    same_airport_pair        set of routings between same O/D
    fictional_no_fly         explanatory only; never canonical baseline

ELIGIBILITY STATES (per spec §15):
    ELIGIBLE       — a baseline of this class could be available
    NOT_ELIGIBLE   — geometry/mission rules preclude this class
    UNKNOWN        — insufficient evidence to determine eligibility

HARD RULES (per spec §4, §18):
    - baseline ≠ cheapest candidate
    - baseline ≠ first candidate
    - baseline ≠ Jev survivor
    - Baseline canonicalization works even when PriceEvidence is null.

ARCHITECTURE (per spec §3):
    Travel Mission
      ↓
    Candidate
      ↓
    Baseline Eligibility
      ↓
    Baseline Classification
      ↓
    Canonical Baseline
      ↓
    Comparison Pair
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Canonical enums reused from price_intelligence (READ ONLY).
import price_intelligence as _pi  # type: ignore[import-not-found]

VS_UNKNOWN = _pi.VS_UNKNOWN
VS_ESTIMATED = _pi.VS_ESTIMATED
VS_DATABASE = _pi.VS_DATABASE
VS_LIVE = _pi.VS_LIVE
VS_VERIFIED = _pi.VS_VERIFIED
SRC_LIVE = _pi.SRC_LIVE
SRC_CACHE = _pi.SRC_CACHE
SRC_INDICATIVE = _pi.SRC_INDICATIVE

# Forbidden identifiers (defensive guard)
_FORBIDDEN_KEYS = (
    "arbitrage_score", "opportunity_score", "candidate_score",
    "predicted_savings", "expected_profit", "winner", "BOOKABLE",
)

# v1.1.4 §3.1 baseline classes (verbatim — do not rename without v1.1.4 update)
BL_CLASS_CANONICAL_DIRECT = "canonical_direct"
BL_CLASS_CONVENTIONAL_HUB = "conventional_hub"
BL_CLASS_SECONDARY_ENTRY = "secondary_entry"
BL_CLASS_OUTER_PORT_POSITIONING = "outer_port_positioning"
BL_CLASS_SAME_AIRPORT_PAIR = "same_airport_pair"
BL_CLASS_FICTIONAL_NO_FLY = "fictional_no_fly"

# Compatibility labels from spec §5
BL_CONVENTIONAL = "conventional"
BL_SAME_HUB = "same_hub"
BL_SAME_CARRIER = "same_carrier"
BL_SAME_TICKET = "same_ticket"
BL_POSITIONING = "positioning"
BL_OUTER_PORT = "outer_port"

# Eligibility states (per spec §15)
ELIGIBILITY_ELIGIBLE = "ELIGIBLE"
ELIGIBILITY_NOT_ELIGIBLE = "NOT_ELIGIBLE"
ELIGIBILITY_UNKNOWN = "UNKNOWN"

# Airport semantics (per spec §10)
AIRPORT_EXACT = "AIRPORT_EXACT"
AIRPORT_GROUP = "AIRPORT_GROUP"
METRO_GROUP = "METRO_GROUP"
AIRPORT_UNKNOWN = "UNKNOWN"

# European secondary-entry airports (per v1.1.4 §3.1 list)
EUROPEAN_SECONDARY_ENTRY = {
    "LIS", "ZRH", "VIE", "CPH", "WAW", "DUB", "MUC",
    # additional common European secondary entries (extending the same class)
    "BRU", "OSL", "ARN", "HEL", "BUD", "PRG", "SOF", "OTP",
}

# Outer-port airports (per v1.1.4 §3.1 + spec §5)
OUTER_PORTS = {
    "KUL", "BKK", "SIN", "CGK",
    # additional Asia outer ports
    "HKG", "TPE", "MNL", "KIX", "NRT", "HND", "ICN",
}

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
BASELINE_OUTPUT_PATH = DATA_DIR / "baseline_evidence_v1_2_4.json"
BASELINE_TRACE_PATH = DATA_DIR / "baseline_trace_v1_2_4.json"
SYNTHETIC_FIXTURES_PATH = DATA_DIR / "_synthetic_baseline_fixtures_v1_2_4.json"

CANONICALIZATION_RULE_VERSION = "v1.2.4/v1"


# -----------------------------------------------------------------------------
# Travel Mission + Candidate canonicalization
# -----------------------------------------------------------------------------

def normalize_airport(code: Any) -> str | None:
    """Normalize an airport code to upper-case IATA form, or None if blank."""
    if not isinstance(code, str):
        return None
    code = code.strip().upper()
    if not code or not re.match(r"^[A-Z0-9]{3}$", code):
        return None
    return code


def canonicalize_mission(mission: dict[str, Any] | None) -> dict[str, Any]:
    """Build a normalized Travel Mission record (provider-agnostic).

    Required keys (caller may provide):
      mission_id, origin, destination, travel_date, return_date,
      cabin, passenger_count, passenger_types
    """
    m: dict[str, Any] = mission if isinstance(mission, dict) else {}
    return {
        "mission_id": m.get("mission_id"),
        "origin": normalize_airport(m.get("origin")),
        "destination": normalize_airport(m.get("destination")),
        "travel_date": m.get("travel_date") if isinstance(m.get("travel_date"), str) else None,
        "return_date": m.get("return_date") if isinstance(m.get("return_date"), str) else None,
        "is_round_trip": bool(m.get("return_date")),
        "cabin": (m.get("cabin") or "").strip().lower() or None,
        "passenger_count": m.get("passenger_count") if isinstance(m.get("passenger_count"), int) else None,
        "passenger_types": [str(t) for t in (m.get("passenger_types") or []) if isinstance(t, str)],
        "passenger_basis_known": (
            isinstance(m.get("passenger_count"), int) and bool(m.get("passenger_types"))
        ),
        "raw": m,
    }


def canonicalize_candidate(candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Build a normalized Candidate record (provider-agnostic).

    Accepts both the heuristic shape used in `data/flight_candidates.json`
    and the structured shape used in tests. All fields are optional; the
    canonical record makes missing/unknown-ness explicit.
    """
    c: dict[str, Any] = candidate if isinstance(candidate, dict) else {}

    # Segments — accept either `segments: [...]` or derive from long_haul/short_haul
    segments = c.get("segments") if isinstance(c.get("segments"), list) else []

    routing_list: list[tuple[str, str]] = []
    for seg in segments:
        if isinstance(seg, dict):
            o = normalize_airport(seg.get("from"))
            d = normalize_airport(seg.get("to"))
            if o and d:
                routing_list.append((o, d))

    # Origin / destination — explicit, else derived from segments / long_haul
    origin = (normalize_airport(c.get("origin"))
              or (routing_list[0][0] if routing_list else None))
    destination = (normalize_airport(c.get("destination"))
                   or (routing_list[-1][1] if routing_list else None))

    # Date
    travel_date = c.get("travel_date") if isinstance(c.get("travel_date"), str) else None
    return_date = c.get("return_date") if isinstance(c.get("return_date"), str) else None

    # Cabin / passenger basis — preserve unknowns per spec §13
    cabin_raw = c.get("cabin") or c.get("long_haul", {}).get("cabin") if isinstance(c.get("long_haul"), dict) else c.get("cabin")
    cabin = (str(cabin_raw) if cabin_raw is not None else None)
    cabin_norm = (cabin.strip().lower() if cabin else None) or None

    pc = c.get("passenger_count")
    pc_int = pc if isinstance(pc, int) else None
    ptypes = c.get("passenger_types")
    ptypes_norm = [str(t) for t in ptypes] if isinstance(ptypes, list) else None

    # Carriers
    marketing_carriers = []
    operating_carriers = []
    if isinstance(c.get("carriers"), list):
        for carrier in c["carriers"]:
            if isinstance(carrier, dict):
                mc = carrier.get("marketing_carrier")
                oc = carrier.get("operating_carrier")
                if isinstance(mc, str):
                    marketing_carriers.append(mc.strip().upper())
                if isinstance(oc, str):
                    operating_carriers.append(oc.strip().upper())
            elif isinstance(carrier, str):
                marketing_carriers.append(carrier.strip().upper())

    # Ticket structure
    ticket_count = c.get("ticket_count") if isinstance(c.get("ticket_count"), int) else None
    ticket_structure = c.get("ticket_structure")
    if ticket_structure is None and ticket_count is not None:
        ticket_structure = "multi-ticket" if ticket_count > 1 else "single-ticket"

    # Schedule / price / FX evidence status (whether each was surfaced)
    schedule_evidence_status = c.get("schedule_evidence_status") or "UNKNOWN"
    price_evidence_status = c.get("price_evidence_status") or "UNKNOWN"
    fx_evidence_status = c.get("fx_evidence_status") or "UNKNOWN"

    return {
        "candidate_id": c.get("id") or c.get("candidate_id"),
        "origin": origin,
        "destination": destination,
        "routing": routing_list,
        "segment_count": len(routing_list),
        "is_non_stop": (len(routing_list) == 1),
        "travel_date": travel_date,
        "return_date": return_date,
        "is_round_trip": bool(return_date),
        "cabin": cabin_norm,
        "cabin_known": cabin_norm is not None,
        "passenger_count": pc_int,
        "passenger_count_known": isinstance(pc_int, int),
        "passenger_types": ptypes_norm,
        "passenger_types_known": bool(ptypes_norm),
        "marketing_carriers": marketing_carriers,
        "operating_carriers": operating_carriers,
        "operating_carriers_known": len(operating_carriers) > 0,
        "ticket_structure": ticket_structure,
        "ticket_count": ticket_count,
        "schedule_evidence_status": schedule_evidence_status,
        "price_evidence_status": price_evidence_status,
        "fx_evidence_status": fx_evidence_status,
        "outer_port_origin": origin in OUTER_PORTS if origin else None,
        "outer_port_destination": destination in OUTER_PORTS if destination else None,
        "secondary_entry_origin": origin in EUROPEAN_SECONDARY_ENTRY if origin else None,
        "secondary_entry_destination": destination in EUROPEAN_SECONDARY_ENTRY if destination else None,
        "raw_provider": c.get("provider"),
        "raw_provider_mode": c.get("provider_mode"),
    }


# -----------------------------------------------------------------------------
# Baseline eligibility evaluation
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class EligibilityRule:
    """A rule that determines whether a baseline class is eligible
    for a given (mission, candidate)."""
    name: str
    applies: bool  # whether the rule has anything to say
    eligible: bool | None  # True=eligible, False=not, None=unknown


def evaluate_baseline_eligibility(mission: dict[str, Any],
                                    candidate: dict[str, Any]) -> dict[str, Any]:
    """For each of the 6 baseline classes from v1.1.4 §3.1, compute
    ELIGIBLE / NOT_ELIGIBLE / UNKNOWN.
    """
    o = candidate.get("origin")
    d = candidate.get("destination")
    seg_count = candidate.get("segment_count", 0)
    is_non_stop = candidate.get("is_non_stop", False)
    is_outer_port_origin = candidate.get("outer_port_origin")
    is_outer_port_destination = candidate.get("outer_port_destination")
    is_se_entry_destination = candidate.get("secondary_entry_destination")

    rules: list[EligibilityRule] = []

    # 1. canonical_direct — only when a non-stop exists between O and D.
    #    The candidate itself is non-stop means a non-stop is possible;
    #    for *another* candidate to be a canonical_direct baseline, the
    #    routing class must include non-stop. We surface as ELIGIBLE
    #    when the candidate is itself non-stop, or when the
    #    mission/candidate pair is plausible (origin + destination
    #    known). UNKNOWN when the segment count is 0 (insufficient).
    rules.append(EligibilityRule(
        name=BL_CLASS_CANONICAL_DIRECT,
        applies=(o is not None and d is not None),
        eligible=(is_non_stop if o and d else None),
    ))

    # 2. conventional_hub — single-connection through primary alliance
    #    hub. ELIGIBLE when mission O/D known and candidate is single
    #    connection (segment_count == 2). UNKNOWN when no segments.
    if o and d and seg_count == 2:
        rule_conventional_hub = EligibilityRule(
            name=BL_CLASS_CONVENTIONAL_HUB,
            applies=True,
            eligible=True,
        )
    elif o and d and seg_count == 1:
        rule_conventional_hub = EligibilityRule(
            name=BL_CLASS_CONVENTIONAL_HUB,
            applies=True,
            eligible=False,  # non-stop — hub-style baseline not applicable here
        )
    else:
        rule_conventional_hub = EligibilityRule(
            name=BL_CLASS_CONVENTIONAL_HUB,
            applies=(o is not None and d is not None),
            eligible=None,
        )
    rules.append(rule_conventional_hub)

    # 3. secondary_entry — destination is a European secondary entry OR
    #    mission routes through one.
    if is_se_entry_destination is True:
        rule_se = EligibilityRule(
            name=BL_CLASS_SECONDARY_ENTRY,
            applies=True,
            eligible=True,
        )
    elif o and d and d not in EUROPEAN_SECONDARY_ENTRY:
        rule_se = EligibilityRule(
            name=BL_CLASS_SECONDARY_ENTRY,
            applies=True,
            eligible=False,  # destination not in secondary-entry set
        )
    else:
        rule_se = EligibilityRule(
            name=BL_CLASS_SECONDARY_ENTRY,
            applies=(o is not None and d is not None),
            eligible=None,
        )
    rules.append(rule_se)

    # 4. outer_port_positioning — origin OR destination is an outer port,
    #    AND the candidate has multi-ticket structure (or routing through
    #    outer port). ELIGIBLE in that case.
    is_outer_port = (
        is_outer_port_origin is True or is_outer_port_destination is True
    )
    is_multi_ticket = (candidate.get("ticket_structure") == "multi-ticket"
                       or (candidate.get("ticket_count") or 0) > 1)
    if o and d and is_outer_port and is_multi_ticket:
        rule_op = EligibilityRule(
            name=BL_CLASS_OUTER_PORT_POSITIONING,
            applies=True,
            eligible=True,
        )
    elif o and d and not is_outer_port:
        rule_op = EligibilityRule(
            name=BL_CLASS_OUTER_PORT_POSITIONING,
            applies=True,
            eligible=False,
        )
    else:
        rule_op = EligibilityRule(
            name=BL_CLASS_OUTER_PORT_POSITIONING,
            applies=(o is not None and d is not None),
            eligible=None,
        )
    rules.append(rule_op)

    # 5. same_airport_pair — valid whenever origin+destination are known
    #    (a set of alternatives could exist).
    rules.append(EligibilityRule(
        name=BL_CLASS_SAME_AIRPORT_PAIR,
        applies=(o is not None and d is not None),
        eligible=True if (o and d) else None,
    ))

    # 6. fictional_no_fly — never eligible as canonical baseline
    #    (per v1.1.4 §3.1: "explanatory / sensitivity only; never used
    #    as the canonical baseline"). Mark NOT_ELIGIBLE always when
    #    mission/candidate is parsed.
    rules.append(EligibilityRule(
        name=BL_CLASS_FICTIONAL_NO_FLY,
        applies=True,
        eligible=False,
    ))

    out = []
    for r in rules:
        if r.eligible is True:
            state = ELIGIBILITY_ELIGIBLE
        elif r.eligible is False:
            state = ELIGIBILITY_NOT_ELIGIBLE
        else:
            state = ELIGIBILITY_UNKNOWN
        out.append({
            "baseline_class": r.name,
            "eligibility": state,
            "rule_applies": r.applies,
        })

    return {
        "candidate_id": candidate.get("candidate_id"),
        "baseline_classes": out,
    }


# -----------------------------------------------------------------------------
# Canonical baseline record (for each eligible class)
# -----------------------------------------------------------------------------

def canonicalize_baseline(mission: dict[str, Any],
                            candidate: dict[str, Any],
                            baseline_class: str,
                            retrieved_at: str) -> dict[str, Any]:
    """Build a Canonical Baseline record.

    Per spec §7: the canonical baseline is provider-agnostic. It captures
    the *structure* of a baseline, not a real provider's response.

    Per spec §21: provenance records source candidate + canonicalization
    timestamp + rule version.
    """
    return {
        "schema_version": "v1.2.4",
        "baseline_class": baseline_class,
        "mission_binding": {
            "mission_id": mission.get("mission_id"),
            "origin": mission.get("origin"),
            "destination": mission.get("destination"),
            "travel_date": mission.get("travel_date"),
            "return_date": mission.get("return_date"),
            "is_round_trip": mission.get("is_round_trip"),
            "cabin": mission.get("cabin"),
            "passenger_count": mission.get("passenger_count"),
            "passenger_types": mission.get("passenger_types"),
            "passenger_basis_known": mission.get("passenger_basis_known"),
        },
        "candidate_binding": {
            "candidate_id": candidate.get("candidate_id"),
        },
        "canonical_representation": {
            "origin": candidate.get("origin"),
            "destination": candidate.get("destination"),
            "routing": candidate.get("routing"),
            "segment_count": candidate.get("segment_count"),
            "travel_date": candidate.get("travel_date"),
            "return_date": candidate.get("return_date"),
            "is_round_trip": candidate.get("is_round_trip"),
            "airports": (([candidate["origin"]] if candidate.get("origin") else [])
                         + [seg[1] for seg in (candidate.get("routing") or [])]),
            "routing_family": _derive_routing_family(candidate),
            "marketing_carriers": candidate.get("marketing_carriers") or [],
            "operating_carriers": candidate.get("operating_carriers") or [],
            "operating_carriers_known": candidate.get("operating_carriers_known"),
            "cabin": candidate.get("cabin"),
            "cabin_known": candidate.get("cabin_known"),
            "passenger_count": candidate.get("passenger_count"),
            "passenger_count_known": candidate.get("passenger_count_known"),
            "passenger_types": candidate.get("passenger_types"),
            "passenger_types_known": candidate.get("passenger_types_known"),
            "ticket_structure": candidate.get("ticket_structure"),
            "ticket_count": candidate.get("ticket_count"),
            "positioning": candidate.get("outer_port_origin") is True
                            or candidate.get("outer_port_destination") is True,
            "outer_port": candidate.get("outer_port_origin") is True
                            or candidate.get("outer_port_destination") is True,
            "secondary_entry": candidate.get("secondary_entry_destination") is True,
            "airport_change": _has_airport_change(candidate),
            "multi_ticket": candidate.get("ticket_structure") == "multi-ticket",
            "schedule_evidence_status": candidate.get("schedule_evidence_status"),
            "price_evidence_status": candidate.get("price_evidence_status"),
            "fx_evidence_status": candidate.get("fx_evidence_status"),
        },
        "canonicalization_reason": (
            f"baseline class '{baseline_class}' is ELIGIBLE for the "
            f"given mission/candidate pair under rule version "
            f"{CANONICALIZATION_RULE_VERSION}. This is a structural "
            f"reference, NOT a price-based selection (never the cheapest "
            f"candidate, first candidate, or Jev survivor)."
        ),
        "verification_status": VS_DATABASE,  # structural baseline
        "source": "baseline_canonicalization_v1_2_4",
        "is_identity": False,
        "supports_no_credential": True,
        "warnings": [],
        "failure_reason": None,
        "failure_kind": None,
        "provenance": {
            "source": "baseline_canonicalization_v1_2_4",
            "source_type": SRC_CACHE,
            "endpoint": None,
            "retrieved_at": retrieved_at,
            "verification_status": VS_DATABASE,
            "canonicalization_rule_version": CANONICALIZATION_RULE_VERSION,
            "evidence_arity": 0,
            "derived_from": {
                "candidate_id": candidate.get("candidate_id"),
                "candidate_origin": candidate.get("origin"),
                "candidate_destination": candidate.get("destination"),
                "candidate_provider": candidate.get("raw_provider"),
                "candidate_provider_mode": candidate.get("raw_provider_mode"),
            },
        },
    }


def _derive_routing_family(candidate: dict[str, Any]) -> str:
    """Derive a routing family label (per spec §17).

    routing_family is structural evidence, NOT arbitrage classification.
    """
    seg = candidate.get("segment_count", 0)
    if seg == 0:
        return "unknown"
    if seg == 1:
        return "conventional"
    if seg == 2:
        if candidate.get("secondary_entry_destination"):
            return "secondary_entry"
        if candidate.get("outer_port_origin") or candidate.get("outer_port_destination"):
            return "outer_port"
        return "conventional_hub"
    if seg >= 3:
        return "unusual_routing"
    return "unknown"


def _has_airport_change(candidate: dict[str, Any]) -> bool | None:
    """Detect an airport change between consecutive segments.

    Returns True/False when both endpoints are known; None when unknown.
    """
    routing = candidate.get("routing") or []
    if len(routing) < 2:
        if len(routing) == 1:
            return False
        return None
    for i in range(len(routing) - 1):
        prev_arrival = routing[i][1]
        next_departure = routing[i + 1][0]
        if prev_arrival is None or next_departure is None:
            return None
        if prev_arrival != next_departure:
            return True
    return False


# -----------------------------------------------------------------------------
# Comparison pair (one candidate + one baseline class)
# -----------------------------------------------------------------------------

def build_comparison_pair(mission: dict[str, Any],
                            candidate: dict[str, Any],
                            baseline: dict[str, Any]) -> dict[str, Any]:
    """Build a Comparison Pair structure (per spec §3).

    Per spec §16: hard/soft/unknown comparability semantics preserved.
    Per spec §18: no price-based selection.
    """
    # Hard parity rules (per v1.1.4 §3.2)
    hard_match_origin = (mission.get("origin") == candidate.get("origin"))
    hard_match_destination = (mission.get("destination") == candidate.get("destination"))
    hard_match_date = (mission.get("travel_date") == candidate.get("travel_date"))
    hard_match_return = (mission.get("return_date") == candidate.get("return_date"))
    hard_match_cabin = (
        mission.get("cabin") == candidate.get("cabin")
        and candidate.get("cabin_known") is True
    )
    hard_match_passenger = (
        mission.get("passenger_count") == candidate.get("passenger_count")
        and candidate.get("passenger_count_known") is True
        and mission.get("passenger_basis_known")
    )

    if all([hard_match_origin, hard_match_destination, hard_match_date,
            hard_match_return, hard_match_cabin, hard_match_passenger]):
        comparability = "hard_comparable"
    elif (hard_match_origin and hard_match_destination and hard_match_date and hard_match_passenger
          and (not hard_match_cabin or not hard_match_return)):
        comparability = "soft_comparable"
    else:
        comparability = "unknown"

    return {
        "schema_version": "v1.2.4",
        "comparison_pair_id": f"{candidate.get('candidate_id')}::{baseline.get('baseline_class')}",
        "candidate_id": candidate.get("candidate_id"),
        "baseline_class": baseline.get("baseline_class"),
        "comparability": comparability,
        "hard_match": {
            "origin": hard_match_origin,
            "destination": hard_match_destination,
            "date": hard_match_date,
            "return_date": hard_match_return,
            "cabin": hard_match_cabin,
            "passenger_basis": hard_match_passenger,
        },
        "soft_observations": {
            "outer_port_candidate": candidate.get("outer_port_origin") is True
                                       or candidate.get("outer_port_destination") is True,
            "ticket_structure": candidate.get("ticket_structure"),
            "airport_change": baseline["canonical_representation"].get("airport_change"),
        },
        "verification_status": VS_DATABASE,
        "source": "baseline_canonicalization_v1_2_4",
        "is_identity": False,
        "supports_no_credential": True,
        "warnings": [],
        "failure_reason": None,
        "failure_kind": None,
        "provenance": baseline.get("provenance"),
    }


# -----------------------------------------------------------------------------
# Top-level orchestration
# -----------------------------------------------------------------------------

def canonicalize_for_candidate(mission: dict[str, Any],
                                  candidate: dict[str, Any]) -> dict[str, Any]:
    """Top-level: canonicalize a single candidate against a single mission.

    Returns:
        {
          mission_canonical: {...},
          candidate_canonical: {...},
          baseline_eligibility: [{baseline_class, eligibility, ...}, ...],
          canonical_baselines: [CanonicalBaseline...],   # only for ELIGIBLE classes
          comparison_pairs:   [ComparisonPair...],
          retrieved_at: ISO8601,
        }
    """
    retrieved_at = datetime.now(timezone.utc).isoformat()

    # Step 1: canonicalize mission + candidate (provider-agnostic)
    mission_canon = canonicalize_mission(mission)
    candidate_canon = canonicalize_candidate(candidate)

    # Step 2: baseline eligibility (per spec §15)
    eligibility = evaluate_baseline_eligibility(mission_canon, candidate_canon)

    # Step 3: canonical baselines + comparison pairs (only for ELIGIBLE)
    canonical_baselines: list[dict[str, Any]] = []
    comparison_pairs: list[dict[str, Any]] = []
    for entry in eligibility["baseline_classes"]:
        if entry["eligibility"] != ELIGIBILITY_ELIGIBLE:
            continue
        bl = canonicalize_baseline(mission_canon, candidate_canon,
                                     entry["baseline_class"], retrieved_at)
        canonical_baselines.append(bl)
        comparison_pairs.append(build_comparison_pair(mission_canon, candidate_canon, bl))

    payload = {
        "schema_version": "v1.2.4",
        "mission_canonical": mission_canon,
        "candidate_canonical": candidate_canon,
        "baseline_eligibility": eligibility,
        "canonical_baselines": canonical_baselines,
        "comparison_pairs": comparison_pairs,
        "canonicalization_rule_version": CANONICALIZATION_RULE_VERSION,
        "retrieved_at": retrieved_at,
        "verification_status": VS_DATABASE,
        "source": "baseline_canonicalization_v1_2_4",
        "is_identity": False,
        "supports_no_credential": True,
        "warnings": [],
        "failure_reason": None,
        "failure_kind": None,
        "provenance": {
            "source": "baseline_canonicalization_v1_2_4",
            "source_type": SRC_CACHE,
            "endpoint": None,
            "retrieved_at": retrieved_at,
            "verification_status": VS_DATABASE,
            "canonicalization_rule_version": CANONICALIZATION_RULE_VERSION,
            "evidence_arity": (1 + len(canonical_baselines)),
        },
    }

    # Defensive guard
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in _FORBIDDEN_KEYS:
        if forbidden in serialized:
            raise AssertionError(f"Forbidden token leaked into output: {forbidden}")

    return payload


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baseline Canonicalization v1.2.4")
    parser.add_argument("--mission", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=str(BASELINE_OUTPUT_PATH))
    parser.add_argument("--trace", type=Path, default=str(BASELINE_TRACE_PATH))
    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\nBaseline Canonicalization v1.2.4", file=sys.stderr)
    print(f"  Mission: {args.mission}", file=sys.stderr)
    print(f"  Candidate: {args.candidate}", file=sys.stderr)

    if not args.mission.exists():
        print(f"\n[ERROR] Mission file not found: {args.mission}", file=sys.stderr)
        return 11
    if not args.candidate.exists():
        print(f"\n[ERROR] Candidate file not found: {args.candidate}", file=sys.stderr)
        return 11

    mission = json.loads(args.mission.read_text())
    candidate = json.loads(args.candidate.read_text())

    payload = canonicalize_for_candidate(mission, candidate)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n  Output: {args.output}", file=sys.stderr)

    trace_payload = {
        "trace_at": started_at,
        "mission_path": str(args.mission),
        "candidate_path": str(args.candidate),
        "candidate_id": payload["candidate_canonical"]["candidate_id"],
        "eligibility": payload["baseline_eligibility"]["baseline_classes"],
        "n_eligible_baselines": len(payload["canonical_baselines"]),
        "n_comparison_pairs": len(payload["comparison_pairs"]),
    }
    args.trace.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False))
    print(f"  Trace:  {args.trace}", file=sys.stderr)

    print("\n" + "=" * 60, file=sys.stderr)
    print("BASELINE CANONICALIZATION — RESULT", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  mission: {payload['mission_canonical']['mission_id']}", file=sys.stderr)
    print(f"  candidate: {payload['candidate_canonical']['candidate_id']}", file=sys.stderr)
    print(f"  eligible_baselines: {len(payload['canonical_baselines'])}", file=sys.stderr)
    for bl in payload["canonical_baselines"]:
        print(f"    - {bl['baseline_class']}", file=sys.stderr)
    print(f"  unknown_eligibility: "
          f"{sum(1 for e in payload['baseline_eligibility']['baseline_classes'] if e['eligibility'] == ELIGIBILITY_UNKNOWN)}",
           file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

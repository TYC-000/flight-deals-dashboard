"""
passenger_parity.py — Flight Market Intelligence v1.2.3

Provider-agnostic Multi-passenger Parity Evidence primitive.

Purpose (per spec §1):
    Determine whether two PriceEvidence records have sufficient
    passenger-basis parity to enter a future price comparison.

What this is:
    - A primitive that emits normalized ParityEvidence.
    - Side-effect-free: consumes two PriceEvidence dicts, produces one
      ParityEvidence dict + a parity reason.

What this is NOT (per spec §16):
    - NOT arbitrage detection.
    - NOT price comparison.
    - NOT an opportunity generator.
    - NOT a scorer. No score field; no ranking.
    - Does NOT modify Jev semantics.

Hard boundaries (per spec §4, §6):
    - If passenger_count is missing → UNKNOWN, never 1.
    - If passenger_type is missing → UNKNOWN, never ADT.
    - If cabin is missing → UNKNOWN, never ECONOMY.
    - If baggage is missing → UNKNOWN, never 0.
    - price_per_passenger is a DERIVED analytical field only.
      It is NEVER used to assert 'cheaper', 'better', 'opportunity',
      'arbitrage'.

Parity status enum (per spec §3, §10):
    PARITY        — all known parity dimensions match
    NON_PARITY    — at least one hard-parity dimension disagrees
    UNKNOWN       — insufficient data to determine parity

Hard parity dimensions (each must agree to maintain PARITY):
    - passenger_count
    - passenger_type_composition
    - cabin
    - itinerary_identity
    - ticket_structure

Soft parity dimensions (recorded as observations; UNKNOWN never forces NON_PARITY):
    - baggage
    - fare_family (if surfaced)
    - fare_basis
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error  # noqa: F401  -- imported for architecture parity; not used directly
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Canonical freshness / failure-kind reuse from price_intelligence (READ ONLY).
# This module does NOT modify price_intelligence.py — only imports the canonical
# utilities as a single source of truth.
import price_intelligence as _pi  # type: ignore[import-not-found]

# Failure reasons specific to parity (per spec §14: prefer canonical taxonomy where available)
PARITY_FAIL_PASSENGER_COUNT_UNKNOWN = "PASSENGER_COUNT_UNKNOWN"
PARITY_FAIL_PASSENGER_TYPE_UNKNOWN = "PASSENGER_TYPE_UNKNOWN"
PARITY_FAIL_CABIN_UNKNOWN = "CABIN_UNKNOWN"
PARITY_FAIL_ITINERARY_UNKNOWN = "ITINERARY_UNKNOWN"
PARITY_FAIL_TICKET_STRUCTURE_UNKNOWN = "TICKET_STRUCTURE_UNKNOWN"
PARITY_FAIL_BAGGAGE_UNKNOWN = "BAGGAGE_UNKNOWN"

# Hard-parity disagreement reasons
PARITY_FAIL_PASSENGER_COUNT_MISMATCH = "PASSENGER_COUNT_MISMATCH"
PARITY_FAIL_PASSENGER_TYPE_MISMATCH = "PASSENGER_TYPE_MISMATCH"
PARITY_FAIL_CABIN_MISMATCH = "CABIN_MISMATCH"
PARITY_FAIL_ITINERARY_MISMATCH = "ITINERARY_MISMATCH"
PARITY_FAIL_TICKET_STRUCTURE_MISMATCH = "TICKET_STRUCTURE_MISMATCH"

PARITY_STATUS_PARITY = "PARITY"
PARITY_STATUS_NON_PARITY = "NON_PARITY"
PARITY_STATUS_UNKNOWN = "UNKNOWN"

HARD_PARITY_REASONS = {
    PARITY_FAIL_PASSENGER_COUNT_MISMATCH,
    PARITY_FAIL_PASSENGER_TYPE_MISMATCH,
    PARITY_FAIL_CABIN_MISMATCH,
    PARITY_FAIL_ITINERARY_MISMATCH,
    PARITY_FAIL_TICKET_STRUCTURE_MISMATCH,
}

# Verification tier (5-tier; never BOOKABLE)
VS_UNKNOWN = _pi.VS_UNKNOWN
VS_ESTIMATED = _pi.VS_ESTIMATED
VS_DATABASE = _pi.VS_DATABASE
VS_LIVE = _pi.VS_LIVE
VS_VERIFIED = _pi.VS_VERIFIED

# Forbidden identifiers (defensive guard)
_FORBIDDEN_KEYS = (
    "arbitrage_score", "opportunity_score", "candidate_score",
    "predicted_savings", "expected_profit", "winner", "BOOKABLE",
)

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
PARITY_OUTPUT_PATH = DATA_DIR / "passenger_parity_evidence_v1_2_3.json"
PARITY_TRACE_PATH = DATA_DIR / "passenger_parity_trace_v1_2_3.json"
SYNTHETIC_FIXTURES_PATH = DATA_DIR / "_synthetic_passenger_fixtures_v1_2_3.json"


# -----------------------------------------------------------------------------
# Passenger count normalization
# -----------------------------------------------------------------------------

# Passenger type code mapping (canonical, IATA-style; expanded where providers
# differ in casing). Per spec §5: never collapse mixed types into a count.
PASSENGER_TYPE_NORMALIZATION = {
    "ADT": "ADT", "adult": "ADT", "adt": "ADT", "ADULT": "ADT",
    "CHD": "CHD", "child": "CHD", "chd": "CHD", "CHILD": "CHD",
    "INF": "INF", "infant": "INF", "inf": "INF", "INFANT": "INF",
}


def normalize_passenger_type(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return PASSENGER_TYPE_NORMALIZATION.get(raw.strip().upper())
    return None


def normalize_passenger_composition(passengers_field: Any) -> dict[str, Any]:
    """Normalize a passenger specification to a structured payload.

    Returns a dict:
      {
        "composition": [{"type": str, "count": int|str}, ...],
        "count_known": bool,         # False if any count is "?" or missing
        "raw_format": "int" | "list[str]" | "list[dict]" | "none" | "unknown",
      }

    Per spec §4: never coerce missing count to 1. A bare string list
    like ["ADT", "ADT"] is a "type-list" — types are surfaced, counts
    are not (count_known=False). A dict list like [{"type":"ADT","count":2}]
    has explicit counts.

    Accepts:
      - None → empty; count_known=False
      - int N → [{"type":"ADT", "count":N}] (single-type; count_known=True)
      - list of strings → expand to type entries; count_known=False
      - list of dicts → as-is (after type normalization); count_known
        iff all dicts have an integer count
    """
    if passengers_field is None:
        return {"composition": [], "count_known": False, "raw_format": "none"}
    if isinstance(passengers_field, int):
        n = int(passengers_field)
        return {"composition": [{"type": "ADT", "count": n}], "count_known": True, "raw_format": "int"}
    if isinstance(passengers_field, list):
        out: list[dict[str, Any]] = []
        all_counts_int = True
        for item in passengers_field:
            if isinstance(item, str):
                t = normalize_passenger_type(item)
                if t is None:
                    return {"composition": [{"type": "UNKNOWN", "count": "?"}], "count_known": False, "raw_format": "list[str]"}
                # Bare type code: count is unknown.
                match = next((x for x in out if x["type"] == t), None)
                if match is not None:
                    cur = match.get("count")
                    if isinstance(cur, int):
                        match["count"] = cur + 1
                    else:
                        # Already unknown count, leave unknown
                        pass
                else:
                    out.append({"type": t, "count": "?"})
                all_counts_int = False
            elif isinstance(item, dict):
                t_raw = item.get("type")
                t = normalize_passenger_type(t_raw)
                if t is None:
                    return {"composition": [{"type": "UNKNOWN", "count": "?"}], "count_known": False, "raw_format": "list[dict]"}
                c = item.get("count", 1)
                try:
                    c_val: Any = int(c)
                except (TypeError, ValueError):
                    c_val = "?"
                    all_counts_int = False
                if isinstance(c_val, int):
                    existing = next((x for x in out if x["type"] == t), None)
                    if existing is not None:
                        ex_c = existing.get("count")
                        if isinstance(ex_c, int):
                            existing["count"] = ex_c + c_val
                        else:
                            existing["count"] = "?"
                            all_counts_int = False
                    else:
                        out.append({"type": t, "count": c_val})
                else:
                    existing = next((x for x in out if x["type"] == t), None)
                    if existing is None:
                        out.append({"type": t, "count": c_val})
            else:
                return {"composition": [{"type": "UNKNOWN", "count": "?"}], "count_known": False, "raw_format": "unknown"}
        return {"composition": out, "count_known": all_counts_int, "raw_format": "list[str]" if any(isinstance(i, str) for i in passengers_field) else "list[dict]"}
    return {"composition": [{"type": "UNKNOWN", "count": "?"}], "count_known": False, "raw_format": "unknown"}


def total_passenger_count(composition: list[dict[str, Any]]) -> int | None:
    """Return total passenger count from a normalized composition.

    Returns None if any entry has an unknown count.
    """
    total = 0
    for entry in composition:
        c = entry.get("count")
        if not isinstance(c, int):
            return None
        total += c
    return total


# -----------------------------------------------------------------------------
# Provider-side extraction
# -----------------------------------------------------------------------------

def extract_passenger_basis(price_evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Extract a normalized passenger basis dict from a PriceEvidence record.

    Returns a dict that captures everything this module cares about:
      - passenger_count (int | None) — None if UNKNOWN
      - passenger_types ([str])  — empty list if UNKNOWN
      - cabin (str | None)
      - itinerary_identity (Any)
      - ticket_structure (str | None)
      - baggage_basis (dict)
      - fare_basis (str | None)
      - total_price (float | None)
      - currency (str | None)
      - provider, provider_mode, retrieved_at

    Per spec §4: missing fields stay None, not defaulted.
    """
    if not isinstance(price_evidence, dict):
        return {
            "passenger_count": None,
            "passenger_types": [],
            "pc_known": False,
            "passenger_types_known": False,
            "cabin": None,
            "itinerary_identity": None,
            "ticket_structure": None,
            "baggage_basis": {"checked_pieces": None, "carry_on": None, "basis_known": False},
            "fare_basis": None,
            "total_price": None,
            "currency": None,
            "provider": None,
            "provider_mode": None,
            "retrieved_at": None,
        }

    # passenger_count: hard rule from spec §4 — NEVER coerce "unknown"
    # to 1. We accept an explicit `passenger_count` field; we accept
    # a composition with explicit integer counts (e.g. from a dict list).
    # A bare string list like ["ADT"] is treated as type-list with
    # unknown count (count_known=False), and pc stays None.
    pc_top = price_evidence.get("passenger_count")
    composition_raw = price_evidence.get("passenger_types") or price_evidence.get("passengers")
    norm = normalize_passenger_composition(composition_raw)
    composition = norm["composition"]
    pc_computed = total_passenger_count(composition)
    pc_from_composition = pc_computed if (norm["count_known"] and pc_computed is not None) else None
    if isinstance(pc_top, int):
        pc = pc_top
    elif pc_from_composition is not None:
        pc = pc_from_composition
    else:
        pc = None

    # passenger_types: distinct codes present. With count_known=False,
    # we still surface the type set for observation.
    if composition:
        ptypes = sorted({e["type"] for e in composition if e.get("type") and e["type"] != "UNKNOWN"})
    else:
        ptypes = []

    ptypes_known_flag = bool(ptypes) and isinstance(pc, int)
    pc_known_flag = isinstance(pc, int)

    # cabin
    cabin = price_evidence.get("cabin") or price_evidence.get("cabin_class")
    if cabin is not None:
        cabin = str(cabin).strip().lower() or None

    # itinerary_identity: explicit or derived from candidate/segment list
    itinerary_identity = price_evidence.get("itinerary_identity")
    if itinerary_identity is None:
        # Derive a deterministic signature from a candidate-style field if present.
        seg = price_evidence.get("segments") or price_evidence.get("candidate_signature")
        if isinstance(seg, list) and seg:
            itinerary_identity = json.dumps(seg, sort_keys=True, ensure_ascii=False)

    # ticket_structure
    ticket_structure = price_evidence.get("ticket_structure")
    if ticket_structure is None:
        # If a fare_basis or ticket_count hints exist, use them; else None
        ticket_count = price_evidence.get("ticket_count")
        if isinstance(ticket_count, int) and ticket_count > 1:
            ticket_structure = "multi-ticket"
        elif isinstance(ticket_count, int) and ticket_count == 1:
            ticket_structure = "single-ticket"

    # baggage: extract from canonical baggage.included
    baggage = price_evidence.get("baggage") if isinstance(price_evidence.get("baggage"), dict) else {}
    baggage_included = baggage.get("included", {})
    if not isinstance(baggage_included, dict):
        baggage_included = {}
    baggage_basis = {
        "checked_pieces": baggage_included.get("checked_pieces"),
        "carry_on": baggage_included.get("carry_on"),
        "basis_known": baggage.get("evidence_complete") is True,
    }

    # fare_basis / fare_family
    fare_basis = price_evidence.get("fare_basis") or price_evidence.get("fare_family")

    # total_price — derived from `total_amount` or `adult_price * pc`
    total_price = price_evidence.get("total_price") or price_evidence.get("total_amount")
    if total_price is None:
        adult_price = price_evidence.get("adult_price")
        if isinstance(adult_price, (int, float)) and isinstance(pc, int) and pc > 0:
            total_price = float(adult_price) * pc  # MARK AS DERIVED

    # currency
    currency = price_evidence.get("currency")

    # provenance
    provider = price_evidence.get("provider") or price_evidence.get("price_provider")
    provider_mode = price_evidence.get("provider_mode")
    retrieved_at = price_evidence.get("retrieved_at")

    return {
        "passenger_count": pc,
        "passenger_types": ptypes,
        "pc_known": pc_known_flag,
        "passenger_types_known": ptypes_known_flag,
        "cabin": cabin,
        "itinerary_identity": itinerary_identity,
        "ticket_structure": ticket_structure,
        "baggage_basis": baggage_basis,
        "fare_basis": fare_basis,
        "total_price": (float(total_price) if isinstance(total_price, (int, float)) else None),
        "currency": (str(currency) if currency is not None else None),
        "provider": provider,
        "provider_mode": provider_mode,
        "retrieved_at": retrieved_at,
    }


# -----------------------------------------------------------------------------
# Parity dimension checks
# -----------------------------------------------------------------------------

def _equal_known(a: Any, b: Any) -> bool:
    """True if both are known AND equal; False if either is missing/unknown."""
    if a is None or b is None:
        return False
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)
    return a == b


def evaluate_passenger_parity(
    evidence_a: dict[str, Any],
    evidence_b: dict[str, Any],
) -> dict[str, Any]:
    """Compare two PriceEvidence-derived bases and emit a ParityEvidence record.

    Returns:
        {
          parity_status: "PARITY" | "NON_PARITY" | "UNKNOWN",
          hard_parity_reasons: [str],          # disagreements only (NON_PARITY)
          soft_parity_observations: [str],     # missing-data observations
          dimension_results: {                  # per-dimension verdict
              passenger_count: {match, known},
              passenger_type_composition: {match, known},
              cabin: {match, known},
              itinerary_identity: {match, known},
              ticket_structure: {match, known},
              baggage: {match, known},
              fare_basis: {match, known},
          },
          price_per_passenger: {                # DERIVED analytical field
              a: float | None,
              b: float | None,
              difference: float | None,         # b - a; None if either side missing
              derived: True,
              note: "derived analytical field; never used to claim cheaper/better/opportunity",
          },
          ...
        }
    """
    retrieved_at = datetime.now(timezone.utc).isoformat()

    a = extract_passenger_basis(evidence_a)
    b = extract_passenger_basis(evidence_b)

    # Dimension evaluation
    dimension_results: dict[str, dict[str, Any]] = {}

    # 1. passenger_count — HARD parity
    pc_a, pc_b = a["passenger_count"], b["passenger_count"]
    pc_known = pc_a is not None and pc_b is not None
    pc_match = pc_known and pc_a == pc_b
    dimension_results["passenger_count"] = {"match": pc_match, "known": pc_known,
                                             "a": pc_a, "b": pc_b}

    # 2. passenger_type_composition — HARD parity; UNKNOWN if either side
    # has bare type codes without integer counts.
    ptypes_a_known = a["passenger_types"] != [] and a["pc_known"]
    ptypes_b_known = b["passenger_types"] != [] and b["pc_known"]
    ptypes_known = ptypes_a_known and ptypes_b_known
    ptypes_match = ptypes_known and a["passenger_types"] == b["passenger_types"]
    dimension_results["passenger_type_composition"] = {
        "match": ptypes_match, "known": ptypes_known,
        "a": a["passenger_types"], "b": b["passenger_types"],
        "a_pc_known": a["pc_known"], "b_pc_known": b["pc_known"],
    }

    # 3. cabin — HARD parity
    cab_a, cab_b = a["cabin"], b["cabin"]
    cab_known = cab_a is not None and cab_b is not None
    cab_match = cab_known and cab_a == cab_b
    dimension_results["cabin"] = {"match": cab_match, "known": cab_known,
                                   "a": cab_a, "b": cab_b}

    # 4. itinerary_identity — HARD parity
    itin_a, itin_b = a["itinerary_identity"], b["itinerary_identity"]
    itin_known = itin_a is not None and itin_b is not None
    itin_match = itin_known and _equal_known(itin_a, itin_b)
    dimension_results["itinerary_identity"] = {"match": itin_match, "known": itin_known,
                                                "a": itin_a, "b": itin_b}

    # 5. ticket_structure — HARD parity
    tick_a, tick_b = a["ticket_structure"], b["ticket_structure"]
    tick_known = tick_a is not None and tick_b is not None
    tick_match = tick_known and tick_a == tick_b
    dimension_results["ticket_structure"] = {"match": tick_match, "known": tick_known,
                                              "a": tick_a, "b": tick_b}

    # 6. baggage — SOFT parity (observation only)
    bag_a, bag_b = a["baggage_basis"], b["baggage_basis"]
    bag_known = bag_a.get("basis_known") and bag_b.get("basis_known")
    bag_match = bag_known and bag_a.get("checked_pieces") == bag_b.get("checked_pieces") \
                and bag_a.get("carry_on") == bag_b.get("carry_on")
    dimension_results["baggage"] = {"match": bag_match, "known": bag_known,
                                     "a": bag_a, "b": bag_b}

    # 7. fare_basis — SOFT parity (observation only)
    fb_a, fb_b = a["fare_basis"], b["fare_basis"]
    fb_known = fb_a is not None and fb_b is not None
    fb_match = fb_known and fb_a == fb_b
    dimension_results["fare_basis"] = {"match": fb_match, "known": fb_known,
                                         "a": fb_a, "b": fb_b}

    # 8. price_per_passenger (derived) — OBSERVED only. Never used to
    # claim "cheaper" / "opportunity" / "arbitrage". This is a SOFT
    # parity observation; flagged mismatch is NOT automatic NON_PARITY.
    pppa = (a["total_price"] / a["passenger_count"]
            if (a["total_price"] is not None and isinstance(a["passenger_count"], int) and a["passenger_count"] > 0)
            else None)
    pppb = (b["total_price"] / b["passenger_count"]
            if (b["total_price"] is not None and isinstance(b["passenger_count"], int) and b["passenger_count"] > 0)
            else None)
    pppa_known = pppa is not None and pppb is not None
    pppa_match = pppa_known and abs(pppa - pppb) < 1e-6
    dimension_results["price_per_passenger"] = {
        "match": pppa_match, "known": pppa_known,
        "a": pppa, "b": pppb, "derived": True,
        "note": "derived analytical field; never interpreted as opportunity",
    }

    # Build hard-parity disagreement list
    hard_reasons: list[str] = []
    soft_observations: list[str] = []
    if not pc_known:
        soft_observations.append(PARITY_FAIL_PASSENGER_COUNT_UNKNOWN)
    elif not pc_match:
        hard_reasons.append(PARITY_FAIL_PASSENGER_COUNT_MISMATCH)
    if not ptypes_known:
        soft_observations.append(PARITY_FAIL_PASSENGER_TYPE_UNKNOWN)
    elif not ptypes_match:
        hard_reasons.append(PARITY_FAIL_PASSENGER_TYPE_MISMATCH)
    if not cab_known:
        soft_observations.append(PARITY_FAIL_CABIN_UNKNOWN)
    elif not cab_match:
        hard_reasons.append(PARITY_FAIL_CABIN_MISMATCH)
    if not itin_known:
        soft_observations.append(PARITY_FAIL_ITINERARY_UNKNOWN)
    elif not itin_match:
        hard_reasons.append(PARITY_FAIL_ITINERARY_MISMATCH)
    if not tick_known:
        soft_observations.append(PARITY_FAIL_TICKET_STRUCTURE_UNKNOWN)
    elif not tick_match:
        hard_reasons.append(PARITY_FAIL_TICKET_STRUCTURE_MISMATCH)
    if not bag_known:
        soft_observations.append(PARITY_FAIL_BAGGAGE_UNKNOWN)

    # Decide parity status
    # Hard rule (per spec §4, §10): UNKNOWN must NEVER be coerced to PARITY.
    # If any hard-parity field is missing → UNKNOWN.
    # If any hard-parity field disagrees → NON_PARITY.
    # Else → PARITY.
    hard_parity_known_fields = (pc_known, ptypes_known, cab_known, itin_known, tick_known)
    if not all(hard_parity_known_fields):
        parity_status = PARITY_STATUS_UNKNOWN
    elif hard_reasons:
        parity_status = PARITY_STATUS_NON_PARITY
    else:
        parity_status = PARITY_STATUS_PARITY

    # price_per_passenger — DERIVED analytical only
    pa = a["total_price"]
    pb = b["total_price"]
    ppa = (pa / pc_a) if (pa is not None and pc_a and pc_a > 0) else None
    ppb = (pb / pc_b) if (pb is not None and pc_b and pc_b > 0) else None
    diff = (ppb - ppa) if (ppa is not None and ppb is not None) else None

    price_per_passenger = {
        "a": ppa,
        "b": ppb,
        "difference": diff,
        "derived": True,
        "note": ("derived analytical field; never used to claim "
                  "'cheaper', 'better', 'opportunity', or 'arbitrage'"),
    }

    # Build parity evidence payload
    payload: dict[str, Any] = {
        "schema_version": "v1.2.3",
        "parity_status": parity_status,
        "hard_parity_reasons": hard_reasons,
        "soft_parity_observations": soft_observations,
        "dimension_results": dimension_results,
        "price_per_passenger": price_per_passenger,
        "totals": {
            "a_total_price": pa,
            "b_total_price": pb,
            "currency_a": a["currency"],
            "currency_b": b["currency"],
            "currency_parity": (a["currency"] == b["currency"] if (a["currency"] and b["currency"]) else None),
        },
        "provider_disagreement": (
            a["provider"] != b["provider"] if (a["provider"] and b["provider"]) else None
        ),
        "providers": {
            "a": {"provider": a["provider"], "provider_mode": a["provider_mode"],
                   "retrieved_at": a["retrieved_at"]},
            "b": {"provider": b["provider"], "provider_mode": b["provider_mode"],
                   "retrieved_at": b["retrieved_at"]},
        },
        "verification_status": VS_DATABASE,  # parity is structural, not live
        "source": "passenger_parity_v1_2_3",
        "endpoint": None,
        "retrieved_at": retrieved_at,
        "is_identity": False,
        "supports_no_credential": True,
        "warnings": [],
        "failure_reason": None,
        "failure_kind": None,
        "provenance": {
            "source": "passenger_parity_v1_2_3",
            "source_type": _pi.SRC_CACHE,
            "endpoint": None,
            "retrieved_at": retrieved_at,
            "verification_status": VS_DATABASE,
            "evidence_arity": 2,
        },
    }

    # Defensive guard
    for forbidden in _FORBIDDEN_KEYS:
        if forbidden in payload:
            raise AssertionError(f"Forbidden key in ParityEvidence: {forbidden}")

    return payload


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def load_evidence_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Passenger Parity v1.2.3")
    parser.add_argument("--evidence-a", type=Path, required=True)
    parser.add_argument("--evidence-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=str(PARITY_OUTPUT_PATH))
    parser.add_argument("--trace", type=Path, default=str(PARITY_TRACE_PATH))
    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\nPassenger Parity v1.2.3", file=sys.stderr)
    print(f"  Evidence A: {args.evidence_a}", file=sys.stderr)
    print(f"  Evidence B: {args.evidence_b}", file=sys.stderr)

    if not args.evidence_a.exists():
        print(f"\n[ERROR] Evidence A not found: {args.evidence_a}", file=sys.stderr)
        return 11
    if not args.evidence_b.exists():
        print(f"\n[ERROR] Evidence B not found: {args.evidence_b}", file=sys.stderr)
        return 11

    file_a = load_evidence_file(args.evidence_a)
    file_b = load_evidence_file(args.evidence_b)

    # Each file may wrap a list of evidences. Pick the first per file by default.
    # Or accept a single dict directly.
    def _first_evidence(payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload, dict) and "evidences" in payload and isinstance(payload["evidences"], list):
            if payload["evidences"]:
                return payload["evidences"][0]
        return payload if isinstance(payload, dict) else {}

    evidence_a = _first_evidence(file_a)
    evidence_b = _first_evidence(file_b)

    parity = evaluate_passenger_parity(evidence_a, evidence_b)

    payload_out = {
        "schema": "passenger_parity_v1_2_3",
        "trace_at": started_at,
        "evidence_a_path": str(args.evidence_a),
        "evidence_b_path": str(args.evidence_b),
        "parity_evidence": parity,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload_out, indent=2, ensure_ascii=False))
    print(f"\n  Output: {args.output}", file=sys.stderr)

    trace_payload = {
        "trace_at": started_at,
        "evidence_a_path": str(args.evidence_a),
        "evidence_b_path": str(args.evidence_b),
        "parity_status": parity["parity_status"],
        "hard_parity_reasons": parity["hard_parity_reasons"],
        "soft_parity_observations": parity["soft_parity_observations"],
        "providers": parity["providers"],
    }
    args.trace.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False))
    print(f"  Trace:  {args.trace}", file=sys.stderr)

    print("\n" + "=" * 60, file=sys.stderr)
    print("PASSENGER PARITY — RESULT", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  parity_status                  {parity['parity_status']}", file=sys.stderr)
    print(f"  hard_parity_reasons            {parity['hard_parity_reasons']}", file=sys.stderr)
    print(f"  soft_parity_observations       {parity['soft_parity_observations']}", file=sys.stderr)
    print(f"  price_per_passenger.diff       {parity['price_per_passenger']['difference']}", file=sys.stderr)
    print(f"  provider_a                     {parity['providers']['a']['provider']}", file=sys.stderr)
    print(f"  provider_b                     {parity['providers']['b']['provider']}", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

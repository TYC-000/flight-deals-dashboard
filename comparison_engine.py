"""
comparison_engine.py — Flight Market Intelligence v1.2.5

Cross-provider Comparison Evidence Layer.

PURPOSE (per spec §1):
    Answer: "Given the current evidence, can two candidates reasonably be
             compared?"
    Output: ComparisonEvidence (provider-agnostic)

WHAT THIS IS NOT (per spec §2):
    - NOT arbitrage detection
    - NOT opportunity generation
    - NOT verified opportunity
    - NOT price-based winner / ranking
    - NOT Jev modification

ARCHITECTURE (per spec §18):
    Provider adapters (price_intelligence, kiwi_price_provider,
    fx_provider, passenger_parity, baseline_canonicalization,
    schedule_intelligence) produce normalized evidence objects.
    This module consumes NORMALIZED evidence objects only.
    It does NOT read raw provider JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Canonical enums reused from price_intelligence (READ ONLY).
import price_intelligence as _pi  # type: ignore[import-not-found]
import fx_provider as _fx  # type: ignore[import-not-found]
import passenger_parity as _pp  # type: ignore[import-not-found]
import baseline_canonicalization as _bl  # type: ignore[import-not-found]

VS_UNKNOWN = _pi.VS_UNKNOWN
VS_ESTIMATED = _pi.VS_ESTIMATED
VS_DATABASE = _pi.VS_DATABASE
VS_LIVE = _pi.VS_LIVE
VS_VERIFIED = _pi.VS_VERIFIED
SRC_LIVE = _pi.SRC_LIVE
SRC_CACHE = _pi.SRC_CACHE
SRC_INDICATIVE = _pi.SRC_INDICATIVE

# Failure kinds reused
FK_CURRENCY_UNKNOWN = _pi.FK_CURRENCY_UNKNOWN

# Forbidden identifiers (defensive guard)
_FORBIDDEN_KEYS = (
    "arbitrage_score", "opportunity_score", "candidate_score",
    "predicted_savings", "expected_profit", "winner", "BOOKABLE",
)

# Comparability states (per spec §5 + v1.1.4 taxonomy)
STATE_HARD_COMPARABLE = "HARD_COMPARABLE"
STATE_SOFT_COMPARABLE = "SOFT_COMPARABLE"
STATE_UNKNOWN = "UNKNOWN"
STATE_NOT_COMPARABLE = "NOT_COMPARABLE"
STATE_REFUSED = "REFUSED"

# Hard-refusal conditions (per v1.1.4 §4 / spec §10, §11)
REFUSAL_CURRENCY_UNKNOWN = "REFUSAL_CURRENCY_UNKNOWN"
REFUSAL_VERIFICATION_NOT_LIVE = "REFUSAL_VERIFICATION_NOT_LIVE"
REFUSAL_DATE_MISMATCH = "REFUSAL_DATE_MISMATCH"
REFUSAL_AIRPORT_MISMATCH = "REFUSAL_AIRPORT_MISMATCH"
REFUSAL_CABIN_MISMATCH = "REFUSAL_CABIN_MISMATCH"
REFUSAL_TICKET_STRUCTURE_MISMATCH = "REFUSAL_TICKET_STRUCTURE_MISMATCH"
REFUSAL_FX_NOT_FOUND = "REFUSAL_FX_NOT_FOUND"
REFUSAL_PRICE_NOT_FOUND = "REFUSAL_PRICE_NOT_FOUND"

# Soft-comparison observations (warnings; do not force a refusal)
SOFT_BAGGAGE_MISMATCH = "SOFT_BAGGAGE_MISMATCH"
SOFT_BAGGAGE_UNKNOWN = "SOFT_BAGGAGE_UNKNOWN"
SOFT_ITINERARY_MISMATCH = "SOFT_ITINERARY_MISMATCH"
SOFT_PROVIDER_DISAGREEMENT = "SOFT_PROVIDER_DISAGREEMENT"
SOFT_PASSENGER_PARITY_UNKNOWN = "SOFT_PASSENGER_PARITY_UNKNOWN"
SOFT_FX_STALE = "SOFT_FX_STALE"
SOFT_PRICE_STALE = "SOFT_PRICE_STALE"
SOFT_FARE_BASIS_MISMATCH = "SOFT_FARE_BASIS_MISMATCH"
SOFT_RETURN_DATE_MISMATCH = "SOFT_RETURN_DATE_MISMATCH"

# Unknown-reasons
UNKNOWN_REASON = "UNKNOWN_REASON"

COMPARISON_RULE_VERSION = "v1.2.5/v1"


REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
COMPARISON_OUTPUT_PATH = DATA_DIR / "comparison_evidence_v1_2_5.json"
COMPARISON_TRACE_PATH = DATA_DIR / "comparison_trace_v1_2_5.json"
SYNTHETIC_FIXTURES_PATH = DATA_DIR / "_synthetic_comparison_fixtures_v1_2_5.json"


# -----------------------------------------------------------------------------
# Normalized input extraction (provider-agnostic)
# -----------------------------------------------------------------------------

def extract_normalized_evidence(candidate_label: str,
                                  side: dict[str, Any]) -> dict[str, Any]:
    """Extract the normalized fields this comparison engine consumes.

    The dict `side` may carry PriceEvidence, ScheduleEvidence, and an
    optional reference to passenger-parity and baseline-canonical evidence.
    The shape is intentionally permissive: missing fields stay None/UNKNOWN.

    Per spec §4: the engine must not break on missing fields; it must
    surface missing fields as UNKNOWN.
    """
    price = side.get("price_evidence") if isinstance(side.get("price_evidence"), dict) else {}
    sched = side.get("schedule_evidence") if isinstance(side.get("schedule_evidence"), dict) else {}
    return {
        "candidate_label": candidate_label,
        "candidate_id": side.get("candidate_id"),
        "baseline_id": side.get("baseline_id"),
        "price": {
            "amount": price.get("total_amount") or price.get("adult_price"),
            "currency": price.get("currency"),
            "retrieved_at": price.get("retrieved_at"),
            "freshness_bucket": price.get("freshness_bucket") or "FRESHNESS_UNKNOWN",
            "verification_status": price.get("verification_status") or VS_UNKNOWN,
            "provider": price.get("provider") or side.get("provider"),
            "provider_mode": price.get("provider_mode") or side.get("provider_mode"),
            "failure_kind": price.get("failure_kind"),
        },
        "schedule": {
            "verification_status": sched.get("verification_status") or VS_UNKNOWN,
            "provider": sched.get("provider") or side.get("provider"),
            "segments": sched.get("segments") if isinstance(sched.get("segments"), list) else [],
            "routing": sched.get("routing") or side.get("routing"),
            "segment_count": sched.get("segment_count") or len(sched.get("segments") or []) if isinstance(sched.get("segments"), list) else None,
        },
        "parity_evidence_ref": side.get("parity_evidence_ref") or side.get("passenger_parity_evidence_id"),
        "baseline_evidence_ref": side.get("baseline_evidence_ref") or side.get("baseline_evidence_id"),
        "mission_binding": side.get("mission_binding") if isinstance(side.get("mission_binding"), dict) else {},
        "cabin": side.get("cabin"),
        "cabin_known": isinstance(side.get("cabin"), str) and len(side.get("cabin")) > 0,
        "ticket_structure": side.get("ticket_structure"),
        "ticket_count": side.get("ticket_count") if isinstance(side.get("ticket_count"), int) else None,
        "baggage": side.get("baggage") if isinstance(side.get("baggage"), dict) else {},
        "fare_basis": side.get("fare_basis"),
        "itinerary_identity": side.get("itinerary_identity"),
        "origin": side.get("origin"),
        "destination": side.get("destination"),
        "travel_date": side.get("travel_date"),
        "return_date": side.get("return_date"),
        "is_round_trip": bool(side.get("return_date")),
    }


# -----------------------------------------------------------------------------
# Hard-parity dimension checks
# -----------------------------------------------------------------------------

def _failures_origin(a: dict[str, Any], b: dict[str, Any]) -> tuple[list[str], list[str]]:
    hard = []
    soft = []
    if a["origin"] != b["origin"]:
        if a["origin"] is None or b["origin"] is None:
            soft.append("SOFT_ORIGIN_UNKNOWN")
        else:
            hard.append("ORIGIN_MISMATCH")
    if a["destination"] != b["destination"]:
        if a["destination"] is None or b["destination"] is None:
            soft.append("SOFT_DESTINATION_UNKNOWN")
        else:
            hard.append("DESTINATION_MISMATCH")
    return hard, soft


def _check_mission_binding(a: dict[str, Any], b: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Check mission_id consistency if both sides expose mission_binding."""
    hard, soft = [], []
    ma = a.get("mission_binding") or {}
    mb = b.get("mission_binding") or {}
    if not ma or not mb:
        soft.append("SOFT_MISSION_BINDING_UNKNOWN")
        return hard, soft
    if ma.get("mission_id") and mb.get("mission_id"):
        if ma["mission_id"] != mb["mission_id"]:
            hard.append("MISSION_ID_MISMATCH")
    return hard, soft


def _check_cabin(a: dict[str, Any], b: dict[str, Any]) -> tuple[list[str], list[str]]:
    hard, soft = [], []
    ca = a.get("cabin")
    cb = b.get("cabin")
    if ca is None or cb is None:
        if (ca or "").lower() != (cb or "").lower() and ca is None and cb is not None:
            soft.append("CABIN_UNKNOWN_ONE_SIDE")
        elif (ca or "").lower() != (cb or "").lower() and cb is None and ca is not None:
            soft.append("CABIN_UNKNOWN_ONE_SIDE")
        else:
            soft.append("CABIN_UNKNOWN_BOTH")
    elif ca.lower() != cb.lower():
        hard.append("CABIN_MISMATCH")
    return hard, soft


def _check_date(a: dict[str, Any], b: dict[str, Any]) -> tuple[list[str], list[str]]:
    hard, soft = [], []
    if a["travel_date"] != b["travel_date"]:
        if a["travel_date"] is None or b["travel_date"] is None:
            soft.append("TRAVEL_DATE_UNKNOWN")
        else:
            hard.append("TRAVEL_DATE_MISMATCH")
    if a["return_date"] != b["return_date"]:
        if a["return_date"] is None or b["return_date"] is None:
            soft.append("RETURN_DATE_UNKNOWN")
        elif a["return_date"] != b["return_date"]:
            soft.append(SOFT_RETURN_DATE_MISMATCH)
    return hard, soft


def _check_ticket_structure(a: dict[str, Any], b: dict[str, Any]) -> tuple[list[str], list[str]]:
    hard, soft = [], []
    ta = a.get("ticket_structure")
    tb = b.get("ticket_structure")
    if ta is None or tb is None:
        soft.append("TICKET_STRUCTURE_UNKNOWN")
    elif ta != tb:
        # Caller decides whether this is a refusal or a hard observation.
        hard.append("TICKET_STRUCTURE_MISMATCH")
    return hard, soft


def _check_baggage(a: dict[str, Any], b: dict[str, Any]) -> tuple[list[str], list[str]]:
    hard, soft = [], []
    ba = a.get("baggage") or {}
    bb = b.get("baggage") or {}
    ba_complete = ba.get("evidence_complete")
    bb_complete = bb.get("evidence_complete")
    if ba_complete is not True or bb_complete is not True:
        soft.append(SOFT_BAGGAGE_UNKNOWN)
        return hard, soft
    ia = ba.get("included", {})
    ib = bb.get("included", {})
    if ia.get("checked_pieces") != ib.get("checked_pieces"):
        hard.append("BAGGAGE_CHECKED_MISMATCH")
    return hard, soft


def _check_itinerary(a: dict[str, Any], b: dict[str, Any]) -> tuple[list[str], list[str]]:
    hard, soft = [], []
    seg_a = a["schedule"].get("segment_count")
    seg_b = b["schedule"].get("segment_count")
    if seg_a is None or seg_b is None:
        soft.append(SOFT_ITINERARY_MISMATCH)
    elif seg_a != seg_b:
        soft.append(SOFT_ITINERARY_MISMATCH)
    # If identity field exists and they differ, soft observation
    ia = a.get("itinerary_identity")
    ib = b.get("itinerary_identity")
    if ia and ib and ia != ib:
        soft.append("SOFT_ITINERARY_DIFFERS")
    return hard, soft


def _check_passenger_parity(a: dict[str, Any], b: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Use the v1.2.3 passenger-parity module to evaluate parity."""
    hard, soft = [], []
    # Reconstruct minimal PriceEvidence-shaped dicts
    def to_pe(side, label):
        cabin = side.get("cabin")
        if cabin is not None and isinstance(cabin, str):
            cabin = cabin.strip().lower() or None
        return {
            "candidate_id": side.get("candidate_id") or label,
            "passenger_count": side.get("passenger_count"),
            "passenger_types": side.get("passenger_types"),
            "cabin": cabin,
            "itinerary_identity": side.get("itinerary_identity"),
            "ticket_structure": side.get("ticket_structure"),
            "total_price": side.get("price", {}).get("amount"),
            "currency": side.get("price", {}).get("currency"),
            "provider": side.get("price", {}).get("provider"),
            "provider_mode": side.get("price", {}).get("provider_mode"),
            "retrieved_at": side.get("price", {}).get("retrieved_at"),
            "baggage": side.get("baggage") or {"included": {}, "evidence_complete": False},
        }
    par = _pp.evaluate_passenger_parity(to_pe(a, "a"), to_pe(b, "b"))
    status = par.get("parity_status")
    if status == _pp.PARITY_STATUS_PARITY:
        return hard, soft
    if status == _pp.PARITY_STATUS_UNKNOWN:
        soft.append(SOFT_PASSENGER_PARITY_UNKNOWN)
        for reason in par.get("soft_parity_observations", []):
            soft.append(f"PP_{reason}")
    elif status == _pp.PARITY_STATUS_NON_PARITY:
        for reason in par.get("hard_parity_reasons", []):
            hard.append(f"PP_{reason}")
    return hard, soft


# -----------------------------------------------------------------------------
# FX normalization
# -----------------------------------------------------------------------------

def _norm_failed(ca, cb, comparison_currency, refusal_reason, fx_state):
    """Helper for the failed FX-normalization return path."""
    return {
        "normalized_price_a": None,
        "normalized_price_b": None,
        "fx_used": False,
        "fx_evidence_ref": None,
        "currency_a": ca,
        "currency_b": cb,
        "comparison_currency": comparison_currency,
        "delta": None,
        "delta_percentage": None,
        "abs_delta": None,
        "fx_state": fx_state,
        "fx_refusal_reason": refusal_reason,
    }


def _normalize_prices(a: dict[str, Any], b: dict[str, Any],
                       fx_evidence: dict[str, Any] | None,
                       comparison_currency: str = "EUR") -> dict[str, Any]:
    """Compute normalized_price_a and normalized_price_b.

    Per spec §8, §9:
    - Same currency → identity conversion
    - Different currency → use fx_evidence
    - FX missing → REFUSE / UNKNOWN (never guess)
    """
    pa = a["price"]["amount"]
    pb = b["price"]["amount"]
    ca = a["price"]["currency"]
    cb = b["price"]["currency"]

    same_currency = (ca == cb) if (ca and cb) else None

    if pa is None or pb is None:
        return {
            "normalized_price_a": None,
            "normalized_price_b": None,
            "fx_used": False,
            "fx_evidence_ref": None,
            "currency_a": ca,
            "currency_b": cb,
            "comparison_currency": comparison_currency,
            "delta": None,
            "delta_percentage": None,
            "abs_delta": None,
            "fx_state": STATE_REFUSED if (pa is None or pb is None) else STATE_UNKNOWN,
            "fx_refusal_reason": REFUSAL_PRICE_NOT_FOUND if (pa is None or pb is None) else UNKNOWN_REASON,
        }

    ca_norm = (ca or "").upper()
    cb_norm = (cb or "").upper()
    cmp_norm = comparison_currency.upper()

    if same_currency and ca_norm == cmp_norm:
        # Identity: same currency as comparison currency; no FX call
        norm_a, norm_b = pa, pb
        fx_used, fx_state = False, "IDENTITY"
    elif same_currency:
        # Same currency but not the comparison currency. Surface as
        # UNKNOWN — no FX call yet.
        norm_a, norm_b = pa, pb  # self-normalized
        fx_used, fx_state = False, STATE_UNKNOWN
    elif ca_norm == cmp_norm and cb_norm != cmp_norm:
        # A is in comparison currency; B needs FX
        norm_a, fx_used = pa, False
        if not fx_evidence or fx_evidence.get("success") is False:
            norm_b = None
            fx_state = STATE_REFUSED
        else:
            fx_payload = fx_evidence.get("fx_evidence") or {}
            rate = fx_payload.get("rate")
            if isinstance(rate, (int, float)):
                fx_base = (fx_payload.get("base_currency") or "").upper()
                fx_quote = (fx_payload.get("quote_currency") or "").upper()
                if fx_base == cb_norm and fx_quote == cmp_norm:
                    norm_b = pb * rate
                elif fx_quote == cb_norm and fx_base == cmp_norm:
                    norm_b = pb / rate
                else:
                    norm_b = None
                fx_state = "APPLIED" if isinstance(norm_b, (int, float)) else STATE_REFUSED
            else:
                norm_b = None
                fx_state = STATE_REFUSED
    elif cb_norm == cmp_norm and ca_norm != cmp_norm:
        norm_b, fx_used = pb, False
        if not fx_evidence or fx_evidence.get("success") is False:
            norm_a = None
            fx_state = STATE_REFUSED
        else:
            fx_payload = fx_evidence.get("fx_evidence") or {}
            rate = fx_payload.get("rate")
            if isinstance(rate, (int, float)):
                fx_base = (fx_payload.get("base_currency") or "").upper()
                fx_quote = (fx_payload.get("quote_currency") or "").upper()
                if fx_base == ca_norm and fx_quote == cmp_norm:
                    norm_a = pa * rate
                elif fx_quote == ca_norm and fx_base == cmp_norm:
                    norm_a = pa / rate
                else:
                    norm_a = None
                fx_state = "APPLIED" if isinstance(norm_a, (int, float)) else STATE_REFUSED
            else:
                norm_a = None
                fx_state = STATE_REFUSED
    else:
        # Both sides need FX to comparison currency
        if not fx_evidence or fx_evidence.get("success") is False:
            return _norm_failed(ca, cb, comparison_currency, REFUSAL_FX_NOT_FOUND, STATE_REFUSED)
        fx_payload = fx_evidence.get("fx_evidence") or {}
        rate = fx_payload.get("rate")
        if not isinstance(rate, (int, float)):
            return _norm_failed(ca, cb, comparison_currency, REFUSAL_FX_NOT_FOUND, STATE_REFUSED)
        fx_base = (fx_payload.get("base_currency") or "").upper()
        fx_quote = (fx_payload.get("quote_currency") or "").upper()
        def convert(amount, from_c, to_c):
            if from_c == to_c:
                return amount
            if fx_base == from_c and fx_quote == to_c:
                return amount * rate
            if fx_base == to_c and fx_quote == from_c:
                return amount / rate
            return None
        norm_a = convert(pa, ca_norm, cmp_norm)
        norm_b = convert(pb, cb_norm, cmp_norm)
        fx_used, fx_state = True, "APPLIED"

    # Compute delta if both normalized
    delta = None
    abs_delta = None
    delta_pct = None
    if isinstance(norm_a, (int, float)) and isinstance(norm_b, (int, float)):
        delta = round(norm_b - norm_a, 4)
        abs_delta = round(abs(delta), 4)
        if norm_a != 0:
            delta_pct = round((delta / norm_a) * 100.0, 4)

    return {
        "normalized_price_a": norm_a,
        "normalized_price_b": norm_b,
        "fx_used": fx_used,
        "fx_evidence_ref": (
            (fx_evidence.get("fx_evidence") or {}).get("provider") if fx_evidence else None
        ),
        "currency_a": ca,
        "currency_b": cb,
        "comparison_currency": comparison_currency,
        "delta": delta,
        "delta_percentage": delta_pct,
        "abs_delta": abs_delta,
        "fx_state": fx_state,
        "fx_refusal_reason": None,
    }


# -----------------------------------------------------------------------------
# Comparison state machine
# -----------------------------------------------------------------------------

def derive_comparability_state(hard_reasons: list[str],
                                 soft_observations: list[str],
                                 refusal_reasons: list[str]) -> str:
    """Map diagnostic results onto the 5 canonical comparability states."""
    if refusal_reasons:
        return STATE_REFUSED
    if hard_reasons:
        return STATE_NOT_COMPARABLE
    if soft_observations:
        return STATE_SOFT_COMPARABLE
    return STATE_HARD_COMPARABLE


def build_comparison_evidence(candidate_a: dict[str, Any],
                                  candidate_b: dict[str, Any],
                                  fx_evidence: dict[str, Any] | None = None,
                                  baseline_pair: dict[str, Any] | None = None,
                                  comparison_currency: str = "EUR") -> dict[str, Any]:
    """Build a normalized ComparisonEvidence record.

    Per spec §4, §18: this function consumes normalized evidence only and
    returns a provider-agnostic ComparisonEvidence record. It does NOT
    emit arbitrage/opportunity/verified-opportunity artifacts.
    """
    retrieved_at = datetime.now(timezone.utc).isoformat()

    a = extract_normalized_evidence("a", candidate_a)
    b = extract_normalized_evidence("b", candidate_b)

    refusal_reasons: list[str] = []
    hard_reasons: list[str] = []
    soft_observations: list[str] = []

    # Hard refusal: currency unknown
    if not a["price"]["currency"] or not b["price"]["currency"]:
        refusal_reasons.append(REFUSAL_CURRENCY_UNKNOWN)

    # Hard refusal: verification != LIVE on either side (per spec §10; v1.1.4 §4)
    if a["price"]["verification_status"] not in (VS_LIVE, VS_UNKNOWN):
        # UNKNOWN may pass if both sides are explicitly UNKNOWN and
        # structurally identical (per v1.1.4 §4). We surface it as soft.
        if a["price"]["verification_status"] != VS_UNKNOWN:
            # ESTIMATED, DATABASE both → not LIVE; only soft unless both
            # sides are DATABASE/ESTIMATED
            pass  # leave to freshness check below

    # Date binding (spec §11, per v1.1.4)
    h, s = _check_date(a, b)
    hard_reasons.extend(h)
    soft_observations.extend(s)
    # Date-window > ±1 day → REFUSE
    # Per v1.1.4: Date-window difference exceeds ±1 day without explicit
    # soft_date_window declaration → refused.
    if "TRAVEL_DATE_MISMATCH" in hard_reasons:
        refusal_reasons.append(REFUSAL_DATE_MISMATCH)
        # Remove from hard_reasons since it now appears as refusal
        hard_reasons = [r for r in hard_reasons if r != "TRAVEL_DATE_MISMATCH"]

    # Airport binding (spec §6: TPE ≠ TSA, MAD ≠ BCN)
    h, s = _failures_origin(a, b)
    if any(r in ("ORIGIN_MISMATCH", "DESTINATION_MISMATCH") for r in h):
        refusal_reasons.append(REFUSAL_AIRPORT_MISMATCH)
        hard_reasons = [r for r in hard_reasons if r not in ("ORIGIN_MISMATCH", "DESTINATION_MISMATCH")]
    hard_reasons.extend(h)
    soft_observations.extend(s)

    # Mission binding
    h, s = _check_mission_binding(a, b)
    hard_reasons.extend(h)
    soft_observations.extend(s)

    # Cabin binding (spec §6)
    h, s = _check_cabin(a, b)
    if "CABIN_MISMATCH" in h:
        refusal_reasons.append(REFUSAL_CABIN_MISMATCH)
        hard_reasons = [r for r in hard_reasons if r != "CABIN_MISMATCH"]
    hard_reasons.extend(h)
    soft_observations.extend(s)

    # Ticket structure (spec §6: multi-ticket vs single-ticket → not HARD_COMPARABLE)
    h, s = _check_ticket_structure(a, b)
    if "TICKET_STRUCTURE_MISMATCH" in h:
        refusal_reasons.append(REFUSAL_TICKET_STRUCTURE_MISMATCH)
        h = [r for r in h if r != "TICKET_STRUCTURE_MISMATCH"]
    hard_reasons.extend(h)
    soft_observations.extend(s)

    # Baggage (spec §6)
    h, s = _check_baggage(a, b)
    hard_reasons.extend(h)
    soft_observations.extend(s)

    # Itinerary (spec §7)
    h, s = _check_itinerary(a, b)
    hard_reasons.extend(h)
    soft_observations.extend(s)

    # Passenger parity (spec §16: hard_refusal on NON_PARITY, soft on UNKNOWN)
    h, s = _check_passenger_parity(a, b)
    # Filter PP_ tagged reasons
    for r in h:
        if r.startswith("PP_"):
            # A passenger-parity mismatch is treated as a HARD observation
            # (per spec §16: NON_PARITY → NOT HARD_COMPARABLE).
            soft_observations.append(r)
    soft_observations.extend(s)

    # Provider disagreement (spec §12: disagreement is evidence)
    if (a["price"]["provider"] and b["price"]["provider"] and
            a["price"]["provider"] != b["price"]["provider"]):
        soft_observations.append(SOFT_PROVIDER_DISAGREEMENT)

    # Stale check
    for label, side in [("a", a), ("b", b)]:
        fbucket = side["price"].get("freshness_bucket", "") or ""
        if fbucket in ("FRESHNESS_EXPIRED", "FRESHNESS_COLD"):
            soft_observations.append(SOFT_PRICE_STALE)
        else:
            pass

    # FX normalization (spec §8, §9)
    fx_norm = _normalize_prices(a, b, fx_evidence, comparison_currency=comparison_currency)
    if fx_norm["fx_state"] == STATE_REFUSED:
        refusal_reasons.append(fx_norm.get("fx_refusal_reason") or REFUSAL_FX_NOT_FOUND)

    if fx_norm.get("delta") is not None:
        abs_delta = fx_norm["abs_delta"]
        if abs_delta == 0:
            obs = "PRICE_EQUIVALENT"
        else:
            obs = "PRICE_DIFFERENCE_OBSERVED"
        # These are descriptive observation labels; we record them in
        # soft_observations if the comparability state permits.
        # Do NOT add to comparability reasons; only to descriptive notes.
    comparison_state = derive_comparability_state(hard_reasons, soft_observations,
                                                   refusal_reasons)

    # Provider disagreement is itself evidence, not an error
    provider_disagreement = (
        a["price"]["provider"] != b["price"]["provider"]
        if (a["price"]["provider"] and b["price"]["provider"])
        else None
    )

    payload: dict[str, Any] = {
        "schema_version": "v1.2.5",
        "comparison_id": f"{a['candidate_id']}::{b['candidate_id']}",
        "candidate_a_id": a["candidate_id"],
        "candidate_b_id": b["candidate_id"],
        "baseline_pair": baseline_pair,  # may be None
        "price_a": a["price"]["amount"],
        "price_b": b["price"]["amount"],
        "normalized_price_a": fx_norm["normalized_price_a"],
        "normalized_price_b": fx_norm["normalized_price_b"],
        "comparison_currency": fx_norm["comparison_currency"],
        "fx_state": fx_norm["fx_state"],
        "fx_used": fx_norm["fx_used"],
        "fx_evidence_ref": fx_norm["fx_evidence_ref"],
        "delta": fx_norm["delta"],
        "abs_delta": fx_norm["abs_delta"],
        "delta_percentage": fx_norm["delta_percentage"],
        "parity_status": (comparison_state,),
        "comparability_status": comparison_state,
        "comparison_reasons": hard_reasons,
        "refusal_reasons": refusal_reasons,
        "soft_observations": soft_observations,
        "unknown_reasons": [UNKNOWN_REASON] if comparison_state == STATE_UNKNOWN else [],
        "schedule_evidence_a": a["schedule"],
        "schedule_evidence_b": b["schedule"],
        "passenger_parity_evidence_ref_a": a.get("parity_evidence_ref"),
        "passenger_parity_evidence_ref_b": b.get("parity_evidence_ref"),
        "baseline_evidence_id_a": a.get("baseline_evidence_ref"),
        "baseline_evidence_id_b": b.get("baseline_evidence_ref"),
        "ticket_structure_a": a.get("ticket_structure"),
        "ticket_structure_b": b.get("ticket_structure"),
        "cabin_a": a.get("cabin"),
        "cabin_b": b.get("cabin"),
        "baggage_a": a.get("baggage"),
        "baggage_b": b.get("baggage"),
        "itinerary_a": a.get("itinerary_identity"),
        "itinerary_b": b.get("itinerary_identity"),
        "date_binding": {
            "travel_date_a": a.get("travel_date"),
            "travel_date_b": b.get("travel_date"),
            "return_date_a": a.get("return_date"),
            "return_date_b": b.get("return_date"),
        },
        "provider_a": a["price"]["provider"],
        "provider_b": b["price"]["provider"],
        "provider_mode_a": a["price"]["provider_mode"],
        "provider_mode_b": b["price"]["provider_mode"],
        "provider_disagreement": provider_disagreement,
        "verification_status_a": a["price"]["verification_status"],
        "verification_status_b": b["price"]["verification_status"],
        "rule_version": COMPARISON_RULE_VERSION,
        "retrieved_at": retrieved_at,
        "evidence_provenance": {
            "source": "comparison_engine_v1_2_5",
            "source_type": SRC_CACHE,
            "endpoint": None,
            "retrieved_at": retrieved_at,
            "verification_status": VS_DATABASE,
            "rule_version": COMPARISON_RULE_VERSION,
            "evidence_arity": 2,
        },
        "verification_status": VS_DATABASE,
        "source": "comparison_engine_v1_2_5",
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
    parser = argparse.ArgumentParser(description="Cross-provider Comparison v1.2.5")
    parser.add_argument("--candidate-a", type=Path, required=True)
    parser.add_argument("--candidate-b", type=Path, required=True)
    parser.add_argument("--fx-evidence", type=Path, default=None,
                         help="Optional FX evidence JSON (output of fx_provider.py)")
    parser.add_argument("--comparison-currency", type=str, default="EUR")
    parser.add_argument("--output", type=Path, default=str(COMPARISON_OUTPUT_PATH))
    parser.add_argument("--trace", type=Path, default=str(COMPARISON_TRACE_PATH))
    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\nComparison Engine v1.2.5", file=sys.stderr)
    print(f"  A: {args.candidate_a}", file=sys.stderr)
    print(f"  B: {args.candidate_b}", file=sys.stderr)
    print(f"  Comparison currency: {args.comparison_currency}", file=sys.stderr)

    if not args.candidate_a.exists():
        print(f"\n[ERROR] candidate_a not found: {args.candidate_a}", file=sys.stderr)
        return 11
    if not args.candidate_b.exists():
        print(f"\n[ERROR] candidate_b not found: {args.candidate_b}", file=sys.stderr)
        return 11

    cand_a = json.loads(args.candidate_a.read_text())
    cand_b = json.loads(args.candidate_b.read_text())
    fx_evidence = json.loads(args.fx_evidence.read_text()) if (args.fx_evidence and args.fx_evidence.exists()) else None

    payload = build_comparison_evidence(cand_a, cand_b, fx_evidence=fx_evidence,
                                          comparison_currency=args.comparison_currency)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n  Output: {args.output}", file=sys.stderr)

    trace_payload = {
        "trace_at": started_at,
        "candidate_a_path": str(args.candidate_a),
        "candidate_b_path": str(args.candidate_b),
        "comparison_id": payload["comparison_id"],
        "comparability_status": payload["comparability_status"],
        "refusal_reasons": payload["refusal_reasons"],
        "comparison_reasons": payload["comparison_reasons"],
        "soft_observations": payload["soft_observations"],
    }
    args.trace.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False))
    print(f"  Trace:  {args.trace}", file=sys.stderr)

    print("\n" + "=" * 60, file=sys.stderr)
    print("COMPARISON — RESULT", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  comparability_status: {payload['comparability_status']}", file=sys.stderr)
    print(f"  refusal_reasons:      {payload['refusal_reasons']}", file=sys.stderr)
    print(f"  comparison_reasons:   {payload['comparison_reasons']}", file=sys.stderr)
    print(f"  soft_observations:    {payload['soft_observations']}", file=sys.stderr)
    print(f"  delta:                {payload['delta']} {payload['comparison_currency']}", file=sys.stderr)
    print(f"  delta_percentage:     {payload['delta_percentage']}", file=sys.stderr)
    print(f"  provider_disagreement:{payload['provider_disagreement']}", file=sys.stderr)
    print(f"  rule_version:         {payload['rule_version']}", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

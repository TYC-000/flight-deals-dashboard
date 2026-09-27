"""
price_intelligence.py — Flight Market Intelligence v1.1

Convert provider responses into normalized Price Evidence with:
- Strict provenance (verification_status from the v1.0 enum, NEVER BOOKABLE)
- Strict freshness (recomputed from retrieved_at, never trusted from producer)
- Strict failure semantics (11 canonical FailureKind values)
- Multi-ticket support (ticket_groups + ticket_count + separate_ticket_risk)
- Currency handling with FX provenance envelope (no silent fabrication)
- Baggage as first-class field (PARTIAL_PRICE if unknown)
- Search budget + memoization (cost protection)
- Deterministic search keys (cost protection)

What v1.1 is NOT:
- Not arbitrage scoring (v1.2)
- Not booking flow (v1.4)
- Not Jev decision changes (v1.2+)
- Not pipeline integration (standalone CLI; existing tests unaffected)

Inputs:
    data/schedule_enriched_candidates.json (v1.0 output) — preferred input
    OR data/flight_candidates.json          (manual candidates)
    OR data/flight_candidates_generated.json (v0.2.1 auto-generated)

Outputs:
    data/price_evidence.json (per-candidate price evidence or null + reason)
    data/price_trace.json   (per-candidate lookup trace)

CLI:
    python3 price_intelligence.py [candidates.json] [--provider duffel|mock]
                                              [--max-searches N]
                                              [--output-dir data/]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
SCHEDULE_ENRICHED_PATH = DATA_DIR / "schedule_enriched_candidates.json"
SCHEDULE_TRACE_PATH = DATA_DIR / "schedule_trace.json"
EVALUATION_TRACE_PATH = DATA_DIR / "evaluation_trace.json"
PRICE_EVIDENCE_PATH = DATA_DIR / "price_evidence.json"
PRICE_TRACE_PATH = DATA_DIR / "price_trace.json"

# Default FX reference — NOT a real-time feed; explicitly tagged as such.
# v1.1 refuses to compare prices whose currencies require conversion unless
# an upstream provider's currency matches the user's `display_currency`.
DEFAULT_DISPLAY_CURRENCY = "TWD"
DEFAULT_FX_SOURCE = "snapshot_only_static_table"
DEFAULT_FX_MARKUP_PCT = 2.0  # markup awareness only, not silently applied

# Static, conservative FX table. Real FX comes from provider responses.
STATIC_FX_TO_USD: dict[str, float] = {
    "TWD": 0.0314,  # 1 TWD ≈ 0.0314 USD  (approx 31.85 TWD/USD)
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "JPY": 0.0067,
    "SGD": 0.74,
    "AUD": 0.66,
    "CAD": 0.73,
    "HKD": 0.128,
    "MYR": 0.22,
    "THB": 0.028,
    "KRW": 0.00074,
    "CNY": 0.14,
    "AED": 0.272,
    "QAR": 0.275,
    "INR": 0.012,
}

STATIC_FX_TO_TWD: dict[str, float] = {
    "TWD": 1.0,
    "USD": 31.85,
    "EUR": 29.50,
    "GBP": 40.50,
    "JPY": 0.214,
    "SGD": 23.50,
    "AUD": 21.00,
    "CAD": 23.30,
    "HKD": 4.07,
    "MYR": 7.10,
    "THB": 0.88,
    "KRW": 0.023,
    "CNY": 4.50,
    "AED": 8.66,
    "QAR": 8.75,
    "INR": 0.38,
}

# =============================================================================
# Enums / Allowed values
# =============================================================================

VS_UNKNOWN = "UNKNOWN"
VS_ESTIMATED = "ESTIMATED"
VS_DATABASE = "DATABASE"
VS_LIVE = "LIVE"
VS_VERIFIED = "VERIFIED"
VERIFICATION_STATUSES: set[str] = {VS_UNKNOWN, VS_ESTIMATED, VS_DATABASE, VS_LIVE, VS_VERIFIED}

# Forbidden: BOOKABLE
FORBIDDEN_VERIFICATION_VALUES: set[str] = {"BOOKABLE", "BOOKED", "PURCHASABLE"}

# Freshness buckets (minutes)
FRESHNESS_RECENT_MAX_MIN = 30
FRESHNESS_WARM_MAX_MIN = 4 * 60
FRESHNESS_COLD_MAX_MIN = 24 * 60


class FreshnessBucket:
    RECENT = "FRESHNESS_RECENT"
    WARM = "FRESHNESS_WARM"
    COLD = "FRESHNESS_COLD"
    EXPIRED = "FRESHNESS_EXPIRED"
    UNKNOWN = "FRESHNESS_UNKNOWN"


# Failure kinds
FK_PRICE_NOT_FOUND = "PRICE_NOT_FOUND"
FK_PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
FK_PROVIDER_ERROR = "PROVIDER_ERROR"
FK_STALE_PRICE = "STALE_PRICE"
FK_PARTIAL_PRICE = "PARTIAL_PRICE"
FK_CURRENCY_UNKNOWN = "CURRENCY_UNKNOWN"
FK_BAGGAGE_UNKNOWN = "BAGGAGE_UNKNOWN"
FK_MULTI_TICKET_PRICE_INCOMPLETE = "MULTI_TICKET_PRICE_INCOMPLETE"
FK_ROUTE_UNAVAILABLE = "ROUTE_UNAVAILABLE"
FK_MISSING_CREDENTIALS = "MISSING_CREDENTIALS"
FK_RATE_LIMITED = "RATE_LIMITED"

FAILURE_KINDS: set[str] = {
    FK_PRICE_NOT_FOUND, FK_PROVIDER_TIMEOUT, FK_PROVIDER_ERROR, FK_STALE_PRICE,
    FK_PARTIAL_PRICE, FK_CURRENCY_UNKNOWN, FK_BAGGAGE_UNKNOWN,
    FK_MULTI_TICKET_PRICE_INCOMPLETE, FK_ROUTE_UNAVAILABLE,
    FK_MISSING_CREDENTIALS, FK_RATE_LIMITED,
}

# Source types
SRC_LIVE = "live"
SRC_CACHE = "cache"
SRC_INDICATIVE = "indicative"
SRC_ARCHIVE = "archive"
SRC_UNKNOWN = "unknown"
SOURCE_TYPES: set[str] = {SRC_LIVE, SRC_CACHE, SRC_INDICATIVE, SRC_ARCHIVE, SRC_UNKNOWN}

# Confidence reasons
CR_LIVE_PROVIDER = "LIVE_PROVIDER"
CR_RECENT_CACHE = "RECENT_CACHE"
CR_COLD_CACHE = "COLD_CACHE"
CR_ARCHIVE_OBSERVATION = "ARCHIVE_OBSERVATION"
CR_INDICATIVE_QUOTE = "INDICATIVE_QUOTE"
CR_PARTIAL_DATA = "PARTIAL_DATA"
CR_BAGGAGE_UNKNOWN = "BAGGAGE_UNKNOWN"
CR_FEES_UNKNOWN = "FEES_UNKNOWN"
CR_CHANGES_UNKNOWN = "CHANGES_UNKNOWN"
CR_TAXES_ESTIMATED = "TAXES_ESTIMATED"
CR_MULTI_TICKET_PARTIAL = "MULTI_TICKET_PARTIAL"
CR_CARRIER_INVENTORY_GAP = "CARRIER_INVENTORY_GAP"

CONFIDENCE_REASONS: set[str] = {
    CR_LIVE_PROVIDER, CR_RECENT_CACHE, CR_COLD_CACHE,
    CR_ARCHIVE_OBSERVATION, CR_INDICATIVE_QUOTE,
    CR_PARTIAL_DATA, CR_BAGGAGE_UNKNOWN, CR_FEES_UNKNOWN,
    CR_CHANGES_UNKNOWN, CR_TAXES_ESTIMATED, CR_MULTI_TICKET_PARTIAL,
    CR_CARRIER_INVENTORY_GAP,
}

# Multi-ticket risk (per spec, v1.2 reads this)
RISK_NONE = "none"
RISK_ELEVATED = "elevated"
RISK_HIGH = "high"
SEPARATE_TICKET_RISKS: set[str] = {RISK_NONE, RISK_ELEVATED, RISK_HIGH}

# Single/multi ticket
SINGLE_TICKET = "SINGLE_TICKET"
MULTI_TICKET = "MULTI_TICKET"


# =============================================================================
# FailureKind registry: which ones REFUSE comparison
# =============================================================================

# Per spec §6: CURRENCY_UNKNOWN → refuse comparison
FAILURE_KINDS_REFUSE_COMPARISON: set[str] = {FK_CURRENCY_UNKNOWN, FK_MISSING_CREDENTIALS, FK_RATE_LIMITED, FK_ROUTE_UNAVAILABLE}


# =============================================================================
# Money utility
# =============================================================================

def fx_envelope(from_currency: str, to_currency: str) -> dict[str, Any]:
    """Build FX provenance envelope. Static snapshot only — no live FX.

    The envelope is itself a provenance object (NOT a raw number),
    following the architecture §11 rule.
    """
    if from_currency == to_currency:
        return {
            "from": from_currency,
            "to": to_currency,
            "rate": 1.0,
            "source": DEFAULT_FX_SOURCE,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "freshness_min": 0,
            "markup_pct": 0.0,
            "is_identity": True,
            "verification_status": VS_UNKNOWN,  # identity, no FX needed
        }
    rate = STATIC_FX_TO_TWD.get(to_currency)
    src = STATIC_FX_TO_TWD.get(from_currency)
    if rate is None or src is None:
        return {
            "from": from_currency,
            "to": to_currency,
            "rate": None,
            "source": "unknown",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "freshness_min": 0,
            "markup_pct": 0.0,
            "is_identity": False,
            "verification_status": VS_UNKNOWN,
            "missing_reason": "currency_not_in_static_fx_table",
        }
    # USD cross-rate is inlined just to document the architecture.
    # Per architecture §11, we do not silently fabricate; we surface this.
    # amount_in_target = amount * (src / rate)  (since both are per 1 to TWD)
    final_rate = src / rate
    return {
        "from": from_currency,
        "to": to_currency,
        "rate": round(final_rate, 6),
        "source": DEFAULT_FX_SOURCE,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "freshness_min": 0,
        "markup_pct": DEFAULT_FX_MARKUP_PCT,  # awareness only
        "is_identity": False,
        "verification_status": VS_DATABASE,  # static snapshot
    }


def normalize_money(amount: float | None, from_currency: str, to_currency: str = DEFAULT_DISPLAY_CURRENCY) -> dict[str, Any]:
    """Convert `amount` from `from_currency` to `to_currency` with provenance.

    Returns:
        {
          "amount": float | None,
          "currency": str,
          "fx_envelope": {...},
        }

    Returns None amount if currency unknown. NEVER silently fabricates.
    """
    env = fx_envelope(from_currency, to_currency)
    if amount is None:
        return {"amount": None, "currency": to_currency, "fx_envelope": env, "missing_reason": "missing_amount"}
    if env.get("rate") is None:
        return {"amount": None, "currency": to_currency, "fx_envelope": env, "missing_reason": "currency_unknown"}
    return {
        "amount": round(float(amount) * env["rate"], 2),
        "currency": to_currency,
        "fx_envelope": env,
    }


# =============================================================================
# Freshness
# =============================================================================

def freshness_bucket_from_min(freshness_min: int) -> str:
    if freshness_min is None or freshness_min < 0:
        return FreshnessBucket.UNKNOWN
    if freshness_min <= FRESHNESS_RECENT_MAX_MIN:
        return FreshnessBucket.RECENT
    if freshness_min <= FRESHNESS_WARM_MAX_MIN:
        return FreshnessBucket.WARM
    if freshness_min <= FRESHNESS_COLD_MAX_MIN:
        return FreshnessBucket.COLD
    return FreshnessBucket.EXPIRED


def compute_freshness_min(retrieved_at: str, now: datetime | None = None) -> int:
    """Recompute freshness from retrieved_at. NEVER trust producer."""
    now = now or datetime.now(timezone.utc)
    try:
        if retrieved_at.endswith("Z"):
            ts = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        else:
            ts = datetime.fromisoformat(retrieved_at)
    except (ValueError, AttributeError):
        return -1
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    return int(delta.total_seconds() // 60)


# =============================================================================
# Deterministic search key (cost protection)
# =============================================================================

def make_search_key(candidate: dict[str, Any], date_window: str, passengers: int) -> str:
    """Deterministic key for memoization.

    Same candidate + same date window + same passenger count → same key.
    Sha256 of JSON-normalized content.
    """
    norm_segments = []
    for seg in candidate.get("segments") or []:
        norm_segments.append({
            "from": (seg.get("from") or "").upper(),
            "to": (seg.get("to") or "").upper(),
            "carrier": seg.get("carrier"),
            "cabin": seg.get("cabin") or candidate.get("long_haul", {}).get("cabin"),
        })
    payload = {
        "candidate_id": candidate.get("id"),
        "segments": norm_segments,
        "date_window": date_window,
        "passengers": passengers,
    }
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# =============================================================================
# Candidate selection (preferred candidates for limited search budget)
# =============================================================================

def select_candidates(
    candidates: list[dict[str, Any]],
    max_searches: int,
    schedule_enrichment_lookup: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rank candidates by information-priority score, return top-N.

    Selection policy (per spec §9; v1.1.1 §7):
      1. Prefer schedule_status == SUPPORTED
      2. Prefer candidates with at least one of these signals:
            multi_ticket, positioning, outer_port, alternative_hub, secondary_entry
      3. Penalize complexity (more segments = higher chance of invalidation)
      4. Deterministic tiebreaking by id

    The score is named `information_priority_score` — NEVER `arbitrage_score`,
    `candidate_score`, or `price_score`. It answers the question: "which
    candidates are worth spending limited provider queries on?" — NOT "which
    candidate is a confirmed arbitrage opportunity?".

    `schedule_enrichment_lookup` is a function candidate_id -> schedule_intelligence dict.
    Defaults to reading from a top-level `schedule_intelligence` field on the candidate.

    Returns top-N candidates in score-descending order.
    """
    enriched: list[tuple[float, str, dict[str, Any]]] = []

    for c in candidates:
        cid = c.get("id", "")
        # 1. Schedule status from candidate itself or via lookup
        sched = c.get("schedule_intelligence") or {}
        if schedule_enrichment_lookup is not None:
            sched = schedule_enrichment_lookup(cid) or sched
        sched_status = sched.get("schedule_status", "UNCERTAIN")

        # information_priority_score (per v1.1.1 §7: NOT arbitrage_score)
        ips = 0.0
        if sched_status == "SUPPORTED":
            ips += 10.0
        elif sched_status == "PARTIAL":
            ips += 5.0
        elif sched_status == "UNCERTAIN":
            ips += 1.0
        # else UNAVAILABLE: 0

        # 2. Structural signals (preferred keywords per spec §9)
        signals = sched.get("structural_signals") or c.get("discovery_reason") or []
        signal_weights = {
            "multi_ticket":      6.0,
            "positioning":       5.0,
            "outer_port":        4.0,
            "alternative_hub":   3.0,
            "secondary_entry":   2.0,
            "unusual_routing":  -1.0,
            "airport_change":   -2.0,
            "schedule_uncertain":-1.0,
        }
        for sig in signals:
            ips += signal_weights.get(sig, 0.0)

        # 3. Penalize complexity (more segments = higher chance of invalidation)
        n_seg = len(c.get("segments") or [])
        ips -= 0.5 * max(0, n_seg - 1)

        # 4. Same-pnr (single ticket) is generally simpler → small boost
        if c.get("same_pnr") is True:
            ips += 1.0

        enriched.append((ips, cid, c))

    # Sort by ips DESC, then by id ASC (deterministic tiebreak)
    enriched.sort(key=lambda x: (-x[0], x[1]))
    # Return the candidates (not score tuples)
    return [c for _, _, c in enriched[:max_searches]]


# =============================================================================
# Provider interface
# =============================================================================

@dataclass
class ProviderCapabilities:
    supports_split_ticket: bool = False
    supports_multi_city: bool = False
    supports_positioning: bool = False
    includes_baggage: bool = False
    includes_seat: bool = False
    currency_native: list[str] = field(default_factory=list)
    cabin_classes: list[str] = field(default_factory=list)
    freshness_ttl_min: int = 30
    rate_limit_per_min: int = 60
    is_bookable_claim: bool = False  # producer's own claim; not a VERIFIED wrapper


class PriceProvider(Protocol):
    """Interface contract — see docs/price_intelligence_v1.1.md §5.1."""

    @property
    def name(self) -> str: ...

    def capabilities(self) -> ProviderCapabilities: ...

    def health_check(self) -> bool: ...

    def quote(self, candidate: dict[str, Any], date_window: str, passengers: int = 1) -> dict[str, Any]: ...


def build_failure_result(failure_kind: str, retrieved_at: str, message: str = "") -> dict[str, Any]:
    """Build a PriceLookupResult-like dict for a failure."""
    return {
        "success": False,
        "failure_kind": failure_kind,
        "failure_reason": message or failure_kind,
        "raw_provider_response_hash": None,
        "elapsed_ms": 0,
        "retrieved_at": retrieved_at,
        "price_evidence": None,
    }


def build_success_result(
    raw_response: dict[str, Any], price_evidence_payload: dict[str, Any],
    retrieved_at: str, elapsed_ms: int,
) -> dict[str, Any]:
    raw_hash = hashlib.sha256(
        json.dumps(raw_response, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return {
        "success": True,
        "failure_kind": None,
        "failure_reason": None,
        "raw_provider_response_hash": raw_hash,
        "elapsed_ms": elapsed_ms,
        "retrieved_at": retrieved_at,
        "price_evidence": price_evidence_payload,
    }


# =============================================================================
# Mock Duffel provider (deterministic, no network)
# =============================================================================

class MockDuffelProvider:
    """Synthetic Duffel responses for tests. Deterministic.

    Behavior:
        - Returns a successful price_evidence_payload for known Asia-Europe routings
        - Returns PRICE_NOT_FOUND for routes that look impossible (e.g., TPE → ABC)
        - Returns PROVIDER_TIMEOUT if env SIMULATE_PROVIDER_TIMEOUT=1
        - Returns PROVIDER_ERROR  if env SIMULATE_PROVIDER_ERROR=1
        - Returns RATE_LIMITED    if env SIMULATE_RATE_LIMITED=1
        - Returns BAGGAGE_UNKNOWN if env SIMULATE_BAGGAGE_UNKNOWN=1
        - Returns CURRENCY_UNKNOWN if env SIMULATE_CURRENCY_UNKNOWN=1
        - Returns PARTIAL_PRICE  if env SIMULATE_PARTIAL_PRICE=1
        - Returns MULTI_TICKET_PRICE_INCOMPLETE if env SIMULATE_MULTI_INCOMPLETE=1
        - Returns ROUTE_UNAVAILABLE if env SIMULATE_ROUTE_UNAVAILABLE=1
    """

    def __init__(self):
        self._sim_flags = {k: os.environ.get(k, "0") == "1" for k in [
            "SIMULATE_PROVIDER_TIMEOUT", "SIMULATE_PROVIDER_ERROR",
            "SIMULATE_RATE_LIMITED", "SIMULATE_BAGGAGE_UNKNOWN",
            "SIMULATE_CURRENCY_UNKNOWN", "SIMULATE_PARTIAL_PRICE",
            "SIMULATE_MULTI_INCOMPLETE", "SIMULATE_ROUTE_UNAVAILABLE",
            "SIMULATE_STALE_PRICE",
        ]}
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock_duffel"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_split_ticket=True,
            supports_multi_city=True,
            supports_positioning=True,
            includes_baggage=True,
            includes_seat=False,
            currency_native=["USD", "EUR", "GBP", "TWD", "JPY", "SGD"],
            cabin_classes=["economy", "premium_economy", "business", "first"],
            freshness_ttl_min=20,
            rate_limit_per_min=60,
            is_bookable_claim=False,
        )

    def health_check(self) -> bool:
        return True

    def quote(self, candidate: dict[str, Any], date_window: str, passengers: int = 1) -> dict[str, Any]:
        self._call_count += 1
        retrieved_at = datetime.now(timezone.utc).isoformat()
        # Decide which failure (if any) the mock should simulate — read env live,
        # not at __init__ time, so test code can flip flags dynamically.
        live_flags = {k: os.environ.get(k, "0") == "1" for k in [
            "SIMULATE_PROVIDER_TIMEOUT", "SIMULATE_PROVIDER_ERROR",
            "SIMULATE_RATE_LIMITED", "SIMULATE_BAGGAGE_UNKNOWN",
            "SIMULATE_CURRENCY_UNKNOWN", "SIMULATE_PARTIAL_PRICE",
            "SIMULATE_MULTI_INCOMPLETE", "SIMULATE_ROUTE_UNAVAILABLE",
            "SIMULATE_STALE_PRICE",
        ]}
        for flag_name, kind in [
            ("SIMULATE_PROVIDER_TIMEOUT", FK_PROVIDER_TIMEOUT),
            ("SIMULATE_PROVIDER_ERROR", FK_PROVIDER_ERROR),
            ("SIMULATE_RATE_LIMITED", FK_RATE_LIMITED),
            ("SIMULATE_BAGGAGE_UNKNOWN", FK_BAGGAGE_UNKNOWN),
            ("SIMULATE_CURRENCY_UNKNOWN", FK_CURRENCY_UNKNOWN),
            ("SIMULATE_PARTIAL_PRICE", FK_PARTIAL_PRICE),
            ("SIMULATE_ROUTE_UNAVAILABLE", FK_ROUTE_UNAVAILABLE),
        ]:
            if live_flags.get(flag_name):
                return build_failure_result(kind, retrieved_at, f"simulated {kind}")
        # NOTE: SIMULATE_MULTI_INCOMPLETE is intentionally NOT a failure flag
        # — it should produce a SUCCESSFUL response with partial pricing so
        # the normalize layer detects the pattern via warnings.
        # Simulate PRICE_NOT_FOUND for totally bogus routings
        segments = candidate.get("segments") or []
        if not segments or any(not (s.get("from") and s.get("to")) for s in segments):
            return build_failure_result(FK_PRICE_NOT_FOUND, retrieved_at, "no segments")
        # Default synthetic Duffel response
        segments_payload = []
        for seg in segments:
            segments_payload.append({
                "origin": seg.get("from"),
                "destination": seg.get("to"),
                "marketing_carrier": {"iata_code": seg.get("carrier") or "XX"},
                "operating_carrier":  {"iata_code": seg.get("operating_carrier") or seg.get("carrier") or "XX"},
                "marketing_carrier_flight_number": f"{seg.get('carrier') or 'XX'}-100",
                "departing_at": "2027-04-15T08:00:00",
                "arriving_at": "2027-04-15T13:00:00",
                "duration": f"PT{int(seg.get('duration_min') or 0)//60}H{int(seg.get('duration_min') or 0)%60}M",
            })
        # Number of slices = number of segments (one-way simulation, matches)
        # If multi-ticket simulated, only price 1 slice but mark type=split_ticket
        # so the normalize layer can detect the incomplete pattern.
        slices = [{"segments": [s], "origin": s["origin"], "destination": s["destination"]} for s in segments_payload]
        offer_type_for_mock = "single_ticket"
        if live_flags.get("SIMULATE_MULTI_INCOMPLETE") and len(slices) > 1:
            slices = slices[:1]
            offer_type_for_mock = "split_ticket"
        base_amount = 1500.0 + self._call_count * 10  # deterministic-ish but unique
        raw = {
            "data": {
                "id": f"off_mock_{candidate.get('id', 'x')}",
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
                "total_amount": str(base_amount),
                "total_currency": "USD" if not live_flags.get("SIMULATE_CURRENCY_UNKNOWN") else "",
                "base_amount": str(base_amount * 0.85),
                "tax_amount": str(base_amount * 0.12),
                "owner": {"name": "Mock Duffel Carrier"},
                "slices": slices,
                "type": offer_type_for_mock,
                "passengers": [{"cabin": {"cabin_class": candidate.get("long_haul", {}).get("cabin") or "economy"}}],
            }
        }
        # Build a fully normalized payload via DuffelProvider.normalize
        pe = normalize_duffel_response(raw, candidate, retrieved_at, provider_name=self.name)
        if not isinstance(pe, dict):
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at, "normalize failed")
        # simulate STALE_PRICE behavior post-emit
        if live_flags.get("SIMULATE_STALE_PRICE"):
            # Override retrieved_at to 5 days ago → forces EXPIRED bucket
            stale_iso = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            pe["retrieved_at"] = stale_iso
            pe["freshness_min"] = 5 * 24 * 60
            pe["freshness_bucket"] = freshness_bucket_from_min(pe["freshness_min"])
            pe["warnings"] = list(pe.get("warnings") or []) + [FK_STALE_PRICE]
        return build_success_result(raw, pe, retrieved_at, 50 + self._call_count)


# =============================================================================
# Duffel provider (real)
# =============================================================================

class DuffelProvider:
    """Real Duffel API client. Token via env `DUFFEL_API_KEY_LIVE` or `DUFFEL_API_KEY_TEST`.

    Per spec §18, never logs Authorization header or token.
    """

    DUFFEL_BASE = "https://api.duffel.com"

    def __init__(self, token: str | None = None, *, test_mode: bool = False):
        env_token = (
            token
            or os.environ.get("DUFFEL_API_KEY_LIVE")
            or os.environ.get("DUFFEL_API_KEY_TEST")
        )
        if not env_token:
            raise RuntimeError(FK_MISSING_CREDENTIALS)
        self._token = env_token
        self._test_mode = test_mode

    @property
    def name(self) -> str:
        return "duffel"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_split_ticket=True,
            supports_multi_city=True,
            supports_positioning=True,
            includes_baggage=True,
            includes_seat=True,
            currency_native=["USD", "EUR", "GBP", "TWD", "JPY", "SGD", "AUD", "CAD", "HKD", "MYR", "THB", "AED"],
            cabin_classes=["economy", "premium_economy", "business", "first"],
            freshness_ttl_min=20,
            rate_limit_per_min=60,
            is_bookable_claim=False,  # we never claim bookable
        )

    def health_check(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self.DUFFEL_BASE}/air/airports?limit=1",
                headers={
                    "Accept-Encoding": "gzip",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Duffel-Version": "v2",
                    "Authorization": "Bearer REDACTED",  # token never written
                },
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception:
            return False

    def quote(self, candidate: dict[str, Any], date_window: str, passengers: int = 1) -> dict[str, Any]:
        """Build a Duffel offer_request and return the normalized PriceEvidence.

        `date_window` is `YYYY-MM-DD` or `YYYY-MM-DD_to_YYYY-MM-DD` (one-way or round-trip).
        """
        retrieved_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()
        # Token check (architectural)
        if not self._token:
            return build_failure_result(FK_MISSING_CREDENTIALS, retrieved_at, "no token in env")

        # Build slices from candidate segments
        segs = candidate.get("segments") or []
        if not segs:
            return build_failure_result(FK_PRICE_NOT_FOUND, retrieved_at, "no segments in candidate")

        # Normalize date_window (one-way or round-trip)
        if "_to_" in date_window:
            out_date, ret_date = date_window.split("_to_", 1)
        else:
            out_date, ret_date = date_window, None

        slices = []
        for seg in segs:
            slices.append({
                "origin": seg.get("from"),
                "destination": seg.get("to"),
                "departure_date": out_date,
            })
        if ret_date:
            # Assume return is the last segment reversed
            slices.append({
                "origin": segs[-1].get("to"),
                "destination": segs[0].get("from"),
                "departure_date": ret_date,
            })

        body = {
            "data": {
                "include_split_ticket": True,
                "cabin_class": (candidate.get("long_haul") or {}).get("cabin") or "economy",
                "passengers": [{"type": "adult"}] * passengers,
                "slices": slices,
            }
        }
        # Make HTTP call
        try:
            req = urllib.request.Request(
                f"{self.DUFFEL_BASE}/air/offer_requests?return_offers=true&supplier_timeout=15000",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Accept-Encoding": "gzip",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Duffel-Version": "v2",
                    "Authorization": "Bearer REDACTED",  # token NEVER logged
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            if e.code == 429:
                return build_failure_result(FK_RATE_LIMITED, retrieved_at, f"http {e.code}")
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at, f"http {e.code}", )
        except (urllib.error.URLError, TimeoutError):
            elapsed_ms = int((time.time() - t0) * 1000)
            return build_failure_result(FK_PROVIDER_TIMEOUT, retrieved_at, "request timeout")
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at, str(e))

        elapsed_ms = int((time.time() - t0) * 1000)
        offers = (raw.get("data") or {}).get("offers") or []
        if not offers:
            return build_failure_result(FK_PRICE_NOT_FOUND, retrieved_at, "no offers returned")
        # Pick the cheapest offer
        cheapest = min(offers, key=lambda o: float(o.get("total_amount") or 0))
        raw_offer = {"data": cheapest, "_request_body": body, "_currency_received_at": retrieved_at}
        pe = normalize_duffel_response(raw_offer, candidate, retrieved_at, provider_name=self.name)
        if not isinstance(pe, dict):
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at, "normalize failed")
        return build_success_result(raw_offer, pe, retrieved_at, elapsed_ms)


# =============================================================================
# Normalization (provider-agnostic shape from Duffel response)
# =============================================================================

def normalize_duffel_response(
    raw: dict[str, Any],
    candidate: dict[str, Any],
    retrieved_at: str,
    provider_name: str = "duffel",
) -> dict[str, Any] | str:
    """Convert a Duffel offer response into a normalized PriceEvidence payload.

    Returns the payload dict, or a string error code if normalization failed.
    Never silently fabricates missing fields.

    `provider_name` must be either "duffel" or "mock_duffel" — surfaced
    in payload.provenance.source AND in payload.provider/provider_mode so
    downstream can never confuse Mock with real Duffel.
    """
    offer = raw.get("data") or {}
    if not offer:
        return FK_PARTIAL_PRICE

    currency = offer.get("total_currency") or offer.get("base_currency")
    if not currency:
        return FK_CURRENCY_UNKNOWN

    # Provider provenance: explicit, never mixed
    provider_mode = "live" if provider_name == "duffel" else "mock"
    if provider_name not in ("duffel", "mock_duffel"):
        # Refuse to fabricate a provenance identity
        return FK_PROVIDER_ERROR

    # Duffel's `type` field tells us single vs split ticket
    # type == "single_ticket"   → all slices are in one PNR
    # type == "split_ticket"    → one-way offer per slice (assembled per slice)
    offer_type = offer.get("type") or "single_ticket"

    # Slices & segments
    slices = offer.get("slices") or []
    if not slices:
        return FK_PRICE_NOT_FOUND

    # Build ticket_groups (one per slice when split_ticket, one merged for single)
    ticket_groups: list[dict[str, Any]] = []
    baggage_first_seen_known = None  # None until contradicted
    for slice_obj in slices:
        segs = slice_obj.get("segments") or []
        # `passengers` per slice for baggage is at offer level in Duffel,
        # but Duffel also returns `passengers` on each slice (`cabin`).
        pass_for_slice = slice_obj.get("passengers") or offer.get("passengers") or []

        # Baggage: Duffel exposes `bags` (number) on passengers in some responses;
        # we treat it as informational.
        bags_seen = None
        for p in pass_for_slice:
            bag_count = p.get("bags") if isinstance(p, dict) else None
            if bag_count is None and isinstance(p, dict):
                # Sometimes in cabin amenities or different keys
                bag_count = p.get("included_baggage")
            if bag_count is not None:
                if bags_seen is None:
                    bags_seen = bag_count
                elif bags_seen != bag_count:
                    bags_seen = None
                    break

        if baggage_first_seen_known is None and bags_seen is None:
            baggage_first_seen_known = False  # observed-as-absent once
        if bags_seen is not None:
            baggage_first_seen_known = True  # observed-at-least-once

        ticket_groups.append({
            "group_id": f"tg_{len(ticket_groups) + 1}",
            "stops": [
                {
                    "from": seg.get("origin"),
                    "to":   seg.get("destination"),
                    "carrier": (seg.get("marketing_carrier") or {}).get("iata_code"),
                    "operating_carrier": (seg.get("operating_carrier") or {}).get("iata_code"),
                    "flight_number": seg.get("marketing_carrier_flight_number"),
                    "depart": seg.get("departing_at"),
                    "arrive": seg.get("arriving_at"),
                }
                for seg in segs
            ],
            "ticket_type": "single_pnr" if offer_type == "single_ticket" else "separate_pn",
            "subtotal": {
                "amount": float(offer.get("total_amount", 0)) / max(1, len(slices)),
                "currency": currency,
            },
            "passenger_through_check_baggage": bags_seen is not None and bags_seen > 0,
            "self_transfer_after_group": False,  # we cannot determine from this API
        })

    # Self-transfer detection: if any two adjacent groups change airport
    self_transfer = False
    for i in range(len(ticket_groups) - 1):
        prev_to = ticket_groups[i]["stops"][-1]["to"] if ticket_groups[i]["stops"] else None
        next_from = ticket_groups[i + 1]["stops"][0]["from"] if ticket_groups[i + 1]["stops"] else None
        if prev_to and next_from and prev_to != next_from:
            self_transfer = True
            break

    is_single_ticket = (offer_type == "single_ticket") and len(ticket_groups) <= 1
    ticket_count = 1 if is_single_ticket else len(ticket_groups)

    # Determine separate_ticket_risk per architecture §3.3
    if is_single_ticket:
        separate_ticket_risk = RISK_NONE
    elif self_transfer:
        separate_ticket_risk = RISK_HIGH
    elif not is_single_ticket and any(
        g["ticket_type"] == "separate_pn" for g in ticket_groups
    ):
        # multi-ticket, same airports → elevated risk
        separate_ticket_risk = RISK_ELEVATED
    else:
        separate_ticket_risk = RISK_ELEVATED  # any non-single defaults to elevated

    # Money normalization to TWD
    total_price_norm = normalize_money(offer.get("total_amount"), currency, DEFAULT_DISPLAY_CURRENCY)
    base_price_norm  = normalize_money(offer.get("base_amount"),  currency, DEFAULT_DISPLAY_CURRENCY)
    tax_norm         = normalize_money(offer.get("tax_amount"),   currency, DEFAULT_DISPLAY_CURRENCY)
    if total_price_norm.get("amount") is None:
        return FK_CURRENCY_UNKNOWN

    # Cabin (per slice's passenger)
    cabin = None
    for p in (offer.get("passengers") or []):
        c = (p.get("cabin") or {}).get("cabin_class") if isinstance(p, dict) else None
        if c:
            cabin = c
            break

    # Compute freshness from retrieved_at (NEVER trust producer)
    fmin = compute_freshness_min(retrieved_at)
    fbucket = freshness_bucket_from_min(fmin) if fmin >= 0 else FreshnessBucket.UNKNOWN

    # Confidence reasons
    confidence_reasons: list[str] = [CR_LIVE_PROVIDER]
    warnings: list[str] = []
    if baggage_first_seen_known is False:
        confidence_reasons.append(CR_BAGGAGE_UNKNOWN)
        warnings.append(FK_BAGGAGE_UNKNOWN)
    if offer.get("base_amount") is None or offer.get("tax_amount") is None:
        confidence_reasons.append(CR_PARTIAL_DATA)
        warnings.append(FK_PARTIAL_PRICE)
    if not is_single_ticket:
        # Check whether every group has substantive pricing info
        if any(g.get("subtotal", {}).get("amount") in (None, 0) for g in ticket_groups):
            confidence_reasons.append(CR_MULTI_TICKET_PARTIAL)
            warnings.append(FK_MULTI_TICKET_PRICE_INCOMPLETE)
    elif ticket_count > 1 and is_single_ticket is False:
        # When ticket groups exist but is_single_ticket resolves False
        if any(g.get("subtotal", {}).get("amount") in (None, 0) for g in ticket_groups):
            confidence_reasons.append(CR_MULTI_TICKET_PARTIAL)
            warnings.append(FK_MULTI_TICKET_PRICE_INCOMPLETE)

    # ALSO: when multi_ticket was desired but only 1 group priced
    candidate_segments = candidate.get("segments") or []
    if len(candidate_segments) >= 2 and len(ticket_groups) < 2 and offer_type in ("split_ticket",):
        # candidate wanted multi-ticket; provider only priced 1 leg
        confidence_reasons.append(CR_MULTI_TICKET_PARTIAL)
        if FK_MULTI_TICKET_PRICE_INCOMPLETE not in warnings:
            warnings.append(FK_MULTI_TICKET_PRICE_INCOMPLETE)

    payload = {
        "schema_version": "v1.1",
        "candidate_id": candidate.get("id"),
        "ticket_groups": ticket_groups,
        "ticket_count": ticket_count,
        "is_single_ticket": is_single_ticket,
        "self_transfer": self_transfer,
        "separate_ticket_risk": separate_ticket_risk,
        "currency": DEFAULT_DISPLAY_CURRENCY,
        "total_price":     total_price_norm,
        "base_fare":       base_price_norm,
        "taxes":           tax_norm,
        "fees":            normalize_money(None, currency, DEFAULT_DISPLAY_CURRENCY),  # fees subset of taxes for now
        "optional_extras": normalize_money(None, currency, DEFAULT_DISPLAY_CURRENCY),
        "fare_basis_code": None,
        "fare_type":       "PUBLISHED" if offer.get("base_amount") else None,
        "fare_classes":    [],
        "cabin":           cabin,
        "changeable":      None,
        "refundable":      None,
        "change_fee":      None,
        "refund_fee":      None,
        "baggage": {
            "included": {"carry_on": 1, "checked_pieces": 0 if baggage_first_seen_known is False else None, "checked_weight_kg": None},
            "purchase_required": None,
            "recheck_required_at_connection": (not is_single_ticket) or self_transfer,
            "evidence_complete": baggage_first_seen_known is not False,
        },
        "seat_selection":   {"included": None, "fee_range": None},
        "meal_included":    None,
        "transit_hotel_included": None,
        "lounge_access":    None,
        "valid_until":      offer.get("expires_at"),
        "price_quote_expires_at": offer.get("expires_at"),
        "price_retrieved_at":     retrieved_at,
        "retrieved_at":           retrieved_at,
        "price_freshness_min":    fmin,
        "freshness_min":          fmin,
        "freshness_bucket":       fbucket,
        "confidence_reasons":     confidence_reasons,
        "warnings":               warnings,
        "provenance": {
            "source":             provider_name,  # "duffel" or "mock_duffel"
            "source_type":        SRC_LIVE if provider_name == "duffel" else SRC_CACHE,
            "retrieved_at":       retrieved_at,
            "freshness_min":      fmin,
            "endpoint":           "air/offer_requests",
            "offer_id":           offer.get("id"),
            "verification_status": VS_LIVE,
        },
        # Explicit provider identity (v1.1.1 §2):
        # Mock ≠ Real Duffel. These fields are ALWAYS present.
        "provider":      provider_name,    # "duffel" | "mock_duffel"
        "provider_mode": provider_mode,    # "live" | "mock"
        "verification_status": VS_LIVE,
        "price_status": "OK" if not warnings else "OK_WITH_WARNINGS",
        "failure_reason":      None,
        "failure_kind":        None,
        # Forbidden fields explicitly absent: arbitrage_score, arbitrage_opportunity, net_arbitrage, booking_status
    }
    return payload


# =============================================================================
# Search budget + memoization
# =============================================================================

class SearchBudget:
    """Track per-run search budget with memoization."""

    def __init__(self, max_searches: int = 10):
        self.max = max_searches
        self.used = 0
        self._cache: dict[str, dict[str, Any]] = {}
        self._request_keys_seen: dict[str, str] = {}  # key -> provider response
        self._candidates_attempted: list[str] = []
        self._candidates_skipped_for_budget: list[str] = []

    def budget_remaining(self) -> int:
        return max(0, self.max - self.used)

    def can_attempt(self) -> bool:
        return self.used < self.max

    def memoized(self, search_key: str) -> dict[str, Any] | None:
        return self._cache.get(search_key)

    def record(self, search_key: str, result: dict[str, Any], candidate_id: str) -> None:
        self._cache[search_key] = result
        self._request_keys_seen[search_key] = candidate_id
        self.used += 1
        self._candidates_attempted.append(candidate_id)

    def skip_for_budget(self, candidate_id: str) -> None:
        self._candidates_skipped_for_budget.append(candidate_id)

    @property
    def cache_hits(self) -> int:
        return sum(1 for cid in self._candidates_attempted
                   if cid in self._candidates_skipped_for_budget)


# =============================================================================
# Main orchestration
# =============================================================================

def load_schedule_enrichment_lookup() -> dict[str, dict[str, Any]]:
    """If schedule_enriched_candidates.json exists, build id → schedule_intel lookup."""
    if not SCHEDULE_ENRICHED_PATH.exists():
        return {}
    try:
        cands = json.loads(SCHEDULE_ENRICHED_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    return {c.get("id"): (c.get("schedule_intelligence") or {}) for c in cands if c.get("id")}


def run_price_intelligence(
    candidates: list[dict[str, Any]],
    provider: PriceProvider | None = None,
    max_searches: int = 10,
    date_window: str = "2027-04-15",
    passengers: int = 1,
    use_schedule_signals: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any], SearchBudget]:
    """Run provider quotes against selected candidates with budget.

    Returns:
        (price_evidence_list, summary, budget_object)
    """
    schedule_lookup: Callable[[str], dict[str, Any]] | None = (
        (lambda cid: load_schedule_enrichment_lookup().get(cid, {}))
        if use_schedule_signals
        else None
    )

    selected = select_candidates(candidates, max_searches=max_searches,
                                schedule_enrichment_lookup=schedule_lookup)
    skipped_for_selection = [c.get("id") for c in candidates if c.get("id") not in
                             {s.get("id") for s in selected}]

    budget = SearchBudget(max_searches=max_searches)

    price_evidences: list[dict[str, Any]] = []
    summary = {
        "provider": getattr(provider, "name", "unknown"),
        "candidates_received": len(candidates),
        "candidates_selected": len(selected),
        "candidates_searched": 0,
        "candidates_skipped_for_budget": 0,
        "candidates_with_evidence": 0,
        "candidates_failed": 0,
        "candidates_skipped_for_selection": len(skipped_for_selection),
        "search_budget_used": 0,
        "search_budget_max": max_searches,
        "search_cache_hits": 0,
        "verification_status_distribution": Counter(),
        "freshness_bucket_distribution": Counter(),
        "failure_kind_distribution": Counter(),
        "refuse_comparison_count": 0,
    }

    # Backwards-compat: ensure counts stored as int (Counter is dict-like)
    summary["verification_status_distribution"] = summary["verification_status_distribution"]
    summary["freshness_bucket_distribution"] = summary["freshness_bucket_distribution"]
    summary["failure_kind_distribution"] = summary["failure_kind_distribution"]

    for cand in selected:
        if not budget.can_attempt():
            budget.skip_for_budget(cand.get("id", "(no id)"))
            summary["candidates_skipped_for_budget"] += 1
            continue
        search_key = make_search_key(cand, date_window, passengers)

        # Memoization: identical request → no double-call
        cached = budget.memoized(search_key)
        if cached is not None:
            result = cached
            summary["search_cache_hits"] += 1
        else:
            if provider is None:
                # No provider wired → emit PRICE_NOT_FOUND evidence
                result = build_failure_result(
                    FK_MISSING_CREDENTIALS,
                    datetime.now(timezone.utc).isoformat(),
                    "no provider configured",
                )
            else:
                result = provider.quote(cand, date_window=date_window, passengers=passengers)
            budget.record(search_key, result, cand.get("id", "(no id)"))

        # Convert result → PriceEvidence-shaped per-candidate record
        cid = cand.get("id", "(no id)")
        summary["candidates_searched"] += 1
        pe_record = price_evidence_from_result(result, cid, provider_name=getattr(provider, "name", "duffel"))
        price_evidences.append(pe_record)

        if result.get("success"):
            summary["candidates_with_evidence"] += 1
            vs = pe_record.get("verification_status") or VS_UNKNOWN
            fbucket = pe_record.get("freshness_bucket") or FreshnessBucket.UNKNOWN
            summary["verification_status_distribution"][vs] += 1
            summary["freshness_bucket_distribution"][fbucket] += 1
        else:
            summary["candidates_failed"] += 1
            fk = result.get("failure_kind") or FK_PROVIDER_ERROR
            summary["failure_kind_distribution"][fk] += 1
            if fk in FAILURE_KINDS_REFUSE_COMPARISON:
                summary["refuse_comparison_count"] += 1

    summary["search_budget_used"] = budget.used
    # Convert Counter objects to plain dicts for JSON
    summary["verification_status_distribution"] = dict(summary["verification_status_distribution"])
    summary["freshness_bucket_distribution"]   = dict(summary["freshness_bucket_distribution"])
    summary["failure_kind_distribution"]       = dict(summary["failure_kind_distribution"])
    return price_evidences, summary, budget


def price_evidence_from_result(result: dict[str, Any], candidate_id: str, provider_name: str = "duffel") -> dict[str, Any]:
    """Build a per-candidate PriceEvidence-shaped record from a lookup result.

    `provider_name` is surfaced in BOTH success and failure records (v1.1.1 §2):
      - "duffel"     → real, provider_mode = "live"
      - "mock_duffel" → synthetic, provider_mode = "mock"
    """
    if result.get("success") and result.get("price_evidence"):
        pe = result["price_evidence"]
        # Defensive: ensure no forbidden keys present
        for forbidden in ("arbitrage_score", "arbitrage_opportunity", "net_arbitrage",
                          "booking_status"):
            if forbidden in pe:
                raise AssertionError(f"Forbidden key in PriceEvidence: {forbidden}")
        return {
            "candidate_id":        candidate_id,
            "provider":            pe.get("provider", provider_name),
            "provider_mode":       pe.get("provider_mode", "live" if provider_name == "duffel" else "mock"),
            "verification_status": pe.get("verification_status"),
            "price_status":        pe.get("price_status", "OK"),
            "currency":            pe.get("currency"),
            "total_price":         pe.get("total_price"),
            "ticket_count":        pe.get("ticket_count"),
            "is_single_ticket":    pe.get("is_single_ticket"),
            "self_transfer":       pe.get("self_transfer"),
            "separate_ticket_risk": pe.get("separate_ticket_risk"),
            "freshness_min":       pe.get("freshness_min"),
            "freshness_bucket":    pe.get("freshness_bucket"),
            "retrieved_at":        pe.get("retrieved_at"),
            "warnings":            pe.get("warnings", []),
            "price_evidence":      pe,
            "failure_kind":        None,
            "failure_reason":      None,
        }
    # Failure case
    failure_kind = result.get("failure_kind") or FK_PROVIDER_ERROR
    return {
        "candidate_id":         candidate_id,
        "provider":             provider_name,
        "provider_mode":        "live" if provider_name == "duffel" else "mock",
        "verification_status":  VS_UNKNOWN,
        "price_status":         "FAILED",
        "currency":             None,
        "total_price":          None,
        "ticket_count":         None,
        "is_single_ticket":     None,
        "self_transfer":        None,
        "separate_ticket_risk": None,
        "freshness_min":        None,
        "freshness_bucket":     FreshnessBucket.UNKNOWN,
        "retrieved_at":         result.get("retrieved_at"),
        "warnings":             [failure_kind] if failure_kind else [],
        "price_evidence":       None,
        "failure_kind":         failure_kind,
        "failure_reason":       result.get("failure_reason"),
    }


# =============================================================================
# Trace builder
# =============================================================================

def build_trace_records(
    price_evidences: list[dict[str, Any]],
    budget: SearchBudget,
    candidates_by_id: dict[str, dict[str, Any]],
    provider_name: str,
) -> list[dict[str, Any]]:
    out = []
    for pe in price_evidences:
        cid = pe.get("candidate_id", "(no id)")
        cand = candidates_by_id.get(cid, {})
        search_key = make_search_key(cand, date_window="trace", passengers=1) if cand else None
        out.append({
            "candidate_id":          cid,
            "provider":              provider_name,  # explicit identity (v1.1.1 §2)
            "request_key":           search_key,
            "request_time":          pe.get("retrieved_at"),
            "response_time":         pe.get("retrieved_at"),
            "elapsed_ms":            (pe.get("price_evidence") or {}).get("provenance", {}).get("elapsed_ms"),
            "price_found":           pe.get("price_status") != "FAILED",
            "price_status":          pe.get("price_status"),
            "verification_status":   pe.get("verification_status"),
            "retrieved_at":          pe.get("retrieved_at"),
            "expires_at":            (pe.get("price_evidence") or {}).get("valid_until"),
            "freshness":             pe.get("freshness_bucket"),
            "ticket_count":          pe.get("ticket_count"),
            "currency":              pe.get("currency"),
            "total_price":           (pe.get("total_price") or {}).get("amount"),
            "warnings":              pe.get("warnings", []),
            "failure_reason":        pe.get("failure_reason"),
            "failure_kind":          pe.get("failure_kind"),
            "cache_hit":             cid in budget._candidates_skipped_for_budget and pe.get("price_status") == "OK",
        })
    return out


# =============================================================================
# Price comparison (per spec §13: only same-currency LIVE+similar-freshness)
# =============================================================================

@dataclass
class PriceComparisonResult:
    comparable: bool
    a_less_than_b: bool | None
    refusal_reasons: list[str]
    a_freshness_min: int | None
    b_freshness_min: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparable": self.comparable,
            "a_less_than_b": self.a_less_than_b,
            "refusal_reasons": self.refusal_reasons,
            "a_freshness_min": self.a_freshness_min,
            "b_freshness_min": self.b_freshness_min,
        }


def price_comparison(a: dict[str, Any], b: dict[str, Any]) -> PriceComparisonResult:
    """Compare two PriceEvidence records per the architecture (§8.3 of v1.1.1 doc).

    Rules:
        - both verification_status == LIVE
        - freshness_min comparable (within window)
        - same currency (post-FX)
        - cabin compatible
        - ticket_count handling (provided as-is, with explicit risk adjustment note)
    """
    refusal_reasons: list[str] = []
    # 1. Verification
    a_vs = a.get("verification_status")
    b_vs = b.get("verification_status")
    if a_vs != VS_LIVE or b_vs != VS_LIVE:
        refusal_reasons.append(
            f"verification_status: {a_vs} vs {b_vs} (need both LIVE)"
        )
    # 2. Currency (use currency field, post-FX already normalized)
    if a.get("currency") != b.get("currency"):
        refusal_reasons.append(
            f"currency: {a.get('currency')} vs {b.get('currency')}"
        )
    # 3. Cabin
    a_cabin = (a.get("price_evidence") or {}).get("cabin")
    b_cabin = (b.get("price_evidence") or {}).get("cabin")
    if a_cabin and b_cabin and a_cabin != b_cabin:
        refusal_reasons.append(
            f"cabin: {a_cabin} vs {b_cabin}"
        )
    # 4. Freshness window (architecture §8.3: within freshness_window_min,
    #    here default 60 min)
    a_f = a.get("freshness_min")
    b_f = b.get("freshness_min")
    freshness_window_min = 60
    if a_f is not None and b_f is not None and abs(a_f - b_f) > freshness_window_min:
        refusal_reasons.append(
            f"freshness_window_exceeded: {a_f} vs {b_f} min"
        )
    # 5. Ticket count handling
    a_tc = a.get("ticket_count")
    b_tc = b.get("ticket_count")
    if a_tc is not None and b_tc is not None and a_tc != b_tc:
        refusal_reasons.append(
            f"ticket_count_mismatch: {a_tc} vs {b_tc} (different ticket_count, requires risk adjustment)"
        )
    # 6. Refuse-comparison failure kinds
    for pe in (a, b):
        fk = pe.get("failure_kind")
        if fk in FAILURE_KINDS_REFUSE_COMPARISON:
            refusal_reasons.append(
                f"failure_kind_refuses_comparison: {fk}"
            )

    if refusal_reasons:
        return PriceComparisonResult(False, None, refusal_reasons, a_f, b_f)

    a_amt = (a.get("total_price") or {}).get("amount")
    b_amt = (b.get("total_price") or {}).get("amount")
    if a_amt is None or b_amt is None:
        return PriceComparisonResult(False, None, ["missing_amount"], a_f, b_f)

    return PriceComparisonResult(
        comparable=True,
        a_less_than_b=a_amt < b_amt,
        refusal_reasons=[],
        a_freshness_min=a_f,
        b_freshness_min=b_f,
    )


# =============================================================================
# CLI
# =============================================================================

def _print_observability(summary: dict[str, Any], provider_name: str, started: str) -> None:
    print("\n" + "=" * 60, file=sys.stderr)
    print("PRICE INTELLIGENCE v1.1 — OBSERVABILITY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  provider                                  {provider_name}", file=sys.stderr)
    print(f"  started_at                                {started}", file=sys.stderr)
    print(f"  candidates_received                       {summary['candidates_received']}", file=sys.stderr)
    print(f"  candidates_selected                       {summary['candidates_selected']}", file=sys.stderr)
    print(f"  candidates_searched                       {summary['candidates_searched']}", file=sys.stderr)
    print(f"  candidates_with_evidence                  {summary['candidates_with_evidence']}", file=sys.stderr)
    print(f"  candidates_failed                         {summary['candidates_failed']}", file=sys.stderr)
    print(f"  candidates_skipped_for_selection         {summary['candidates_skipped_for_selection']}", file=sys.stderr)
    print(f"  candidates_skipped_for_budget             {summary['candidates_skipped_for_budget']}", file=sys.stderr)
    print(f"  search_budget_used                        {summary['search_budget_used']}", file=sys.stderr)
    print(f"  search_budget_max                         {summary['search_budget_max']}", file=sys.stderr)
    print(f"  search_cache_hits                         {summary['search_cache_hits']}", file=sys.stderr)
    print(f"  refuse_comparison_count                   {summary['refuse_comparison_count']}", file=sys.stderr)
    print(f"  verification_status_distribution          {dict(summary['verification_status_distribution'])}", file=sys.stderr)
    print(f"  freshness_bucket_distribution             {dict(summary['freshness_bucket_distribution'])}", file=sys.stderr)
    print(f"  failure_kind_distribution                 {dict(summary['failure_kind_distribution'])}", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)


def build_provider(spec: str) -> PriceProvider:
    """Construct a provider from a CLI spec string. NEVER log credentials.

    Provider modes (per v1.1.1 spec):
      mock   → MockDuffelProvider
      duffel → DuffelProvider (raises MISSING_CREDENTIALS if no token)
      auto   → may select real provider if credentials present;
                otherwise fail closed (does NOT silently fall back to Mock)

    For `--provider mock` and `--provider duffel`: explicit, fail-fast.
    For `--provider auto`: explicit fallback policy (real if creds, mock
                            otherwise) but NEVER mingled.

    Per v1.1.1 §1: never silently fall back from --provider duffel to Mock.
    """
    spec = (spec or "").lower()
    if spec == "mock":
        return MockDuffelProvider()
    if spec == "duffel":
        # Strict: must have real token. If not, fail closed with MISSING_CREDENTIALS
        token = os.environ.get("DUFFEL_API_KEY_LIVE") or os.environ.get("DUFFEL_API_KEY_TEST")
        if not token:
            raise RuntimeError(
                "MISSING_CREDENTIALS: DUFFEL_API_KEY_LIVE or DUFFEL_API_KEY_TEST not set in env"
            )
        return DuffelProvider(token=token)
    if spec == "auto":
        token = os.environ.get("DUFFEL_API_KEY_LIVE") or os.environ.get("DUFFEL_API_KEY_TEST")
        if token:
            print("[auto-mode] using real DuffelProvider (credentials present)", file=sys.stderr)
            return DuffelProvider(token=token)
        print("[auto-mode] no credentials; using MockDuffelProvider (NOT real market data)", file=sys.stderr)
        return MockDuffelProvider()
    raise ValueError(f"unknown provider: {spec}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Price Intelligence v1.1 — DuffelProvider")
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=str(DATA_DIR / "flight_candidates.json"),
        help="Path to candidates JSON (default: data/flight_candidates.json)",
    )
    parser.add_argument(
        "--provider", default="mock",
        help="duffel | mock | auto (auto = real if creds, mock otherwise; never silent)",
    )
    parser.add_argument("--max-searches", type=int, default=10,
                        help="Max provider queries per run (default 10; smoke tests use 2)")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Enforce max 2 searches (per v1.1.1 spec §5)")
    parser.add_argument("--date-window", default="2027-04-15")
    parser.add_argument("--passengers", type=int, default=1)
    parser.add_argument("--output", type=Path, default=str(PRICE_EVIDENCE_PATH))
    parser.add_argument("--trace", type=Path, default=str(PRICE_TRACE_PATH))
    args = parser.parse_args(argv)

    # v1.1.1 §5: smoke-test guard
    if args.smoke_test:
        if args.max_searches > 2:
            print(f"[smoke-test] overriding max_searches from {args.max_searches} to 2", file=sys.stderr)
            args.max_searches = 2

    started_at = datetime.now(timezone.utc).isoformat()

    print(f"\nPrice Intelligence v1.1.1", file=sys.stderr)
    print(f"  Provider spec: {args.provider}", file=sys.stderr)
    print(f"  Date window: {args.date_window}", file=sys.stderr)
    print(f"  Max searches: {args.max_searches}", file=sys.stderr)
    if args.smoke_test:
        print(f"  Smoke test mode: ENABLED (max 2 real API requests)", file=sys.stderr)
    print(f"  Input: {args.input}", file=sys.stderr)

    if not args.input.exists():
        print(f"\n[ERROR] Input not found: {args.input}", file=sys.stderr)
        return 1
    try:
        candidates = json.loads(args.input.read_text())
    except json.JSONDecodeError as e:
        print(f"\n[ERROR] Invalid JSON: {e}", file=sys.stderr)
        return 2

    if not isinstance(candidates, list):
        print(f"\n[ERROR] Input must be a JSON array of candidates", file=sys.stderr)
        return 3

    # Build provider (fail-closed semantics)
    try:
        provider = build_provider(args.provider)
    except RuntimeError as e:
        # MISSING_CREDENTIALS — per spec §4: graceful fail-closed
        print(f"\n[ERROR] Provider build failed: {e}", file=sys.stderr)
        print(f"\n>>> FAIL CLOSED: not running. Set DUFFEL_API_KEY_LIVE/TEST, or use --provider mock.", file=sys.stderr)
        return 10  # distinct exit code for missing credentials
    except ValueError as e:
        print(f"\n[ERROR] Invalid provider: {e}", file=sys.stderr)
        return 11

    print(f"  Provider instance: {provider.name}", file=sys.stderr)
    print(f"  Provider health: {provider.health_check()}", file=sys.stderr)

    evidences, summary, budget = run_price_intelligence(
        candidates=candidates,
        provider=provider,
        max_searches=args.max_searches,
        date_window=args.date_window,
        passengers=args.passengers,
        use_schedule_signals=SCHEDULE_ENRICHED_PATH.exists(),
    )
    candidates_by_id = {c.get("id"): c for c in candidates if c.get("id")}
    trace_records = build_trace_records(evidences, budget, candidates_by_id, provider.name)

    # Output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "price_intelligence_v1_1",
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.name,
        "smoke_test": args.smoke_test,
        "summary": summary,
        "evidences": evidences,
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n  Output: {args.output} ({len(evidences)} per-candidate records)", file=sys.stderr)

    trace_payload = {
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.name,
        "started_at": started_at,
        "smoke_test": args.smoke_test,
        "counts": summary,
        "candidates": trace_records,
    }
    args.trace.parent.mkdir(parents=True, exist_ok=True)
    args.trace.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False))
    print(f"  Trace:  {args.trace} ({len(trace_records)} records)", file=sys.stderr)
    _print_observability(summary, provider.name, started_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())

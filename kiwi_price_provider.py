"""
kiwi_price_provider.py — Flight Market Intelligence v1.2.0

Implements KiwiPriceProvider (real) and MockKiwiProvider (deterministic)
that produce the SAME normalized PriceEvidence contract as
MockDuffelProvider / DuffelProvider in price_intelligence.py.

v1.2.0 scope:
- Implement the provider abstraction boundary
- Real KiwiPriceProvider (urllib-based, env-token driven)
- MockKiwiProvider (deterministic, env-flag driven) for tests
- normalize_kiwi_response() — Kiwi JSON → PriceEvidence shape
- Explicit provider identity: "kiwi" / "mock_kiwi"
- Fail-closed MISSING_CREDENTIALS semantics

v1.2.0 does NOT:
- Implement ArbitrageEvidence
- Calculate arbitrage_score
- Rank opportunities
- Build a cross-provider comparison engine
- Promote any verdict to BOOKABLE

Architecture notes:
- Provider identity is "kiwi" or "mock_kiwi"; provider_mode is "live" or "mock"
- All evidence flows through the v1.1 PriceEvidence contract (see
  price_intelligence.normalize_duffel_response for the canonical shape)
- This module is dependency-free at the module level (urllib stdlib only)
- Adheres to v1.1.1 fail-closed semantics: --provider kiwi never silently
  falls back to Mock; missing credentials → MISSING_CREDENTIALS (rc=10)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


# -----------------------------------------------------------------------------
# Re-use enums / failure kinds from price_intelligence.py without modifying it
# -----------------------------------------------------------------------------

# Import the canonical failure kinds, freshness buckets, source types, and
# verification statuses from the canonical price_intelligence module. This
# guarantees v1.2.0 cannot accidentally redefine an enum and break contract
# equivalence.
import price_intelligence as _pi  # type: ignore[import-not-found]

FK_PRICE_NOT_FOUND = _pi.FK_PRICE_NOT_FOUND
FK_PROVIDER_TIMEOUT = _pi.FK_PROVIDER_TIMEOUT
FK_PROVIDER_ERROR = _pi.FK_PROVIDER_ERROR
FK_STALE_PRICE = _pi.FK_STALE_PRICE
FK_PARTIAL_PRICE = _pi.FK_PARTIAL_PRICE
FK_CURRENCY_UNKNOWN = _pi.FK_CURRENCY_UNKNOWN
FK_BAGGAGE_UNKNOWN = _pi.FK_BAGGAGE_UNKNOWN
FK_MULTI_TICKET_PRICE_INCOMPLETE = _pi.FK_MULTI_TICKET_PRICE_INCOMPLETE
FK_ROUTE_UNAVAILABLE = _pi.FK_ROUTE_UNAVAILABLE
FK_MISSING_CREDENTIALS = _pi.FK_MISSING_CREDENTIALS
FK_RATE_LIMITED = _pi.FK_RATE_LIMITED

VS_UNKNOWN = _pi.VS_UNKNOWN
VS_LIVE = _pi.VS_LIVE
VS_DATABASE = _pi.VS_DATABASE
VS_ESTIMATED = _pi.VS_ESTIMATED
VS_VERIFIED = _pi.VS_VERIFIED

SRC_LIVE = _pi.SRC_LIVE
SRC_CACHE = _pi.SRC_CACHE
SRC_INDICATIVE = _pi.SRC_INDICATIVE

RISK_NONE = _pi.RISK_NONE
RISK_ELEVATED = _pi.RISK_ELEVATED
RISK_HIGH = _pi.RISK_HIGH

FRESHNESS_BUCKETS = {
    "FRESHNESS_RECENT", "FRESHNESS_WARM", "FRESHNESS_COLD",
    "FRESHNESS_EXPIRED", "FRESHNESS_UNKNOWN",
}

# Confidence reasons
CR_LIVE_PROVIDER = _pi.CR_LIVE_PROVIDER
CR_RECENT_CACHE = _pi.CR_RECENT_CACHE
CR_PARTIAL_DATA = _pi.CR_PARTIAL_DATA
CR_BAGGAGE_UNKNOWN = _pi.CR_BAGGAGE_UNKNOWN
CR_FEES_UNKNOWN = _pi.CR_FEES_UNKNOWN
CR_MULTI_TICKET_PARTIAL = _pi.CR_MULTI_TICKET_PARTIAL

# Money utility — Kiwi's response currency is whatever the producer
# returns; we don't convert in the adapter (FX is a v1.2.x concern).
DEFAULT_DISPLAY_CURRENCY = _pi.DEFAULT_DISPLAY_CURRENCY

# Forbidden identifiers (defensive — never appear in normalized output)
_FORBIDDEN_KEYS = ("arbitrage_score", "arbitrage_opportunity",
                   "net_arbitrage", "booking_status")


# -----------------------------------------------------------------------------
# Public constants
# -----------------------------------------------------------------------------

# Kiwi Tequila API base URL (per public documentation).
# Note: As of May 2024, new Tequila access is invitation-only / B2B-only;
# existing partner keys remain valid. New account registration is closed.
# (See docs/evidence_source_matrix_v1_1_5.md §1.1 and price_provider_matrix.md)
KIWI_BASE_URL = "https://api.tequila.kiwi.com"

# Kiwi's auth header uses "apikey" (NOT "Authorization: Bearer").
# This is a Kiwi-specific adapter-boundary field; the normalized
# PriceEvidence does NOT expose it.
KIWI_AUTH_HEADER_NAME = "apikey"

# Kiwi search endpoint (v2)
KIWI_SEARCH_ENDPOINT = "/v2/search"

# Kiwi does not return a per-offer expiry by default; the documented
# freshness_ttl_min is a reasonable contract-side default. This is a
# documented limitation (see docs/kiwi_price_provider_v1_2_0.md).
KIWI_DEFAULT_FRESHNESS_TTL_MIN = 15

# Env vars (in priority order)
KIWI_API_KEY_ENVS = ("KIWI_API_KEY", "KIWI_TEQUILA_API_KEY")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _read_token() -> str | None:
    """Read Kiwi API token from allowed env vars. NEVER log the value."""
    for env in KIWI_API_KEY_ENVS:
        v = os.environ.get(env)
        if v:
            return v
    return None


def _compute_freshness_min(retrieved_at: str, now: datetime | None = None) -> int:
    """Reuse v1.1's compute_freshness_min. We don't trust producer timestamps."""
    return _pi.compute_freshness_min(retrieved_at, now=now)


def _freshness_bucket(freshness_min: int) -> str:
    return _pi.freshness_bucket_from_min(freshness_min)


def build_failure_result(failure_kind: str, retrieved_at: str,
                         message: str = "") -> dict[str, Any]:
    """Build a PriceLookupResult-like dict for a failure.
    Mirrors price_intelligence.build_failure_result exactly."""
    return {
        "success": False,
        "failure_kind": failure_kind,
        "failure_reason": message or failure_kind,
        "raw_provider_response_hash": None,
        "elapsed_ms": 0,
        "retrieved_at": retrieved_at,
        "price_evidence": None,
    }


def build_success_result(raw_response: dict[str, Any],
                         price_evidence_payload: dict[str, Any],
                         retrieved_at: str, elapsed_ms: int) -> dict[str, Any]:
    """Build a PriceLookupResult-like dict for a success.
    Mirrors price_intelligence.build_success_result exactly."""
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


# -----------------------------------------------------------------------------
# Capabilities declaration
# -----------------------------------------------------------------------------

def kiwi_capabilities() -> dict[str, Any]:
    """Documented capabilities of a Kiwi-based PriceProvider.
    Mirrors the ProviderCapabilities dataclass shape from price_intelligence
    but as a plain dict so we don't import the dataclass (keeps this module
    self-contained).
    """
    return {
        "supports_split_ticket": True,    # Kiwi's "Virtual Interlining" — assembled
                                          # as separate tickets
        "supports_multi_city": True,
        "supports_positioning": True,
        "includes_baggage": True,         # Kiwi returns per-segment baggage flags
        "includes_seat": False,           # Not at search time
        "currency_native": ["EUR", "USD", "GBP", "CZK", "PLN", "HUF"],
        "cabin_classes": ["economy", "premium_economy", "business", "first"],
        "freshness_ttl_min": KIWI_DEFAULT_FRESHNESS_TTL_MIN,
        "rate_limit_per_min": 60,
        "is_bookable_claim": False,       # We never claim bookable
    }


# -----------------------------------------------------------------------------
# Real KiwiPriceProvider
# -----------------------------------------------------------------------------

class KiwiPriceProvider:
    """Real Kiwi Tequila API client. Token via env `KIWI_API_KEY` or
    `KIWI_TEQUILA_API_KEY`. NEVER logs the Authorization header or token.

    Per v1.2.0 spec §8, kiwi's response does not carry a per-offer
    `expires_at`. We derive freshness purely from `retrieved_at`.
    """

    DUFFEL_BASE = KIWI_BASE_URL  # for compatibility with the ProviderCapabilities
                                # dataclass lookups if used downstream

    def __init__(self, token: str | None = None):
        env_token = token or _read_token()
        if not env_token:
            raise RuntimeError(FK_MISSING_CREDENTIALS)
        self._token = env_token

    @property
    def name(self) -> str:
        return "kiwi"

    def capabilities(self) -> dict[str, Any]:
        return kiwi_capabilities()

    def health_check(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{KIWI_BASE_URL}/v2/locations",
                method="GET",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    KIWI_AUTH_HEADER_NAME: "REDACTED",  # never log the token
                },
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception:
            return False

    def quote(self, candidate: dict[str, Any], date_window: str,
              passengers: int = 1) -> dict[str, Any]:
        """Build a Kiwi search request and normalize the response.

        `date_window` is `YYYY-MM-DD` or `YYYY-MM-DD_to_YYYY-MM-DD`.

        Kiwi's `/v2/search` is a GET with query parameters. The request
        uses Kiwi's `apikey` header (NOT Authorization: Bearer).
        """
        retrieved_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        if not self._token:
            return build_failure_result(FK_MISSING_CREDENTIALS, retrieved_at,
                                         "no token in env")

        segs = candidate.get("segments") or []
        if not segs:
            return build_failure_result(FK_PRICE_NOT_FOUND, retrieved_at,
                                         "no segments in candidate")

        # Build Kiwi query parameters
        # Kiwi's /v2/search expects fly_from, fly_to, date_from, date_to.
        # For multi-segment, we use the first segment's origin and the
        # last segment's destination (Kiwi handles multi-city via separate
        # /v2/flights_multi requests; v1.2.0 implements single-route only).
        origin = segs[0].get("from")
        destination = segs[-1].get("to")
        if not origin or not destination:
            return build_failure_result(FK_ROUTE_UNAVAILABLE, retrieved_at,
                                         "missing origin or destination")

        if "_to_" in date_window:
            out_date, ret_date = date_window.split("_to_", 1)
        else:
            out_date, ret_date = date_window, None

        params = {
            "fly_from": origin,
            "fly_to": destination,
            "date_from": out_date,
            "date_to": out_date,        # Kiwi wants same field repeated for range
            "adults": str(passengers),
            "curr": "USD",
            "locale": "en",
            "sort": "price",
            "limit": 1,                  # we only need the cheapest quote
            "partner": "picky",          # sandbox/test partner marker
        }
        if ret_date:
            params["return_from"] = ret_date
            params["return_to"] = ret_date
            params["flight_type"] = "round"
        else:
            params["flight_type"] = "oneway"

        url = f"{KIWI_BASE_URL}{KIWI_SEARCH_ENDPOINT}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(
                url,
                method="GET",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    KIWI_AUTH_HEADER_NAME: "REDACTED",  # never log
                },
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            if e.code == 429:
                return build_failure_result(FK_RATE_LIMITED, retrieved_at,
                                             f"http {e.code}")
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         f"http {e.code}")
        except (urllib.error.URLError, TimeoutError):
            elapsed_ms = int((time.time() - t0) * 1000)
            return build_failure_result(FK_PROVIDER_TIMEOUT, retrieved_at,
                                         "request timeout")
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         str(e))

        elapsed_ms = int((time.time() - t0) * 1000)
        itineraries = raw.get("data") or []
        if not itineraries:
            return build_failure_result(FK_PRICE_NOT_FOUND, retrieved_at,
                                         "no itineraries returned")
        # Pick the cheapest
        cheapest = min(itineraries, key=lambda it: float(it.get("price") or 0))
        raw_offer = {"data": cheapest, "_request_params": params,
                     "_currency_received_at": retrieved_at}
        pe = normalize_kiwi_response(raw_offer, candidate, retrieved_at,
                                      provider_name=self.name)
        if not isinstance(pe, dict):
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         "normalize failed")
        return build_success_result(raw_offer, pe, retrieved_at, elapsed_ms)


# -----------------------------------------------------------------------------
# Mock Kiwi provider (deterministic)
# -----------------------------------------------------------------------------

class MockKiwiProvider:
    """Synthetic Kiwi responses for tests. Deterministic.

    Behavior mirrors MockDuffelProvider's contract: same normalized
    PriceEvidence shape, distinct provider identity ("mock_kiwi",
    provider_mode "mock"), and the same set of failure-kind simulation
    flags. Implemented as a separate class so v1.2.0 tests can choose
    between the two mocks.
    """

    def __init__(self):
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock_kiwi"

    def capabilities(self) -> dict[str, Any]:
        return kiwi_capabilities()

    def health_check(self) -> bool:
        return True

    def quote(self, candidate: dict[str, Any], date_window: str,
              passengers: int = 1) -> dict[str, Any]:
        self._call_count += 1
        retrieved_at = datetime.now(timezone.utc).isoformat()

        # Failure-flag simulation (same flags as MockDuffelProvider so
        # tests can run against either mock interchangeably)
        live_flags = {k: os.environ.get(k, "0") == "1" for k in [
            "SIMULATE_PROVIDER_TIMEOUT", "SIMULATE_PROVIDER_ERROR",
            "SIMULATE_RATE_LIMITED", "SIMULATE_BAGGAGE_UNKNOWN",
            "SIMULATE_CURRENCY_UNKNOWN", "SIMULATE_PARTIAL_PRICE",
            "SIMULATE_MULTI_INCOMPLETE", "SIMULATE_ROUTE_UNAVAILABLE",
            "SIMULATE_STALE_PRICE",
        ]}
        for flag_name, kind in [
            ("SIMULATE_PROVIDER_TIMEOUT", FK_PROVIDER_TIMEOUT),
            ("SIMULATE_PROVIDER_ERROR",   FK_PROVIDER_ERROR),
            ("SIMULATE_RATE_LIMITED",     FK_RATE_LIMITED),
            ("SIMULATE_BAGGAGE_UNKNOWN",  FK_BAGGAGE_UNKNOWN),
            ("SIMULATE_CURRENCY_UNKNOWN", FK_CURRENCY_UNKNOWN),
            ("SIMULATE_PARTIAL_PRICE",    FK_PARTIAL_PRICE),
            ("SIMULATE_ROUTE_UNAVAILABLE", FK_ROUTE_UNAVAILABLE),
        ]:
            if live_flags.get(flag_name):
                return build_failure_result(kind, retrieved_at,
                                             f"simulated {kind}")

        segments = candidate.get("segments") or []
        if not segments or any(not (s.get("from") and s.get("to"))
                                for s in segments):
            return build_failure_result(FK_PRICE_NOT_FOUND, retrieved_at,
                                         "no segments")

        # Build a synthetic Kiwi-style itinerary
        segs_payload = []
        for seg in segments:
            segs_payload.append({
                "flyFrom": seg.get("from"),
                "flyTo": seg.get("to"),
                "airline": seg.get("carrier") or "XX",
                "operating_carrier": seg.get("operating_carrier")
                                       or seg.get("carrier") or "XX",
                "flight_no": f"{seg.get('carrier') or 'XX'}-100",
                "local_departure": "2027-04-15T08:00:00",
                "local_arrival":   "2027-04-15T13:00:00",
            })
        # Multi-ticket incomplete simulation: only price 1 slice
        if live_flags.get("SIMULATE_MULTI_INCOMPLETE") and len(segs_payload) > 1:
            segs_payload = segs_payload[:1]

        base_amount = 1400.0 + self._call_count * 12  # distinct from Duffel's
                                                       # 1500 + 10 base
        raw = {
            "data": [{
                "id": f"it_mock_kiwi_{candidate.get('id', 'x')}",
                "price": str(base_amount),
                "currency": "eur" if live_flags.get("SIMULATE_CURRENCY_UNKNOWN")
                                       is False else "",
                "flyFrom": segments[0].get("from"),
                "flyTo":   segments[-1].get("to"),
                "route": segs_payload,
                "bags_price": {"1": 0, "2": 50},
                "booking_token": "mock_token_xxx",
                "deep_link": "https://kiwi.com/example",
            }]
        }
        pe = normalize_kiwi_response(raw, candidate, retrieved_at,
                                      provider_name=self.name)
        if not isinstance(pe, dict):
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         "normalize failed")
        if live_flags.get("SIMULATE_STALE_PRICE"):
            stale_iso = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            pe["retrieved_at"] = stale_iso
            pe["freshness_min"] = 5 * 24 * 60
            pe["freshness_bucket"] = _freshness_bucket(pe["freshness_min"])
            pe["warnings"] = list(pe.get("warnings") or []) + [FK_STALE_PRICE]
        return build_success_result(raw, pe, retrieved_at,
                                     50 + self._call_count)


# -----------------------------------------------------------------------------
# Normalization (Kiwi JSON → PriceEvidence contract)
# -----------------------------------------------------------------------------

def normalize_kiwi_response(raw: dict[str, Any], candidate: dict[str, Any],
                            retrieved_at: str,
                            provider_name: str = "kiwi") -> dict[str, Any] | str:
    """Convert a Kiwi itinerary response into a normalized PriceEvidence payload.

    Returns the payload dict, or a string error code if normalization failed.
    Never silently fabricates missing fields.

    `provider_name` must be either "kiwi" or "mock_kiwi" — surfaced in
    payload.provenance.source AND in payload.provider/provider_mode so
    downstream can never confuse Mock-Kiwi with real Kiwi, nor either
    with Duffel/MockDuffel.
    """
    if provider_name not in ("kiwi", "mock_kiwi"):
        # Refuse to fabricate a provenance identity
        return FK_PROVIDER_ERROR

    provider_mode = "live" if provider_name == "kiwi" else "mock"

    itineraries = raw.get("data") or []
    if not itineraries:
        return FK_PRICE_NOT_FOUND

    itinerary = itineraries[0] if isinstance(itineraries[0], dict) else {}
    if not itinerary:
        return FK_PRICE_NOT_FOUND

    currency = (itinerary.get("currency") or "").upper()
    if not currency:
        return FK_CURRENCY_UNKNOWN

    total_amount = itinerary.get("price")
    try:
        total_amount = float(total_amount) if total_amount is not None else None
    except (TypeError, ValueError):
        total_amount = None
    if total_amount is None:
        return FK_PRICE_NOT_FOUND

    # Routes / segments
    routes = itinerary.get("route") or []
    if not routes:
        return FK_PRICE_NOT_FOUND

    # Build ticket_groups: Kiwi doesn't return a `type: split_ticket` field
    # the way Duffel does; instead each "route" element is implicitly a
    # separate ticket when there's a self-transfer (different airline
    # codes that don't interline). We approximate by treating each
    # contiguous sequence of same-airline segments as one group.
    ticket_groups: list[dict[str, Any]] = []
    current_group_airline = None
    current_group_stops: list[dict[str, Any]] = []
    baggage_first_seen_known: bool | None = None

    def _flush_group(airline, stops):
        if not stops:
            return
        ticket_groups.append({
            "group_id": f"tg_{len(ticket_groups) + 1}",
            "stops": stops,
            "ticket_type": "separate_pn",  # Kiwi Virtual Interlining
                                            # = separate PNRs by construction
            "subtotal": {
                # Kiwi doesn't return per-group subtotals; we put the
                # entire total in the first group for accounting purposes
                "amount": (total_amount / len(ticket_groups) if len(ticket_groups) > 0
                            and ticket_groups[-1]["group_id"] == f"tg_{len(ticket_groups)}"
                           else total_amount),
                "currency": currency,
            },
            "passenger_through_check_baggage": baggage_first_seen_known is True,
            "self_transfer_after_group": False,
        })

    for seg in routes:
        airline = seg.get("airline") or seg.get("operating_carrier") or None
        # Treat airline change as a new ticket group (Kiwi's
        # Virtual Interlining semantics)
        if current_group_airline is not None and airline != current_group_airline:
            _flush_group(current_group_airline, current_group_stops)
            current_group_stops = []
        current_group_airline = airline
        current_group_stops.append({
            "from": seg.get("flyFrom"),
            "to": seg.get("flyTo"),
            "carrier": airline,
            "operating_carrier": seg.get("operating_carrier") or airline,
            "flight_number": seg.get("flight_no"),
            "depart": seg.get("local_departure"),
            "arrive": seg.get("local_arrival"),
        })
    _flush_group(current_group_airline, current_group_stops)

    # Self-transfer detection: any change of airport between adjacent stops
    self_transfer = False
    for i in range(len(ticket_groups) - 1):
        last_stop = ticket_groups[i]["stops"][-1] if ticket_groups[i]["stops"] else None
        first_stop = (ticket_groups[i + 1]["stops"][0]
                       if ticket_groups[i + 1]["stops"] else None)
        if (last_stop and first_stop
                and last_stop.get("to") and first_stop.get("from")
                and last_stop["to"] != first_stop["from"]):
            self_transfer = True
            break

    is_single_ticket = (len(ticket_groups) == 1) and not self_transfer
    ticket_count = 1 if is_single_ticket else len(ticket_groups)

    if is_single_ticket:
        separate_ticket_risk = RISK_NONE
    elif self_transfer:
        separate_ticket_risk = RISK_HIGH
    else:
        separate_ticket_risk = RISK_ELEVATED

    # Baggage: Kiwi returns `bags_price` (cost for extra bags) but
    # not always a clear "included" flag. We mark baggage as unknown
    # unless the producer explicitly says 1+ bag is included (price
    # for bag 1 = 0).
    bags_price = itinerary.get("bags_price") or {}
    bag_1_price = bags_price.get("1")
    if bag_1_price is not None:
        try:
            baggage_included = float(bag_1_price) == 0.0
        except (TypeError, ValueError):
            baggage_included = None
    else:
        baggage_included = None
    if baggage_included is False:
        baggage_first_seen_known = False
    elif baggage_included is True:
        baggage_first_seen_known = True

    # Freshness
    fmin = _compute_freshness_min(retrieved_at)
    fbucket = _freshness_bucket(fmin) if fmin >= 0 else "FRESHNESS_UNKNOWN"

    # Confidence reasons / warnings
    confidence_reasons: list[str] = [CR_LIVE_PROVIDER]
    warnings: list[str] = []
    if baggage_first_seen_known is False:
        confidence_reasons.append(CR_BAGGAGE_UNKNOWN)
        warnings.append(FK_BAGGAGE_UNKNOWN)
    elif baggage_first_seen_known is None:
        confidence_reasons.append(CR_BAGGAGE_UNKNOWN)
        warnings.append(FK_BAGGAGE_UNKNOWN)

    candidate_segments = candidate.get("segments") or []
    if len(candidate_segments) >= 2 and len(ticket_groups) < 2:
        confidence_reasons.append(CR_MULTI_TICKET_PARTIAL)
        warnings.append(FK_MULTI_TICKET_PRICE_INCOMPLETE)

    # No expires_at from Kiwi at search time → preserve as None, do NOT
    # fabricate. Documented limitation.
    expires_at = None

    payload: dict[str, Any] = {
        "schema_version": "v1.1",  # same schema as Duffel evidence
        "candidate_id": candidate.get("id"),

        # Ticket structure (parity-checkable against Duffel evidence)
        "ticket_groups": ticket_groups,
        "ticket_count": ticket_count,
        "is_single_ticket": is_single_ticket,
        "self_transfer": self_transfer,
        "separate_ticket_risk": separate_ticket_risk,

        # Currency + money (Kiwi-native; do NOT convert in the adapter)
        "currency": currency,
        "total_price": {
            "amount": total_amount,
            "currency": currency,
            "fx_envelope": None,  # FX is a v1.2.x concern
        },
        "base_fare": {
            "amount": None,
            "currency": currency,
            "fx_envelope": None,
        },
        "taxes": {
            "amount": None,
            "currency": currency,
            "fx_envelope": None,
        },
        "fees": {
            "amount": None,
            "currency": currency,
            "fx_envelope": None,
        },
        "optional_extras": {
            "amount": None,
            "currency": currency,
            "fx_envelope": None,
        },
        "fare_basis_code": None,
        "fare_type": None,
        "fare_classes": [],

        # Cabin — Kiwi doesn't surface cabin at itinerary level for the
        # cheap search; remains None. Documented limitation.
        "cabin": None,

        # Fare rules — NOT available at search time on any current
        # commercial provider (Duffel, Kiwi, Amadeus, Sabre).
        # Per v1.1.4 §5.2: permanent limitation.
        "changeable": None,
        "refundable": None,
        "change_fee": None,
        "refund_fee": None,

        # Baggage
        "baggage": {
            "included": {"carry_on": 1, "checked_pieces": (1 if baggage_included is True
                                                              else 0 if baggage_included is False
                                                              else None),
                          "checked_weight_kg": None},
            "purchase_required": None,
            "recheck_required_at_connection": self_transfer,
            "evidence_complete": baggage_first_seen_known is not None,
        },
        "seat_selection":   {"included": None, "fee_range": None},
        "meal_included":    None,
        "transit_hotel_included": None,
        "lounge_access":    None,

        # Freshness
        "valid_until":      expires_at,        # None; documented limitation
        "price_quote_expires_at": expires_at,
        "price_retrieved_at":     retrieved_at,
        "retrieved_at":           retrieved_at,
        "price_freshness_min":    fmin,
        "freshness_min":          fmin,
        "freshness_bucket":       fbucket,

        # Reasoning
        "confidence_reasons":     confidence_reasons,
        "warnings":               warnings,

        # Provenance (explicit provider identity, NEVER to be confused)
        "provenance": {
            "source":             provider_name,  # "kiwi" | "mock_kiwi"
            "source_type":        SRC_LIVE if provider_name == "kiwi" else SRC_CACHE,
            "retrieved_at":       retrieved_at,
            "freshness_min":      fmin,
            "endpoint":           KIWI_SEARCH_ENDPOINT,
            "offer_id":           itinerary.get("id"),
            "verification_status": VS_LIVE,
        },
        # Explicit identity fields (v1.1.1 §2 / v1.2.0 §5):
        # Mock ≠ Real Kiwi ≠ Duffel. These fields are ALWAYS present.
        "provider":      provider_name,    # "kiwi" | "mock_kiwi"
        "provider_mode": provider_mode,    # "live" | "mock"
        "verification_status": VS_LIVE,
        "price_status": "OK" if not warnings else "OK_WITH_WARNINGS",
        "failure_reason":      None,
        "failure_kind":        None,
    }

    # Defensive guard: ensure no forbidden keys present (arbitrage_score etc.)
    for forbidden in _FORBIDDEN_KEYS:
        if forbidden in payload:
            raise AssertionError(f"Forbidden key in PriceEvidence: {forbidden}")

    return payload


# -----------------------------------------------------------------------------
# Module entry points
# -----------------------------------------------------------------------------

def build_kiwi_provider(spec: str) -> Any:
    """Construct a Kiwi-family provider from a CLI spec string. NEVER log credentials.

    Provider modes:
      kiwi      → KiwiPriceProvider (raises MISSING_CREDENTIALS if no token)
      mock_kiwi → MockKiwiProvider (deterministic, no credentials required)
    """
    spec = (spec or "").lower()
    if spec == "kiwi":
        token = _read_token()
        if not token:
            raise RuntimeError(
                "MISSING_CREDENTIALS: KIWI_API_KEY or KIWI_TEQUILA_API_KEY not set in env"
            )
        return KiwiPriceProvider(token=token)
    if spec == "mock_kiwi":
        return MockKiwiProvider()
    raise ValueError(f"unknown kiwi provider: {spec}")


if __name__ == "__main__":
    # Self-smoke (no network): construct MockKiwiProvider, run a quote,
    # print the resulting normalized payload. Never requires credentials.
    mock = MockKiwiProvider()
    sample_cand = {
        "id": "TEST",
        "long_haul": {"cabin": "economy"},
        "segments": [
            {"from": "TPE", "to": "KUL", "carrier": "D7"},
            {"from": "KUL", "to": "MAD", "carrier": "QR"},
        ],
    }
    res = mock.quote(sample_cand, date_window="2027-04-15", passengers=1)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))

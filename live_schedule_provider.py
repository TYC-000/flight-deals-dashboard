"""
live_schedule_provider.py — Flight Market Intelligence v1.2.1

Implements a ScheduleProvider abstraction with three implementations:
  - OpenFlightsScheduleProvider  (DATABASE evidence; reuses v1.0 OpenFlights logic)
  - DuffelScheduleProvider        (LIVE evidence; uses Duffel air/offer_requests)
  - MockDuffelScheduleProvider    (deterministic; for tests)

The normalized output is a `ScheduleEvidence` record per candidate,
independent from PriceEvidence. This separation matches v1.1.4 §1.7
(ScheduleEvidence is a separate evidence type from PriceEvidence)
and v1.1.5 §12 (ScheduleProvider is a separate protocol).

v1.2.1 scope:
- ScheduleProvider Protocol
- Three concrete implementations
- normalize_schedule_response() helpers
- ScheduleEvidence schema (normalized; see normalize_schedule_response)
- Schedule search budget (10 default, 2 smoke-test cap)
- Date binding to mission_date_window
- Connection-time computation from real timestamps
- Airport-change detection
- Operating-carrier preservation
- Multi-city preservation (per-slice, not collapsed)
- Failure-kind taxonomy mapped to v1.1.1 canonical FailureKinds

v1.2.1 does NOT:
- Compare prices (no ArbitrageEvidence)
- Implement ArbitrageEvidence or opportunity ranking
- Implement arbitrage_score / net savings
- Modify PriceEvidence or schedule_intelligence.py (only adds an
  additional layer that produces ScheduleEvidence alongside v1.0's
  existing per-candidate `schedule_intelligence` block)
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

# Reuse canonical enums / failure kinds from price_intelligence without
# modifying it. This guarantees v1.2.1 cannot redefine an enum and break
# contract equivalence.
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
VS_ESTIMATED = _pi.VS_ESTIMATED
VS_DATABASE = _pi.VS_DATABASE
VS_LIVE = _pi.VS_LIVE
VS_VERIFIED = _pi.VS_VERIFIED

VERIFICATION_STATUSES = _pi.VERIFICATION_STATUSES

SRC_LIVE = _pi.SRC_LIVE
SRC_CACHE = _pi.SRC_CACHE
SRC_DATABASE = "database"
SRC_UNKNOWN = "unknown"

# Public constants
REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
OPENFLIGHTS_DIR = Path("/Users/aib/.hermes/cache/data/openflights")
OPENFLIGHTS_AIRPORTS = OPENFLIGHTS_DIR / "airports.dat"
OPENFLIGHTS_ROUTES = OPENFLIGHTS_DIR / "routes.dat"

DUFFEL_BASE_URL = "https://api.duffel.com"
DUFFEL_OFFER_REQUESTS_ENDPOINT = "/air/offer_requests"

# Env vars (Duffel tokens, in priority order)
DUFFEL_TOKEN_ENVS = ("DUFFEL_API_KEY_LIVE", "DUFFEL_API_KEY_TEST")

# Forbidden identifiers (defensive guard in normalized output)
_FORBIDDEN_KEYS = ("arbitrage_score", "arbitrage_opportunity",
                   "net_arbitrage", "booking_status")


# -----------------------------------------------------------------------------
# Schedule search budget
# -----------------------------------------------------------------------------

class ScheduleSearchBudget:
    """Track per-run schedule search budget with memoization.

    Default max 10 searches per run; smoke-test caps at 2.
    Separate from PriceSearchBudget (per spec §12).
    """
    def __init__(self, max_searches: int = 10):
        self.max = max_searches
        self.used = 0
        self._cache: dict[str, dict[str, Any]] = {}

    def budget_remaining(self) -> int:
        return max(0, self.max - self.used)

    def can_attempt(self) -> bool:
        return self.used < self.max

    def memoized(self, key: str) -> dict[str, Any] | None:
        return self._cache.get(key)

    def record(self, key: str, result: dict[str, Any]) -> None:
        self._cache[key] = result
        self.used += 1


# -----------------------------------------------------------------------------
# ScheduleProvider Protocol
# -----------------------------------------------------------------------------

class ScheduleProvider(Protocol):
    """Schedule evidence provider protocol (analogous to PriceProvider)."""

    @property
    def name(self) -> str: ...

    def health_check(self) -> bool: ...

    def lookup(self, candidate: dict[str, Any], date_window: str,
               passengers: int = 1) -> dict[str, Any]:
        """Return a ScheduleLookupResult-like dict.

        Success shape: {"success": True, "schedule_evidence": {...},
                        "retrieved_at": ISO8601, "elapsed_ms": int,
                        "raw_response_hash": str, "failure_kind": None,
                        "failure_reason": None}

        Failure shape: {"success": False, "schedule_evidence": None,
                        "failure_kind": str, "failure_reason": str, ...}
        """


def _read_duffel_token() -> str | None:
    for env in DUFFEL_TOKEN_ENVS:
        v = os.environ.get(env)
        if v:
            return v
    return None


def build_failure_result(failure_kind: str, retrieved_at: str,
                         message: str = "") -> dict[str, Any]:
    return {
        "success": False,
        "schedule_evidence": None,
        "failure_kind": failure_kind,
        "failure_reason": message or failure_kind,
        "raw_response_hash": None,
        "elapsed_ms": 0,
        "retrieved_at": retrieved_at,
    }


def build_success_result(schedule_payload: dict[str, Any],
                         raw_response: dict[str, Any],
                         retrieved_at: str, elapsed_ms: int) -> dict[str, Any]:
    raw_hash = hashlib.sha256(
        json.dumps(raw_response, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return {
        "success": True,
        "schedule_evidence": schedule_payload,
        "failure_kind": None,
        "failure_reason": None,
        "raw_response_hash": raw_hash,
        "elapsed_ms": elapsed_ms,
        "retrieved_at": retrieved_at,
    }


# -----------------------------------------------------------------------------
# Helpers for connection / airport change / multi-city
# -----------------------------------------------------------------------------

def _parse_iso(s: str | None) -> datetime | None:
    """Parse ISO8601 datetime string. Returns None on failure."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        return None


def _compute_connection_min(arriving_iso: str | None,
                             departing_iso: str | None) -> int | None:
    """Compute connection minutes. Returns None if either timestamp absent
    or if arriving_at >= departing_at (invalid)."""
    arr = _parse_iso(arriving_iso)
    dep = _parse_iso(departing_iso)
    if arr is None or dep is None:
        return None
    if dep < arr:
        return None
    return int((dep - arr).total_seconds() // 60)


def _is_overnight(arriving_iso: str | None,
                   departing_iso: str | None) -> bool | None:
    """Detect overnight connection. Returns None if timestamps missing."""
    arr = _parse_iso(arriving_iso)
    dep = _parse_iso(departing_iso)
    if arr is None or dep is None:
        return None
    return arr.date() != dep.date()


def _airport_change(arrival_airport: str | None,
                     departure_airport: str | None) -> bool | None:
    """Returns True iff airports differ; False iff same; None if either
    missing."""
    if not arrival_airport or not departure_airport:
        return None
    return arrival_airport.upper() != departure_airport.upper()


def _is_tight_connection(connection_min: int | None,
                          threshold_min: int = 90) -> bool | None:
    """Heuristic only: < 90 min considered tight. Returns None when
    connection_min is None."""
    if connection_min is None:
        return None
    return connection_min < threshold_min


def _normalize_iso_duration_to_minutes(duration: str | None) -> int | None:
    """Parse ISO 8601 duration (e.g., 'PT2H23M') to minutes. Returns None
    on parse failure."""
    if not duration:
        return None
    import re as _re
    m = _re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration)
    if not m:
        return None
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 60 + mi + (1 if s >= 30 else 0)


# -----------------------------------------------------------------------------
# OpenFlightsScheduleProvider (DATABASE evidence)
# -----------------------------------------------------------------------------

class OpenFlightsScheduleProvider:
    """Reads the cached OpenFlights data and produces DATABASE evidence.

    This is the v1.0 evidence source wrapped as a ScheduleProvider.
    It does NOT make any network calls; it reads the cached data files
    at /Users/aib/.hermes/cache/data/openflights/.
    """

    def __init__(self):
        self._airports: dict[str, dict[str, Any]] | None = None
        self._routes: set[tuple[str, str]] | None = None

    @property
    def name(self) -> str:
        return "openflights"

    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_live": False,
            "supports_database": True,
            "supports_per_date": False,   # OpenFlights has no date-specific schedules
            "supports_aircraft": False,
            "supports_terminal": False,
            "supports_connection_time": False,  # no timestamps in OpenFlights
            "freshness_ttl_min": 60 * 24 * 7,  # OpenFlights is a weekly DB dump
            "rate_limit_per_min": 0,
        }

    def health_check(self) -> bool:
        return OPENFLIGHTS_AIRPORTS.exists() and OPENFLIGHTS_ROUTES.exists()

    def _ensure_loaded(self):
        if self._airports is None:
            self._airports = {}
            if OPENFLIGHTS_AIRPORTS.exists():
                with open(OPENFLIGHTS_AIRPORTS, "r", encoding="utf-8",
                          errors="replace") as f:
                    for line in f:
                        parts = line.strip().split(",")
                        if len(parts) >= 5:
                            iata = parts[4].strip('"')
                            if iata:
                                self._airports[iata.upper()] = {
                                    "name": parts[1].strip('"'),
                                    "city": parts[2].strip('"'),
                                    "country": parts[3].strip('"'),
                                    "iata": iata.upper(),
                                }
        if self._routes is None:
            self._routes = set()
            if OPENFLIGHTS_ROUTES.exists():
                with open(OPENFLIGHTS_ROUTES, "r", encoding="utf-8",
                          errors="replace") as f:
                    for line in f:
                        parts = line.strip().split(",")
                        if len(parts) >= 5:
                            airline, airline_id, src, src_id, dst, dst_id = parts[:6]
                            if src and dst:
                                self._routes.add((src.upper(), dst.upper()))

    def lookup(self, candidate: dict[str, Any], date_window: str,
               passengers: int = 1) -> dict[str, Any]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        if not self.health_check():
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         "openflights data files missing")
        self._ensure_loaded()

        segments = candidate.get("segments") or []
        if not segments:
            return build_failure_result(FK_ROUTE_UNAVAILABLE, retrieved_at,
                                         "no segments")

        seg_schedules: list[dict[str, Any]] = []
        for idx, seg in enumerate(segments):
            src = (seg.get("from") or "").upper()
            dst = (seg.get("to") or "").upper()
            if not src or not dst:
                seg_schedules.append({
                    "segment_index": idx,
                    "origin": src or None,
                    "destination": dst or None,
                    "verification_status": VS_UNKNOWN,
                    "departure_date": None,
                    "departure_time": None,
                    "arrival_date": None,
                    "arrival_time": None,
                    "duration_minutes": None,
                    "flight_number": None,
                    "marketing_carrier": None,
                    "operating_carrier": None,
                    "aircraft": None,
                })
                continue
            # OpenFlights is structural only: route existence, no schedule details.
            route_exists = (src, dst) in (self._routes or set())
            seg_schedules.append({
                "segment_index": idx,
                "origin": src,
                "destination": dst,
                "departure_date": None,   # OpenFlights has no date-specific schedules
                "departure_time": None,
                "arrival_date": None,
                "arrival_time": None,
                "duration_minutes": None,
                "flight_number": None,
                "marketing_carrier": None,
                "operating_carrier": None,
                "aircraft": None,
                "verification_status": VS_DATABASE if route_exists else VS_UNKNOWN,
                "route_exists_in_db": route_exists,
            })

        # Aggregate to candidate-level schedule_status
        statuses = [s["verification_status"] for s in seg_schedules]
        if all(s == VS_DATABASE for s in statuses):
            sched_status = "SUPPORTED"
        elif any(s == VS_DATABASE for s in statuses):
            sched_status = "PARTIAL"
        elif any(s == VS_UNKNOWN for s in statuses):
            sched_status = "UNCERTAIN"
        else:
            sched_status = "UNAVAILABLE"

        # Connection computation requires timestamps; OpenFlights has none.
        connection_checks: list[dict[str, Any]] = []
        for i in range(len(seg_schedules) - 1):
            prev = seg_schedules[i]
            nxt = seg_schedules[i + 1]
            connection_checks.append({
                "between_segment_index": i,
                "arrival_airport": prev["destination"],
                "departure_airport": nxt["origin"],
                "connection_time_min": None,
                "overnight_connection": None,
                "tight_connection": None,
                "airport_change_required": _airport_change(prev["destination"],
                                                              nxt["origin"]),
            })

        schedule_payload = {
            "candidate_id": candidate.get("id"),
            "provider": "openflights",
            "provider_mode": "database",
            "retrieved_at": retrieved_at,
            "mission_date_window": date_window,
            "searched_date": date_window,    # OpenFlights can't narrow; document
            "expires_at": None,
            "freshness": None,
            "verification_status": VS_DATABASE if sched_status == "SUPPORTED"
                                            else VS_UNKNOWN,
            "schedule_status": sched_status,
            "segments": seg_schedules,
            "connection_checks": connection_checks,
            "aircraft_in_disclosure": False,
            "terminal_in_disclosure": False,
            "live_search_used": False,
            "warnings": [],
            "failure_reason": None,
            "provenance": {
                "source": "openflights",
                "source_type": SRC_DATABASE,
                "endpoint": "file://openflights/airports.dat+routes.dat",
                "retrieved_at": retrieved_at,
                "verification_status": VS_DATABASE,
            },
        }
        return build_success_result(schedule_payload,
                                     raw_response={"type": "openflights_db"},
                                     retrieved_at=retrieved_at, elapsed_ms=1)


# -----------------------------------------------------------------------------
# DuffelScheduleProvider (LIVE evidence)
# -----------------------------------------------------------------------------

class DuffelScheduleProvider:
    """Real Duffel schedule provider. Returns LIVE ScheduleEvidence.

    Per spec §2, the current Duffel `air/offer_requests` endpoint returns
    full LIVE schedule data on each offer. We use `return_offers=true`
    with the candidate's segments as slices, and normalize the response.
    """

    def __init__(self, token: str | None = None):
        env_token = token or _read_duffel_token()
        if not env_token:
            raise RuntimeError(FK_MISSING_CREDENTIALS)
        self._token = env_token

    @property
    def name(self) -> str:
        return "duffel"

    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_live": True,
            "supports_database": False,
            "supports_per_date": True,
            "supports_aircraft": True,
            "supports_terminal": True,
            "supports_connection_time": True,  # computed from departing_at/arriving_at
            "freshness_ttl_min": 20,
            "rate_limit_per_min": 60,
        }

    def health_check(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{DUFFEL_BASE_URL}/air/airports?limit=1",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Duffel-Version": "v2",
                    "Authorization": "Bearer REDACTED",  # never log token
                },
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception:
            return False

    def lookup(self, candidate: dict[str, Any], date_window: str,
               passengers: int = 1) -> dict[str, Any]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        if not self._token:
            return build_failure_result(FK_MISSING_CREDENTIALS, retrieved_at,
                                         "no token")

        segments = candidate.get("segments") or []
        if not segments:
            return build_failure_result(FK_ROUTE_UNAVAILABLE, retrieved_at,
                                         "no segments")

        # Build slices — multi-city preserved per spec §11.
        # Each segment becomes its own slice (TPE→KUL, KUL→DXB, DXB→MAD
        # = 3 slices). Duffel handles multi-city natively.
        if "_to_" in date_window:
            out_date, ret_date = date_window.split("_to_", 1)
        else:
            out_date, ret_date = date_window, None

        slices = []
        for seg in segments:
            slices.append({
                "origin": seg.get("from"),
                "destination": seg.get("to"),
                "departure_date": out_date,
            })

        body = {
            "data": {
                "include_split_ticket": True,
                "passengers": [{"type": "adult"}] * passengers,
                "slices": slices,
            }
        }

        try:
            req = urllib.request.Request(
                f"{DUFFEL_BASE_URL}{DUFFEL_OFFER_REQUESTS_ENDPOINT}"
                f"?return_offers=true&supplier_timeout=15000",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Duffel-Version": "v2",
                    "Authorization": "Bearer REDACTED",
                },
                method="POST",
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
        offers = (raw.get("data") or {}).get("offers") or []
        if not offers:
            return build_failure_result(FK_ROUTE_UNAVAILABLE, retrieved_at,
                                         "no offers returned for the requested date")

        # Pick the cheapest offer for the schedule evidence.
        cheapest = min(offers, key=lambda o: float(o.get("total_amount") or 0))
        schedule_payload = normalize_duffel_schedule_response(
            cheapest, candidate, retrieved_at, date_window,
            provider_name=self.name,
        )
        if not isinstance(schedule_payload, dict):
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         "normalize failed")
        return build_success_result(schedule_payload,
                                     raw_response={"data": cheapest,
                                                    "_request_body": body},
                                     retrieved_at=retrieved_at,
                                     elapsed_ms=elapsed_ms)


# -----------------------------------------------------------------------------
# MockDuffelScheduleProvider (deterministic, for tests)
# -----------------------------------------------------------------------------

class MockDuffelScheduleProvider:
    """Deterministic mock for tests. Same canonical failure modes as
    MockDuffelProvider / MockKiwiProvider."""

    def __init__(self):
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock_duffel"

    def capabilities(self) -> dict[str, Any]:
        return DuffelScheduleProvider(token="__noop__").capabilities()

    def health_check(self) -> bool:
        return True

    def lookup(self, candidate: dict[str, Any], date_window: str,
               passengers: int = 1) -> dict[str, Any]:
        self._call_count += 1
        retrieved_at = datetime.now(timezone.utc).isoformat()

        # Failure-flag simulation
        flags = {k: os.environ.get(k, "0") == "1" for k in [
            "SIMULATE_PROVIDER_TIMEOUT", "SIMULATE_PROVIDER_ERROR",
            "SIMULATE_RATE_LIMITED", "SIMULATE_ROUTE_UNAVAILABLE",
            "SIMULATE_STALE_PRICE",
        ]}
        for fname, kind in [
            ("SIMULATE_PROVIDER_TIMEOUT", FK_PROVIDER_TIMEOUT),
            ("SIMULATE_PROVIDER_ERROR",   FK_PROVIDER_ERROR),
            ("SIMULATE_RATE_LIMITED",     FK_RATE_LIMITED),
            ("SIMULATE_ROUTE_UNAVAILABLE", FK_ROUTE_UNAVAILABLE),
        ]:
            if flags.get(fname):
                return build_failure_result(kind, retrieved_at,
                                             f"simulated {kind}")

        segments = candidate.get("segments") or []
        if not segments:
            return build_failure_result(FK_ROUTE_UNAVAILABLE, retrieved_at,
                                         "no segments")

        # Build a synthetic Duffel offer payload (multi-city preserved).
        # Generate deterministic timestamps spaced by 5h flight + 2h layover,
        # so all N segments and N-1 connections have meaningful data.
        base_dt = datetime(2027, 4, 15, 8, 0, 0, tzinfo=timezone.utc)
        slices = []
        cur_depart_dt = base_dt
        for i, seg in enumerate(segments):
            flight_min = 5 * 60   # 5h flight (mock)
            arr_dt = cur_depart_dt.replace() + _pi.timedelta(minutes=flight_min)
            slices.append({
                "origin": seg.get("from"),
                "destination": seg.get("to"),
                "segments": [{
                    "origin": seg.get("from"),
                    "destination": seg.get("to"),
                    "operating_carrier_flight_number":
                        f"{seg.get('operating_carrier') or seg.get('carrier') or 'XX'}-{100 + i}",
                    "operating_carrier": {"iata_code":
                                           seg.get("operating_carrier")
                                           or seg.get("carrier") or "XX"},
                    "marketing_carrier_flight_number":
                        f"{seg.get('carrier') or 'XX'}-{100 + i}",
                    "marketing_carrier": {"iata_code":
                                           seg.get("carrier") or "XX"},
                    "departing_at": cur_depart_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "arriving_at": arr_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "duration": f"PT{int(flight_min // 60)}H{int(flight_min % 60)}M",
                    "aircraft": {"iata_code": "789", "name": "Boeing 787-9"},
                }],
                "duration": f"PT{int(flight_min // 60)}H{int(flight_min % 60)}M",
            })
            # Next leg departs 2h after this arrival
            cur_depart_dt = arr_dt + _pi.timedelta(hours=2)

        # Build a synthetic Duffel-style offer
        synthetic_offer = {
            "id": f"off_mock_sched_{candidate.get('id', 'x')}",
            "expires_at": (datetime.now(timezone.utc).replace(microsecond=0)
                           ).isoformat() + "Z",   # ~immediate expiry for testing
            "total_amount": "1500.00",
            "total_currency": "USD",
            "slices": slices,
            "live_mode": False,
        }
        schedule_payload = normalize_duffel_schedule_response(
            synthetic_offer, candidate, retrieved_at, date_window,
            provider_name=self.name,
        )
        if not isinstance(schedule_payload, dict):
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         "normalize failed")
        if flags.get("SIMULATE_STALE_PRICE"):
            stale_iso = (datetime.now(timezone.utc)
                         - _pi.timedelta(days=5)).isoformat()
            schedule_payload["retrieved_at"] = stale_iso
            schedule_payload["freshness"] = "FRESHNESS_EXPIRED"
            schedule_payload["warnings"] = list(schedule_payload.get("warnings") or []) + [FK_STALE_PRICE]
        return build_success_result(schedule_payload,
                                     raw_response={"data": synthetic_offer},
                                     retrieved_at=retrieved_at,
                                     elapsed_ms=50 + self._call_count)


# -----------------------------------------------------------------------------
# Normalization (provider-agnostic ScheduleEvidence contract)
# -----------------------------------------------------------------------------

def normalize_duffel_schedule_response(
        offer: dict[str, Any], candidate: dict[str, Any],
        retrieved_at: str, date_window: str,
        provider_name: str = "duffel",
) -> dict[str, Any] | str:
    """Convert a Duffel offer response into a normalized ScheduleEvidence payload.

    Returns the payload dict, or a string error code if normalization failed.

    `provider_name` must be one of {"duffel", "mock_duffel"} so the
    provider identity is non-confusable with OpenFlights.
    """
    if provider_name not in ("duffel", "mock_duffel"):
        return FK_PROVIDER_ERROR

    slices = offer.get("slices") or []
    if not slices:
        return FK_ROUTE_UNAVAILABLE

    expires_at = offer.get("expires_at")  # may be None
    live_mode = offer.get("live_mode", None)

    seg_schedules: list[dict[str, Any]] = []
    for idx, slc in enumerate(slices):
        # Duffel returns per-slice `segments[]`; for the typical single-leg
        # slice, there's exactly one segment. Multi-leg slices are rare.
        # Accept either Duffel-shaped (origin/destination as dict with
        # iata_code) or simple-string origin/destination (mock-friendly).
        for sidx, seg in enumerate(slc.get("segments") or []):
            origin_raw = seg.get("origin")
            if isinstance(origin_raw, dict):
                origin = origin_raw.get("iata_code")
            else:
                origin = origin_raw
            destination_raw = seg.get("destination")
            if isinstance(destination_raw, dict):
                destination = destination_raw.get("iata_code")
            else:
                destination = destination_raw
            mc_raw = seg.get("marketing_carrier")
            if isinstance(mc_raw, dict):
                marketing_carrier = mc_raw.get("iata_code")
            else:
                marketing_carrier = mc_raw
            oc_raw = seg.get("operating_carrier")
            if isinstance(oc_raw, dict):
                operating_carrier = oc_raw.get("iata_code")
            else:
                operating_carrier = oc_raw
            departing_at = seg.get("departing_at")
            arriving_at = seg.get("arriving_at")
            duration_min = _normalize_iso_duration_to_minutes(seg.get("duration"))
            aircraft_raw = seg.get("aircraft")
            if isinstance(aircraft_raw, dict):
                aircraft = aircraft_raw.get("iata_code")
            else:
                aircraft = aircraft_raw
            seg_schedules.append({
                "segment_index": len(seg_schedules),
                "slice_index": idx,
                "origin": origin,
                "destination": destination,
                "departure_date": (departing_at or "").split("T")[0] or None,
                "departure_time": (departing_at or "").split("T")[1].rstrip("Z") if departing_at else None,
                "arrival_date": (arriving_at or "").split("T")[0] or None,
                "arrival_time": (arriving_at or "").split("T")[1].rstrip("Z") if arriving_at else None,
                "departing_at_iso": departing_at,
                "arriving_at_iso": arriving_at,
                "duration_minutes": duration_min,
                "flight_number": seg.get("marketing_carrier_flight_number"),
                "operating_carrier_flight_number": seg.get("operating_carrier_flight_number"),
                "marketing_carrier": marketing_carrier,
                "operating_carrier": operating_carrier,
                "aircraft": aircraft,
                "verification_status": VS_LIVE,  # Duffel returned timestamps
            })

    if not seg_schedules:
        return FK_ROUTE_UNAVAILABLE

    # Connection checks (per spec §8 / §9)
    connection_checks: list[dict[str, Any]] = []
    for i in range(len(seg_schedules) - 1):
        prev = seg_schedules[i]
        nxt = seg_schedules[i + 1]
        # Connection time = prev ARRIVAL → next DEPARTURE (not prev.departure)
        conn_min = _compute_connection_min(prev.get("arriving_at_iso"),
                                            nxt.get("departing_at_iso"))
        overnight = _is_overnight(prev.get("arriving_at_iso"),
                                    nxt.get("departing_at_iso"))
        airport_chg = _airport_change(prev.get("destination"),
                                        nxt.get("origin"))
        tight = _is_tight_connection(conn_min)
        connection_checks.append({
            "between_segment_index": i,
            "arrival_airport": prev.get("destination"),
            "departure_airport": nxt.get("origin"),
            "connection_time_min": conn_min,
            "overnight_connection": overnight,
            "tight_connection": tight,
            "airport_change_required": airport_chg,
        })

    # Schedule status (per spec §6, v1.1.0 conventions)
    # LIVE evidence from Duffel → schedule_status = SUPPORTED if all
    # segments have LIVE evidence; PARTIAL if mixed; UNCERTAIN if none.
    vs_set = {s["verification_status"] for s in seg_schedules}
    if vs_set == {VS_LIVE}:
        sched_status = "SUPPORTED"
    elif VS_LIVE in vs_set:
        sched_status = "PARTIAL"
    else:
        sched_status = "UNCERTAIN"

    # Per spec §6: "VERIFIED must only be emitted if the existing
    # evidence rules actually justify it." LIVE from a price-offer is
    # not VERIFIED — it's LIVE, not VERIFIED. The 5-tier enum is
    # preserved unchanged.
    verification_status = VS_LIVE

    payload: dict[str, Any] = {
        "candidate_id": candidate.get("id"),
        "provider": provider_name,    # "duffel" | "mock_duffel"
        "provider_mode": "live" if provider_name == "duffel" else "mock",
        "retrieved_at": retrieved_at,
        "mission_date_window": date_window,
        "searched_date": date_window,
        "expires_at": expires_at,
        "freshness": None,    # computed by caller using compute_freshness_min
        "verification_status": verification_status,
        "schedule_status": sched_status,
        "live_mode": live_mode,
        "segments": seg_schedules,
        "connection_checks": connection_checks,
        "aircraft_in_disclosure": any(s.get("aircraft") for s in seg_schedules),
        "terminal_in_disclosure": any(
            (s.get("origin") and "terminal" in str(s))
            for s in []   # not surfaced in this normalized shape
        ) or False,
        "live_search_used": True,
        "warnings": [],
        "failure_reason": None,
        "provenance": {
            "source": provider_name,
            "source_type": SRC_LIVE if provider_name == "duffel" else SRC_CACHE,
            "endpoint": DUFFEL_OFFER_REQUESTS_ENDPOINT,
            "retrieved_at": retrieved_at,
            "offer_id": offer.get("id"),
            "live_mode": live_mode,
            "verification_status": verification_status,
        },
    }

    # Defensive guard
    for forbidden in _FORBIDDEN_KEYS:
        if forbidden in payload:
            raise AssertionError(f"Forbidden key in ScheduleEvidence: {forbidden}")

    return payload


# -----------------------------------------------------------------------------
# ScheduleEvidence -> compute freshness
# -----------------------------------------------------------------------------

def compute_schedule_freshness(schedule_evidence: dict[str, Any]) -> str:
    """Compute freshness bucket for ScheduleEvidence independently of
    PriceEvidence freshness (per spec §16)."""
    retrieved = schedule_evidence.get("retrieved_at")
    if not retrieved:
        return "FRESHNESS_UNKNOWN"
    fmin = _pi.compute_freshness_min(retrieved)
    return _pi.freshness_bucket_from_min(fmin)


# -----------------------------------------------------------------------------
# ScheduleProvider factory
# -----------------------------------------------------------------------------

def build_schedule_provider(spec: str) -> ScheduleProvider:
    """Construct a ScheduleProvider from a CLI spec string. NEVER log credentials.

    Modes:
      openflights        → OpenFlightsScheduleProvider (DATABASE)
      duffel             → DuffelScheduleProvider (LIVE; fail closed if no creds)
      mock_duffel        → MockDuffelScheduleProvider (deterministic)
      auto               → duffel if creds else openflights (explicit log)
    """
    spec = (spec or "").lower()
    if spec == "openflights":
        return OpenFlightsScheduleProvider()
    if spec == "mock_duffel":
        return MockDuffelScheduleProvider()
    if spec == "duffel":
        token = _read_duffel_token()
        if not token:
            raise RuntimeError(
                "MISSING_CREDENTIALS: DUFFEL_API_KEY_LIVE or DUFFEL_API_KEY_TEST not set in env"
            )
        return DuffelScheduleProvider(token=token)
    if spec == "auto":
        token = _read_duffel_token()
        if token:
            print("[schedule-auto] using real DuffelScheduleProvider (credentials present)",
                  file=sys.stderr)
            return DuffelScheduleProvider(token=token)
        print("[schedule-auto] no credentials; using OpenFlightsScheduleProvider (DATABASE evidence)",
              file=sys.stderr)
        return OpenFlightsScheduleProvider()
    raise ValueError(f"unknown schedule provider: {spec}")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _print_observability(summary: dict[str, Any], provider_name: str,
                          started: str) -> None:
    print("\n" + "=" * 60, file=sys.stderr)
    print("LIVE SCHEDULE PROVIDER v1.2.1 — OBSERVABILITY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  schedule_provider                            {provider_name}", file=sys.stderr)
    print(f"  started_at                                   {started}", file=sys.stderr)
    print(f"  candidates_received                          {summary['candidates_received']}", file=sys.stderr)
    print(f"  candidates_looked_up                         {summary['candidates_looked_up']}", file=sys.stderr)
    print(f"  candidates_with_live_evidence                {summary['candidates_with_live_evidence']}", file=sys.stderr)
    print(f"  candidates_with_database_evidence            {summary['candidates_with_database_evidence']}", file=sys.stderr)
    print(f"  candidates_failed                            {summary['candidates_failed']}", file=sys.stderr)
    print(f"  candidates_skipped_for_budget               {summary['candidates_skipped_for_budget']}", file=sys.stderr)
    print(f"  schedule_budget_used                         {summary['schedule_budget_used']}", file=sys.stderr)
    print(f"  schedule_budget_max                          {summary['schedule_budget_max']}", file=sys.stderr)
    print(f"  verification_status_distribution             {dict(summary['verification_status_distribution'])}", file=sys.stderr)
    print(f"  schedule_status_distribution                 {dict(summary['schedule_status_distribution'])}", file=sys.stderr)
    print(f"  failure_kind_distribution                    {dict(summary['failure_kind_distribution'])}", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live Schedule Provider v1.2.1")
    parser.add_argument("input", type=Path, nargs="?",
                         default=str(DATA_DIR / "flight_candidates.json"))
    parser.add_argument("--schedule-provider", default="openflights",
                         help="openflights | duffel | mock_duffel | auto")
    parser.add_argument("--max-searches", type=int, default=10)
    parser.add_argument("--smoke-test", action="store_true",
                         help="Enforce max 2 schedule searches")
    parser.add_argument("--date-window", default="2027-04-15")
    parser.add_argument("--passengers", type=int, default=1)
    parser.add_argument("--output", type=Path,
                         default=str(DATA_DIR / "schedule_evidence_v1_2_1.json"))
    parser.add_argument("--trace", type=Path,
                         default=str(DATA_DIR / "schedule_trace_v1_2_1.json"))
    args = parser.parse_args(argv)

    if args.smoke_test and args.max_searches > 2:
        print(f"[smoke-test] overriding max_searches from {args.max_searches} to 2",
              file=sys.stderr)
        args.max_searches = 2

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\nLive Schedule Provider v1.2.1", file=sys.stderr)
    print(f"  Schedule-provider spec: {args.schedule_provider}", file=sys.stderr)
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

    try:
        provider = build_schedule_provider(args.schedule_provider)
    except RuntimeError as e:
        print(f"\n[ERROR] Provider build failed: {e}", file=sys.stderr)
        print(f"\n>>> FAIL CLOSED: not running. Set appropriate credential, or use --schedule-provider openflights.",
              file=sys.stderr)
        return 10
    except ValueError as e:
        print(f"\n[ERROR] Invalid provider: {e}", file=sys.stderr)
        return 11

    print(f"  Provider instance: {provider.name}", file=sys.stderr)
    print(f"  Provider health: {provider.health_check()}", file=sys.stderr)

    budget = ScheduleSearchBudget(max_searches=args.max_searches)
    evidences: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "candidates_received": len(candidates),
        "candidates_looked_up": 0,
        "candidates_with_live_evidence": 0,
        "candidates_with_database_evidence": 0,
        "candidates_failed": 0,
        "candidates_skipped_for_budget": 0,
        "schedule_budget_used": 0,
        "schedule_budget_max": args.max_searches,
        "verification_status_distribution": {},
        "schedule_status_distribution": {},
        "failure_kind_distribution": {},
    }

    for cand in candidates:
        cid = cand.get("id", "(no id)")
        if not budget.can_attempt():
            summary["candidates_skipped_for_budget"] += 1
            continue
        # Memoization key: deterministic from cid + date_window + passengers
        memo_key = f"{cid}|{args.date_window}|{args.passengers}"
        cached = budget.memoized(memo_key)
        if cached is not None:
            result = cached
        else:
            result = provider.lookup(cand, date_window=args.date_window,
                                      passengers=args.passengers)
            budget.record(memo_key, result)
        summary["candidates_looked_up"] += 1
        if result.get("success"):
            pe = result["schedule_evidence"]
            evidences.append({
                "candidate_id": cid,
                "provider": pe.get("provider"),
                "provider_mode": pe.get("provider_mode"),
                "verification_status": pe.get("verification_status"),
                "schedule_status": pe.get("schedule_status"),
                "schedule_evidence": pe,
                "retrieved_at": result.get("retrieved_at"),
                "freshness": compute_schedule_freshness(pe),
            })
            vs = pe.get("verification_status")
            ss = pe.get("schedule_status")
            summary["verification_status_distribution"][vs] = (
                summary["verification_status_distribution"].get(vs, 0) + 1)
            summary["schedule_status_distribution"][ss] = (
                summary["schedule_status_distribution"].get(ss, 0) + 1)
            if vs == VS_LIVE:
                summary["candidates_with_live_evidence"] += 1
            elif vs == VS_DATABASE:
                summary["candidates_with_database_evidence"] += 1
        else:
            summary["candidates_failed"] += 1
            fk = result.get("failure_kind") or FK_PROVIDER_ERROR
            summary["failure_kind_distribution"][fk] = (
                summary["failure_kind_distribution"].get(fk, 0) + 1)
            evidences.append({
                "candidate_id": cid,
                "provider": provider.name,
                "provider_mode": "live" if provider.name == "duffel" else "mock" if provider.name.startswith("mock") else "database",
                "schedule_evidence": None,
                "retrieved_at": result.get("retrieved_at"),
                "failure_kind": fk,
                "failure_reason": result.get("failure_reason"),
                "freshness": None,
            })

    summary["schedule_budget_used"] = budget.used

    # Output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "live_schedule_provider_v1_2_1",
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.name,
        "smoke_test": args.smoke_test,
        "summary": summary,
        "evidences": evidences,
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n  Output: {args.output} ({len(evidences)} per-candidate records)",
          file=sys.stderr)

    trace_payload = {
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "schedule_provider": provider.name,
        "started_at": started_at,
        "smoke_test": args.smoke_test,
        "counts": summary,
        "candidates": evidences,
    }
    args.trace.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False))
    print(f"  Trace:  {args.trace}", file=sys.stderr)

    _print_observability(summary, provider.name, started_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())

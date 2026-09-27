"""
fx_provider.py — Flight Market Intelligence v1.2.2

Provider-agnostic FX Evidence layer using Frankfurter v2 as the first
real provider.

Pipeline (per spec §1):
  Currency → FX Evidence → Normalized Comparison Value

The output is a normalized FXEvidence record independent of any
provider-specific response shape. Provider-specific fields (e.g.,
Frankfurter's `date` and `rate` JSON keys) stay inside the provider
adapter and never leak into the core Evidence schema.

Architecture per spec §3:
  FXProvider (Protocol)
    ↓
  FrankfurterFXProvider       (real; v2 public API; no credential)
  MockFXProvider              (deterministic; for tests)

Per spec §15, this module is dependency-free at the module level
(urllib stdlib only). All canonical enums (failure kinds, freshness
buckets, verification statuses) are reused from price_intelligence.

v1.2.2 scope:
- FXProvider Protocol
- FrankfurterFXProvider (urllib-based, no credential)
- MockFXProvider (deterministic, env-flag driven)
- normalize_frankfurter_response() — Frankfurter JSON → FXEvidence
- FX search budget (10 default, 2 smoke-test cap)
- Date binding (rate_date, retrieved_at, freshness)
- Identity conversion (same currency → rate=1, no API call)
- Failure semantics (8 canonical failure kinds; per spec §7)
- Reused v1.1.5 freshness buckets (no parallel freshness scheme)

v1.2.2 does NOT:
- Implement ArbitrageEvidence
- Calculate arbitrage_score
- Rank opportunities
- Modify Jev scoring semantics
- Modify v1.1 PriceEvidence schema
- Implement baseline construction or parity validation
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

# Reuse canonical enums / failure kinds / freshness utilities from
# price_intelligence without modifying it. This guarantees v1.2.2 cannot
# redefine an enum and break contract equivalence.
import price_intelligence as _pi  # type: ignore[import-not-found]

# Failure kinds (we extend the v1.1 set with FX-specific ones; v1.1's
# CURRENCY_UNKNOWN is reused; FX_NOT_FOUND and INVALID_FX_RESPONSE and
# STALE_FX are new but stay distinct from BOOKABLE etc.)
FK_CURRENCY_UNKNOWN = _pi.FK_CURRENCY_UNKNOWN
FK_PROVIDER_TIMEOUT = _pi.FK_PROVIDER_TIMEOUT
FK_PROVIDER_ERROR = _pi.FK_PROVIDER_ERROR
FK_STALE_PRICE = _pi.FK_STALE_PRICE
FK_RATE_LIMITED = _pi.FK_RATE_LIMITED
FK_MISSING_CREDENTIALS = _pi.FK_MISSING_CREDENTIALS
FK_ROUTE_UNAVAILABLE = _pi.FK_ROUTE_UNAVAILABLE

# New FX-specific failure kinds (per spec §7)
FK_FX_NOT_FOUND = "FX_NOT_FOUND"
FK_INVALID_FX_RESPONSE = "INVALID_FX_RESPONSE"

FAILURE_KINDS_FX = {
    FK_FX_NOT_FOUND, FK_INVALID_FX_RESPONSE, FK_CURRENCY_UNKNOWN,
    FK_PROVIDER_TIMEOUT, FK_PROVIDER_ERROR, FK_STALE_PRICE,
    FK_RATE_LIMITED, FK_MISSING_CREDENTIALS, FK_ROUTE_UNAVAILABLE,
}

# Verification enum (5-tier, NO BOOKABLE)
VS_UNKNOWN = _pi.VS_UNKNOWN
VS_ESTIMATED = _pi.VS_ESTIMATED
VS_DATABASE = _pi.VS_DATABASE
VS_LIVE = _pi.VS_LIVE
VS_VERIFIED = _pi.VS_VERIFIED

# Source types
SRC_LIVE = _pi.SRC_LIVE
SRC_CACHE = _pi.SRC_CACHE
SRC_INDICATIVE = _pi.SRC_INDICATIVE

# Reuse freshness utilities (no parallel scheme per spec §6)
FRESHNESS_RECENT_MAX_MIN = _pi.FRESHNESS_RECENT_MAX_MIN
FRESHNESS_WARM_MAX_MIN = _pi.FRESHNESS_WARM_MAX_MIN
FRESHNESS_COLD_MAX_MIN = _pi.FRESHNESS_COLD_MAX_MIN


# -----------------------------------------------------------------------------
# Public constants
# -----------------------------------------------------------------------------

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
FX_EVIDENCE_PATH = DATA_DIR / "fx_evidence_v1_2_2.json"
FX_TRACE_PATH = DATA_DIR / "fx_trace_v1_2_2.json"
SYNTHETIC_FX_FIXTURES_PATH = DATA_DIR / "_synthetic_fx_fixtures_v1_2_2.json"

# Frankfurter v2 API (per official docs at https://frankfurter.dev)
# - No credential required
# - Historical data back to 1948
# - Source: 84 central banks
# - Time zone: UTC
# - Latest endpoint returns today's rate (latest available)
# - Historical endpoint: returns end-of-day UTC value, or empty array
#   for future dates
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev"
FRANKFURTER_RATE_ENDPOINT = "/v2/rate/{base}/{quote}"
FRANKFURTER_RATES_ENDPOINT = "/v2/rates"
FRANKFURTER_CURRENCIES_ENDPOINT = "/v2/currencies"

# Frankfurter does NOT require a credential. We do not accept one.
# This is documented as a hard architectural decision (see §11 below).

# Per spec §5: distinguish "latest/current FX" from "historical FX".
# If `date_window` matches today (UTC), we fetch latest; otherwise historical.

# Forbidden identifiers (defensive guard in normalized output)
_FORBIDDEN_KEYS = ("arbitrage_score", "arbitrage_opportunity",
                   "net_arbitrage", "booking_status", "BOOKABLE")


# -----------------------------------------------------------------------------
# FX search budget
# -----------------------------------------------------------------------------

class FXSearchBudget:
    """Track per-run FX search budget with memoization.

    Default max 10 searches per run; smoke-test caps at 2.
    Identity conversions (same currency) do NOT consume the budget.
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
# FXProvider Protocol
# -----------------------------------------------------------------------------

class FXProvider(Protocol):
    """FX evidence provider protocol (analogous to PriceProvider)."""

    @property
    def name(self) -> str: ...

    def capabilities(self) -> dict[str, Any]: ...

    def health_check(self) -> bool: ...

    def quote(self, base: str, quote: str, *,
              rate_date: str | None = None) -> dict[str, Any]:
        """Return an FXLookupResult-like dict.

        Success shape: {"success": True, "fx_evidence": {...},
                        "retrieved_at": ISO8601, ...}

        Failure shape: {"success": False, "fx_evidence": None,
                        "failure_kind": str, ...}
        """


def build_failure_result(failure_kind: str, retrieved_at: str,
                         message: str = "") -> dict[str, Any]:
    return {
        "success": False,
        "fx_evidence": None,
        "failure_kind": failure_kind,
        "failure_reason": message or failure_kind,
        "raw_response_hash": None,
        "elapsed_ms": 0,
        "retrieved_at": retrieved_at,
    }


def build_success_result(fx_payload: dict[str, Any],
                         raw_response: dict[str, Any],
                         retrieved_at: str, elapsed_ms: int) -> dict[str, Any]:
    raw_hash = hashlib.sha256(
        json.dumps(raw_response, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return {
        "success": True,
        "fx_evidence": fx_payload,
        "failure_kind": None,
        "failure_reason": None,
        "raw_response_hash": raw_hash,
        "elapsed_ms": elapsed_ms,
        "retrieved_at": retrieved_at,
    }


# -----------------------------------------------------------------------------
# FrankfurterFXProvider (real)
# -----------------------------------------------------------------------------

class FrankfurterFXProvider:
    """Real Frankfurter v2 client. NO CREDENTIAL required (per official docs).

    Per spec §11: "If Frankfurter does not need credential: explicitly
    document 'No credential required by the documented public API.'"

    Architecture:
      - latest rate: GET /v2/rate/{base}/{quote}
      - historical rate: GET /v2/rate/{base}/{quote}?date=YYYY-MM-DD
        (NOTE: Frankfurter's `/v2/rate/{base}/{quote}` accepts a `?date=` query
        parameter; this is how the public docs handle historical single-pair)
      - bulk rates: GET /v2/rates?base=USD&quotes=EUR (used only for
        health_check)
    """

    def __init__(self, base_url: str = FRANKFURTER_BASE_URL):
        # No credential — constructor takes only an optional base_url override
        # for test/self-hosted scenarios.
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "frankfurter"

    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_live": True,
            "supports_historical": True,
            "supports_identity_conversion": False,  # we handle that in adapter
            "supports_no_credential": True,
            "freshness_ttl_min": 60 * 24,    # historical; today's rate valid until EOD UTC
            "rate_limit_per_min": 60,        # undocumented; conservative default
            "currency_coverage": "201 currencies from 84 central banks",
            "history_back_to": "1948",
        }

    def health_check(self) -> bool:
        try:
            url = f"{self._base_url}{FRANKFURTER_RATES_ENDPOINT}?base=EUR&quotes=USD"
            req = urllib.request.Request(url, method="GET",
                                          headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception:
            return False

    def quote(self, base: str, quote: str, *,
              rate_date: str | None = None) -> dict[str, Any]:
        """Fetch the rate from `base` to `quote`, optionally for a
        specific historical date.

        Returns a PriceLookupResult-like dict. Identity conversions
        (base == quote, case-insensitive) are handled here: rate=1, no
        API call, no budget consumed.
        """
        retrieved_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        if not base or not quote:
            return build_failure_result(FK_CURRENCY_UNKNOWN, retrieved_at,
                                         "missing base or quote")

        base_u = base.upper()
        quote_u = quote.upper()

        # Per spec §9: identity conversion (EUR → EUR) should not call API
        if base_u == quote_u:
            fx_payload = normalize_identity_conversion(
                base_u, quote_u, retrieved_at,
                rate_date=rate_date,
                provider_name=self.name,
            )
            return build_success_result(
                fx_payload, raw_response={"type": "identity"},
                retrieved_at=retrieved_at, elapsed_ms=0,
            )

        # Build URL. Frankfurter's `/v2/rate/{base}/{quote}` accepts an
        # optional `?date=YYYY-MM-DD` query parameter for historical rates.
        path = FRANKFURTER_RATE_ENDPOINT.format(base=base_u, quote=quote_u)
        url = f"{self._base_url}{path}"
        if rate_date:
            url += f"?date={rate_date}"

        try:
            req = urllib.request.Request(
                url, method="GET",
                # Per observation: Frankfurter rejects the Python urllib
                # default User-Agent with 403. Must set a UA.
                headers={
                    "Accept": "application/json",
                    "User-Agent": "fx_provider_v1_2_2/1.0 (no-credential)",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                raw_text = r.read().decode("utf-8")
                raw = json.loads(raw_text)
        except urllib.error.HTTPError as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            if e.code == 429:
                return build_failure_result(FK_RATE_LIMITED, retrieved_at,
                                             f"http {e.code}")
            if e.code == 404:
                return build_failure_result(FK_FX_NOT_FOUND, retrieved_at,
                                             f"http 404 (rate not found)")
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         f"http {e.code}")
        except (urllib.error.URLError, TimeoutError):
            elapsed_ms = int((time.time() - t0) * 1000)
            return build_failure_result(FK_PROVIDER_TIMEOUT, retrieved_at,
                                         "request timeout")
        except (json.JSONDecodeError, ValueError) as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            return build_failure_result(FK_INVALID_FX_RESPONSE, retrieved_at,
                                         f"invalid JSON: {e}")
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         str(e))

        elapsed_ms = int((time.time() - t0) * 1000)
        fx_payload = normalize_frankfurter_response(
            raw, base_u, quote_u, retrieved_at,
            rate_date=rate_date,
            provider_name=self.name,
        )
        if not isinstance(fx_payload, dict):
            return build_failure_result(fx_payload, retrieved_at,
                                         "normalize failed")
        return build_success_result(fx_payload, raw_response=raw,
                                     retrieved_at=retrieved_at,
                                     elapsed_ms=elapsed_ms)


# -----------------------------------------------------------------------------
# MockFXProvider (deterministic, for tests)
# -----------------------------------------------------------------------------

class MockFXProvider:
    """Synthetic FX responses for tests. Deterministic.

    Per spec §9 fixtures: USD→EUR, JPY→EUR, BDT→EUR, EUR→EUR,
    plus unsupported currency, missing FX, stale FX, provider error,
    timeout, invalid response.
    """

    # Deterministic rates (kept stable for test repeatability)
    MOCK_RATES = {
        ("USD", "EUR"): 0.92,
        ("EUR", "USD"): 1.087,
        ("JPY", "EUR"): 0.0061,
        ("EUR", "JPY"): 163.93,
        ("GBP", "EUR"): 1.17,
        ("EUR", "GBP"): 0.854,
        ("TWD", "EUR"): 0.028,
        ("EUR", "TWD"): 35.71,
        # Note: BDT (Bangladeshi Taka) intentionally omitted — exercises
        # the unsupported-currency path (FX_NOT_FOUND).
    }

    def __init__(self):
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock_frankfurter"

    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_live": True,
            "supports_historical": True,
            "supports_identity_conversion": False,
            "supports_no_credential": True,
            "freshness_ttl_min": 60 * 24,
            "rate_limit_per_min": 1000,
            "currency_coverage": "deterministic subset; BDT unsupported",
            "history_back_to": "mock",
        }

    def health_check(self) -> bool:
        return True

    def quote(self, base: str, quote: str, *,
              rate_date: str | None = None) -> dict[str, Any]:
        self._call_count += 1
        retrieved_at = datetime.now(timezone.utc).isoformat()

        # Failure-flag simulation
        flags = {k: os.environ.get(k, "0") == "1" for k in [
            "SIMULATE_FX_TIMEOUT", "SIMULATE_FX_ERROR", "SIMULATE_FX_RATE_LIMITED",
            "SIMULATE_FX_INVALID_RESPONSE", "SIMULATE_FX_STALE",
        ]}
        if flags.get("SIMULATE_FX_TIMEOUT"):
            return build_failure_result(FK_PROVIDER_TIMEOUT, retrieved_at,
                                         "simulated timeout")
        if flags.get("SIMULATE_FX_ERROR"):
            return build_failure_result(FK_PROVIDER_ERROR, retrieved_at,
                                         "simulated provider error")
        if flags.get("SIMULATE_FX_RATE_LIMITED"):
            return build_failure_result(FK_RATE_LIMITED, retrieved_at,
                                         "simulated rate limited")
        if flags.get("SIMULATE_FX_INVALID_RESPONSE"):
            return build_failure_result(FK_INVALID_FX_RESPONSE, retrieved_at,
                                         "simulated invalid response")

        if not base or not quote:
            return build_failure_result(FK_CURRENCY_UNKNOWN, retrieved_at,
                                         "missing base or quote")

        base_u = base.upper()
        quote_u = quote.upper()

        # Identity conversion (no API call)
        if base_u == quote_u:
            fx_payload = normalize_identity_conversion(
                base_u, quote_u, retrieved_at,
                rate_date=rate_date,
                provider_name=self.name,
            )
            return build_success_result(
                fx_payload, raw_response={"type": "identity"},
                retrieved_at=retrieved_at, elapsed_ms=0,
            )

        # FX_NOT_FOUND for unsupported pair
        rate = self.MOCK_RATES.get((base_u, quote_u))
        if rate is None:
            return build_failure_result(FK_FX_NOT_FOUND, retrieved_at,
                                         f"no mock rate for {base_u}->{quote_u}")

        # Stale simulation: override rate_date to a stale day
        effective_rate_date = rate_date
        if flags.get("SIMULATE_FX_STALE"):
            effective_rate_date = "2020-01-01"   # very old

        # Build synthetic Frankfurter-shaped response
        raw = {
            "amount": 1.0,
            "base": base_u,
            "date": effective_rate_date or datetime.now(timezone.utc).date().isoformat(),
            "rates": {quote_u: rate},
        }
        fx_payload = normalize_frankfurter_response(
            raw, base_u, quote_u, retrieved_at,
            rate_date=effective_rate_date,
            provider_name=self.name,
        )
        if not isinstance(fx_payload, dict):
            return build_failure_result(fx_payload, retrieved_at,
                                         "normalize failed")
        return build_success_result(fx_payload, raw_response=raw,
                                     retrieved_at=retrieved_at,
                                     elapsed_ms=2)


# -----------------------------------------------------------------------------
# Normalization (Frankfurter response → FXEvidence)
# -----------------------------------------------------------------------------

def normalize_frankfurter_response(raw: dict[str, Any], base: str, quote: str,
                                     retrieved_at: str,
                                     rate_date: str | None = None,
                                     provider_name: str = "frankfurter") -> dict[str, Any] | str:
    """Convert a Frankfurter response into a normalized FXEvidence payload.

    Returns the payload dict, or a string error code if normalization failed.

    `provider_name` must be one of {"frankfurter", "mock_frankfurter"} so
    identity is non-confusable.

    Per spec §5: date binding surfaces BOTH `rate_date` (the FX rate's
    effective date, e.g., from Frankfurter's `date` field) AND
    `retrieved_at` (when our adapter called the API). The two MUST be
    distinct.
    """
    if provider_name not in ("frankfurter", "mock_frankfurter"):
        return FK_PROVIDER_ERROR

    base_u = (base or "").upper()
    quote_u = (quote or "").upper()
    if not base_u or not quote_u:
        return FK_CURRENCY_UNKNOWN

    # Frankfurter returns:
    #   /v2/rate/{base}/{quote}     → {"amount": 1.0, "base": "EUR", "date": "2026-09-27", "rates": {"USD": 1.1398}}
    #   /v2/rates?base=...&quotes= → [{"date": "2026-09-27", "base": "USD", "quote": "EUR", "rate": 0.87736}, ...]
    # Normalize both shapes.
    fx_rate_date = None
    fx_rate = None

    if isinstance(raw, dict):
        # Object shape
        if "rates" in raw and isinstance(raw["rates"], dict):
            # /v2/rate/{base}/{quote} or /v2/rates?base=USD shape
            fx_rate = raw["rates"].get(quote_u)
            fx_rate_date = raw.get("date")
        elif "rate" in raw:
            fx_rate = raw.get("rate")
            fx_rate_date = raw.get("date")
    elif isinstance(raw, list) and raw:
        # Array shape (from /v2/rates?quotes=EUR)
        for row in raw:
            if (isinstance(row, dict)
                    and row.get("base") == base_u
                    and row.get("quote") == quote_u):
                fx_rate = row.get("rate")
                fx_rate_date = row.get("date")
                break

    if fx_rate is None:
        return FK_FX_NOT_FOUND

    try:
        fx_rate = float(fx_rate)
    except (TypeError, ValueError):
        return FK_INVALID_FX_RESPONSE

    # Normalize rate_date
    if fx_rate_date:
        # Frankfurter dates are YYYY-MM-DD
        if not isinstance(fx_rate_date, str):
            fx_rate_date = str(fx_rate_date)
    if rate_date:
        # Explicit override (e.g., historical request) takes precedence
        fx_rate_date = rate_date

    # Per spec §5: distinguish "latest" vs "historical"
    today = datetime.now(timezone.utc).date().isoformat()
    is_historical = bool(fx_rate_date and fx_rate_date != today)
    freshness_label = "historical" if is_historical else "latest/current"

    # Compute freshness_min based on retrieved_at only (canonical scheme)
    fmin = _pi.compute_freshness_min(retrieved_at)
    fbucket = _pi.freshness_bucket_from_min(fmin) if fmin >= 0 else "FRESHNESS_UNKNOWN"

    payload: dict[str, Any] = {
        "schema_version": "v1.2.2",
        "provider": provider_name,
        "provider_mode": "live" if provider_name == "frankfurter" else "mock",
        "base_currency": base_u,
        "quote_currency": quote_u,
        "rate": fx_rate,
        "rate_date": fx_rate_date,            # the FX rate's effective date
        "rate_source_type": "historical" if is_historical else "latest/current",
        "retrieved_at": retrieved_at,          # when our adapter called API
        "freshness_min": fmin,
        "freshness_bucket": fbucket,
        "freshness_label": freshness_label,    # human-readable hint
        "verification_status": VS_LIVE,        # per spec §4
        "source": "frankfurter",
        "endpoint": "/v2/rate/{base}/{quote}",
        "request_metadata": {
            "is_historical_request": is_historical,
            "explicit_rate_date": rate_date,
        },
        # Per spec §5: explicit about what the evidence is
        "is_identity": False,
        "supports_no_credential": True,
        "warnings": [],
        "failure_reason": None,
        "failure_kind": None,
        "provenance": {
            "source": provider_name,
            "source_type": SRC_LIVE if provider_name == "frankfurter" else SRC_CACHE,
            "endpoint": "/v2/rate/{base}/{quote}",
            "retrieved_at": retrieved_at,
            "rate_date": fx_rate_date,
            "verification_status": VS_LIVE,
        },
    }

    # Defensive guard
    for forbidden in _FORBIDDEN_KEYS:
        if forbidden in payload:
            raise AssertionError(f"Forbidden key in FXEvidence: {forbidden}")

    return payload


def normalize_identity_conversion(base: str, quote: str, retrieved_at: str,
                                    rate_date: str | None = None,
                                    provider_name: str = "frankfurter") -> dict[str, Any]:
    """Build an FXEvidence payload for identity conversion (base == quote).

    Per spec §9: "EUR → EUR should produce identity conversion: rate=1,
    not an unnecessary API call."
    """
    base_u = (base or "").upper()
    quote_u = (quote or "").upper()
    fmin = _pi.compute_freshness_min(retrieved_at)
    fbucket = _pi.freshness_bucket_from_min(fmin) if fmin >= 0 else "FRESHNESS_UNKNOWN"
    return {
        "schema_version": "v1.2.2",
        "provider": provider_name,
        "provider_mode": "live" if provider_name == "frankfurter" else "mock",
        "base_currency": base_u,
        "quote_currency": quote_u,
        "rate": 1.0,
        "rate_date": rate_date,
        "rate_source_type": "identity",
        "retrieved_at": retrieved_at,
        "freshness_min": fmin,
        "freshness_bucket": fbucket,
        "freshness_label": "identity (no API call)",
        "verification_status": VS_DATABASE,   # identity is structural, not live
        "source": "identity",
        "endpoint": None,
        "request_metadata": {
            "is_historical_request": False,
            "explicit_rate_date": rate_date,
        },
        "is_identity": True,
        "supports_no_credential": True,
        "warnings": [],
        "failure_reason": None,
        "failure_kind": None,
        "provenance": {
            "source": provider_name,
            "source_type": SRC_CACHE,           # identity, no real call
            "endpoint": None,
            "retrieved_at": retrieved_at,
            "rate_date": rate_date,
            "verification_status": VS_DATABASE,
            "note": "identity conversion; no API call consumed",
        },
    }


# -----------------------------------------------------------------------------
# FXSearchBudget + CLI orchestration
# -----------------------------------------------------------------------------

def build_fx_provider(spec: str) -> FXProvider:
    """Construct an FXProvider from a CLI spec string.

    Modes:
      frankfurter  → FrankfurterFXProvider (real; no creds)
      mock         → MockFXProvider (deterministic)
      auto         → frankfurter if available, else mock (with explicit log)
    """
    spec = (spec or "").lower()
    if spec == "frankfurter":
        return FrankfurterFXProvider()
    if spec == "mock":
        return MockFXProvider()
    if spec == "auto":
        try:
            real = FrankfurterFXProvider()
            print("[fx-auto] using real FrankfurterFXProvider (no credential needed)",
                  file=sys.stderr)
            return real
        except Exception as e:
            print(f"[fx-auto] real Frankfurter unavailable ({e}); using MockFXProvider",
                  file=sys.stderr)
            return MockFXProvider()
    raise ValueError(f"unknown fx provider: {spec}")


def _print_observability(summary: dict[str, Any], provider_name: str,
                          started: str) -> None:
    print("\n" + "=" * 60, file=sys.stderr)
    print("FX PROVIDER v1.2.2 — OBSERVABILITY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  fx_provider                                  {provider_name}", file=sys.stderr)
    print(f"  started_at                                   {started}", file=sys.stderr)
    print(f"  conversions_requested                        {summary['conversions_requested']}", file=sys.stderr)
    print(f"  conversions_succeeded                        {summary['conversions_succeeded']}", file=sys.stderr)
    print(f"  conversions_failed                           {summary['conversions_failed']}", file=sys.stderr)
    print(f"  identity_conversions                         {summary['identity_conversions']}", file=sys.stderr)
    print(f"  conversions_skipped_for_budget               {summary['conversions_skipped_for_budget']}", file=sys.stderr)
    print(f"  search_budget_used                           {summary['search_budget_used']}", file=sys.stderr)
    print(f"  search_budget_max                            {summary['search_budget_max']}", file=sys.stderr)
    print(f"  verification_status_distribution             {dict(summary['verification_status_distribution'])}", file=sys.stderr)
    print(f"  freshness_bucket_distribution                {dict(summary['freshness_bucket_distribution'])}", file=sys.stderr)
    print(f"  failure_kind_distribution                    {dict(summary['failure_kind_distribution'])}", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FX Provider v1.2.2 — Frankfurter")
    parser.add_argument("--fx-provider", default="frankfurter",
                         help="frankfurter | mock | auto")
    parser.add_argument("--max-searches", type=int, default=10)
    parser.add_argument("--smoke-test", action="store_true",
                         help="Enforce max 2 FX searches")
    parser.add_argument("--base", default="USD")
    parser.add_argument("--quote", default="TWD")
    parser.add_argument("--rate-date", default=None,
                         help="YYYY-MM-DD for historical FX (default: latest)")
    parser.add_argument("--output", type=Path, default=str(FX_EVIDENCE_PATH))
    parser.add_argument("--trace", type=Path, default=str(FX_TRACE_PATH))
    args = parser.parse_args(argv)

    if args.smoke_test and args.max_searches > 2:
        print(f"[smoke-test] overriding max_searches from {args.max_searches} to 2",
              file=sys.stderr)
        args.max_searches = 2

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\nFX Provider v1.2.2", file=sys.stderr)
    print(f"  FX-provider spec: {args.fx_provider}", file=sys.stderr)
    print(f"  Base: {args.base}  Quote: {args.quote}  Rate-date: {args.rate_date or 'latest'}",
          file=sys.stderr)
    print(f"  Max searches: {args.max_searches}", file=sys.stderr)
    if args.smoke_test:
        print(f"  Smoke test mode: ENABLED (max 2 real API requests)", file=sys.stderr)

    try:
        provider = build_fx_provider(args.fx_provider)
    except ValueError as e:
        print(f"\n[ERROR] Invalid provider: {e}", file=sys.stderr)
        return 11

    print(f"  Provider instance: {provider.name}", file=sys.stderr)
    print(f"  Provider health: {provider.health_check()}", file=sys.stderr)

    # Single-conversion CLI mode: --base / --quote / --rate-date
    budget = FXSearchBudget(max_searches=args.max_searches)
    summary = {
        "conversions_requested": 1,
        "conversions_succeeded": 0,
        "conversions_failed": 0,
        "identity_conversions": 0,
        "conversions_skipped_for_budget": 0,
        "search_budget_used": 0,
        "search_budget_max": args.max_searches,
        "verification_status_distribution": {},
        "freshness_bucket_distribution": {},
        "failure_kind_distribution": {},
    }

    # Identity conversions don't consume budget (per spec §9)
    is_identity = args.base.upper() == args.quote.upper()
    if is_identity:
        summary["identity_conversions"] = 1
        result = provider.quote(args.base, args.quote, rate_date=args.rate_date)
    elif not budget.can_attempt():
        summary["conversions_skipped_for_budget"] = 1
        retrieved_at = datetime.now(timezone.utc).isoformat()
        result = build_failure_result(
            "RATE_LIMITED", retrieved_at,
            "search budget exhausted")
    else:
        result = provider.quote(args.base, args.quote, rate_date=args.rate_date)
        memo_key = f"{args.base}|{args.quote}|{args.rate_date or 'latest'}"
        budget.record(memo_key, result)

    summary["search_budget_used"] = budget.used

    evidences: list[dict[str, Any]] = []
    if result["success"]:
        summary["conversions_succeeded"] = 1
        pe = result["fx_evidence"]
        evidences.append({
            "base": args.base,
            "quote": args.quote,
            "provider": pe.get("provider"),
            "provider_mode": pe.get("provider_mode"),
            "verification_status": pe.get("verification_status"),
            "fx_evidence": pe,
            "retrieved_at": result.get("retrieved_at"),
            "rate_date": pe.get("rate_date"),
            "rate": pe.get("rate"),
        })
        vs = pe.get("verification_status")
        fbucket = pe.get("freshness_bucket")
        summary["verification_status_distribution"][vs] = (
            summary["verification_status_distribution"].get(vs, 0) + 1)
        summary["freshness_bucket_distribution"][fbucket] = (
            summary["freshness_bucket_distribution"].get(fbucket, 0) + 1)
    else:
        summary["conversions_failed"] = 1
        fk = result.get("failure_kind") or "PROVIDER_ERROR"
        summary["failure_kind_distribution"][fk] = (
            summary["failure_kind_distribution"].get(fk, 0) + 1)
        evidences.append({
            "base": args.base,
            "quote": args.quote,
            "provider": provider.name,
            "provider_mode": "live" if provider.name == "frankfurter" else "mock",
            "fx_evidence": None,
            "retrieved_at": result.get("retrieved_at"),
            "failure_kind": fk,
            "failure_reason": result.get("failure_reason"),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "fx_provider_v1_2_2",
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "fx_provider": provider.name,
        "smoke_test": args.smoke_test,
        "summary": summary,
        "evidences": evidences,
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n  Output: {args.output}", file=sys.stderr)

    trace_payload = {
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "fx_provider": provider.name,
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

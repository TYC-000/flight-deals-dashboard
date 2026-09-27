# Kiwi PriceProvider — v1.2.0 (Implementation)

> Implementation of the Kiwi Tequila PriceProvider integration per
> the v1.1.5 Evidence Source Matrix Gap A ("second price producer").
>
> This document covers: API access status, authentication, provider
> modes, normalization, provenance, freshness, failure semantics,
> limitations, smoke-test status, and schema compatibility.

---

## 1. API access status

| Item | Status |
|---|---|
| Public API availability        | **REST API documented; new access invitation-only as of May 2024** |
| Documentation                  | Available at `https://tequila.kiwi.com/portal/docs/tequila_api` (B2B partner portal) |
| New account registration       | **Closed** — only via B2B partner application to `affiliates@kiwi.com` |
| Existing partner keys          | **Valid** — existing partner keys continue to work |
| Endpoint                       | `GET https://api.tequila.kiwi.com/v2/search` |
| Authentication header          | `apikey` (NOT `Authorization: Bearer`) |

### Reference

- `https://tequila.kiwi.com/portal/docs/tequila_api`
- `https://github.com/ohm-vision/kiwi-tequila-api` (unofficial SDK)
- `https://docs.skypickerpublicapi.apiary.io` (legacy search API)
- `https://github.com/kiwicom/kiwicom-python` (legacy Python wrapper)

---

## 2. Authentication

Two env vars are read in priority order:
- `KIWI_API_KEY`
- `KIWI_TEQUILA_API_KEY`

The `apikey` header is set by the adapter directly; the value is
**NEVER** logged, **NEVER** propagated into the normalized
PriceEvidence, and **NEVER** written to trace files.

The `MISSING_CREDENTIALS` failure kind is raised when neither env
var is set under `--provider kiwi`. This is fail-closed (rc=10) per
v1.1.1 + v1.2.0 §4.

---

## 3. Provider modes

| CLI flag | Behavior |
|---|---|
| `--provider kiwi`        | Use `KiwiPriceProvider` (real). Fail closed with rc=10 if no credential. |
| `--provider mock_kiwi`   | Use `MockKiwiProvider` (deterministic, no network). |
| `--provider auto`        | If Duffel creds present → real DuffelProvider; else if Kiwi creds present → real KiwiPriceProvider; else → `MockDuffelProvider` with explicit log line. |
| `--provider duffel`      | **Unchanged from v1.1.1.** Never falls back to Kiwi or Mock. |
| `--provider mock`        | **Unchanged from v1.1.1.** `MockDuffelProvider` only. |

**No silent substitution.** Specified provider mode is honored.

---

## 4. Normalization

`normalize_kiwi_response()` converts a Kiwi `/v2/search` response
into the same `PriceEvidence` schema produced by
`price_intelligence.normalize_duffel_response()`.

### 4.1 Key transformations

| Kiwi field         | PriceEvidence field      | Notes |
|---|---|---|
| `data[].id`               | `provenance.offer_id`     | unique per itinerary |
| `data[].price`            | `total_price.amount`      | float |
| `data[].currency`         | `currency` (uppercased)   | do NOT convert; FX is v1.2.x |
| `data[].route[]`          | `ticket_groups[].stops[]` | carrier-change → new group |
| `route[].flyFrom/flyTo`   | `stops[].from/to`         | same field names |
| `route[].airline`         | `stops[].carrier`         | marketing carrier |
| `route[].operating_carrier` | `stops[].operating_carrier` | when disclosed |
| `route[].flight_no`       | `stops[].flight_number`   | string |
| `route[].local_departure` | `stops[].depart`          | producer timestamp |
| `route[].local_arrival`   | `stops[].arrive`          | producer timestamp |
| `data[].bags_price`       | `baggage.included.*`      | cost-aware; 0 = included |

### 4.2 Multi-ticket inference

Kiwi does **not** return a `type: "split_ticket"` field the way
Duffel does. Instead, Kiwi's "Virtual Interlining" produces
itineraries where non-cooperating carriers implicitly form separate
PNRs.

v1.2.0 approximates this by treating each contiguous sequence of
**same-airline** segments as one ticket group. A change of
marketing_carrier triggers a new group. This is structurally
identical to Duffel's split_ticket representation in terms of the
downstream contract.

### 4.3 Provider-specific leakage guard

The following Kiwi-specific fields are **never** propagated into the
normalized `PriceEvidence`:

- `booking_token`
- `deep_link`
- `bags_price` (raw) — only the inferred `baggage.included.*` block
- `passengers[]` raw (Kiwi may return more granular passenger info)

---

## 5. Provenance

| Field | Mock Kiwi | Real Kiwi |
|---|---|---|
| `provider`            | `"mock_kiwi"` | `"kiwi"` |
| `provider_mode`       | `"mock"`      | `"live"` |
| `provenance.source`   | `"mock_kiwi"` | `"kiwi"` |
| `provenance.source_type` | `SRC_CACHE` (`"cache"`) | `SRC_LIVE` (`"live"`) |
| `provenance.endpoint` | `"/v2/search"` | `"/v2/search"` |

Identity is non-confusable across all four producer / mode combinations:
`{mock_duffel, duffel, mock_kiwi, kiwi}`.

---

## 6. Freshness

Per spec §8:

| Field | Source |
|---|---|
| `retrieved_at`           | computed at adapter call time, NOT trusted from producer |
| `freshness_min`          | computed by `price_intelligence.compute_freshness_min` |
| `freshness_bucket`       | one of RECENT/WARM/COLD/EXPIRED/UNKNOWN |
| `valid_until`            | **None** — Kiwi does NOT return per-offer expiry |
| `price_quote_expires_at` | **None** — same |
| `freshness_ttl_min`      | 15 (documented in capabilities; used by `select_candidates`) |

The `valid_until == None` is a **documented limitation**, not an
oversight. It is preserved explicitly so downstream consumers can
distinguish "no expiry known" from "expires soon".

---

## 7. Failure semantics

All 11 canonical FailureKinds from v1.1 are honored:

| FailureKind                       | Trigger |
|---|---|
| `MISSING_CREDENTIALS`             | `--provider kiwi` without `KIWI_API_KEY` / `KIWI_TEQUILA_API_KEY` |
| `PRICE_NOT_FOUND`                 | Empty `data[]` from Kiwi, or no segments in candidate |
| `ROUTE_UNAVAILABLE`               | Missing origin / destination |
| `CURRENCY_UNKNOWN`                | `SIMULATE_CURRENCY_UNKNOWN=1` (mock) or empty currency (real) |
| `BAGGAGE_UNKNOWN`                 | `SIMULATE_BAGGAGE_UNKNOWN=1` (mock) or no baggage info (real) |
| `PROVIDER_TIMEOUT`                | `urllib.URLError` / `TimeoutError` |
| `PROVIDER_ERROR`                  | HTTP non-200, non-429; or other exception |
| `RATE_LIMITED`                    | HTTP 429 |
| `STALE_PRICE`                     | `SIMULATE_STALE_PRICE=1` (mock); no real equivalent |
| `PARTIAL_PRICE`                   | `SIMULATE_PARTIAL_PRICE=1` (mock) |
| `MULTI_TICKET_PRICE_INCOMPLETE`   | Multi-segment candidate with single ticket_group produced |

`PROVIDER_ERROR` is **NEVER** interpreted as:
- "expensive"
- "no arbitrage"
- "no opportunity"

(per spec §12 / v1.1.4 §12).

---

## 8. Limitations

### 8.1 Per Kiwi's documented behavior (permanent)

| Limitation | Impact |
|---|---|
| **Cabin not surfaced in itinerary** | `cabin == null` in PriceEvidence. Documented. |
| **Fare rules unavailable at search time** | `refundable / changeable / change_fee / refund_fee` all null. Documented in v1.1.4 §5.2. |
| **Equipment (aircraft) sometimes null** | Optional field; producer doesn't always disclose. |
| **No `expires_at`** | `valid_until == None`. |
| **Booking must happen via Kiwi deeplink** | Not relevant to v1.2.0 (no booking flow). |

### 8.2 Implementation limitations

| Limitation | Notes |
|---|---|
| Multi-city routes use the FIRST segment's origin and LAST segment's destination | Kiwi's `/v2/flights_multi` would be more accurate; not implemented in v1.2.0 (single-route only) |
| Multi-ticket inference uses marketing_carrier-change heuristic | Approximation of Kiwi's Virtual Interlining; may misclassify rare interline cases |
| `total_price` subtotal per group is duplicated in the first group | Kiwi does not return per-group subtotals; the entire total goes into the first group for accounting; documented as a known shape |

### 8.3 Real API validation

**KIWI REAL PROVIDER VALIDATION NOT PERFORMED.**

Reason: No `KIWI_API_KEY` / `KIWI_TEQUILA_API_KEY` was present in any
of the allowed credential locations (env, `~/.hermes/.env`, shell rc).
The Kiwi Tequila API requires B2B partner application, and we are not
in possession of a partner key.

The real `KiwiPriceProvider` is implemented (urllib-based), but its
first end-to-end validation is deferred until a credential is provided.

---

## 9. Smoke-test status

| Test | Result |
|---|---|
| Real Kiwi request count | **0** (no credential) |
| Real Kiwi response count | **0** |
| Real Kiwi failure count | **0** |
| Mock Kiwi request count | covered by 60-test v1.2.0 suite |
| Mock Kiwi response count | covered |
| Smoke-test hard-limit (`--smoke-test`) | **PASS** — caps at 2 even when `--max-searches 10` given |
| Provider health check | Mock returns True; real returns False on network failure (graceful) |

---

## 10. Schema compatibility

Verified by `test_kiwi_price_provider_v1_2_0.py` Test C: the canonical
44-key schema set from `normalize_duffel_response()` is fully
populated by `normalize_kiwi_response()` for the same canonical fields.

Fields that may differ between providers (and that's correct):

| Field | Duffel behavior | Kiwi behavior |
|---|---|---|
| `currency` | native (e.g., USD, EUR, GBP) | native (Kiwi's `currency` param; default USD) |
| `total_price.currency` | matches `currency` field | matches |
| `fare_type` | `"PUBLISHED"` if `base_amount` present | `null` (Kiwi doesn't surface) |
| `cabin` | populated from `passengers[].cabin` | `null` (Kiwi doesn't surface in itinerary) |
| `provenance.endpoint` | `air/offer_requests` | `/v2/search` |
| `provenance.source` | `duffel` / `mock_duffel` | `kiwi` / `mock_kiwi` |

The fields that **must not** differ are the identity, structural, and
freshness fields — all preserved.

---

## 11. Files added / modified

**Added:**
- `kiwi_price_provider.py` (700+ lines, real + mock + normalize + CLI)
- `test_kiwi_price_provider_v1_2_0.py` (60 assertions, 19 tests, all PASS)
- `docs/kiwi_price_provider_v1_2_0.md` (this document)

**Modified:**
- `price_intelligence.py` (`build_provider()` extended to support
  `kiwi`, `mock_kiwi`, and to make `auto` prefer Duffel, then Kiwi,
  then MockDuffelProvider)
- `data/price_evidence.json` (regenerated; `provider` field now
  can be one of `mock_duffel | duffel | mock_kiwi | kiwi`)
- `data/price_trace.json` (regenerated)

**NOT modified:**
- `candidate_discovery.py`, `schedule_intelligence.py`,
  `run_pipeline.py`, `eval_flight_yc.py`, `flight_dashboard.py`
  (per spec §17)

---

## 12. Regression results

| Suite | Tests | Status |
|---|---|---|
| v0.2          | 6   | ✅ PASS |
| v0.2.1        | 7   | ✅ PASS |
| v1.0          | 72  | ✅ PASS |
| v1.1          | 104 | ✅ PASS |
| v1.1.1        | 83  | ✅ PASS |
| **v1.2.0**    | **60** | ✅ **PASS** |

No regression. All existing tests continue to pass with no modification.

---

## STOP CONDITION

**v1.2.0 — Kiwi PriceProvider Integration COMPLETE.**

> **KIWI REAL PROVIDER VALIDATION NOT PERFORMED** — no credential available.
> Real `KiwiPriceProvider` is implemented and unit-tested (against
> `MISSING_CREDENTIALS` semantics). End-to-end round-trip validation is
> deferred until a real `KIWI_API_KEY` is provided.

Do **NOT** begin v1.2.1 (Live Schedule Upgrade) or Arbitrage Detection
automatically.

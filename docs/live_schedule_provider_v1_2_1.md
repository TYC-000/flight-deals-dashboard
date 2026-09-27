# Live Schedule Provider — v1.2.1 (Implementation)

> Implementation of the Live Schedule Upgrade per v1.1.5 Evidence Source
> Matrix Gap B. Closes the gap between **DATABASE route existence**
> (OpenFlights) and **LIVE schedule evidence** (Duffel `air/offer_requests`).
>
> v1.2.1 does NOT do arbitrage detection. It produces **ScheduleEvidence**
> alongside PriceEvidence; the comparison engine belongs to a later milestone.

---

## 1. Provider capabilities

Three concrete `ScheduleProvider` implementations:

| Provider | Verification | Per-date schedule | Aircraft | Connection time | Terminal |
|---|---|---|---|---|---|
| `OpenFlightsScheduleProvider` | `DATABASE` / `UNKNOWN` | ❌ | ❌ | ❌ | ❌ |
| `DuffelScheduleProvider`       | `LIVE`              | ✅ | ✅ | ✅ (computed) | ✅ (when disclosed) |
| `MockDuffelScheduleProvider`   | `LIVE` (mock)       | ✅ (synthetic) | ✅ (synthetic) | ✅ (computed) | ❌ |

The `ScheduleProvider` Protocol (per v1.1.5 §12):

```
class ScheduleProvider(Protocol):
    name: str
    capabilities() -> dict[str, Any]
    health_check() -> bool
    lookup(candidate, date_window, passengers=1) -> dict[str, Any]
```

## 2. API access status

### Duffel `air/offer_requests`

- **Endpoint**: `POST https://api.duffel.com/air/offer_requests?return_offers=true&supplier_timeout=15000`
- **Auth**: `Authorization: Bearer <DUFFEL_API_KEY_LIVE|TEST>` header
- **Headers**: `Duffel-Version: v2`, `Accept: application/json`, `Content-Type: application/json`
- **Rate limit**: 60 req/min
- **Cost**: $0.005/excess search (over 1500:1 search-to-book ratio)

### OpenFlights

- **Source**: cached at `/Users/aib/.hermes/cache/data/openflights/`
- **Files**: `airports.dat` (6,072 airports) + `routes.dat` (37,595 routes)
- **No network required**

## 3. Authentication

Duffel token discovery (priority order):
- `DUFFEL_API_KEY_LIVE`
- `DUFFEL_API_KEY_TEST`

Missing token under `--schedule-provider duffel` → `MISSING_CREDENTIALS` (rc=10).

**REAL LIVE SCHEDULE VALIDATION NOT PERFORMED** — no credential available in this environment.

## 4. Provider modes (CLI)

| `--schedule-provider` | Behavior |
|---|---|
| `openflights` | Always uses cached OpenFlights (DATABASE). No credential needed. |
| `duffel`      | Real DuffelScheduleProvider. **Fail closed** if no credential (rc=10). |
| `mock_duffel` | MockDuffelScheduleProvider. Deterministic, no network. |
| `auto`        | Duffel if credential, else OpenFlights (with explicit log line). |

**No silent substitution.** Specified mode is honored.

## 5. Normalized ScheduleEvidence

`normalize_duffel_schedule_response()` converts a Duffel `offer` (already
LIVE-priced) into a `ScheduleEvidence` record. The contract:

```python
ScheduleEvidence = {
    candidate_id,                 # str
    provider,                     # "duffel" | "mock_duffel" | "openflights"
    provider_mode,                # "live" | "mock" | "database"
    retrieved_at,                 # ISO8601 (computed at adapter call time)
    mission_date_window,          # YYYY-MM-DD or YYYY-MM-DD_to_YYYY-MM-DD
    searched_date,                # bound to mission_date_window
    expires_at,                   # offer's expires_at (Duffel); None for OpenFlights
    freshness,                    # bucket (computed by caller)
    verification_status,          # LIVE | DATABASE | UNKNOWN (NEVER BOOKABLE)
    schedule_status,              # SUPPORTED | PARTIAL | UNCERTAIN | UNAVAILABLE
    live_mode,                    # bool (Duffel-specific; surfaced as info)
    segments: [
        {
            segment_index, slice_index,
            origin, destination,
            departure_date, departure_time,
            arrival_date, arrival_time,
            departing_at_iso, arriving_at_iso,
            duration_minutes,
            flight_number,
            operating_carrier_flight_number,
            marketing_carrier,
            operating_carrier,        # preserved separately from marketing
            aircraft,                  # IATA aircraft code (when disclosed)
            verification_status,       # per-segment LIVE / DATABASE / UNKNOWN
        },
        ...
    ],
    connection_checks: [
        {
            between_segment_index,
            arrival_airport, departure_airport,
            connection_time_min,       # computed only when both timestamps present
            overnight_connection,      # bool | None
            tight_connection,          # bool | None (<90 min threshold)
            airport_change_required,   # bool | None
        },
        ...
    ],
    aircraft_in_disclosure,        # bool — any segment has aircraft?
    terminal_in_disclosure,         # bool
    live_search_used,               # bool — Duffel returned this via offer_request?
    warnings: [...],
    failure_reason,                 # None on success
    provenance: {
        source, source_type,        # "duffel" | "mock_duffel" | "openflights"
        endpoint,                   # "air/offer_requests" or "file://openflights/..."
        retrieved_at,
        offer_id | None,            # Duffel offer id; null for OpenFlights
        live_mode | None,            # Duffel `live_mode` field
        verification_status,
    },
}
```

Forbidden fields (defensive guard at normalize time):
`arbitrage_score`, `arbitrage_opportunity`, `net_arbitrage`, `booking_status`.

## 6. Date binding

- `mission_date_window` (user-supplied via `--date-window`) is bound into
  every evidence record.
- `searched_date` is bound to the same value (Duffel was queried for
  that date).
- `retrieved_at` is computed at the moment the adapter calls the
  producer — **NEVER** borrowed from PriceEvidence.
- OpenFlights evidence records the same fields, with `searched_date`
  reflecting that OpenFlights cannot narrow to a specific date.

## 7. Freshness

Independent from PriceEvidence per spec §16:

- `freshness` field is computed by `compute_schedule_freshness()` using
  the canonical `freshness_bucket_from_min` from `price_intelligence.py`.
- Schedule buckets: RECENT / WARM / COLD / EXPIRED / UNKNOWN.
- A FRESH price on a STALE schedule is acceptable ONLY with a
  `schedule_uncertainty` warning preserved.

## 8. Connection evidence (per spec §8)

| Field | Source | If missing |
|---|---|---|
| `connection_time_min` | `prev.arriving_at → next.departing_at` | `None` |
| `overnight_connection` | `arr.date != dep.date` | `None` |
| `tight_connection` | `connection_time_min < 90` | `None` |
| `airport_change_required` | `prev.destination != next.origin` | `None` |

All four are evidence-derived; never inferred.

For OpenFlights (no timestamps) all four are `None`. This is correct —
the route may exist, but we cannot compute connection timing without
real schedule data.

## 9. Airport change detection

`airport_change_required = True` iff:
- `prev_segment.destination` is known
- `next_segment.origin` is known
- The two airports are different (case-insensitive)

Examples:
- TPE→KUL→SIN: arrival KUL, departure KUL → **same → False**
- LHR→MAD, LGW→BCN: arrival LHR, departure LGW → **different → True** (self-transfer risk)
- Missing either airport → **None** (not False)

## 10. Operating carrier preservation

Per spec §10:
- `marketing_carrier` and `operating_carrier` are preserved **separately**.
- Duffel exposes both in `segments[].marketing_carrier.iata_code` and
  `segments[].operating_carrier.iata_code`.
- When operating carrier is unavailable, `operating_carrier = None`
  (NEVER collapsed into marketing_carrier).

## 11. Multi-city preservation

Per spec §11:
- Each candidate segment becomes its own Duffel slice in the request.
- The response's `slices[].segments[]` are flattened into
  `ScheduleEvidence.segments[]` with `slice_index` preserved.
- Multi-city candidates are NOT collapsed to first-origin / last-destination.
- If the provider cannot faithfully represent the candidate,
  the failure is surfaced via `failure_kind = ROUTE_UNAVAILABLE`,
  never by silent distortion.

## 12. Failure semantics

All 11 canonical FailureKinds from v1.1 are honored:

| FailureKind | Trigger |
|---|---|
| `MISSING_CREDENTIALS`             | `--schedule-provider duffel` without token |
| `ROUTE_UNAVAILABLE`               | No offers for the requested date; or no segments in candidate |
| `PROVIDER_TIMEOUT`                | urllib timeout / URLError |
| `PROVIDER_ERROR`                  | HTTP non-200, non-429 |
| `RATE_LIMITED`                    | HTTP 429 |

`PROVIDER_ERROR` is **NEVER** interpreted as:
- "expensive"
- "no arbitrage"
- "no opportunity"

## 13. OpenFlights reconciliation (spec §15)

Architecture:
```
OpenFlightsScheduleProvider     → DATABASE ScheduleEvidence
DuffelScheduleProvider          → LIVE ScheduleEvidence
```

Both evidence records are emitted as **independent observations** for the
same candidate:

```python
{
    "candidate_id": "...",
    "openflights": {
        "provider": "openflights",
        "verification_status": "DATABASE",
        "schedule_status": "SUPPORTED" | "PARTIAL" | "UNCERTAIN",
        "verification_status": "DATABASE",
    },
    "duffel": {
        "provider": "duffel",
        "verification_status": "LIVE",
        "schedule_status": "SUPPORTED",
    },
}
```

If OpenFlights says `SUPPORTED` and Duffel says `ROUTE_UNAVAILABLE`,
the disagreement is **explicitly preserved** — neither is hidden or
overridden.

## 14. Smoke-test status

| Metric | Value |
|---|---|
| Real Duffel schedule requests   | **0** (no credential) |
| Real Duffel schedule responses  | **0** |
| Real Duffel schedule failures   | **0** |
| Mock Duffel schedule requests   | covered by 97-test v1.2.1 suite |
| Smoke-test hard limit (`--smoke-test`) | **PASS** — caps at 2 even when `--max-searches 10` given |

**REAL LIVE SCHEDULE VALIDATION NOT PERFORMED.**

## 15. Limitations

### 15.1 Permanent (per current commercial providers)

| Limitation | Notes |
|---|---|
| Fare rules unavailable at search time | Per v1.1.4 §5.2 |
| Cabin not always surfaced on OpenFlights | DB dump does not include per-flight cabin |
| Operating carrier equipment occasionally null | When producer doesn't disclose |

### 15.2 v1.2.1 implementation limitations

| Limitation | Notes |
|---|---|
| OpenFlights connection_time_min is always None | OpenFlights has no per-segment timestamps |
| OpenFlights aircraft is always None | OpenFlights has no equipment data |
| MockDuffel timestamps are deterministic (`08:00 + 5h + 2h layover`) | For reproducible tests; documented |
| `multi-city` queried as separate slices | Duffel handles natively; no collapse |
| No `live_mode` propagation | Carried in payload but not used for VERIFIED status (per spec §6) |

### 15.3 No real validation

No real Duffel credential in any allowed location; the smoke-test
harness and 97-test mock suite confirm the architecture. End-to-end
real validation is deferred until a credential is provided.

## 16. Files added / modified

**Added:**
- `live_schedule_provider.py` (~1080 lines; Protocol + 3 implementations + normalize + CLI)
- `test_schedule_provider_v1_2_1.py` (97 assertions, 18 tests, all PASS)
- `docs/live_schedule_provider_v1_2_1.md` (this document)
- `data/schedule_evidence_v1_2_1.json` (CLI output)
- `data/schedule_trace_v1_2_1.json` (CLI output)
- `data/_synthetic_cands_for_v121.json` (test fixture)

**Modified:**
- None. **No production module was touched**, per spec §19.

**NOT modified (per spec §19):**
- `candidate_discovery.py`
- `schedule_intelligence.py`
- `run_pipeline.py`
- `eval_flight_yc.py`
- `flight_dashboard.py`

## 17. Regression results

| Suite | Tests | Status |
|---|---|---|
| v0.2          | 6   | ✅ PASS |
| v0.2.1        | 7   | ✅ PASS |
| v1.0          | 72  | ✅ PASS |
| v1.1          | 104 | ✅ PASS |
| v1.1.1        | 83  | ✅ PASS |
| v1.2.0 Kiwi   | 60  | ✅ PASS |
| **v1.2.1 schedule** | **97** | ✅ **PASS** |

**Zero regression.** All existing tests continue to pass with no modification.

---

## STOP CONDITION

**v1.2.1 — Live Schedule Upgrade COMPLETE.**

> **REAL LIVE SCHEDULE VALIDATION NOT PERFORMED** — no credential available.
> Real `DuffelScheduleProvider` is implemented and unit-tested for
> fail-closed semantics. End-to-end round-trip validation is deferred
> until a real `DUFFEL_API_KEY_*` is provided.

Do **NOT** begin v1.2.2 (Frankfurter FX) or Arbitrage Detection.

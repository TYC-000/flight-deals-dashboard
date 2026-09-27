# Flight Market Intelligence v1.0 — Schedule Intelligence

> First layer of the Flight Market Intelligence architecture.
> Replaces "estimated" with "DATABASE" schedule evidence.
> **No price, no arbitrage, no booking, no live data.**

## What v1.0 does

For each candidate from `flight_candidates.json` (or `flight_candidates_generated.json`):

1. Looks up each segment's `from→to` pair in OpenFlights `routes.dat`
2. Looks up each `iata` code in OpenFlights `airports.dat`
3. Assigns each segment:
   - `schedule_source`: `openflights_database` or `unknown`
   - `verification_status`: `DATABASE` or `UNKNOWN`
   - `confidence`: derived from airport + route coverage
   - `departure` / `arrival` / `duration_minutes` / `operating_carrier`: **always `null`** — never fabricated
4. Computes per-candidate:
   - `schedule_status`: SUPPORTED / PARTIAL / UNAVAILABLE
   - `structural_signals`: alternative_hub, outer_port, positioning, multi_ticket,
     secondary_entry, unusual_routing, airport_change, schedule_uncertain, etc.
   - `connection_checks`: same_airport, airport_change, self_transfer, missing_schedule per adjacent pair
5. Emits `data/schedule_enriched_candidates.json` and `data/schedule_trace.json`

## What v1.0 does NOT do

- ❌ Fabricate any scheduled times
- ❌ Real-time / live flight schedule data
- ❌ Fare data
- ❌ Arbitrage scoring
- ❌ Booking verification
- ❌ Modify `candidate_discovery.py`, `run_pipeline.py`, `eval_flight_yc.py`, `flight_dashboard.py`
- ❌ Write `LIVE` or `VERIFIED` status (never produced)

## Data source

| File | Source | Size | Purpose |
|------|--------|------|---------|
| `airports.dat` | OpenFlights (raw CSV) | 1.1 MB | IATA → city/country/timezone/coords |
| `routes.dat`   | OpenFlights (raw CSV) | 2.4 MB | (airline, from, to) route database |

Both files cached at `/Users/aib/.hermes/cache/data/openflights/`.

**License:** OpenFlights data, free to use with attribution (https://openflights.org/data.php).

## Verification status used by v1.0

| Status | When | Emitted by v1.0? |
|--------|------|------------------|
| `UNKNOWN` | Route not in OpenFlights | ✅ YES |
| `ESTIMATED` | (Not used; reserved for v1.1+) | ❌ no |
| `DATABASE` | Route exists in OpenFlights | ✅ YES |
| `LIVE` | Paid API | ❌ no |
| `VERIFIED` | Carrier-direct inventory feed | ❌ no |

**`VERIFIED` is reserved. NEVER means BOOKABLE.**

## schedule_status vs verification_status

These are different concepts:

- `verification_status` (per segment): **source/data provenance**
- `schedule_status` (per candidate): **candidate-level completeness**

| Per-segment statuses | schedule_status |
|---------------------|-----------------|
| All DATABASE | SUPPORTED |
| Some DATABASE / some UNKNOWN | PARTIAL |
| All UNKNOWN | UNAVAILABLE |

## Output files

### `data/schedule_enriched_candidates.json`

Preserves ALL original v0.2.1 candidate fields. Adds:

```json
{
  "schedule_intelligence": {
    "applied_at": "ISO timestamp",
    "data_source": "OpenFlights routes.dat/airports.dat — DATABASE evidence only.",
    "schedule_status": "SUPPORTED | PARTIAL | UNAVAILABLE | UNCERTAIN",
    "structural_signals": ["outer_port", "alternative_hub", ...],
    "segment_schedules": [
      {
        "origin": "TPE",
        "destination": "KUL",
        "departure": null,
        "arrival": null,
        "duration_minutes": null,
        "operating_carrier": null,
        "schedule_source": "openflights_database",
        "retrieved_at": "ISO timestamp",
        "verification_status": "DATABASE",
        "confidence": 0.75,
        "is_in_openflights_database": true
      },
      ...
    ]
  }
}
```

### `data/schedule_trace.json` (spec §9)

```json
{
  "trace_at": "ISO timestamp",
  "counts": { ... observability ... },
  "candidates": [
    {
      "candidate_id": "AUTO-...",
      "schedule_lookup_attempted": true,
      "schedule_source": "openflights",
      "segments_checked": 2,
      "segments_found": 2,
      "segments_missing": 0,
      "verification_status": "DATABASE",
      "schedule_status": "SUPPORTED",
      "connection_checks": [ ... ],
      "structural_signals": [ ... ],
      "failure_reason": null
    }
  ]
}
```

## Usage

```bash
cd /Users/aib/.hermes/cache/scratch/flight-dashboard
python3 schedule_intelligence.py data/flight_candidates_generated.json
```

Standalone CLI — does **not** modify `run_pipeline.py`.
Output:
- `data/schedule_enriched_candidates.json`
- `data/schedule_trace.json`

## Observability (per spec §13)

```
SCHEDULE INTELLIGENCE v1.0 — OBSERVABILITY
============================================================
  candidates_received                  80
  candidates_with_schedule_evidence    50   (SUPPORTED)
  candidates_partial                   25   (PARTIAL)
  candidates_unknown                   5    (UNAVAILABLE)
  segments_checked                     194
  segments_found                       161  (83%)
  segments_missing                     33   (17%)
  connection_checks_performed          114
  structural_signals_detected          148
  openflights_routes_loaded            37595
  openflights_airports_loaded          6072
```

## Compatibility (verified)

| Pipeline command | Status |
|------------------|--------|
| `python3 candidate_discovery.py examples/mission_tpe_spain.json` | ✅ PASS (unchanged) |
| `python3 eval_flight_yc.py data/flight_candidates.json` | ✅ PASS (unchanged) |
| `python3 run_pipeline.py examples/mission_tpe_spain.json` | ✅ PASS (unchanged) |
| Streamlit dashboard reading `data/flight_results.json` | ✅ PASS (unchanged) |

## Test results

| Suite | Total | Pass |
|-------|-------|------|
| `test_schedule_intelligence_v1.py` | 72 | 72 |
| `test_pipeline_v0.2.py` | 6 | 6 |
| `test_pipeline_v0.2.1.py` | 7 | 7 |

## Known limitations

1. **No scheduled times in OpenFlights** — `departure`, `arrival`, `duration_minutes`,
   `overnight_connection`, `tight_connection` all stay `None`/`False` because the
   data source has no times. v1.1+ (Price/Schedule Intelligence with paid APIs)
   will populate these.
2. **No operating carrier routing** — OpenFlights lists "an airline serves this
   route" but not "which carrier operates your specific segment".
3. **Static snapshot** — OpenFlights data does not reflect recent schedule
   changes (carrier route additions/cancellations).
4. **No fare data** — by design (v1.0 is schedule-only).
5. **No booking-grade evidence** — `DATABASE` means "this route exists in
   a public dataset", **not** "bookable".

## STOP CONDITION

v1.0 complete and tested. Awaiting v1.1 (Price Intelligence) milestone direction.

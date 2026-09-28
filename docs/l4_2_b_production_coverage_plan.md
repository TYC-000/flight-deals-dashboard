# L4.2-B — Production Evidence Coverage Plan

**Milestone**: L4.2-B
**Date**: 2026-09-28
**Mode**: Inspection only (per spec §3 — no production code modifications yet)

---

## 1. Authoritative Production Candidate Source

**`data/flight_candidates.json`** is the authoritative production candidate source.

Evidence:
- `data/flight_results.json` is the **output** of `eval_flight_yc.py` (Jev) consuming `flight_candidates.json`.
- `git log` shows `flight_candidates.json` last modified 2026-09-27 19:00 by `auto-scan: 2026-09-27 19:00 | 9 scanned, 3 new`.
- The launchd job `com.tyc.flightscan` runs `/Users/aib/.hermes/tools/scan_new_deals.py` every 6h, which writes to `flight_candidates.json` and then re-evaluates via Jev.
- `flight_candidates.json` (25 IDs) ⊂ `flight_results.json` (25 IDs in `all_evaluated`) — 100% overlap.

## 2. Candidate ID Location

- Field: top-level `"id"` (string).
- 25 distinct IDs at HEAD, e.g., `KUL-EK-1`, `AUTO-bkk-emirates-BCN`, `KE-ICN-MAD-direct`.

## 3. Population Disconnect From L4.1 Evidence

- L4.1 evidence files (committed at `a0fb42b`) use IDs `AUTO-L41-multi_ticket-TPE-KUL-MAD` and `AUTO-L41-direct_hub-TPE-FRA-MAD` (test fixture).
- `flight_candidates.json` IDs (e.g., `KUL-EK-1`) have **zero overlap** with L4.1 evidence.
- Per audit `docs/l4_2_candidate_lineage_audit.md`: 100% of L4.1 evidence (except FX) is synthetic.

## 4. Schema Normalization Required

Production candidates (`flight_candidates.json`) have:
- Top-level: `id`, `label`, `currency`, `positioning_cost`, `long_haul_cost`, `total_cost`, `tpe_direct_baseline`, `savings_pct`, `positioning` (dict), `long_haul` (dict), `segments` (list), `same_pnr`, `interlined_baggage`, `terminal_change_kul_dxb`, `total_elapsed_min`, `notes`.

Missing fields (needed by v1.x stages):
- `route` (list of IATA codes)
- `origin`, `destination`
- `multi_ticket` (boolean)
- `passengers`, `passenger_types`, `cabin`
- `transit_hotel_cost` (have it; just confirm)
- `min_connection_*_min` (have it)

**Normalization**: derive missing fields from existing structure:
- `route` = unique list from `segments[].from`/`segments[].to`
- `origin` = `segments[0].from`
- `destination` = `segments[-1].to`
- `multi_ticket` = `not same_pnr` (heuristic — distinct tickets when `same_pnr=False`)
- `passengers` = 1 (per `tpe_direct_baseline` baseline assumption; current dashboard uses 1)
- `passenger_types` = `["ADT"]`
- `cabin` = `long_haul.cabin` (lowercased: `Y`/`J` → `economy`/`business`)

## 5. Integration Strategy

Add a new **production-aware entry point** to `l4_1_orchestrator.py`:

```python
def run_l41_pipeline_production(
    candidates_path: Path,      # = data/flight_candidates.json
    mission: dict,              # = a synthetic mission wrapping the candidates
    provider: str = "mock",
    provider_mode: str = "mock",
    fx_provider: str = "frankfurter",
    max_searches: int = 5,      # EXPANDED — run on full population, not budget 2
    max_l4_pairs: int = 5,
    date_window: str = "2027-04-15",
    passengers: int = 1,
    smoke_test: bool = True,
) -> int:
    """
    Run L4.1 against production candidates from `flight_candidates.json`.

    Differences from `run_l41_pipeline`:
      - Loads candidates from file (not regenerated from mission)
      - candidate_id is preserved end-to-end
      - max_searches default = 5 (no budget reduction for production)
      - Records explicit evidence states per candidate (NOT_ANALYZED, INSUFFICIENT_EVIDENCE)
      - Does NOT silently discard candidates
    """
```

Reuses existing `stage_l41_*` functions. No modifications to existing functions. Pure additive.

## 6. Evidence State Coverage for All Candidates

Per spec §8: "80 input candidates → 80 candidate lineage records, NOT 80 → 2".

For each input candidate, the new pipeline emits:
1. **Schedule evidence** — always (OpenFlights DATABASE; coverage 100%)
2. **Price evidence** — by `information_priority_score` selection (top-N by `max_searches`). For candidates NOT selected, emit an explicit `NOT_SELECTED` record (price_status=NOT_SELECTED, with `information_priority_score` for transparency, no price).
3. **FX** — single currency-pair record (TWD→EUR), applies to all candidates in the same currency context.
4. **Parity evidence** — for each pair of LIVE-priced candidates with same origin/destination. For unpaired candidates, no parity record (NOT_PAIRED).
5. **Baseline evidence** — for LIVE-priced candidates only (requires real price). Others: no baseline (NOT_ASSESSED).
6. **Comparison evidence** — for paired LIVE candidates.
7. **L4 evidence** — for compared pairs.

**Critical invariant**: every input candidate retains its `id`. If a candidate reaches no later stage, that's an explicit `NOT_ANALYZED` or `INSUFFICIENT_EVIDENCE` state, not silent deletion.

## 7. Search Budget Policy

Per spec §17: "Do not modify search budget policy."

Existing policy (`price_intelligence.py::select_candidates`):
- `max_searches=2` default
- Top-N by `information_priority_score`

**Production extension** (per spec §8: "process the full production candidate population"):
- Use `max_searches=5` as the production default (L4.1 default for production runs).
- For candidates NOT in top-N: emit explicit `NOT_SELECTED` evidence record (NOT a price; preserves lineage).
- This is an **observation**, not a budget change to `price_intelligence.select_candidates` — we record the selection outcome per candidate.

## 8. Forbidden Changes

(All preserved per spec §17.)

## 9. Out of Scope

- L5 implementation
- New arbitrage logic
- VERIFIED_OPPORTUNITY emission
- New provider integration
- Real Duffel/Kiwi integration
- Modifying `eval_flight_yc.py`
- Modifying `candidate_discovery.py`
- Modifying `dashboard_view_model.py` (only if necessary)

## 10. Expected Post-Milestone State

| Layer | Before | After |
|---|---|---|
| Discovery (population) | 25 production IDs in `flight_candidates.json` | 25 production IDs (unchanged) |
| Schedule v1.2.1 evidence | 2 IDs (synthetic) | 25 IDs (production) |
| Price evidence | 2 IDs (synthetic) | 25 records (5 priced + 20 NOT_SELECTED) |
| FX evidence | 1 currency pair | 1 currency pair (unchanged) |
| Parity evidence | 1 pair | 1+ pairs (depending on LIVE-priced) |
| Baseline evidence | 1 ID | 5 IDs (one per priced candidate) |
| Comparison evidence | 1 pair | 1+ pairs |
| L4 evidence | 1 ID | 1+ IDs |
| Dashboard view | 25 candidates, 0 with evidence | 25 candidates, 25 with explicit evidence records (mix of LIVE/UNKNOWN/REFUSED/NOT_SELECTED) |

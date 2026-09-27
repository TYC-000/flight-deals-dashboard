# Flight Arbitrage Hunter v0.2 — Pipeline Orchestrator

> 自動串接 Mission → Candidate Discovery → Jev Evaluation

## 快速使用

```bash
cd /Users/aib/.hermes/cache/scratch/flight-dashboard
python3 run_pipeline.py examples/mission_tpe_spain.json
```

## Pipeline 行為

```
Mission JSON
    ↓
[1/3] Candidate Discovery
    ↓
data/flight_candidates_generated.json
    ↓
[2/3] Jev Evaluation
    ↓
data/flight_results.json
    ↓
[3/3] Output Summary
```

每個 stage 失敗會明確報告哪個 stage 出錯 + 中間產物保留。

## v0.2 改進（從 v0.1）

1. **Family Diversity Control** — configurable `family_max_ratio` (default 0.35)
   防止單一 family 佔大多數。
2. **Route Normalization** — `_normalize_route()` 自動剝除重複 destination。
3. **Pipeline Orchestrator** — 3 stage 自動串接，明確錯誤處理。
4. **Tests** — 6 個獨立測試，涵蓋 happy path + edge cases。

## Files Added (v0.2)

```
flight-dashboard/
├── run_pipeline.py              (NEW — main orchestrator)
├── test_pipeline_v0.2.py        (NEW — 6 tests)
├── candidate_discovery.py       (MODIFIED — diversity + normalize)
├── examples/mission_tpe_spain.json  (MODIFIED — added family_max_ratio)
└── data/flight_candidates_generated.json  (regenerated)
```

## Files NOT Modified (existing pipeline preserved)

- `/Users/aib/.hermes/tools/eval_flight_yc.py` — Jev evaluator unchanged
- `flight_dashboard.py` — Streamlit dashboard unchanged
- `data/flight_candidates.json` — Manual candidates still work
- All other docs/PDFs

## Acceptance

| Criterion | Status |
|-----------|--------|
| A. Pipeline runs end-to-end | ✅ |
| B. Family diversity enforced | ✅ (max 27.5% in test) |
| C. Route normalization | ✅ (5 unit tests pass) |
| D. Empty candidates → explicit error | ✅ |
| E. Invalid JSON → explicit error | ✅ |
| F. Backward compat with existing CLI | ✅ |
| G. Backward compat with existing Jev | ✅ |
| H. Backward compat with existing JSON | ✅ |
| I. Stage-by-stage logging | ✅ |
| J. Tests | ✅ 6/6 PASS |

## Next Milestone (v0.3+)

- Real schedule sources (OpenFlights API, AviationStack)
- Real price sources (Google Flights, Kiwi API)
- Arbitrage scoring engine (cheap outlier detection)
- Background scheduler integration

## STOP CONDITION

v0.2 complete. Pipeline orchestrator done. No real-time data, no scheduling,
no dashboard redesign. Awaiting next milestone direction.

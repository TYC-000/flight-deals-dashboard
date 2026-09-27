# Flight Arbitrage Hunter v0.2.1 — Evaluation Integrity & Observability

> 修正 v0.2 reporting ambiguity，建立 lifecycle trace。

## v0.2 的問題

```
console: Survivors: 33 (or 28, or 30 — varies each run)
JSON:    all_survivors: 11
```

兩個來源都引用同一個變數，但**數字不同** — 因為每次跑結果會變（LLM API 不穩定）。

## Root Cause（追蹤）

1. **Jev** 內部 `print Survivors: N` 直接 print
2. **Jev** 也寫 `all_survivors: N` 到 JSON
3. v0.2 之前 — 兩者都引用同一個變數，但讀 JSON 那邊讀到的是**上次 launchd scan** 留下的（不是當下 Jev 寫的）：

### Path bug（最大 root cause）

`eval_flight_yc.py` 預設 output = `/tmp/flight_yc_es_results.json`。
v0.2 run_pipeline 沒指定 `-o` → Jev 結果寫到 `/tmp`。
run_pipeline 之後讀 `data/flight_results.json` → 那是 **launchd scan 留下的 22-candidate JSON**。

**所以 console 30 = Jev 當下跑 80 的結果，JSON 11 = launchd 22 的結果。**

修法：v0.2.1 run_pipeline 傳 `-o data/flight_results.json`，Jev 結果直接覆蓋。

## v0.2.1 改動

### Pipeline changes
- Explicit `-o` flag → Jev 結果寫到 `data/flight_results.json`
- Explicit lifecycle counts: Generated / Submitted / Success / Failed / Survivors / Top
- ⚠ Console Survivors vs JSON mismatch detected → 明確警告

### Trace file
- `data/evaluation_trace.json` — 每個 candidate 的 lifecycle 記錄
- Lifecycle stages: `INPUT → EVALUATED → FILTERED → SURVIVORS → TOP`

每個 trace record 包含：
```json
{
  "candidate_id": "AUTO-direct_hub-TPE-FRA-MAD",
  "submitted_to_jev": true,
  "evaluation_success": true,
  "survived": true,
  "in_top3": false,
  "final_rank": null
}
```

failure 時：
```json
{
  "candidate_id": "...",
  "submitted_to_jev": true,
  "evaluation_success": false,
  "evaluation_failure_reason": "routing_verdict=avoid_exhausting",
  "survived": false,
  "in_top3": false,
  "final_rank": null
}
```

### Integrity tests
`test_pipeline_v0.2.1.py`：
- A. submitted == success + failed
- B. survivors <= evaluated
- C. top <= survivors
- D. unique candidate IDs
- E. evaluated has trace
- F. console == JSON

## Files Added / Modified

```
run_pipeline.py                MODIFIED — explicit counts, trace, integrity
candidate_discovery.py         UNCHANGED (v0.2)
eval_flight_yc.py              UNCHANGED (Jev evaluator not touched)
flight_dashboard.py            UNCHANGED (Streamlit not touched)
flight_candidates.json         UNCHANGED (manual candidates still work)
data/evaluation_trace.json     NEW (per-candidate trace)
test_pipeline_v0.2.1.py        NEW (7 integrity tests)
test_pipeline_v0.2.py          UNCHANGED (v0.2 tests still pass)
docs/pipeline_v0.2.1.md       NEW (this file)
```

## Known Limitations

1. **Jev 內部 print 仍可能跟 JSON 不同**（LLM API 不穩定時）
   - 這是 Jev 內部 bug，我們只能 detect 不能 fix（spec 禁止改 Jev）
2. **Trace 只記錄 pipeline 內的狀態** — 如果 Jev 失敗 candidates 沒進 JSON，trace 標 `not_in_jev_output` 但沒有 Jev 內部 error 細節
3. **每次跑結果會變** — LLM 評估非確定性。Trace 顯示 latest run 狀態

## STOP CONDITION

v0.2.1 complete. Awaiting next milestone direction.

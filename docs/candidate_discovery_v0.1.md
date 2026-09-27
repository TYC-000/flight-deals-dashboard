# Candidate Discovery v0.1 — Hermes Flight Arbitrage Hunter

> 自動從 **Travel Mission** 生成 routing candidates，無需人工建檔。

## 設計目標

把目前的 pipeline：

```
flight_candidates.json (人工) → Jev → dashboard
```

升級成：

```
mission.json → candidate_discovery.py → flight_candidates_generated.json
                                              ↓
                                          既有 Jev pipeline
                                              ↓
                                          既有 Streamlit dashboard
```

**沒有** real-time pricing、爬蟲、或大型依賴。

## 快速使用

```bash
python3 candidate_discovery.py examples/mission_tpe_spain.json
```

輸出：
- `data/flight_candidates_generated.json` — 80 個 candidate（已 dedup + capped）
- CLI 印出每個 family 的統計

## Mission 結構

見 `examples/mission_tpe_spain.json`。包含：

- `origin`, `destination`, `departure_date`, `return_date`
- `cabin` (economy / business / first)
- `preferences`: avoid_red_eye, allow_outer_port, allow_multi_ticket, ...
- `constraints`: max_stops, max_total_duration_hours, max_candidates

## 8 個 Routing Families

| Family | 說明 | 數量 (TPE→Spain) |
|--------|------|----------------|
| direct_hub | TPE → major hub → Spain | 12 |
| major_hub | TPE → European hub → Spain | 8 |
| middle_east | TPE → Mid-East hub → Spain | 1 |
| southeast_asia_outer_port | TPE → outer-port → mid-east → Spain | 61 |
| northeast_asia | TPE → ICN/NRT/HND → Europe/Spain | 14 |
| europe_entry | TPE → secondary European entry → Spain | 12 |
| positioning | Explicit positioning flight patterns | 2 |
| multi_ticket | Separate positioning + main flight | 6 |

## Candidate Schema (與既有相容)

**保留**既有 Jev 必要欄位：

```
id, positioning, long_haul, segments, total_cost, savings_pct,
same_pnr, interlined_baggage, total_elapsed_min, ...
```

**新增** v0.1 metadata（不影響 Jev）：

```
candidate_type, positioning_flight, multi_ticket,
price, price_source, discovery_source, discovery_reason,
route, canonical_route_key
```

## 重要的設計原則

1. **不破壞既有 schema** — Jev evaluator 完全不動
2. **不假裝知道價格** — `price: null`, `price_source: "unknown"` 明確標記
3. **不假裝知道 schedule** — `schedule_source: "estimated"` 標記
4. **不假裝 arbitrage 已確認** — `discovery_reason` 包含 `"potential_arbitrage"` 而非 `confirmed`
5. **可擴展** — 加新 family 只需新增 `_family_X()` 並加到 `FAMILY_GENERATORS`

## 已知限制

- 飛行時間是「估算」（無 schedule 來源）
- 機型未指定（影響 Jev aircraft_comfort 分數）
- 沒有 baseline price 比較（baseline 是 `TPE_DIRECT_BASELINE_TWD=180_000` 寫死）
- candidate 排序還沒考慮時間成本 vs 價格比（只是 router type）

## 未來方向

- 真實 schedule 來源（OpenFlights, AviationStack）
- 真實價格來源（API integration）
- Arbitrage scoring engine
- 多 triptych（多航段組合）

## 整合測試

```
$ python3 candidate_discovery.py examples/mission_tpe_spain.json
✅ Generated 80 candidates

$ python3 /Users/aib/.hermes/tools/eval_flight_yc.py data/flight_candidates_generated.json
✅ Jev pipeline accepts and evaluates successfully
```

## File Manifest

```
flight-dashboard/
├── candidate_discovery.py         (NEW — main engine)
├── examples/
│   └── mission_tpe_spain.json    (NEW — test mission)
├── data/
│   └── flight_candidates_generated.json  (NEW — auto-generated output)
├── flight_candidates.json         (UNCHANGED — manual fallback still works)
├── flight_dashboard.py            (UNCHANGED)
└── (no Jev evaluator changes)
```

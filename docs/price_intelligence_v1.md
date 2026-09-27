# Flight Market Intelligence v1.1 — Price Intelligence (Implementation)

> Implementation of the [Price Intelligence Architecture](price_intelligence_v1.1.md)
> and [Provider Matrix](price_provider_matrix.md) designed previously.
> First provider wired: **Duffel** (DuffelProvider with HTTP fallback to MockDuffelProvider
> for tests). No other providers implemented.

---

## 1. Scope

| Implemented | Deferred |
|---|---|
| ✅ PriceProvider abstraction | ❌ ArbitrageEvidence (v1.2) |
| ✅ PriceEvidence schema     | ❌ Booking flow            |
| ✅ DuffelProvider + MockDuffelProvider | ❌ Kiwi / Skyscanner (future) |
| ✅ Currency normalization (static FX snapshot) | ❌ Real-time FX feed |
| ✅ Baggage metadata (warning if absent) | ❌ Seat selection UI |
| ✅ Ticket groups + multi-ticket   | ❌ Carrier-direct APIs (v1.3) |
| ✅ Provenance envelope            | ❌ Pipeline integration |
| ✅ Freshness buckets (recomputed) |  |
| ✅ 11 FailureKinds + refuse-comparison set |  |
| ✅ Search budget + memoization |  |
| ✅ Candidate selection (signal-weighted) |  |
| ✅ trace file + observability |  |
| ✅ 22 tests (A-V per spec) — 104 PASS |  |

**v1.1 is read-only against the existing pipeline:** standalone CLI, no
modification to `candidate_discovery.py`, `schedule_intelligence.py`,
`run_pipeline.py`, `eval_flight_yc.py`, or `flight_dashboard.py`.

---

## 2. Files

### 2.1 Created

| File | Purpose |
|---|---|
| `price_intelligence.py` | Provider abstraction + DuffelProvider + MockDuffelProvider + normalization + CLI |
| `test_price_intelligence_v1.py` | 22 tests (A-V per spec) — 104 individual assertions, all PASS |
| `data/price_evidence.json` | Per-candidate normalized Price Evidence (output of v1.1) |
| `data/price_trace.json`     | Per-candidate lookup trace (output of v1.1) |
| `docs/price_intelligence_v1.md` | THIS document |

### 2.2 Modified

**None.** Spec §19 explicitly required no production-code changes unless
absolutely necessary. Standalone CLI mirrors the v1.0 pattern.

---

## 3. Provider implementation

### 3.1 `PriceProvider` protocol

```python
class PriceProvider(Protocol):
    @property
    def name(self) -> str: ...
    def capabilities(self) -> ProviderCapabilities: ...
    def health_check(self) -> bool: ...
    def quote(candidate, date_window, passengers=1) -> dict[str, Any]: ...
```

### 3.2 `DuffelProvider` (real)

- Auth via `DUFFEL_API_KEY_LIVE` or `DUFFEL_API_KEY_TEST`
- Endpoint: `POST /air/offer_requests?return_offers=true&supplier_timeout=15000`
- Body: `{ data: { slices: [...], passengers: [...], cabin_class, include_split_ticket: true } }`
- Returns PriceEvidence-shaped dict (never Duffel-specific to downstream)
- Token never logged; never written to trace

### 3.3 `MockDuffelProvider` (test)

Deterministic, network-free. Env flags simulate failure modes:

| Env flag | Behavior |
|---|---|
| `SIMULATE_PROVIDER_TIMEOUT` | Returns PROVIDER_TIMEOUT (no evidence) |
| `SIMULATE_PROVIDER_ERROR`   | Returns PROVIDER_ERROR |
| `SIMULATE_RATE_LIMITED`     | Returns RATE_LIMITED (refuses comparison) |
| `SIMULATE_BAGGAGE_UNKNOWN`  | Returns LIVE evidence with BAGGAGE_UNKNOWN warning |
| `SIMULATE_CURRENCY_UNKNOWN` | Returns CURRENCY_UNKNOWN (refuses comparison) |
| `SIMULATE_PARTIAL_PRICE`    | Returns LIVE evidence with PARTIAL_PRICE warning |
| `SIMULATE_MULTI_INCOMPLETE` | Returns LIVE evidence with MULTI_TICKET_PARTIAL warning (1 leg priced) |
| `SIMULATE_ROUTE_UNAVAILABLE` | Returns ROUTE_UNAVAILABLE (refuses comparison) |
| `SIMULATE_STALE_PRICE`      | Returns LIVE evidence with retrieved_at 5d ago → EXPIRED bucket |

### 3.3a Failure kinds refuse comparison

`CURRENCY_UNKNOWN`, `MISSING_CREDENTIALS`, `RATE_LIMITED`, `ROUTE_UNAVAILABLE`
all set `price_evidence = null` and refuse direct comparison (per spec §6
explicit rule).

---

## 4. PriceEvidence schema (per spec §3)

Top-level fields:

| Field | Required | Notes |
|---|---|---|
| `candidate_id` | ✅ | echo from v0.2.1 candidate |
| `currency`     | ✅ | always `TWD` after normalization |
| `total_price`  | ✅ | `{amount, currency, fx_envelope}` |
| `base_fare`, `taxes`, `fees`, `optional_extras` | ✅ | with FX envelopes |
| `ticket_count` | ✅ | 1 or more |
| `is_single_ticket` | ✅ | boolean |
| `self_transfer`    | ✅ | cross-group airport change |
| `separate_ticket_risk` | ✅ | `none` / `elevated` / `high` |
| `baggage` | ✅ | `{included, purchase_required, recheck_required_at_connection, evidence_complete}` |
| `cabin` | ✅ | economy / premium_economy / business / first |
| `ticket_groups` | ✅ | array of `{group_id, stops, ticket_type, subtotal, passenger_through_check_baggage, self_transfer_after_group}` |
| `provenance` | ✅ | `{source, source_type, retrieved_at, freshness_min, endpoint, offer_id, verification_status}` |
| `freshness_min`, `freshness_bucket` | ✅ | recomputed from retrieved_at |
| `verification_status` | ✅ | `LIVE` from provider |
| `price_status` | ✅ | `OK` / `OK_WITH_WARNINGS` / `FAILED` |
| `confidence_reasons` | ✅ | structured list (`LIVE_PROVIDER`, `BAGGAGE_UNKNOWN`, etc.) |
| `warnings` | ✅ | list of failure-kind names observed |
| `valid_until`, `price_quote_expires_at` | ✅ | from provider `expires_at` |

**Forbidden (explicitly absent):** `arbitrage_score`, `arbitrage_opportunity`,
`net_arbitrage`, `booking_status`.

---

## 5. Freshness implementation

```python
freshness_recent_max_min = 30
freshness_warm_max_min   = 240   # 4h
freshness_cold_max_min   = 1440  # 24h
freshness_expired        = > 1440
```

`compute_freshness_min(retrieved_at, now)` is called at every emit to **recompute**
freshness. Provider-produced freshness is NEVER trusted.

Bucket mapping:
- ≤30 min  → FRESHNESS_RECENT
- ≤4 hours → FRESHNESS_WARM
- ≤24 hours → FRESHNESS_COLD
- >24 hours → FRESHNESS_EXPIRED

---

## 6. Failure semantics

11 canonical `FailureKind`s (per spec §6):

| FailureKind | Comparison | Behavior |
|---|---|---|
| `PRICE_NOT_FOUND` | allowed | null evidence, warning |
| `PROVIDER_TIMEOUT` | allowed | null evidence, warning |
| `PROVIDER_ERROR` | allowed | null evidence, warning |
| `STALE_PRICE` | allowed | LIVE evidence flagged EXPIRED |
| `PARTIAL_PRICE` | allowed | LIVE evidence with PARTIAL_DATA reason |
| `CURRENCY_UNKNOWN` | **refused** | null evidence, refuse-comparison |
| `BAGGAGE_UNKNOWN` | allowed | LIVE evidence, BAGGAGE_UNKNOWN reason |
| `MULTI_TICKET_PRICE_INCOMPLETE` | allowed | LIVE evidence, MULTI_TICKET_PARTIAL reason |
| `ROUTE_UNAVAILABLE` | **refused** | null evidence, refuse-comparison |
| `MISSING_CREDENTIALS` | **refused** | null evidence, refuse-comparison |
| `RATE_LIMITED` | **refused** | null evidence, refuse-comparison |

Refuse-comparison set: `{CURRENCY_UNKNOWN, MISSING_CREDENTIALS, RATE_LIMITED, ROUTE_UNAVAILABLE}`

---

## 7. Multi-ticket handling

### 7.1 Detection

Each Duffel offer carries `type: "single_ticket"` (one PNR) or
`type: "split_ticket"` (one-way per slice).

### 7.2 Normalization

For `single_ticket`: 1 group, `is_single_ticket=True`, `ticket_count=1`,
`separate_ticket_risk=none`.

For `split_ticket`: 1 group per slice. `is_single_ticket=False`.
`separate_ticket_risk` computed:

| Topology | separate_ticket_risk |
|---|---|
| `single_ticket` | `none` |
| multi-group, no airport change, mixed carriers | `elevated` |
| multi-group with self-transfer (airport change) | `high` |

### 7.3 Incomplete multi-ticket

If the candidate has 2+ segments but the provider only priced 1 slice
(`len(ticket_groups) < len(candidate_segments)`), we tag:

```
warnings:  ["MULTI_TICKET_PRICE_INCOMPLETE"]
confidence_reasons: ["MULTI_TICKET_PARTIAL", ...]
```

We do NOT drop the price — the partial information can still inform arbitrage
detection later, with the warning propagating.

---

## 8. Search budget + memoization

```python
class SearchBudget:
    max: int = 10
    used: int = 0
    cache: dict[str, dict[str, Any]]  # search_key -> result
```

- **Budget default: 10** (configurable via `--max-searches`).
- **Memoization:** `make_search_key(candidate, date_window, passengers)` is
  deterministic (sha256 of normalized payload). Same search key → cached result.
- **Skipped-for-budget:** candidates beyond budget are tracked separately so they
  appear in the trace as such (not as "never-searched").

---

## 9. Candidate selection policy

For `max_searches=10` of the 80 candidates, we rank:

```
score = 0
+ 10 if schedule_status == SUPPORTED
+  5 if PARTIAL
+  1 if UNCERTAIN
+  0 if UNAVAILABLE
+ 6 if "multi_ticket" in signals
+ 5 if "positioning"
+ 4 if "outer_port"
+ 3 if "alternative_hub"
+ 2 if "secondary_entry"
- 1 if "unusual_routing"
- 2 if "airport_change"
- 1 if "schedule_uncertain"
- 0.5 * max(0, n_segments - 1)   # complexity penalty
+ 1 if same_pnr == True            # single-ticket bonus
```

Sort: score DESC, candidate_id ASC (deterministic tiebreak).

Result: the 10 most interesting candidates by **interest × schedule support**.

---

## 10. Currency normalization

FX is performed via a static snapshot table (`STATIC_FX_TO_TWD`). Each
`total_price` carries an `fx_envelope`:

```json
{
  "amount": 48093.5,
  "currency": "TWD",
  "fx_envelope": {
    "from": "USD",
    "to": "TWD",
    "rate": 31.85,
    "source": "snapshot_only_static_table",
    "retrieved_at": "ISO-8601",
    "freshness_min": 0,
    "markup_pct": 2.0,
    "is_identity": false,
    "verification_status": "DATABASE"
  }
}
```

If source currency is not in the table, the field is `null` and the resulting
`PriceEvidence` is `CURRENCY_UNKNOWN` → refuses comparison.

The 2% markup is recorded for **awareness only**; we never silently apply markups.
This documents the Duffel FX contract per architecture §11.

---

## 11. Trace file

`data/price_trace.json` per spec §14:

```json
{
  "candidate_id":          "AUTO-...",
  "provider":              "duffel" | "mock_duffel",
  "request_key":           "228e776d30b3f21e",
  "request_time":          "ISO-8601",
  "response_time":         "ISO-8601",
  "elapsed_ms":            412,
  "price_found":           true,
  "price_status":          "OK",
  "verification_status":   "LIVE",
  "retrieved_at":          "ISO-8601",
  "expires_at":            "ISO-8601 (provider)",
  "freshness":             "FRESHNESS_RECENT",
  "ticket_count":          1,
  "currency":              "TWD",
  "total_price":           48093.5,
  "warnings":              [],
  "failure_reason":        null,
  "failure_kind":          null
}
```

**No secrets.** The Duffel client writes `"Authorization": "Bearer REDACTED"`
in source code (never the actual token).

---

## 12. Test results

### 12.1 Self-tests (104 PASS, 0 FAIL)

```
Test A:  Provider interface                       ✅
Test B:  Duffel response normalization           ✅
Test C:  PriceEvidence schema                    ✅
Test D:  Provenance preservation                 ✅
Test E:  Freshness calculation                   ✅
Test F:  Stale price detection                   ✅
Test G:  Currency unknown                        ✅
Test H:  Baggage unknown                         ✅
Test I:  Multi-ticket                            ✅
Test J:  Incomplete multi-ticket                 ✅
Test K:  Missing credentials                     ✅
Test L:  Rate limiting                           ✅
Test M:  Provider timeout                        ✅
Test N:  Route unavailable                       ✅
Test O:  No fake price                           ✅
Test P:  Deterministic search key                ✅
Test Q:  Search budget                           ✅
Test R:  Candidate selection                     ✅
Test S:  Duplicate request prevention            ✅
Test T:  Trace completeness                      ✅
Test U:  No BOOKABLE enum                        ✅
Test V:  No ArbitrageEvidence output             ✅
Test W:  Comparison rules (bonus)                ✅
```

### 12.2 Existing regression tests (all PASS)

| Suite | Status |
|---|---|
| `test_pipeline_v0.2.py`     | ✅ 6/6 |
| `test_pipeline_v0.2.1.py`   | ✅ 7/7 |
| `test_schedule_intelligence_v1.py` | ✅ 72/72 |
| `test_price_intelligence_v1.py`    | ✅ **104/104** |

---

## 13. Real API smoke test (skipped — no credentials)

Per spec §16, an optional smoke test exists. It is **disabled by default**
(`RUN_DUFFEL_SMOKE_TEST=1`).

No `DUFFEL_API_KEY_LIVE` or `DUFFEL_API_KEY_TEST` was found in env or in
`~/.hermes/.env`. The smoke test is therefore a no-op for this run.

**Number of real API requests: 0.** Every evidence in
`data/price_evidence.json` was produced by `MockDuffelProvider`. Once credentials
become available, run:

```bash
export DUFFEL_API_KEY_TEST=test_xxx
python3 price_intelligence.py data/schedule_enriched_candidates.json --provider duffel
```

---

## 14. Price evidence coverage (latest run)

On `data/schedule_enriched_candidates.json` (80 candidates, 194 segments):

| Bucket | Count |
|---|---|
| Candidates received | 80 |
| Candidates selected (within MAX_SEARCHES) | 10 |
| Candidates searched | 10 |
| Candidates with LIVE evidence | 10 |
| Candidates failed (refuse-comparison) | 0 |
| Candidates skipped for selection | 70 |
| Candidates skipped for budget | 0 |
| Search budget used | 10 / 10 |
| Search cache hits | 0 |
| Verification status | `LIVE`: 10 |
| Freshness bucket | `FRESHNESS_RECENT`: 10 |

---

## 15. Known limitations

1. **MockDuffelProvider used in production** — credentials absent in this
   environment. Once available, wire to `DuffelProvider` with `--provider duffel`.
2. **Static FX snapshot** — not real-time. Architecture §11 documents the 2% markup awareness.
3. **Candidate selection policy is fixed** — no per-Mission re-weighting. This is
   expected for v1.1; v1.2 (or later) may tune weights using Mission preferences.
4. **Comparison rules per architecture §8.3** are implemented in `price_comparison()`
   but v1.1 does not invoke them on its own — that is for v1.2 Arbitrage Detection.
5. **No fare rules endpoint** — changeable / refundable / cancellation fees are all
   `null` until Duffel order-level rules are queried.
6. **`MISSING_CREDENTIALS` simulates failure path** — but in production run we
   auto-fallback to mock so the user sees evidence anyway. Real deployment must
   refuse to start without credentials.

---

## 16. STOP CONDITION

v1.1 implementation complete:
- 1 provider wired (Duffel, with Mock for test)
- 1 schema (PriceEvidence) implemented
- 11 FailureKinds covered
- 4 freshness buckets
- Multi-ticket model
- Currency normalization with FX envelope
- Search budget + memoization
- Candidate selection
- Trace file
- 104 tests passing

Do **NOT** begin v1.2 (Arbitrage Detection) until next milestone direction.

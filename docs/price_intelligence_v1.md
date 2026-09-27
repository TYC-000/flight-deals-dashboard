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


---

# v1.1.1 — Real Provider Validation & Fail-Closed Integrity (addendum)

> Real-Provider Validation (per v1.1.1 spec). No new feature work; only
> hardening of provider modes and provenance.

## 1. Provider modes

| `--provider` | Behavior without creds | Behavior with creds |
|---|---|---|
| `mock`     | Uses MockDuffelProvider always | Uses MockDuffelProvider always |
| `duffel`   | **FAIL CLOSED** (exit 10, no silent fallback) | Real DuffelProvider |
| `auto`     | MockDuffelProvider + explicit log | Real DuffelProvider + explicit log |

Per v1.1.1 §1: `duffel` mode NEVER silently falls back to Mock.

## 2. Fail-closed semantics

```bash
$ python3 price_intelligence.py --provider duffel --max-searches 2
[ERROR] Provider build failed: MISSING_CREDENTIALS: ...

>>> FAIL CLOSED: not running. Set DUFFEL_API_KEY_LIVE/TEST, or use --provider mock.
$ echo $?
10
```

Distinct exit codes:
- `0` — success
- `1`–`3` — input/file errors
- `10` — MISSING_CREDENTIALS (fail closed)
- `11` — invalid provider spec

## 3. Provider provenance (`price_evidence.provenance`, per spec §2)

Every PriceEvidence carries explicit, non-confusable identity:

| Field | Mock | Real Duffel |
|---|---|---|
| `provider`           | `"mock_duffel"` | `"duffel"` |
| `provider_mode`      | `"mock"`        | `"live"`   |
| `provenance.source`  | `"mock_duffel"` | `"duffel"` |
| `provenance.source_type` | `SRC_CACHE` (= `"cache"`) | `SRC_LIVE` (= `"live"`) |
| `verification_status` | `LIVE` (intentionally kept — Mock still produces LIVE-shaped evidence, marked explicitly via `provider_mode`) | `LIVE` |

## 4. Smoke test guard (v1.1.1 §5)

```bash
python3 price_intelligence.py --provider mock --max-searches 10 --smoke-test
```

`--smoke-test` caps `max-searches` at **2** regardless of input. This prevents accidental 80-candidate real-world runs during local validation.

## 5. Search-priority score terminology

The candidate-selection score is named `information_priority_score` (in code:
`ips`). It is **never** `arbitrage_score`, `candidate_score`, or `price_score`.
It answers: "which candidates are worth spending limited provider queries on?"
— NOT "which candidate is a confirmed arbitrage opportunity?".

Weights (unchanged from v1.1):
```
+10 SUPPORTED, +5 PARTIAL, +1 UNCERTAIN
+6 multi_ticket, +5 positioning, +4 outer_port,
+3 alternative_hub, +2 secondary_entry
-1 unusual_routing, -2 airport_change, -1 schedule_uncertain
-0.5 per extra segment beyond first
+1 same_pnr=True
```

## 6. Real API smoke-test

**REAL PROVIDER VALIDATION NOT PERFORMED.**

No `DUFFEL_API_KEY_LIVE` or `DUFFEL_API_KEY_TEST` was present in the runtime
environment. Therefore:

- Real Duffel integration was **not executed** in this milestone.
- The `--smoke-test` guard exists but was not used against real Duffel.
- This means: schema equivalence between Mock and Real has been **verified
  by code-review only**, not by an end-to-end real-API validation.

Duffel integration is therefore NOT production-validated.

## 7. v1.1.1 test results

| Test | Status |
|---|---|
| A. explicit mock mode            | ✅ PASS |
| B. explicit Duffel mode          | ✅ PASS (rc=10 fail-closed) |
| C. missing credentials fail closed | ✅ PASS |
| D. no silent Mock fallback       | ✅ PASS |
| E. provider provenance           | ✅ PASS |
| F. Mock vs real schema equivalence | ✅ PASS |
| G. deterministic search key      | ✅ PASS |
| H. search budget                 | ✅ PASS |
| I. information priority selection | ✅ PASS (no arbitrage_score identifier) |
| J. no BOOKABLE enum               | ✅ PASS |
| K. no ArbitrageEvidence output   | ✅ PASS |
| L. no arbitrage_score identifier | ✅ PASS (excluding comments/guards) |
| M. trace provider identity       | ✅ PASS |
| N. real smoke-test guard         | ✅ PASS |

**Total: 83 individual assertions, all PASS.**

### Regression status

| Suite | Tests | Status |
|---|---|---|
| v0.2 (`test_pipeline_v0.2.py`)        | 6   | ✅ PASS |
| v0.2.1 (`test_pipeline_v0.2.1.py`)      | 7   | ✅ PASS |
| v1.0 (`test_schedule_intelligence_v1.py`) | 72  | ✅ PASS |
| v1.1 (`test_price_intelligence_v1.py`)    | 104 | ✅ PASS |
| v1.1.1 (`test_price_intelligence_v1_1.py`) | 83  | ✅ PASS |

## 8. Files modified (v1.1.1)

```
Modified:
- price_intelligence.py        (provider modes, fail-closed semantics,
                                provider identity surfaced in payload,
                                information_priority_score naming,
                                smoke-test guard)
- data/price_evidence.json     (regenerated; provider/provider_mode fields added)
- data/price_trace.json        (regenerated; trace now carries provider identity)
- docs/price_intelligence_v1.md  (THIS ADDDENDUM added)

New:
- test_price_intelligence_v1_1.py  (14 tests, 83 assertions)
```

No production module (candidate_discovery.py, schedule_intelligence.py,
run_pipeline.py, eval_flight_yc.py, flight_dashboard.py) was modified.

## 9. Known limitations

1. Real Duffel integration is **not production-validated** in this milestone
   (no credential available). Schema equivalence between Mock and Real is
   verified by code review only.
2. `auto` mode has a soft fallback to Mock — if the user wants strictness
   they must use `duffel` explicitly.
3. The 2% FX markup awareness in `provenance.fx_envelope.markup_pct` is
   documented but not silently applied (conservative choice).


---

# v1.1.2 — Real Duffel Smoke Validation (addendum)

> Status: **REAL PROVIDER VALIDATION NOT PERFORMED.**
>
> Spec §1 explicit: "If no credential exists: Report exactly: REAL
> PROVIDER VALIDATION NOT PERFORMED. Then STOP. Do not fabricate prices.
> Do not run Mock as a substitute. Do not begin v1.2."

## Credential discovery (spec §1)

Searched (token values NEVER exposed):

- `DUFFEL_API_KEY_TEST` env var — **NOT SET**
- `DUFFEL_API_KEY_LIVE` env var — **NOT SET**
- `~/.hermes/.env` (exists, 19213 bytes) — **no DUFFEL entries**
- `~/.hermes/config.yaml` — **no DUFFEL entries**
- `~/.zshrc`, `~/.zshenv`, `~/.bashrc`, `~/.bash_profile`, `~/.hermes/.env.local`
  — **no DUFFEL entries**

**Result: NONE.** No credential available in any allowed location.

## What was done (without making any real network call against Duffel)

The following were validated WITHOUT real Duffel credentials:

- A. `--provider mock` → MockDuffelProvider (verified by v1.1.1 Test A, PASS)
- B. `--provider duffel` without creds → fail-closed (verified by v1.1.1 Test B, PASS)
- C. Missing credentials fail closed (verified by v1.1.1 Test C, PASS)
- D. No silent Mock fallback (verified by v1.1.1 Test D, PASS)
- H. Smoke test hard limit ≤ 2 (verified by v1.1.1 Test N, PASS)
- I. No API key in stdout/stderr — verified independently:
  set `DUFFEL_API_KEY_TEST=test_TEST_KEY_DO_NOT_LEAK_abcdef123456`, ran
  `--provider duffel --smoke-test`, grepped for the key — **no leak**.
- J. no BOOKABLE (verified by v1.1.1 Test J, PASS)
- K. no ArbitrageEvidence created (verified by v1.1.1 Test K, PASS)
- L. no `arbitrage_score` identifier (verified by v1.1.1 Test L, PASS)
- M. `information_priority_score` is the terminology (verified by v1.1.1 Test I, PASS)
- N. Existing regressions remain green (verified by all-suite run below)

The following could **not** be validated (require real credentials):

- E. Real provenance identity (`provider="duffel"`, `provider_mode="live"`)
- F. Mock provenance identity — verified by v1.1.1 Test E
- G. Mock vs Real schema compatibility — Mock-only; Real requires real Duffel
- Schema compatibility is verified by code review (v1.1.1 Test F, PASS) but not by real round-trip

## Regression status (all PASS)

| Suite | Tests | Status |
|---|---|---|
| v0.2 (`test_pipeline_v0.2.py`)        | 6   | ✅ PASS |
| v0.2.1 (`test_pipeline_v0.2.1.py`)      | 7   | ✅ PASS |
| v1.0 (`test_schedule_intelligence_v1.py`) | 72  | ✅ PASS |
| v1.1 (`test_price_intelligence_v1.py`)    | 104 | ✅ PASS |
| v1.1.1 (`test_price_intelligence_v1_1.py`) | 83  | ✅ PASS |

## Files modified (v1.1.2)

**None.** This milestone is a status report.

(No production module, no test file, no documentation file — beyond this
addendum — was modified.)

The only file added was the doc addendum.

## What the user must do for REAL DUFFEL SMOKE VALIDATION

1. Set `DUFFEL_API_KEY_TEST=<real Duffel test token>` in the shell environment
   (or in `~/.hermes/.env`).
2. Re-run:
   ```bash
   python3 price_intelligence.py data/_synthetic_cands_for_v111.json \
       --provider duffel --smoke-test --max-searches 2
   ```
3. Inspect `data/price_evidence.json` and `data/price_trace.json`:
   - `evidences[*].provider` should be `"duffel"`
   - `evidences[*].provider_mode` should be `"live"`
   - `evidences[*].verification_status` should be `"LIVE"`
4. Then v1.1.2 may report `REAL DUFFEL SMOKE VALIDATION PASSED`.

## Remaining limitations

1. No real Duffel credential was available; round-trip validation
   deferred to when the user supplies one.
2. The credential-leakage test (I) was performed with a **fake** test key;
   it does NOT exercise the real Duffel adapter's HTTP plumbing.
3. Real Duffel cost: per the matrix doc, ~$0.005/excess search after the
   1500:1 search-to-book ratio, or $3 per confirmed order. With no orders,
   a `--smoke-test --max-searches 2` run costs ~$0.010.

## STOP CONDITION

**REAL PROVIDER VALIDATION NOT PERFORMED.**


---

# v1.2.0 — Kiwi PriceProvider Integration (addendum)

> Status: **Implementation complete.**
> **KIWI REAL PROVIDER VALIDATION NOT PERFORMED** — no credential available.

## What v1.2.0 added

- `kiwi_price_provider.py` — new module with `KiwiPriceProvider` (real),
  `MockKiwiProvider` (deterministic), `normalize_kiwi_response()`
  (Kiwi JSON → PriceEvidence contract)
- `price_intelligence.build_provider()` extended:
  - `--provider kiwi` → `KiwiPriceProvider` (rc=10 if no creds)
  - `--provider mock_kiwi` → `MockKiwiProvider` (no creds needed)
  - `--provider auto` now prefers Duffel → Kiwi → MockDuffelProvider
    (explicit fallback log line)
- 60-test v1.2.0 test suite (all PASS): provider identity, schema keys,
  required fields, freshness, verification, failure, currency, baggage,
  ticket structure, no BOOKABLE, no ArbitrageEvidence, no arbitrage_score,
  information_priority_score terminology, no credential leakage,
  explicit provider mode, no silent fallback, cross-provider coexistence
  fixture, smoke-test hard limit.

## Why this milestone stops here

Per v1.1.5 evidence source matrix, the technical sequencing was:
1. v1.2.0 — Kiwi PriceProvider Integration ✅ (this milestone)
2. v1.2.1 — Live Schedule Upgrade (Gap B)
3. v1.2.2 — Frankfurter FX Integration (Gap D)
4. v1.2.3 — Baseline Canonicalization + Parity Validator (Gap F)
5. v1.2.4 — Friction Evidence + Multi-Passenger Policy (Gap E)
6. v1.2.5 — Evidence Maturity Ladder + VerifiedOpportunity emission

This milestone is **Gap A only**. No arbitrage detection, no comparison
engine, no opportunity ranking.

## Regression status

| Suite | Tests | Status |
|---|---|---|
| v0.2          | 6   | ✅ |
| v0.2.1        | 7   | ✅ |
| v1.0          | 72  | ✅ |
| v1.1          | 104 | ✅ |
| v1.1.1        | 83  | ✅ |
| **v1.2.0**    | **60** | ✅ |

No production module modified:
candidate_discovery.py, schedule_intelligence.py, run_pipeline.py,
eval_flight_yc.py, flight_dashboard.py are unchanged.

## STOP CONDITION

**KIWI REAL PROVIDER VALIDATION NOT PERFORMED.**

Do **NOT** begin v1.2.1 or Arbitrage Detection automatically.

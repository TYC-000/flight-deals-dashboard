# FX Provider — v1.2.2 (Implementation)

> Provider-agnostic FX Evidence layer using Frankfurter v2 as the first
> real provider. Closes **Gap D** (Real FX) from v1.1.5 Evidence Source
> Matrix.
>
> v1.2.2 does NOT do arbitrage detection. It produces **FXEvidence**
> alongside PriceEvidence and ScheduleEvidence; the comparison engine
> belongs to a later milestone.

---

## 1. Official Frankfurter API research

| Item | Detail | Source |
|---|---|---|
| Current endpoint | `https://api.frankfurter.dev` | https://frankfurter.dev |
| API version | **v2** (v1 is legacy, ECB-only) | official docs |
| Single-pair (latest) | `GET /v2/rate/{base}/{quote}` | example |
| Single-pair (historical) | `GET /v2/rate/{base}/{quote}?date=YYYY-MM-DD` | example |
| Bulk latest | `GET /v2/rates?base=USD&quotes=EUR,GBP` | example |
| Currencies list | `GET /v2/currencies` | example |
| **Credential** | **None required** (public, open-source) | official |
| Cost | Free | official |
| Source data | 84 central banks | official |
| Time zone | All dates/timestamps UTC | official |
| History back to | 1948 | official |
| Rate limit | Undocumented; conservative 60 req/min | empirical |
| License | open-source | official |

### Observed (smoke-tested locally against `https://api.frankfurter.dev`)

- Frankfurter rejects the Python `urllib` default User-Agent with **HTTP 403**.
  All adapters MUST send an explicit `User-Agent` header.
- Latest single pair returns object: `{"amount":1.0,"base":"EUR","date":"2026-09-27","rates":{"USD":1.1398}}`
- Historical with future date returns **empty array** `[]` — so future-date
  retrieval would yield `FX_NOT_FOUND`.
- Bulk with `quotes=A,B` returns array shape `[{date, base, quote, rate}, ...]`
- Rate precision is float (typically 4–5 significant digits).

---

## 2. Architecture

```
Currency → FXProvider → FXEvidence → Normalized Comparison Value
                    ↓
   FrankfurterFXProvider (real; v2; no credential)
   MockFXProvider       (deterministic; for tests)
```

Dependency direction (per spec §3, §15):
- `fx_provider.py` imports from `price_intelligence.py` only for canonical
  enums (failure kinds, verification tiers, freshness constants).
- `price_intelligence.py` is **NOT modified** by v1.2.2.
- No other production module is touched.

---

## 3. FXEvidence schema (per spec §4)

```python
FXEvidence = {
    schema_version: "v1.2.2",
    provider: "frankfurter" | "mock_frankfurter",         # NON-CONFUSABLE identity
    provider_mode: "live" | "mock",                       # distinct from above
    base_currency: "EUR",                                  # uppercased ISO 4217
    quote_currency: "TWD",
    rate: 31.774,                                          # float
    rate_date: "2026-09-27",                                # the FX rate's effective date
    rate_source_type: "latest/current" | "historical" | "identity",
    retrieved_at: ISO8601 with timezone,                   # when our adapter called API
    freshness_min: 0,
    freshness_bucket: "FRESHNESS_RECENT",                  # canonical from v1.1
    freshness_label: "latest/current" | "historical" | "identity (no API call)",
    verification_status: LIVE | DATABASE | UNKNOWN,        # NO BOOKABLE
    source: "frankfurter" | "mock_frankfurter" | "identity",
    endpoint: "/v2/rate/{base}/{quote}" | None,
    request_metadata: {
        is_historical_request: bool,
        explicit_rate_date: str | None,
    },
    is_identity: False | True,
    supports_no_credential: True,
    warnings: [...],
    failure_reason: None | str,
    failure_kind: None | str,
    provenance: {
        source: str,
        source_type: "live" | "cache" | "indicative",
        endpoint: str | None,
        retrieved_at: ISO8601,
        rate_date: str | None,
        verification_status: str,
        note: str | None,                                   # for identity case
    },
}
```

**Distinct provider identities**:
- `provider` ∈ `{frankfurter, mock_frankfurter}` (the producer)
- `provider_mode` ∈ `{live, mock}` (how it was invoked)

Identity conversions (`EUR → EUR`) emit `verification_status=DATABASE`,
`is_identity=True`, and **do not** call any external API.

---

## 4. Failure semantics (per spec §7)

| FailureKind              | Trigger | Hard ref to spec |
|--------------------------|---------|-----------------|
| `MISSING_CREDENTIALS`    | hard-incompatible since Frankfurter requires none | not used |
| `CURRENCY_UNKNOWN`       | empty / non-string base or quote | §7 |
| `FX_NOT_FOUND`           | no row for base→quote in current rates | §7 |
| `FX_PROVIDER_TIMEOUT`    | urllib timeout / URLError | §7 |
| `FX_PROVIDER_ERROR`      | HTTP non-200/non-404/non-429 | §7 |
| `RATE_LIMITED`           | HTTP 429 | §7 |
| `STALE_FX`               | (simulated via `SIMULATE_FX_STALE`) — explicit rate_date override with old date | §7 |
| `INVALID_FX_RESPONSE`    | malformed JSON / unexpected shape | §7 |

**Hard rules**:
- Failure is NEVER interpreted as `expensive`, `cheap`, `no arbitrage`,
  `opportunity`, or `route unavailable`.
- `CURRENCY_UNKNOWN` → REFUSE COMPARISON (this is enforced at the
  normalization level; the comparison path is not implemented in
  v1.2.2 but the primitive is reserved).

---

## 5. Date binding (per spec §5)

`FXEvidence` carries **two** distinct date values:

| Field | Meaning | Source |
|---|---|---|
| `rate_date` | The date the FX rate is effective for (e.g., Frankfurter's `date` field, or user-supplied historical date) | provider response OR explicit `--rate-date` |
| `retrieved_at` | When the adapter made the API call | computed at adapter-call time |

**Hard rule**: `retrieved_at` is NEVER borrowed from PriceEvidence.
**Hard rule**: Frankfurter's response `date` is the rate_date for
"latest" FX; explicit `?date=…` query produces rate_date=that date.

`rate_source_type` is `latest/current`, `historical`, or `identity`,
explicitly distinguishing the three cases.

---

## 6. Freshness (per spec §6)

Canonical buckets from `price_intelligence` (no parallel scheme):

```
FRESHNESS_RECENT     ≤ 30 min
FRESHNESS_WARM       ≤ 4 h
FRESHNESS_COLD       ≤ 24 h
FRESHNESS_EXPIRED    > 24 h
FRESHNESS_UNKNOWN    malformed timestamp / None
```

`freshness_min` is computed only from `retrieved_at` — **never** from
`rate_date`. This keeps FX freshness independent of price freshness.

Identity conversions emit `freshness_bucket=FRESHNESS_RECENT` with
`freshness_label="identity (no API call)"` and `freshness_min=0`.

---

## 7. Real API smoke result (per spec §12)

| Metric | Value |
|---|---|
| Real Frankfurter requests | **2** (rate=1.1398 EUR→USD; rate=31.774 USD→TWD) |
| Real Frankfurter responses | **2** |
| Real Frankfurter failures | **0** |
| **Auth** | None required (public API) |
| Smoke-test cap honored | Yes (`--smoke-test` enforced max 2) |

The CLI proved end-to-end against the public server using User-Agent
`fx_provider_v1_2_2/1.0 (no-credential)`. **No credential used,
no credential sent, no credential stored.**

---

## 8. Static FX removal from comparison path (per spec §8)

v1.2.2 does NOT modify v1.1 PriceEvidence schema. The comparison path
in v1.1 is unaffected. The FX layer is constructed as a standalone
provider that can be invoked **later** by a comparison engine without
breaking backward compatibility.

`identity_conversion()` is exposed for the future comparison engine to
skip unnecessary FX calls when base==quote.

---

## 9. Security (per spec §11)

| Item | Status |
|---|---|
| Frankfurter credential | **None required by the documented public API** (recorded) |
| Constructor signature | `FrankfurterFXProvider(base_url=...)` — no secret param |
| Env-var reads | None for credentials; env flags only for test simulation |
| Trace / evidence files | No `Authorization` / `apikey` / `x-api-key` headers (none are sent) |
| Test R | Set `FAKE_FX_TOKEN_DO_NOT_LEAK_xxxx` env var; grep stdout/stderr/trace/evidence — **zero matches** |

---

## 10. Limitations (per spec §17)

| Limitation | Notes |
|---|---|
| `User-Agent` must be set explicitly | Frankfurter returns 403 on the Python urllib default UA; this is hardcoded to `fx_provider_v1_2_2/1.0 (no-credential)` |
| Rate limit is undocumented | Conservative default 60 req/min; `--smoke-test` caps at 2 |
| Bulk endpoint used only for health_check | Single-pair endpoint preferred for evidence generation |
| Identity conversion is only EUR→EUR pass-through | Other identity conversions (e.g., JPY→JPY) work the same way; the same identity semantics apply |
| Historical empty-array response | Frankfurter returns `[]` for future dates; we surface this as `FX_NOT_FOUND` |
| `MISSING_CREDENTIALS` failure kind is part of the v1.1 enum | Not used by v1.2.2 since Frankfurter requires no credential; preserved for architecture parity |

---

## 11. Files added (per spec §15)

**Added (no production modules modified):**
- `fx_provider.py` (~750 lines; FXProvider Protocol + FrankfurterFXProvider + MockFXProvider + normalize + identity conversion + CLI)
- `test_fx_provider_v1_2_2.py` (26 tests, all PASS)
- `docs/fx_provider_v1_2_2.md` (this document)
- `data/fx_evidence_v1_2_2.json` (CLI output; latest smoke result)
- `data/fx_trace_v1_2_2.json` (CLI trace)

**Modified:** None.
**NOT modified (per spec §15):**
- `candidate_discovery.py`
- `schedule_intelligence.py`
- `live_schedule_provider.py`
- `kiwi_price_provider.py`
- `run_pipeline.py`
- `eval_flight_yc.py`
- `flight_dashboard.py`
- `price_intelligence.py` (only imported for canonical enums; not modified)

---

## 12. Regression results

| Suite | Tests | Status |
|---|---|---|
| v0.2 | 6 | ✅ PASS |
| v0.2.1 | 7 | ✅ PASS |
| v1.0 schedule | 72 | ✅ PASS |
| v1.1 price | 104 | ✅ PASS |
| v1.1.1 | 83 | ✅ PASS |
| v1.2.0 Kiwi | 60 | ✅ PASS |
| v1.2.1 schedule | 97 | ✅ PASS |
| **v1.2.2 FX** | **26** | ✅ **PASS** |

**Zero regression.** All existing tests continue to pass with no
modification.

---

## STOP CONDITION

> v1.2.2 — Frankfurter FX Integration COMPLETE.
> Real Frankfurter API smoke test SUCCEEDED (no credential).
> Zero production modules modified.

Do **NOT** begin v1.2.3, v1.2.4, or Arbitrage Detection.

> **Exact next implementation milestone (per v1.1.5 sequencing):**
> ## v1.2.3 — Multi-passenger Parity (Gap E)

This milestone does **NOT** start automatically.

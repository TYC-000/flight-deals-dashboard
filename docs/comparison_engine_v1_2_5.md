# Cross-provider Comparison Engine — v1.2.5 (Implementation)

> Provider-agnostic **Comparison Evidence Layer**. Answers:
> *"Given the current evidence, can two candidates reasonably be compared?"*
>
> **This milestone does NOT detect arbitrage.** ComparisonEvidence tells us
> whether two evidence objects are comparable; it does NOT claim anything
> about whether a price difference is an arbitrage opportunity.

---

## 1. Objective (per spec §1)

Build a `ComparisonEvidence` layer that:

- Consumes **normalized** evidence (PriceEvidence, ScheduleEvidence,
  passenger-parity, baseline-canonicalization)
- Emits a provider-agnostic ComparisonEvidence record
- Classifies comparability into 5 canonical states
- Records the diagnostic reasons for the classification

It does NOT:

- Compute arbitrage_score
- Generate Opportunity / VerifiedOpportunity
- Pick a "winner"
- Modify Jev

---

## 2. Existing architecture (per spec §3)

**`price_intelligence.py`** — emits PriceEvidence with `verification_status`
(5-tier enum; BOOKABLE NEVER introduced), `total_amount`, `currency`,
`retrieved_at`, `freshness_bucket`, `provider`, `provider_mode`.

**`kiwi_price_provider.py`** — emits Kiwi PriceEvidence with the same
canonical keys (per v1.2.0).

**`live_schedule_provider.py`** — emits ScheduleEvidence (per v1.2.1).

**`fx_provider.py`** — emits FXEvidence (per v1.2.2). v1.2.5 consumes
the `fx_evidence` payload (`base_currency`, `quote_currency`, `rate`,
`rate_date`, `retrieved_at`, `verification_status`).

**`passenger_parity.py`** — emits ParityEvidence (per v1.2.3). v1.2.5
**invokes** the parity evaluator directly for parity status.

**`baseline_canonicalization.py`** — emits CanonicalBaseline records
(per v1.2.4). v1.2.5 consumes the `baseline_pair` reference without
re-deriving baseline semantics.

**v1.1.4 §4 ComparisonEvidence schema** (canonical):

```yaml
ComparisonEvidence = {
  comparable: bool,
  comparable_with_warnings: bool,
  parity_failures: [...],
  refusal_reasons: [...],
  candidate_amount: {amount, currency},
  baseline_amount:  {amount, currency},
  difference:       {amount, currency, signed: bool},
  compared_at:      ISO8601,
  freshness_window_minutes: int,
  freshness_window_exceeded: bool,
}
```

v1.2.5 extends this with descriptives (price delta, percentage delta, FX
state, provider disagreement, baseline_pair, schedule evidence refs)
without altering the canonical v1.1.4 semantics.

---

## 3. ComparisonEvidence schema (per spec §4)

```python
ComparisonEvidence = {
    schema_version: "v1.2.5",
    comparison_id: "{a_id}::{b_id}",
    candidate_a_id, candidate_b_id: str,
    baseline_pair: dict | None,             # v1.2.4 canonical baseline
    price_a, price_b: float | None,
    normalized_price_a, normalized_price_b: float | None,
    comparison_currency: str,
    fx_state: "IDENTITY" | "APPLIED" | "UNKNOWN" | STATE_REFUSED,
    fx_used: bool,
    fx_evidence_ref: str | None,
    delta, abs_delta, delta_percentage: float | None,
    parity_status: tuple,
    comparability_status: STATE,
    comparison_reasons: [...],               # hard mismatches
    refusal_reasons: [...],                  # hard-refusals
    soft_observations: [...],                # warnings; never force refusal
    unknown_reasons: [...],
    schedule_evidence_a, schedule_evidence_b: dict,
    passenger_parity_evidence_ref_a, _b: str | None,
    baseline_evidence_id_a, _b: str | None,
    ticket_structure_a, _b: str | None,
    cabin_a, cabin_b: str | None,
    baggage_a, baggage_b: dict,
    itinerary_a, itinerary_b: Any,
    date_binding: {travel_date_a/b, return_date_a/b},
    provider_a, provider_b: str,
    provider_mode_a, provider_mode_b: str,
    provider_disagreement: bool | None,
    verification_status_a, _b: str,
    rule_version: "v1.2.5/v1",
    retrieved_at: ISO8601,
    evidence_provenance: {source, source_type, endpoint, retrieved_at,
                          verification_status, rule_version, evidence_arity: 2},
    verification_status: "DATABASE",
    source: "comparison_engine_v1_2_5",
    is_identity: False,
    supports_no_credential: True,
    warnings: [], failure_reason: None, failure_kind: None,
}
```

---

## 4. Comparability states (per spec §5)

| State | Meaning | Hard reasons | Soft | Refusal |
|---|---|---|---|---|
| `HARD_COMPARABLE` | All known dimensions match | none | none | none |
| `SOFT_COMPARABLE` | All known dimensions match but at least one soft observation | none | yes | none |
| `UNKNOWN` | Insufficient evidence to determine | none | n/a | none |
| `NOT_COMPARABLE` | At least one hard dimension mismatch | yes | n/a | none |
| `REFUSED` | Hard refusal — currency unknown, FX missing, etc. | n/a | n/a | yes |

This terminology reconciles with v1.1.4 §11.1 (which uses
`POTENTIAL_OPPORTUNITY` / `EVIDENCE_VERIFIED` for higher states). The
mapping:

| v1.2.5 | v1.1.4 §11.1 |
|---|---|
| HARD_COMPARABLE | `POTENTIAL_OPPORTUNITY` |
| SOFT_COMPARABLE | `INSUFFICIENT_EVIDENCE` with parity_passed_via_warnings |
| UNKNOWN | `INSUFFICIENT_EVIDENCE` |
| NOT_COMPARABLE | `NOT_COMPARABLE` |
| REFUSED | `REFUSED` |

---

## 5. Hard comparability (per spec §6)

Pre-conditions for `HARD_COMPARABLE`:

- `origin == origin` (exact airport identity)
- `destination == destination`
- `travel_date == travel_date`  (date-window ±1 day is REFUSED per v1.1.4 §4)
- `return_date == return_date` if either side has return_date
- `cabin == cabin`  (case-insensitive)
- `passenger_basis` matches (per v1.2.3 parity)
- `ticket_structure == ticket_structure` (single vs multi → REFUSED)
- `currency != null` and `verification_status != UNKNOWN/ESTIMATED`

Hard refusal (REFUSED state): any of:

- `REFUSAL_CURRENCY_UNKNOWN`
- `REFUSAL_DATE_MISMATCH` (>±1 day drift)
- `REFUSAL_AIRPORT_MISMATCH` (TPE ≠ MAD; no auto-coalesce)
- `REFUSAL_CABIN_MISMATCH`
- `REFUSAL_TICKET_STRUCTURE_MISMATCH` (single vs multi)
- `REFUSAL_FX_NOT_FOUND` (different currency, no FX evidence)
- `REFUSAL_PRICE_NOT_FOUND` (price missing)

---

## 6. Soft comparability / observations (per spec §6)

| Observation | Surfaced as |
|---|---|
| Baggage basis differs | `BAGGAGE_CHECKED_MISMATCH` (hard→NOT_COMPARABLE) or `SOFT_BAGGAGE_UNKNOWN` |
| Itinerary differs (e.g., TPE→FRA→MAD vs TPE→DOH→MAD) | `SOFT_ITINERARY_MISMATCH` (soft) |
| Provider disagreement | `SOFT_PROVIDER_DISAGREEMENT` (soft) |
| Passenger parity UNKNOWN | `PP_*` from v1.2.3 (soft) |
| Stale price | `SOFT_PRICE_STALE` (soft) |
| FX stale | `SOFT_FX_STALE` (soft; not auto-applied) |
| Fare basis mismatch | `SOFT_FARE_BASIS_MISMATCH` (soft) |

None of these force a refusal.

---

## 7. Cross-provider price normalization (per spec §8)

```
A.currency == B.currency == comparison_currency  → IDENTITY (no FX call)
A.currency == B.currency ≠ comparison_currency    → UNKNOWN (FX needed but not provided)
A in comparison_currency, B not                   → A is identity, B uses FX
B in comparison_currency, A not                   → mirror
A and B both need conversion                     → FX applied if available, else REFUSED
```

Per spec §9:

- Same currency → identity conversion (`rate=1`)
- Different currency → consume v1.2.2 FXEvidence
- FX missing → `REFUSED` / `UNKNOWN` (never guess)
- Static FX in production comparison is NEVER used; FRESH FXEvidence
  is consumed only.

---

## 8. PriceEvidence freshness (per spec §10)

| Bucket | Treated as |
|---|---|
| `FRESHNESS_RECENT` (≤30m) | LIVE-feasible |
| `FRESHNESS_WARM` (≤4h) | LIVE-feasible (soft observation) |
| `FRESHNESS_COLD` (≤24h) | soft `SOFT_PRICE_STALE` |
| `FRESHNESS_EXPIRED` (>24h) | soft `SOFT_PRICE_STALE` |
| `FRESHNESS_UNKNOWN` | preserved as UNKNOWN |

Stale does NOT auto-downgrade to NOT_COMPARABLE; it surfaces a soft
observation. The future upgrade-tier (LIVE → VERIFIED via freshness) is
preserved for v1.3.x and is NOT in v1.2.5's scope.

---

## 9. Date binding (per spec §11)

- `travel_date_a` must match `travel_date_b` for hard comparability
- >±1 day drift → REFUSED (per v1.1.4 §4 explicit policy)
- Missing travel_date on either side → UNKNOWN handling
- Round-trip: `return_date` preserved independently (no collapse)

---

## 10. Provider disagreement (per spec §12)

`provider_disagreement = (a.provider != b.provider)` when both known.

Surfaced as `SOFT_PROVIDER_DISAGREEMENT`. NEVER REFUSED.
`provider_a` and `provider_b` are preserved distinct; the engine does
not pick a winner.

Delta is preserved as `{delta, abs_delta, delta_percentage}` with no
score interpretation.

---

## 11. Critical success example (per spec §27)

```
Candidate A:
  TPE → FRA → MAD
  EUR 420
  1 ADT economy single-ticket, 1 checked bag
  Travel date 2027-04-15
  Provider: Duffel (LIVE)

Candidate B:
  TPE → DOH → MAD
  USD 480
  1 ADT economy single-ticket, 1 checked bag
  Travel date 2027-04-15
  Provider: Kiwi (LIVE)

FX: USD → EUR via Frankfurter, rate 0.88
Comparison currency: EUR
```

Output (test CRIT):

| Field | Value |
|---|---|
| `comparability_status` | `SOFT_COMPARABLE` (provider disagreement + itinerary diff) |
| `price_a` | 420.0 (EUR) |
| `price_b` | 480.0 (USD) |
| `normalized_price_a` | 420.0 (EUR, identity) |
| `normalized_price_b` | 422.4 (480 × 0.88) |
| `delta` | 2.4 EUR |
| `delta_percentage` | 0.57% |
| `provider_a` | duffel |
| `provider_b` | kiwi |
| `provider_disagreement` | True |
| `soft_observations` | includes `SOFT_PROVIDER_DISAGREEMENT`, `SOFT_ITINERARY_MISMATCH` |

It does NOT say "which is the arbitrage" — only that the comparison
is structurally computable.

---

## 12. Passenger parity integration (per spec §16)

The engine calls `passenger_parity.evaluate_passenger_parity(a, b)`
directly. The resulting parity status is mapped:

| Parity status | Engine behavior |
|---|---|
| `PARITY` | not surface |
| `NON_PARITY` | `PP_*` hard observations go to soft_observations; the engine does not auto-REFUSE (because parity is a downstream concern; the comparison still structurally admitted) |
| `UNKNOWN` | `PP_*` soft observations |

This matches v1.2.3's contract.

---

## 13. Schedule evidence (per spec §17)

DATABASE ≠ LIVE; LIVE ≠ VERIFIED. Schedule disagreement is preserved
as evidence, not error:

```yaml
schedule_evidence_a.verification_status: "DATABASE"
schedule_evidence_b.verification_status: "LIVE"
```

The engine surfaces both records; the future upgrade-tier sees them.

---

## 14. Provider-agnostic design (per spec §18)

`comparison_engine.py` does NOT import:

- raw Duffel JSON shape
- raw Kiwi JSON shape
- raw Frankfurter JSON shape

It consumes:

- `price_evidence` dict (canonical 44-key)
- `schedule_evidence` dict (canonical ScheduleEvidence)
- `fx_evidence` dict (canonical FXEvidence)
- `baggage` / `cabin` / `ticket_structure` / `itinerary_identity`
  / passenger fields

Provider adapters stay separate.

---

## 15. Failure semantics (per spec §19)

Any failure becomes one of:

- `refusal_reasons` (forces state to `REFUSED`)
- `comparison_reasons` (forces state to `NOT_COMPARABLE`)
- `soft_observations` (forces state to `SOFT_COMPARABLE` if no others)
- `unknown_reasons` (forces state to `UNKNOWN`)

NEVER `EXPENSIVE`, `CHEAP`, `ARBITRAGE`, `OPPORTUNITY`.

---

## 16. No silent fallback (per spec §20)

Provider identity preserved on every record:

- `provider_a` ≠ `provider_b` is captured
- No substitution from Duffel to Kiwi silently
- `provider_mode_a` and `provider_mode_b` are distinct

---

## 17. Real API (per spec §21)

**0 real API calls** in v1.2.5 (the engine consumes already-emitted
evidence). Hard ceiling ≤2 if any (none used).

---

## 18. Security (per spec §22)

- No Authorization header surface
- No provider tokens in trace
- Test AL: `FAKE_COMPARISON_TOKEN_DO_NOT_LEAK_xxx` env var set; grep
  stdout/stderr/trace/JSON artifacts → 0 matches
- Forbidden tokens guarded at serialization time

---

## 19. Files added (per spec §23)

**Added:**

- `comparison_engine.py` (~750 lines)
- `test_comparison_engine_v1_2_5.py` (41 tests, all PASS)
- `docs/comparison_engine_v1_2_5.md` (this document)
- `data/comparison_evidence_v1_2_5.json`
- `data/comparison_trace_v1_2_5.json`

**Modified:** None. **No production module was touched** (only
imports of canonical enums from price_intelligence, fx_provider,
passenger_parity, baseline_canonicalization).

Jev not modified.

---

## 20. Regression results

| Suite | Tests | Status |
|---|---|---|
| v0.2 | 6 | ✅ |
| v0.2.1 | 7 | ✅ |
| v1.0 | 72 | ✅ |
| v1.1 | 104 | ✅ |
| v1.1.1 | 83 | ✅ |
| v1.2.0 | 60 | ✅ |
| v1.2.1 | 97 | ✅ |
| v1.2.2 | 26 | ✅ |
| v1.2.3 | 30 | ✅ |
| v1.2.4 | 44 | ✅ |
| **v1.2.5** | **41** | ✅ **PASS** |

**Zero regression.**

---

## 21. Known limitations

1. The engine does not currently consume OpenFlights schedule evidence
   directly; it consumes whatever ScheduleEvidence the v1.2.1 module
   provided. This is by design (provider-agnostic at this layer).
2. "Provider disagreement" is captured at the price layer, not at the
   schedule layer (because each side typically has a single schedule
   source).
3. FX normalization requires a single per-pair FX evidence; multi-pair
   FX would need a future batch-FX wrapper.
4. CLI mode is single-pair. Batch comparison across N candidates is out
   of scope.
5. Date drift ±1 day handling is delegated to v1.3.x (today's v1.2.5
   treats >0 day drift as REFUSED, per the simplest reading of v1.1.4 §4).
6. Statistic-level soft observations may not surface everything that a
   future parity-checker would; v1.2.5 records what's structurally known
   from the input dict.

---

## STOP CONDITION

> v1.2.5 — Cross-provider Comparison Engine COMPLETE.
> Zero production modules modified.
> Zero real API calls. Zero credential leakage.
> ComparisonEvidence, NOT ArbitrageEvidence.
> Comparable / not comparable, NOT arbitrage / not arbitrage.

This milestone does NOT begin Arbitrage Detection.

The objective is not to move fast by adding features.
The objective is to build an evidence-grade Flight Arbitrage Hunter where every comparison can eventually answer:
**"Why do we believe these two prices are actually comparable?"**

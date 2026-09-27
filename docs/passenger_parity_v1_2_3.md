# Passenger Parity — v1.2.3 (Implementation)

> Provider-agnostic Multi-passenger Parity Evidence primitive. Closes
> **Gap E** from v1.1.5 Evidence Source Matrix.
>
> v1.2.3 is NOT arbitrage detection. It produces **ParityEvidence** that
> gates whether two PriceEvidence records have the prerequisites for
> a future cross-provider comparison — and **never** claims anything
> about which side is cheaper.

---

## 1. Objective

**What this milestone produces**: A primitive that emits a normalized
**ParityEvidence** record comparing two PriceEvidence records along the
hard dimensions needed for any future price comparison:

- passenger_count
- passenger_type_composition
- cabin
- itinerary_identity
- ticket_structure
- baggage (soft observation only)
- fare_basis (soft observation only)
- price_per_passenger (derived analytical field only)

**What this milestone does NOT do**:

- Arbitrage detection
- ArbitrageEvidence emission
- Opportunity / VerifiedOpportunity
- Ranking / winner selection
- Cheaper-than-baseline logic
- Modify Jev scoring semantics

---

## 2. Existing schema inspection (per spec §2)

**Found in `price_intelligence.py`** (PriceEvidence already exposes):

| Field | Surface |
|---|---|
| `passenger_count` | int via `--passengers` CLI; encoded in `search_metadata` |
| `cabin_class` | str from `long_haul.cabin` |
| `baggage.included.checked_pieces` | int (or None when not disclosed) |
| `baggage.included.carry_on` | int |
| `baggage.evidence_complete` | bool — false when baggage-not-disclosed |
| `provider` / `provider_mode` / `retrieved_at` | top-level provenance |

**Gaps** (added by v1.2.3 if present; otherwise stays `None`):

| Field | Source requirement |
|---|---|
| `passenger_types` | not exposed by current v1.1 — treated as unknown |
| `ticket_structure` | not exposed — derived only if `ticket_count` is present |
| `fare_basis` / `fare_family` | not exposed — observed if present |
| `itinerary_identity` | not surfaced — caller may provide |

**Architecture decision**: v1.2.3 modifies **NOTHING** in `price_intelligence.py`.
The parity layer consumes any dict with the documented fields and is
backward-compatible with current v1.1 / v1.2.x outputs.

---

## 3. Parity Evidence schema

```python
ParityEvidence = {
    schema_version: "v1.2.3",
    parity_status: "PARITY" | "NON_PARITY" | "UNKNOWN",
    hard_parity_reasons:        # disagreements only (NON_PARITY)
        ["PASSENGER_COUNT_MISMATCH" |
         "PASSENGER_TYPE_MISMATCH"  |
         "CABIN_MISMATCH"           |
         "ITINERARY_MISMATCH"       |
         "TICKET_STRUCTURE_MISMATCH"],
    soft_parity_observations:    # missing-data observations (never force NON_PARITY)
        ["PASSENGER_COUNT_UNKNOWN" | ...],
    dimension_results: {
        passenger_count:           {match, known, a, b},
        passenger_type_composition:{match, known, a, b},
        cabin:                     {match, known, a, b},
        itinerary_identity:        {match, known, a, b},
        ticket_structure:          {match, known, a, b},
        baggage:                   {match, known, a, b},  # soft
        fare_basis:                {match, known, a, b},  # soft
        price_per_passenger:       {match, known, a, b, derived, note},  # derived
    },
    price_per_passenger: {
        a, b, difference, derived=True,
        note: "derived analytical field; never used to claim cheaper/better/opportunity/arbitrage"
    },
    totals: {a_total_price, b_total_price, currency_a, currency_b, currency_parity},
    provider_disagreement: True | False | None,
    providers: {a: {provider, provider_mode, retrieved_at},
                 b: {provider, provider_mode, retrieved_at}},
    verification_status: "DATABASE",  # parity is structural
    source: "passenger_parity_v1_2_3",
    is_identity: False,
    supports_no_credential: True,
    warnings: [],
    failure_reason: None,
    failure_kind: None,
    provenance: {source, source_type, retrieved_at, evidence_arity: 2},
}
```

---

## 4. Hard parity dimensions (5 dimensions; any disagreement → NON_PARITY; any unknown → UNKNOWN)

| Dimension | Source |
|---|---|
| `passenger_count` | `passenger_count` field, or composition count (only if all counts are integers) |
| `passenger_type_composition` | distinct type codes (ADT/CHD/INF) |
| `cabin` | `cabin` / `cabin_class` lowercased |
| `itinerary_identity` | explicit, or derived from a candidate signature |
| `ticket_structure` | `single-ticket` / `multi-ticket` / `unknown` |

## 5. Soft observations (4 dimensions; surface only; never force NON_PARITY)

| Dimension | Treatment |
|---|---|
| `baggage` | record in `dimension_results` and `soft_parity_observations`; never fail parity on baggage |
| `fare_basis` | record; never fail parity |
| `currency` | match check recorded in `totals.currency_parity`; not a parity dimension |
| `price_per_passenger` | derived analytical field |

---

## 6. Hard rule: Never coerce missing data to defaults

Per spec §4:

| Missing | Forbidden default | Actual behavior |
|---|---|---|
| `passenger_count` | 1 passenger | UNKNOWN, `pc=None`, `pc_known=False` |
| `passenger_type` | ADT | UNKNOWN, `passenger_types=[]`, `passenger_types_known=False` |
| `cabin` | ECONOMY | UNKNOWN, `cabin=None` |
| `baggage` | 0 bags | UNKNOWN, `baggage.basis_known=False` |

Bare type-list `["ADT", "CHD"]` (without counts) is treated as type-known but count-unknown → `pc_known=False`. Dict-list `[{"type":"ADT","count":2}]` with integer counts is fully known.

---

## 7. Price-per-passenger semantics (derived only)

`price_per_passenger = total_price / passenger_count` is computed and exposed
in `dimension_results.price_per_passenger` and `price_per_passenger`. This is
**strictly an analytical observation field**. The note in `price_per_passenger`
and on `dimension_results.price_per_passenger` explicitly states:

> *"derived analytical field; never used to claim 'cheaper', 'better',
> 'opportunity', or 'arbitrage'"*

A negative `difference` (b < a per-pax) does NOT make parity parity-affecting.
A 1pax @ $500 vs 2pax @ $900 has `difference = -50` and is still PARITY if
all hard dimensions agree — it's the comparison engine's job (a future
milestone) to interpret that observation, not the parity layer's.

---

## 8. Provider provenance

`providers.a.provider` / `providers.a.provider_mode` / `providers.a.retrieved_at`
preserved distinct from `providers.b` so a Duffel-live ↔ Kiwi-live pair is
non-confusable. `provider_disagreement` is computed and surfaced; it is not
an error, it is evidence (per spec §12).

---

## 9. Failure semantics

Per spec §14, parity failures use a parity-specific taxonomy that does not
overlap with v1.1 failure kinds (which apply to provider call failures).
Parity FAILURES are observation labels in `hard_parity_reasons` and
`soft_parity_observations`, NOT in `failure_kind`. The `failure_kind` field
of the ParityEvidence record stays `None` unless the parity function itself
encounters an internal error.

Parity observations **never** map to:

- `PRICE_NOT_FOUND`
- `ROUTE_UNAVAILABLE`
- `EXPENSIVE`
- `NO_ARBITRAGE`
- `OPPORTUNITY`

---

## 10. Security (per spec §15)

| Item | Status |
|---|---|
| Real provider calls required | 0 (deterministic synthetic fixtures only) |
| Hard ceiling if any real call | 2 (none used) |
| `Authorization` header surface | not used (no credentials) |
| FAKE_PROVIDER_TOKEN_DO_NOT_LEAK_xxx env var set, grep stdout/stderr/trace/JSON artifact | 0 matches (Test AC) |

---

## 11. Files added (per spec §17)

**Added:**

- `passenger_parity.py` (~700 lines; extraction + parity evaluation + CLI)
- `test_passenger_parity_v1_2_3.py` (30 tests, all PASS)
- `docs/passenger_parity_v1_2_3.md` (this document)

**Modified:** None. **No production module was touched.**

**NOT modified:**

- `candidate_discovery.py`
- `schedule_intelligence.py`
- `live_schedule_provider.py`
- `kiwi_price_provider.py`
- `fx_provider.py`
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
| v1.0 | 72 | ✅ PASS |
| v1.1 | 104 | ✅ PASS |
| v1.1.1 | 83 | ✅ PASS |
| v1.2.0 Kiwi | 60 | ✅ PASS |
| v1.2.1 schedule | 97 | ✅ PASS |
| v1.2.2 FX | 26 | ✅ PASS |
| **v1.2.3 parity** | **30** | ✅ **PASS** |

**Zero regression.** All existing tests continue to pass with no modification.

---

## 13. Real API request count

**0.** v1.2.3 is fully offline. No real provider calls.

---

## 14. Known limitations (per spec §20)

1. `passenger_types` is not surfaced by v1.1 PriceEvidence schema; this
   means parity records issued against current PriceEvidence records will
   always have `passenger_types_known=False` until a producer surfaces
   the field. This is intentional under spec §2's backward-compat rule.
2. `itinerary_identity` is not surfaced by v1.1 either; until a producer
   surfaces it, this dimension stays UNKNOWN, parity falls back to UNKNOWN.
3. `fare_basis` / `fare_family` are not surfaced; observation only.
4. `ticket_structure` is derived only when `ticket_count` is explicit,
   otherwise UNKNOWN.
5. The CLI is single-pair — it consumes two specific evidence files. A
   batch mode that compares across all candidates is out of scope.
6. The parity layer is purely structural; integrating it with a comparison
   engine that issues prices is a future milestone (e.g., v1.3.x).

---

## STOP CONDITION

> v1.2.3 — Multi-passenger Parity COMPLETE.
> Zero production modules modified.
> Zero real API calls. Zero credential leakage.

> **Exact next implementation milestone (per v1.1.5 sequencing):**
> ## v1.2.4 — Baseline Canonicalization (Gap F)

This milestone does **NOT** start automatically.

The objective is not to move fast by adding features.
The objective is to build an evidence-grade Flight Arbitrage Hunter where every comparison can eventually answer:
**"Why do we believe these two prices are actually comparable?"**

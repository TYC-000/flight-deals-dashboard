# Provider Capability Audit — v1.1.3 (READ-ONLY)

> Status: **architecture/documentation audit only**. No production logic was
> modified. No real Duffel API call was made. No new credential was required.
>
> This document does NOT score opportunities, NOT rank routes, and NOT
> recommend a winner between providers. It only documents what the current
> Duffel provider + PriceEvidence contract can and cannot represent.

---

## 1. Audit method

Inspected (without modification):

| File | Purpose |
|---|---|
| `price_intelligence.py`        | v1.1 implementation (1502 lines) |
| `docs/price_intelligence_v1.md` | v1.1 + v1.1.1 + v1.1.2 reports |
| `docs/price_intelligence_v1.1.md` | v1.1 architecture spec |
| `docs/price_provider_matrix.md` | Provider matrix (Duffel, Kiwi, Skyscanner, etc.) |
| `data/price_evidence.json`     | Latest emitted evidence payload |
| `data/price_trace.json`        | Latest emitted trace |
| `test_price_intelligence_v1.py` | 104 v1.1 regression assertions |
| `test_price_intelligence_v1_1.py` | 83 v1.1.1 validation assertions |

External reference used: the Provider Matrix doc
(`docs/price_provider_matrix.md`) plus Duffel's API documentation patterns
that were captured in that matrix during v1.1 architecture design.

Duffel-specific field names referenced below are sourced from Duffel's
`air/offer_requests` response shape as documented in the matrix.

---

## 2. Capability Matrix

Legend:

- ✅ **Supported** — current v1.1 implementation actively reads / surfaces
  this in the normalized PriceEvidence contract.
- 🟡 **Partially Supported** — read or computed for *some* cases, but not
  robust across all routings / cabin / fare types.
- ⚪ **Not Supported** — not present in either the producer API response
  or the v1.1 normalizer.
- ❓ **UNKNOWN** — not enough evidence in current implementation or docs
  to commit to a support level; "do not invent".

| Capability | Status | Evidence (file + section) |
|---|---|---|
| one-way search                  | ✅     | `price_intelligence.py:687-699` (DuffelProvider.quote builds slices without a return leg when `date_window` has no `_to_`). |
| round-trip search               | ✅     | `price_intelligence.py:700-706` (return slice appended when `_to_` present in `date_window`). |
| multi-city search               | ✅     | `price_intelligence.py:693-706`; each segment becomes a slice; up to N slices are accepted by Duffel's `air/offer_requests`. |
| open-jaw representation         | 🟡     | Round-trip can be approximated (final slice reversed) but is not a first-class constructor; no dedicated `open_jaw` flag. |
| multiple ticket groups          | ✅     | `normalize_duffel_response` builds `ticket_groups[]` from `slices[]` (lines 801-850). |
| multi-ticket construction       | ✅     | Same; `offer.type == "split_ticket"` triggers per-slice pricing; `separate_ticket_risk` enum emitted (lines 861-875). |
| positioning flights             | 🟡     | Can be represented as two separate `ticket_groups` (a positioning leg + main leg); the producer API returns it as multiple slices, not as a structured "positioning" field. No special-case flag. |
| airport change                  | 🟡     | Detected post-hoc: `self_transfer` boolean compares adjacent ticket groups (lines 852-859). Not surfaced as a separate field; inferable but not structured. |
| operating carrier               | ✅     | `ticket_groups[].stops[].operating_carrier` (lines 834-836, reads `segment.operating_carrier.iata_code`). |
| marketing carrier               | ✅     | `ticket_groups[].stops[].carrier` (lines 835). |
| flight number                   | ✅     | `ticket_groups[].stops[].flight_number` (lines 837). |
| departure time                  | ✅     | `ticket_groups[].stops[].depart` (lines 838). |
| arrival time                    | ✅     | `ticket_groups[].stops[].arrive` (lines 839). |
| duration                        | 🟡     | Surfaced indirectly via `stops[].depart`/`arrive` deltas; not stored as a separate field on `stops`. |
| cabin                           | ✅     | `payload.cabin` (lines 884-890); also surfaced per-slice via `slice_obj.passengers[].cabin.cabin_class`. |
| baggage allowance               | 🟡     | `baggage.included.checked_pieces` exists but default is `0` if not seen; `evidence_complete` flag tracks whether the field was actually present. `passenger_through_check_baggage` is per-group. |
| fare conditions (changeable)    | ⚪     | `changeable: null` (line 942). Duffel's `air/offer_requests` does NOT include change rules — those require a separate `order_change_requests` lookup. |
| fare conditions (refundable)    | ⚪     | `refundable: null` (line 943). Same as above. |
| ticket conditions               | ⚪     | `change_fee` / `refund_fee` always null (lines 944-945). |
| price                           | ✅     | `total_price.amount` / `base_fare.amount` / `taxes.amount` (lines 933-935) with FX envelope. |
| currency                        | ✅     | `currency` field on payload; explicit FX provenance envelope via `fx_envelope()` (lines 206-253). |
| expiry                          | ✅     | `valid_until` and `price_quote_expires_at` from `offer.expires_at` (lines 956-957). |
| segment-level data              | ✅     | Each `ticket_groups[].stops[]` carries full segment-level data. |
| connection information          | ⚪     | **NOT** captured. The current v1.1 normalizer does NOT compute `connection_time`, `overnight_connection`, `tight_connection`, or `airport_change` from real segment times. The mock produces hard-coded `08:00/13:00` times that would not survive comparison. |
| schedule verification           | ⚪     | NOT a PriceEvidence concern — schedule is owned by `schedule_intelligence.py` (v1.0, DATABASE evidence from OpenFlights). PriceEvidence does not embed `schedule_status`. |
| real-time availability evidence | ⚪     | Only the price itself is real-time; availability is implied by the offer being returned, but **there is no field that records "the seat was available at retrieval time"** as a discrete observation. Duffel's offer expires within minutes; the `freshness_min` field captures the age but not a separate availability confidence. |

---

## 3. Arbitrage architecture implications

For each potential arbitrage archetype, what the current contract can and
cannot represent.

### A. outer-port arbitrage
(e.g., TPE→KUL→MAD cheaper than TPE→MAD)

- **Affected if missing:** cabin, baggage, ticket_count.
- **Currently representable:** price (total), ticket_groups count, separate_ticket_risk.
- **NOT representable:** the *existence* of the outer-port leg as a labeled
  structural signal — that lives in `schedule_intelligence.structural_signals`,
  not in PriceEvidence. Cross-layer correlation is the responsibility of v1.2.
- **No critical gap**, as long as the consumer joins `schedule_intelligence`
  with `price_intelligence` outputs by `candidate_id`.

### B. alternative-hub arbitrage
(e.g., TPE→DXB→MAD vs TPE→FRA→MAD)

- Same as A. Price comparison alone is not sufficient; the routing-structure
  comparison requires schedule evidence (already in v1.0).
- **No critical gap.**

### C. secondary-entry arbitrage
(e.g., TPE→LIS→MAD with LIS as a separate cheap-entry point)

- Currently representable IF the producer returns the LIS leg at all. Duffel
  does support secondary European entries via `slices[]`. ✅
- **No critical gap**, but v1.2 should not assume the producer always surfaces
  every feasible secondary entry — some are simply not in the inventory.

### D. positioning-flight arbitrage
(e.g., TPE→BKK positioning + BKK→MAD main, two separate tickets)

- 🟡 **Gap**: pricing is representable via multi-ticket construction;
  the *positioning* nature is captured only via `ticket_count > 1`. There's no
  dedicated `is_positioning` flag in the normalized contract.
- v1.2 must infer positioning from candidate metadata (already in
  `candidate_discovery.py` via `positioning` field) and join by `candidate_id`.

### E. multi-ticket arbitrage

- ✅ Well-supported: `ticket_groups`, `separate_ticket_risk`, `self_transfer`.
- The `MULTI_TICKET_PRICE_INCOMPLETE` warning explicitly handles the
  case where the producer prices only some legs.

### F. airport-change routing
(e.g., arrival at LHR, departure from LGW)

- 🟡 **Gap**: detected implicitly via `self_transfer = True` in
  `normalize_duffel_response`, but there is no structured
  `airport_change_required` field. Downstream consumers must re-derive
  it from comparing adjacent `ticket_groups[].stops[].from/to` fields.
- Connection *time* between groups is NOT computed (no `connection_time_min`
  field).

### G. unusual-routing opportunities
(e.g., TPE→HEL→BCN, very long connection)

- 🟡 **Gap**: detected at schedule layer (v1.0). Price layer alone cannot
  detect "unusual" because it doesn't know the standard.
- The `airport_change_required` and `connection_time_min` fields would help
  v1.2 quantify "unusual" but are not present.

### Summary

| Archetype | v1.2 needs join with schedule? | Additional PriceEvidence fields needed? |
|---|---|---|
| A. outer-port             | yes | no |
| B. alternative-hub        | yes | no |
| C. secondary-entry        | partial | no |
| D. positioning-flight     | yes | optional `is_positioning` flag |
| E. multi-ticket           | no  | no |
| F. airport-change routing | partial | `airport_change_required`, `connection_time_min` |
| G. unusual-routing        | yes | optional `connection_time_min` |

---

## 4. PriceEvidence contract review

### 4.1 Fields already sufficient

These fields are present and meaningful enough for cross-routing price
comparison (subject to the comparison rules in `price_comparison()`,
lines 1261-1329):

- `currency` — explicit, with FX envelope
- `total_price`, `base_fare`, `taxes`, `fees`, `optional_extras`
- `ticket_count`, `is_single_ticket`, `self_transfer`, `separate_ticket_risk`
- `cabin` (economy/premium_economy/business/first)
- `baggage.evidence_complete` — explicit "we don't know"
- `freshness_min`, `freshness_bucket`
- `verification_status`, `price_status`, `failure_kind`, `failure_reason`
- `provenance.source`, `provenance.source_type`, `provenance.retrieved_at`,
  `provenance.freshness_min`, `provenance.endpoint`, `provenance.offer_id`,
  `provenance.verification_status`
- `provider`, `provider_mode` — explicit identity

### 4.2 Fields requiring extension (NOT implemented in v1.1.3)

Per the audit matrix (§2), the following are **not present** and would
extend the contract:

| Field | Why needed for v1.2 |
|---|---|
| `airport_change_required` (bool)     | Detect LHR→LGW class routings explicitly |
| `connection_time_min[]` (list[int])  | For each connection, the layover duration; needed to score "schedule friction" |
| `overnight_connection` (bool)        | Detect forced overnight at connection |
| `is_positioning` (bool)              | Distinguish positioning arbitrage from co-ticket arbitrage |
| `fare_class_code` (str \| None)      | RBD code (Y, B, J, etc.) for capacity/availability inference |
| `seats_remaining` (int \| None)      | Producer-side availability hint (if returned) |
| `refundable`, `changeable` (bool \| None) | Lifecycle / risk adjustments |
| `change_fee`, `refund_fee` (Money \| None) | Lifecycle / risk adjustments |

**Decision for v1.1.3:** do NOT add these. They are candidates for v1.2
design, after explicit user approval. Adding them now would constitute
v1.2 scope creep.

### 4.3 Fields that should remain provider-specific

These Duffel-specific fields appear in the raw `_request_body` and/or raw
`raw_provider_response_hash` envelope but MUST NOT leak into the
normalized `PriceEvidence` payload:

- `passengers[]` raw structure
- `segments[].passengers[]` raw
- `owner.name` (the publishing carrier brand name)
- `payment_requirements` (Duffel-specific order-time concept)
- `slices[].segments[].fare_class_code` — should be lifted to a normalized
  field (`fare_class_code`) if/when added, not kept as Duffel-specific

### 4.4 Fields that must never be inferred

Per the spec's false-confidence protections:

- `seats_remaining`: NEVER infer; Duffel may return null and "we don't know"
  is the honest answer
- `refundable` / `changeable`: NEVER infer from fare basis code; require an
  order-level rule fetch (out of scope for v1.1)
- `connection_time_min`: NEVER infer from mock timestamps; the mock currently
  uses hard-coded `08:00 / 13:00` strings, which is a code smell — see §6.1
  below

---

## 5. Semantic boundaries (preserved)

These were already locked in v1.1 + v1.1.1 and remain unchanged by this
audit:

- `VERIFIED != BOOKABLE` — `VERIFIED` is a verification_status; we never
  emit `BOOKABLE`. `FORBIDDEN_VERIFICATION_VALUES = {BOOKABLE, BOOKED, PURCHASABLE}`.
- `PRICE FOUND != GOOD PRICE` — `price_status == "OK"` means a price was
  returned; it does not imply the price is good.
- `CHEAPER != ARBITRAGE` — `price_comparison.a_less_than_b` is a comparison
  result, never a claim of arbitrage.
- `ROUTE EXISTS != FLIGHT OPERATES ON DATE` — schedule evidence is owned
  by `schedule_intelligence.py` (DATABASE evidence from OpenFlights), not by
  PriceEvidence.
- `FLIGHT OPERATES != TICKET AVAILABLE` — even a real Duffel offer is a
  short-lived quote, not a ticket.
- `MULTI-TICKET PRICE != USER-EXECUTABLE ITINERARY` — `MULTI_TICKET_PRICE_INCOMPLETE`
  warning preserves this; `separate_ticket_risk = elevated/high` is the
  structured acknowledgement.
- `SCHEDULE SUPPORTED != OPERABLE` — `schedule_status` is candidate-level
  structural completeness (OpenFlights), not a booking claim.

**No semantic boundary was weakened by this audit.**

---

## 6. Provider abstraction assessment

### 6.1 The current abstraction

```
PriceProvider (Protocol)
    ↓
DuffelProvider     (real)
MockDuffelProvider (deterministic)
```

`PriceProvider` declares: `name`, `capabilities()`, `health_check()`,
`quote(candidate, date_window, passengers)`.

`ProviderCapabilities` is a structured dataclass with:
- `supports_split_ticket`, `supports_multi_city`, `supports_positioning`
- `includes_baggage`, `includes_seat`
- `currency_native[]`, `cabin_classes[]`
- `freshness_ttl_min`, `rate_limit_per_min`
- `is_bookable_claim` — **the producer's own claim, never honored as VERIFIED**

### 6.2 Is this sufficient for a second provider?

**YES** for the structural interface; the `quote()` signature is
provider-agnostic. A future `KiwiProvider`, `AmadeusProvider`, or
`airline-direct` provider can implement `PriceProvider` and slot in.

**Conditions that must be satisfied by the new provider's adapter:**

1. The adapter MUST emit a `PriceEvidence` payload identical in shape to
   what `DuffelProvider.quote()` produces today (or extend it via the
   extension fields in §4.2 — but that requires a contract change approved
   at the architecture level).
2. The adapter MUST populate `provider` and `provider_mode` distinctly.
   A future Kiwi adapter would use `"kiwi"` and `"live"`; an Amadeus
   adapter would use `"amadeus"` and `"live"`. The current `provider_mode`
   enum (`"live" | "mock"`) accommodates this.
3. The adapter MUST respect the 5-tier `verification_status` enum
   (UNKNOWN/ESTIMATED/DATABASE/LIVE/VERIFIED). A provider that cannot
   distinguish ESTIMATED from LIVE should emit UNKNOWN or fail with
   `FK_PROVIDER_ERROR` rather than overclaim.
4. The adapter MUST populate `provenance.source` with a stable identifier
   (e.g., `"kiwi"` or `"amadeus"`) and never share it with another provider.

### 6.3 Adapter-boundary leakage check

Looking at `normalize_duffel_response`, the following Duffel-specific
structures appear in raw input but are not leaked downstream:

- `data.id` → kept as `provenance.offer_id` only, not as a top-level field
- `data.passengers[]` → only `cabin` is read
- `data.owner.name` → not propagated
- `data.slices[].segments[].fare_class_code` (Duffel field) → **NOT** lifted

The contract is clean. A second adapter that lifts additional fields (e.g.,
a Kiwi-specific "quality_score") MUST keep it inside the `price_evidence`
under a provider-namespaced subkey, never as a top-level normalized field.

### 6.4 Known weakness: mock timestamps

The MockDuffelProvider currently emits hard-coded timestamps
(`2027-04-15T08:00:00 / 13:00:00`) that are not anchored to the candidate
or date_window. This means the mock evidence **cannot be compared with
real evidence on freshness grounds** — the timestamps are a code smell.

This does NOT affect the real Duffel adapter (which uses ISO timestamps
parsed from the actual API response). It only affects mock-vs-real
schema comparison if v1.2 attempts to use the mock for stress testing.

**Recommendation for v1.1.3**: do NOT fix this (it would be a code change).
Track as a known limitation.

---

## 7. Critical question 1: Is Duffel alone sufficient?

> "Is Duffel alone sufficient to build a reliable Flight Arbitrage Hunter?"

**Answer: PARTIALLY.**

### Why

**What Duffel alone CAN do:**

1. **Return LIVE prices for structurally-known routings.** For every
   `ticket_groups` construct that is feasible as a Duffel slice (one-way,
   round-trip, multi-city, split_ticket), Duffel can return a real offer
   with valid `total_amount`, `expires_at`, `currency`, and (where supported)
   `cabin`, `baggage`. This covers most routings that the candidate
   discovery v0.1 generator emits.

2. **Distinguish single-ticket vs split-ticket pricing.** Via the `type`
   field on the offer. This is essential for arbitrage detection that
   compares "what if I book it as two separate tickets".

3. **Provide operating vs marketing carrier data.** Useful for filtering
   by Star Alliance vs non-aligned, and for cross-routing comparison.

**What Duffel alone CANNOT do:**

1. **Verify that a route operates on the user's specific travel date.**
   Duffel's offer is a price quote; it does not assert "this flight is
   scheduled on this date". Schedule verification is owned by
   `schedule_intelligence.py` (OpenFlights), which is DATABASE evidence
   only — and OpenFlights itself is known to be stale and incomplete.

2. **Surface fare rules (changeable, refundable, cancellation fee).**
   These require a follow-up `air/order_change_requests` lookup that
   v1.1 does not perform.

3. **Provide seats-remaining information.** Duffel may or may not include
   this; it is not part of the v1.1 normalized contract.

4. **Represent the comparison baseline.** A single provider can compare
   "TPE→KUL→MAD via Duffel" against "TPE→MAD via Duffel", but it cannot
   compare against "what a human booking the same TPE→MAD via the airline
   website would have paid". The **arbitrage boundary is the producer's
   own inventory**, not the user's total cost-of-travel.

5. **Cross-source reality check.** Without a second provider (or a
   scraping layer), there is no way to detect when Duffel is returning a
   price that is structurally wrong (e.g., stale cached data, fare-class
   mismatch). One provider = one source of truth = the same blind spots
   the producer has.

6. **Outer-port / secondary-entry completeness.** Duffel's inventory is
   not exhaustive for every secondary European entry. A route that works
   in Duffel as TPE→LIS→MAD may not surface at all if LIS inventory is
   incomplete in Duffel's catalog at the time of the query.

### Conclusion

Duffel is sufficient for **PriceEvidence generation**, not for
**arbitrage verification**. The current architecture correctly separates
these concerns: v1.1 emits PriceEvidence with strict provenance; v1.2
would be the layer that decides what counts as arbitrage, and at that
layer Duffel alone is insufficient.

---

## 8. Critical question 2: Minimum evidence architecture for genuine arbitrage detection

> "What minimum additional evidence sources would be required before the
> system could claim genuine cross-routing arbitrage detection?"

This is a **capability list**, not a provider recommendation.

### 8.1 Required additional capabilities

For arbitrage detection to be considered **genuine** (not just
"cheaper-looking on one source"), the system would need:

| Capability | Why needed | Currently available? |
|---|---|---|
| **Cross-provider price comparison** | Single-source prices can't distinguish "Duffel sells this cheap" from "this is structurally cheaper". At least 2 producers needed. | NO — only Duffel. |
| **Real-time schedule confirmation for the user's date** | A schedule that exists in OpenFlights may not operate on the user's date. Need a real schedule source (e.g., AviationStack, Duffel's own schedule, airline direct). | NO — OpenFlights is DATABASE only. |
| **Operating-carrier rule fetches** | For changeable/refundable/penalty assessment per fare. | NO — v1.1 leaves these null. |
| **Availability confidence** | Some fare classes sell out fast; arbitrage is irrelevant if no seats. | NO — not in the contract. |
| **Multi-passenger parity** | Today's test fixtures assume 1 passenger. Family/business-travel pricing is meaningfully different. | NO — only `passengers=1` is exercised. |
| **Currency conversion with real FX** | Static snapshot FX (2% markup awareness) is insufficient for international comparison. | NO — static table only. |
| **User's actual travel-date window** | Duffel returns a quote for `date_window`; arbitrage claim depends on the user's specific dates, not arbitrary ones. | PARTIAL — `date_window` is passed but candidates are time-agnostic at discovery. |
| **Baseline comparison** | To call something "cheaper", we need a defined baseline (e.g., TPE→MAD direct on the same dates). | NO — no baseline computation. |

### 8.2 What this means for v1.2

If v1.2 attempts to emit `ArbitrageEvidence` with these capabilities,
it will overclaim. v1.2 should:

1. Refuse to emit any "this is an arbitrage opportunity" claim that
   depends only on Duffel.
2. Require at least one cross-check source (a second provider OR
   baseline computation) before marking anything as arbitrage.
3. Treat single-provider price differences as "Duffel-vs-Duffel"
   observations, not as market-inefficiency findings.

### 8.3 Sources not implemented and not in scope

For completeness, this audit does NOT recommend any of the following:

- Scraping (ToS-violating for most airlines)
- Paid GDS (Amadeus, Sabre) — commercial friction not evaluated
- Airline-direct NDC APIs — per-airline integration cost
- Metasearch aggregators (Skyscanner, Kayak) — commercial friction
  documented in `docs/price_provider_matrix.md`

These are noted only so v1.2 does not silently assume they will be added.

---

## 9. Files added / modified

**Added:**

- `docs/price_provider_capability_audit_v1_1_3.md` (this document)

**Modified:**

- None. (No production module was touched. No new API calls were made.
  No new tests were added — per spec §10, this milestone is
  architecture/documentation only.)

---

## 10. Existing regression results

No tests were run during this milestone (it is read-only). The last
known-good state is the v1.1.2 commit (`d651603`), with all suites
green:

| Suite | Tests | Last known status |
|---|---|---|
| v0.2          | 6   | ✅ PASS |
| v0.2.1        | 7   | ✅ PASS |
| v1.0          | 72  | ✅ PASS |
| v1.1          | 104 | ✅ PASS |
| v1.1.1        | 83  | ✅ PASS |
| v1.1.2        | (no new tests; status report) | ✅ REPORTED |

---

## STOP CONDITION

This is a read-only architecture audit. v1.1.3 STOPs here.

> **Duffel alone is PARTIALLY sufficient** for the current PriceEvidence
> layer. It is **not** sufficient for genuine cross-routing arbitrage
> detection, which would require at minimum: a second producer for
> cross-source comparison, real-time schedule confirmation for the
> user's specific dates, and explicit baseline construction.

Do **NOT** begin v1.2 Arbitrage Detection.

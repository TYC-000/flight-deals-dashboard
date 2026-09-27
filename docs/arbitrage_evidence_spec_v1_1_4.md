# Arbitrage Evidence Specification — v1.1.4

> Status: **SPECIFICATION ONLY.** No production code is modified. No new API
> calls are made. No credential is required. This document is the formal
> definition of the evidence model that a future v1.2 Arbitrage Detection
> layer would require. It does NOT implement detection, scoring, ranking,
> or any kind of recommendation.
>
> The current v1.1.3 audit established that "Duffel alone is PARTIALLY
> sufficient for PriceEvidence and insufficient for genuine cross-routing
> arbitrage detection." This document does not resolve that gap — it only
> defines what *would* need to be true for a future layer to claim
> sufficient evidence.

---

## 0. Forbidden content (per spec §16)

This document must NOT contain (and does NOT contain):

- `arbitrage_score`
- `opportunity_score`
- `candidate_score`
- `ranking`
- "best", "winner", "best deal"
- purchase recommendation
- expected profit, predicted savings

A price difference may be documented descriptively, but it is not
interpreted as an arbitrage opportunity unless the evidence requirements
in §13 are explicitly satisfied.

---

## 1. Core concepts (formal definitions)

### 1.1 Candidate

A **Candidate** is a routing hypothesis produced by `candidate_discovery.py`
(v0.1, v0.2). It is a *structural intent*: "this routing is worth
investigating". A Candidate has no evidence attached at this point.

```
Candidate = {
  id: str,
  candidate_type: str,  # direct_hub | major_hub | outer_port | ...
  segments: [{from, to, carrier, ...}],
  positioning: {...} | None,
  multi_ticket: bool,
  ...
}
```

### 1.2 ScheduleEvidence

A **ScheduleEvidence** is the structural completeness assessment produced
by `schedule_intelligence.py` (v1.0). It is DATABASE evidence from
OpenFlights — *not* a live schedule assertion.

```
ScheduleEvidence = {
  schedule_status: SUPPORTED | PARTIAL | UNCERTAIN | UNAVAILABLE,
  verification_status: DATABASE | UNKNOWN,
  segments_checked, segments_found, segments_missing,
  connection_checks: [...],
  structural_signals: [alternative_hub, outer_port, ...]
}
```

### 1.3 PriceEvidence

A **PriceEvidence** is the normalized price quote produced by
`price_intelligence.py` (v1.1). It is LIVE evidence when retrieved from
a real producer in the freshness window, otherwise DATABASE or UNKNOWN.

```
PriceEvidence = {
  candidate_id,
  provider, provider_mode,
  verification_status: LIVE | DATABASE | ESTIMATED | UNKNOWN | VERIFIED,
  currency, total_price, base_fare, taxes,
  cabin, baggage,
  ticket_count, is_single_ticket,
  self_transfer, separate_ticket_risk,
  freshness_min, freshness_bucket,
  retrieved_at, expires_at,
  provenance: {source, source_type, retrieved_at, endpoint, offer_id, ...},
  warnings: [...],
  confidence_reasons: [...],
  failure_kind | None,
  failure_reason | None,
}
```

### 1.4 RouteStructureEvidence

A **RouteStructureEvidence** is a structural description of the routing
itself, independent of price. It is derived from the Candidate and from
ScheduleEvidence but does not contain a price.

```
RouteStructureEvidence = {
  candidate_id,
  origin, destination,
  intermediate_stops: [airport_code, ...],
  hub_sequence: [airport_code, ...],          # e.g., [TPE, KUL, DXB, MAD]
  carrier_sequence: [iata_code, ...],
  structural_class: outer_port | alternative_hub | secondary_entry
                    | positioning | multi_ticket | direct | unusual_routing,
  airport_changes: [airport_code, ...],       # airports where from/to mismatch
  segment_count,
  total_elapsed_min | None,                   # unknown if schedule absent
  is_round_trip: bool,
  is_open_jaw: bool,
}
```

### 1.5 BaselineEvidence

A **BaselineEvidence** is the price+structure reference against which a
candidate is compared. It is constructed per §3 and has the same shape
as a Candidate plus attached ScheduleEvidence and PriceEvidence.

### 1.6 FrictionEvidence

A **FrictionEvidence** is a non-price risk/penalty representation. See §9.

### 1.7 ComparisonEvidence

A **ComparisonEvidence** is a parity-validated comparison between a
Candidate (with its attached evidence) and a BaselineEvidence. See §4.

### 1.8 ArbitrageEvidence (proposed, NOT implemented)

A **ArbitrageEvidence** is the output of a future v1.2 layer that
satisfies all parity and freshness requirements (§4, §10, §13). It is
NOT a score, NOT a ranking, NOT a recommendation.

### 1.9 Opportunity

An **Opportunity** is the existence of a ComparisonEvidence that is
`comparable == true` and shows a non-zero price difference. It is
*structural*; it is NOT yet a Verified Opportunity.

### 1.10 VerifiedOpportunity

A **VerifiedOpportunity** is an Opportunity whose underlying
ScheduleEvidence, PriceEvidence, and FXEvidence are all FRESH enough
per §10 and whose parity has been validated per §4. It still does not
constitute a recommendation to book.

### 1.11 Distinction table

| Term | Has price? | Has schedule? | Has baseline? | Comparable? | "Book it" claim? |
|---|---|---|---|---|---|
| Candidate              | ❌ | ❌ | ❌ | ❌ | ❌ |
| ScheduleEvidence       | ❌ | ✅ | ❌ | ❌ | ❌ |
| PriceEvidence          | ✅ | ❌ | ❌ | ❌ | ❌ |
| RouteStructureEvidence | ❌ | partial | ❌ | ❌ | ❌ |
| BaselineEvidence       | ✅ | ✅ | ✅ | ❌ | ❌ |
| ComparisonEvidence     | ✅ | ✅ | ✅ | depends on parity | ❌ |
| ArbitrageEvidence      | ✅ | ✅ | ✅ | parity-passed | ❌ |
| Opportunity            | ✅ | ✅ | ✅ | parity-passed | ❌ |
| VerifiedOpportunity    | ✅+FRESH | ✅+FRESH | ✅+FRESH | parity-passed | ❌ (NEVER) |

---

## 2. ArbitrageEvidence object proposal

The proposed schema (NOT implemented in v1.1.4):

```python
ArbitrageEvidence = {
  schema_version: "v1.2-draft",

  # Identification
  candidate_id: str,
  baseline_id: str,
  opportunity_id: str,         # stable per (candidate, baseline_class, date_window)
  state: "Potential Opportunity" | "Evidence Verified" | "Verified Opportunity"
       | "Not Comparable" | "Insufficient Evidence",

  # Referenced evidence (NOT copied; referenced by id)
  candidate_evidence: {
    candidate: {...},           # the routing
    schedule: ScheduleEvidence,
    price:    PriceEvidence,
    route_structure: RouteStructureEvidence,
    friction: FrictionEvidence,
    ticket_structure: TicketStructureEvidence,
  },

  baseline_evidence: {
    baseline: {...},           # the baseline routing
    schedule: ScheduleEvidence,
    price:    PriceEvidence,
    route_structure: RouteStructureEvidence,
    friction: FrictionEvidence,
    ticket_structure: TicketStructureEvidence,
    baseline_class: "direct" | "conventional_hub" | "secondary_entry" | ...,
  },

  # Comparison validity
  comparison: ComparisonEvidence,    # parity-validated

  # Booking intent metadata (NOT a recommendation)
  user_mission: {
    mission_date_window: [date, date] | None,
    passenger_count: int,
    passenger_types: [adult, ...],
    cabin: "economy" | ...,
  },

  # Currency
  fx: FXEvidence,

  # Date binding
  date_window: {
    candidate_searched_at:  ISO8601,
    baseline_searched_at:   ISO8601,
    candidate_retrieved_at: ISO8601,
    baseline_retrieved_at:  ISO8601,
    candidate_expires_at:   ISO8601,
    baseline_expires_at:    ISO8601,
  },

  # Freshness summary (per-evidence-type, NOT a single number)
  freshness_summary: {
    candidate_price:    FreshnessRecord,
    baseline_price:     FreshnessRecord,
    candidate_schedule: FreshnessRecord,
    baseline_schedule:  FreshnessRecord,
    fx:                 FreshnessRecord,
  },

  # Raw price observation (descriptive only; not an interpretation)
  raw_comparison: {
    candidate_total: {amount: ..., currency: ...},
    baseline_total:  {amount: ..., currency: ...},
    difference:      {amount: ..., currency: ...},  # signed; informational only
  },

  # Hard parity result
  hard_parity_passed: bool,
  parity_failures: [...],

  # Warnings / unknown fields (preserved, not replaced)
  warnings: [...],
  unknown_fields: [...],

  # Verification status (5-tier enum, NOT BOOKABLE)
  verification_status: LIVE | DATABASE | ESTIMATED | UNKNOWN | VERIFIED,

  # Required missing-evidence report (when not VerifiedOpportunity)
  required_for_verification: [
    "real-time schedule confirmation for user's date",
    "second producer cross-check",
    "baseline producer cross-check",
    ...
  ],
}
```

**Hard constraint:** The schema must not contain any field whose name
suggests a score, ranking, recommendation, expected profit, or predicted
savings. Reviewers must reject any future extension that introduces
such fields.

---

## 3. Baseline taxonomy

The baseline is **not** a single universal concept. It is a *taxonomy*
with explicit validity conditions.

### 3.1 Baseline classes

| Class | Definition | When valid |
|---|---|---|
| **canonical_direct**         | Single non-stop routing from origin to destination on the same carrier or alliance. | Always available when a non-stop exists between the two cities; otherwise UNAVAILABLE. |
| **conventional_hub**         | Single-connection routing through the user's primary alliance hub (Star Alliance member if user prefers Star Alliance, etc.). | When the user has declared an alliance preference; otherwise use system default. |
| **secondary_entry**          | Two-connection routing through a European secondary entry (LIS, ZRH, VIE, CPH, WAW, DUB, MUC). | When the user's destination is mainland Europe and a secondary entry exists. |
| **outer_port_positioning**   | Two-ticket construction with positioning flight to an outer port (KUL, BKK, SIN, CGK). | When the candidate itself is multi-ticket or positioning; baseline is the conventional_hub for the same origin/destination. |
| **same_airport_pair**        | Any other routing between the same origin/destination airport pair on the same date window. | When multiple routings exist; this class becomes a SET of candidates rather than a single baseline. |
| **fictional_no_fly**         | A constructed baseline representing "what if this routing did not exist"; used to estimate the marginal value of the candidate. | Only for explanatory / sensitivity analysis; never used as the canonical baseline. |

### 3.2 Baseline validity conditions

A baseline is **valid** for a candidate when ALL of:

1. Same origin airport (or origin metro area, explicitly declared)
2. Same destination airport (or destination metro area, explicitly declared)
3. Same date window (with explicit tolerance for ±1 day if the candidate
   is a multi-leg connection)
4. Same passenger count and passenger types
5. Same cabin class
6. Compatible baggage assumption (default: both include at least 1
   carry-on; checked-bag differences trigger a SOFT comparison, see §4.3)

A baseline is **partially valid** (produces a SOFT comparison) when only
1–5 hold and one of: minor baggage mismatch, same-currency-different-FX,
±1-day date drift.

A baseline is **invalid** for hard comparison when any of:

1. Different origin or destination (UNLESS explicitly declared as metro
   pair, in which case it is partially valid)
2. Different passenger count
3. Different cabin class
4. Different fare-condition profile (refundable vs non-refundable)
5. Multi-ticket vs single-ticket mismatch without risk adjustment
   acknowledgement

### 3.3 Baseline provenance

Every baseline must record:

- baseline_class
- baseline_construction_method (deterministic_lookup |
  user_declared | producer_lookup)
- baseline_construction_timestamp
- baseline_evidence_attached: bool (must be true for hard comparison)
- baseline_freshness: FreshnessRecord (per §10)

A baseline constructed from a fictional_no_fly template must carry
`baseline_class = "fictional_no_fly"` AND `sensitivity_only = true`,
which makes it eligible only for descriptive analysis, never for
VerifiedOpportunity state.

---

## 4. Comparison parity

### 4.1 Hard parity requirements (HARD)

Two prices may ONLY be hard-compared if all of the following match:

| Field | Hard requirement |
|---|---|
| origin             | exact airport code OR declared metro pair |
| destination        | exact airport code OR declared metro pair |
| date_window        | exact match (with ±0 day tolerance) |
| passenger_count    | exact match |
| passenger_types    | exact match (adult/adult = ok; adult+child ≠ adult alone) |
| cabin              | exact match (economy vs economy; business vs business; etc.) |
| currency           | exact match post-FX (see §7 for FX requirements) |
| provider           | not required to match (cross-source is allowed) |
| ticket_count       | soft (see §4.3); HARD only when baseline_class demands parity |
| baggage            | soft (see §4.3) |
| fare_conditions    | soft (see §4.3) |

A hard-parity failure produces `comparable == false`, `parity_failures`
list populated, and the evidence does NOT advance to Opportunity state.

### 4.2 Refuse comparison

Comparison is REFUSED when ANY of:

- Currency unknown / not in static FX table AND no live FX provider
- `verification_status != LIVE` on either side (per v1.1 architecture
  §8.3; UNKNOWN may pass if both sides are explicitly UNKNOWN and
  structurally identical)
- `failure_kind` is in the refuse set: `CURRENCY_UNKNOWN`,
  `MISSING_CREDENTIALS`, `RATE_LIMITED`, `ROUTE_UNAVAILABLE`
- Date-window difference exceeds ±1 day without explicit
  `soft_date_window` declaration
- Either side has `is_single_ticket == None`

### 4.3 Soft comparison / warnings

Comparison may proceed with **warnings** (the comparison is still
emitted, but with `parity_failures` containing the warning tags):

| Field | Soft comparison |
|---|---|
| ticket_count        | Multi-ticket vs single-ticket is acceptable as a SOFT comparison with `separate_ticket_risk` flagged |
| baggage             | Different baggage assumptions may be compared with a `baggage_risk` warning |
| fare_conditions     | Refundable vs non-refundable is acceptable with a `flexibility_risk` warning |
| freshness           | Freshness window exceeded may be compared with `stale_warning` |
| provider            | Different providers is acceptable as long as the rest is hard-parity; emitted as `cross_provider_comparison` |

### 4.4 ComparisonEvidence output

```
ComparisonEvidence = {
  comparable: bool,                       # true iff hard parity passes
  comparable_with_warnings: bool,         # true iff soft parity only
  parity_failures: [...],                 # list of parity-violation tags
  refusal_reasons: [...],                 # hard-refusal reasons
  candidate_amount: {amount, currency},
  baseline_amount:  {amount, currency},
  difference:       {amount, currency, signed: bool},  # descriptive only
  compared_at:      ISO8601,
  freshness_window_minutes: int,
  freshness_window_exceeded: bool,
}
```

---

## 5. Date-window binding

### 5.1 The fields

| Field | Where it lives | Meaning |
|---|---|---|
| `mission_date_window`      | Travel Mission JSON | The user's stated travel date range (origin departure date → return date) |
| `candidate_date_window`    | Candidate or PriceEvidence | The date the candidate was *evaluated* for |
| `searched_date`            | PriceEvidence (per quote) | The actual date the producer API was called |
| `retrieved_at`             | PriceEvidence, ScheduleEvidence | The instant the evidence was received |
| `expires_at`               | PriceEvidence (Duffel offer expiry) | The instant the price quote stops being authoritative |
| `valid_until`              | alias of `expires_at` (Duffel `valid_until` field) | same |

### 5.2 Semantic relationships

- `mission_date_window ⊇ candidate_date_window`: the candidate must
  operate on a date within the user's mission.
- `searched_date ⊇ candidate_date_window`: the producer was queried
  for the candidate's date.
- `retrieved_at ≥ searched_date`: the evidence was retrieved no
  earlier than it was queried.
- `expires_at > retrieved_at`: every valid quote has a finite TTL.
- A `retrieved_at + freshness_ttl_min < now` is considered STALE,
  regardless of what `expires_at` says (v1.1 architecture §5).

### 5.3 Why the mock is wrong

The current MockDuffelProvider emits hard-coded
`departing_at: "2027-04-15T08:00:00"`, which is structurally a
fabrication. v1.1.4 documents this as a **limitation that must be
resolved** before any v1.2 layer can rely on mock evidence for
comparison.

The fix (NOT in v1.1.4): the mock should accept a `date_window`
parameter and emit timestamps derived from it. The task is recorded
as an open question (§15).

---

## 6. Passenger parity

### 6.1 Fields

| Field | Type | Meaning |
|---|---|---|
| `passenger_count`  | int                  | total number of passengers |
| `adult_count`      | int                  | ≥ 12 years |
| `child_count`      | int                  | 2–11 years |
| `infant_count`     | int                  | < 2 years (lap) |
| `passenger_types`  | [str]                | explicit per-passenger type list |

### 6.2 Parity rules

| Comparison | Hard or soft? |
|---|---|
| 1 adult vs 1 adult                                | HARD parity (same) |
| 2 adults vs 2 adults                              | HARD parity (same) |
| 2 adults vs 1 adult                               | HARD REFUSE (linear scaling not assumed) |
| 1 adult + 1 child vs 1 adult                      | HARD REFUSE |
| 1 adult vs 1 adult (different cabin)              | HARD REFUSE |
| 1 adult vs 1 adult (same cabin, different meal)   | SOFT warning (meal parity is soft) |

### 6.3 Anti-pattern: linear scaling

A 1-passenger price **must NOT** be multiplied by N to estimate an
N-passenger price. Airline pricing is not linear — it depends on
fare-class availability, group discounts, fare-class mixing, and
currency rounding.

If a future layer needs an N-passenger estimate, it must:

1. Run a separate query with `passenger_count=N`, OR
2. Emit a warning that the comparison is indicative-only.

---

## 7. FX evidence

### 7.1 Fields

| Field | Type | Meaning |
|---|---|---|
| `price_currency`        | str   | currency in which the price was quoted (e.g., USD, EUR) |
| `comparison_currency`   | str   | currency used for the comparison (typically the user's display currency) |
| `fx_rate`               | float | rate applied (units of `comparison_currency` per 1 unit of `price_currency`) |
| `fx_source`             | str   | `static_snapshot_table_v1_1` (current default) or a live source |
| `fx_retrieved_at`       | ISO8601 | when the FX rate was last refreshed |
| `fx_freshness_min`      | int   | age of the FX rate |
| `fx_freshness_bucket`   | str   | FRESH/RECENT/STALE/EXPIRED/UNKNOWN |
| `fx_markup`             | float | markup awareness (e.g., 2% on the static table) |
| `fx_verification_status`| str   | one of the 5-tier enum |

### 7.2 Validity rules

| Condition | FX status |
|---|---|
| `price_currency == comparison_currency`           | VALID (identity, no FX needed) |
| Static FX table, freshness ≤ 24h                   | WARNING (markup applies; static, not live) |
| Static FX table, freshness > 24h                   | REFUSE COMPARISON |
| Live FX provider, freshness ≤ 4h                   | VALID |
| Live FX provider, freshness 4–24h                  | WARNING |
| Live FX provider, freshness > 24h                  | REFUSE COMPARISON |
| `price_currency` not in static FX table, no live FX | REFUSE COMPARISON |

### 7.3 Hard rule

> Static FX snapshots MUST be explicitly distinguished from live FX
> evidence. A comparison that crosses a static-FX boundary is
> `comparable == false` UNLESS the user has explicitly accepted
> static FX for the comparison.

This rule exists because the current v1.1 implementation uses a
**static table** (see `price_intelligence.py:67-103`). Any v1.2 layer
that compares USD-priced vs EUR-priced evidence using the static table
must surface the warning explicitly.

---

## 8. Ticket structure parity

### 8.1 Classification

```
TicketStructureEvidence = {
  is_single_ticket: bool | None,
  ticket_count: int | None,
  same_pnr: bool | None,                 # single-PNR vs separate-PNR
  has_positioning: bool | None,         # one leg is a positioning flight
  has_airport_change: bool | None,      # arrival ≠ next departure airport
  has_self_transfer: bool | None,       # connection is self-managed
  separate_ticket_risk: "none" | "elevated" | "high" | None,
  ticket_groups: [
    {group_id, stops: [...], subtotal: {...}}
  ],
}
```

### 8.2 Parity

A candidate with `ticket_count = 2` (multi-ticket) may NOT be hard-
compared with a baseline of `ticket_count = 1` (single-ticket) without
explicit risk acknowledgement.

A candidate with `has_positioning = true` and a baseline with
`has_positioning = false` is a **soft comparison** with a
`positioning_risk` warning — the user is exposed to:
- Separate-ticket rebooking risk
- Missed-connection risk
- Baggage recheck risk
- Visa-transit risk (when the positioning airport requires transit visa)

These risks must be surfaced **structurally** (not as a numeric score).

---

## 9. Friction evidence

### 9.1 Non-price evidence fields

FrictionEvidence is structured (not scored):

```
FrictionEvidence = {
  baggage: {
    included_pieces: int | None,
    recheck_required: bool | None,
    evidence_complete: bool,
  },
  transfer: {
    type: "self" | "managed" | "none",
    airport_change: bool | None,
    overnight_connection: bool | None,
    min_connection_min: int | None,
    typical_connection_min: int | None,
    evidence_complete: bool,
  },
  schedule_uncertainty: {
    is_uncertain: bool,
    schedule_status: "SUPPORTED" | "PARTIAL" | "UNCERTAIN" | "UNAVAILABLE",
    verification_status: "DATABASE" | "UNKNOWN",
  },
  cancellation_refund: {
    refundable: bool | None,
    changeable: bool | None,
    change_fee: {amount, currency} | None,
    refund_fee: {amount, currency} | None,
    evidence_complete: bool,
  },
  positioning_risk: {
    has_positioning: bool | None,
    separate_pnr: bool | None,
    evidence_complete: bool,
  },
  visa_transit_risk: {
    requires_transit_visa: bool | None,
    evidence_complete: bool,
  },
  warnings: [...],
  unknown_fields: [...],
}
```

### 9.2 What it is NOT

FrictionEvidence is NOT a numeric score. Each field is a boolean,
enum, or count. The future layer (v1.2+) may consume these fields
and decide whether to surface a warning, but this milestone does NOT
define that decision logic.

### 9.3 Required unknown_fields

Every field marked `evidence_complete = false` MUST appear in
`unknown_fields[]` so downstream can detect incomplete evidence.

---

## 10. Evidence freshness

### 10.1 Per-evidence-type freshness

Each evidence type carries its own freshness, NOT a single global one:

```
PriceEvidence.freshness_min      ← computed from retrieved_at
ScheduleEvidence.retrieved_at    ← when OpenFlights was last read
FXEvidence.fx_freshness_min      ← when FX was last refreshed
```

### 10.2 Buckets

The v1.1 freshness buckets (per `FreshnessBucket`):

- `FRESHNESS_RECENT` (≤ 30 min) — typically applicable to LIVE evidence
- `FRESHNESS_WARM` (≤ 4 h)     — typically the upper bound for LIVE
- `FRESHNESS_COLD` (≤ 24 h)    — requires a `stale_warning`
- `FRESHNESS_EXPIRED` (> 24 h) — refuses hard comparison
- `FRESHNESS_UNKNOWN`          — comparison refused by default

The verifier in v1.1 (`freshness_bucket_from_min`) uses 30 / 240 / 1440
minutes; v1.1.4 does not change those defaults but documents that
each evidence type may use a different bucket boundary.

### 10.3 The freshness record

```
FreshnessRecord = {
  retrieved_at: ISO8601,
  freshness_min: int,
  freshness_bucket: "FRESHNESS_RECENT" | "FRESHNESS_WARM"
                  | "FRESHNESS_COLD" | "FRESHNESS_EXPIRED"
                  | "FRESHNESS_UNKNOWN",
  expires_at: ISO8601 | None,      # if applicable
  source: str,                     # e.g., "duffel", "openflights", "static_fx_table"
  verification_status: 5-tier enum,
}
```

### 10.4 Freshness rule for comparisons

Hard comparison requires both sides' PriceEvidence to be ≤
`FRESHNESS_WARM` (4 hours). One side COLD or worse → soft comparison
with `stale_warning`. Both sides EXPIRED → refuse comparison.

Cross-evidence-type freshnesses are independent. A FRESH price on a
STALE schedule is acceptable ONLY with a `schedule_uncertainty`
warning preserved.

### 10.5 Never introduce BOOKABLE

`BOOKABLE` is forbidden in any field, including freshness. Freshness
describes the age of evidence, not the user's ability to act on it.

---

## 11. Opportunity state machine

### 11.1 States

```
NOT_COMPARABLE             — hard parity failure or refusal
INSUFFICIENT_EVIDENCE      — soft parity; required_for_verification populated
POTENTIAL_OPPORTUNITY      — hard parity passes; raw_comparison emitted
EVIDENCE_VERIFIED          — POTENTIAL_OPPORTUNITY + freshness FRESH
VERIFIED_OPPORTUNITY       — EVIDENCE_VERIFIED + all required_for_verification cleared
```

### 11.2 Transitions

```
Candidate
  ↓ attach ScheduleEvidence, PriceEvidence, FXEvidence, FrictionEvidence
ComparableEvidence
  ↓ (parity check)
  ├─→ NOT_COMPARABLE                  (hard failure)
  └─→ INSUFFICIENT_EVIDENCE / POTENTIAL_OPPORTUNITY
        ↓ (freshness check)
        ├─→ INSUFFICIENT_EVIDENCE    (stale or expired)
        └─→ EVIDENCE_VERIFIED         (all fresh)
              ↓ (required_for_verification cleared)
              └─→ VERIFIED_OPPORTUNITY
```

### 11.3 Required for verification

`required_for_verification` is a list of strings; each element names a
gap that, if cleared, transitions EVIDENCE_VERIFIED → VERIFIED_OPPORTUNITY.

Examples:

- `"real-time schedule confirmation for user's date"`
- `"second producer cross-check"`
- `"baseline producer cross-check"`
- `"operating-carrier rule fetches (refundable, changeable)"`
- `"seats-remaining confirmation"`
- `"multi-passenger parity"`
- `"live FX refresh"`

### 11.4 Terminal state

`VERIFIED_OPPORTUNITY` is the highest state. It is NOT "book it".
The state machine does NOT transition to a booking state.

---

## 12. Hard semantic boundaries

### 12.1 Existing boundaries (preserved)

- `VERIFIED != BOOKABLE`
- `PRICE FOUND != GOOD PRICE`
- `CHEAPER != ARBITRAGE`
- `ROUTE EXISTS != FLIGHT OPERATES ON DATE`
- `FLIGHT OPERATES != TICKET AVAILABLE`
- `MULTI-TICKET PRICE != USER-EXECUTABLE ITINERARY`
- `SCHEDULE SUPPORTED != OPERABLE`

### 12.2 New boundaries (added in v1.1.4)

- `PRICE DIFFERENCE != ARBITRAGE EVIDENCE`
- `CANDIDATE != OPPORTUNITY`
- `OPPORTUNITY != VERIFIED OPPORTUNITY`

### 12.3 What this means

Even a 50% price difference does NOT constitute ArbitrageEvidence.
A candidate that happens to be cheaper on Duffel today does NOT
become a "verified opportunity" until all required evidence types
are FRESH, all hard parity passes, and `required_for_verification` is
empty.

---

## 13. Required evidence graph

```
TravelMission
  ↓
Candidate
  ↓ (attach per-evidence-type)
CandidateEvidence
  ├── ScheduleEvidence     (v1.0)
  ├── PriceEvidence        (v1.1)
  ├── RouteStructureEvidence
  ├── FXEvidence
  ├── PassengerParity
  ├── DateWindowBinding
  ├── TicketStructure
  └── FrictionEvidence
  ↓
BaselineConstruction
  ↓ (per §3)
BaselineEvidence
  ↓
ParityValidation
  ↓ (per §4)
ComparisonEvidence
  ↓
Potential ArbitrageEvidence
  ↓ (per §10 freshness)
EvidenceVerified
  ↓ (per §11 required_for_verification cleared)
VerifiedOpportunity
```

Each arrow is a precondition. Missing any precondition halts the graph.

---

## 14. Multi-provider architecture

### 14.1 Producer types

Future producers may include:

- Duffel (current)
- Kiwi Tequila (free, virtual interlining)
- Amadeus Self-Service APIs (commercial)
- airline-direct NDC APIs (per-airline integration cost)
- Skyscanner / Kayak (commercial friction, ToS)
- GDS providers (Sabre, Travelport)

### 14.2 Architectural rule

The Arbitrage layer MUST consume **normalized evidence**, not
provider-specific objects. Each provider adapter:

1. Produces a `PriceEvidence` matching the v1.1 contract (or its
   explicitly-approved extension)
2. Populates `provider` (e.g., `"kiwi"`, `"amadeus"`) and
   `provider_mode` (always `"live"` for real, `"mock"` for synthetic)
3. Populates `provenance.source` with the same identifier
4. Respects the 5-tier `verification_status` enum
5. Does NOT leak provider-specific fields into the normalized
   contract

### 14.3 What the Arbitrage layer sees

The Arbitrage layer sees only:

- Candidate metadata (id, segments, positioning, multi_ticket)
- ScheduleEvidence (uniform shape)
- PriceEvidence (uniform shape)
- RouteStructureEvidence (uniform shape)
- FrictionEvidence (uniform shape)
- ComparisonEvidence (uniform shape)

It does NOT see:

- Raw `passengers[]` arrays from Duffel
- Duffel's `offer.id`
- Any provider-specific `quality_score` or `reliability_index`

A provider that wants to surface provider-specific signal must do so
through the explicit extension fields in §4.2 of the v1.1.3 audit
(after architecture approval), not as a top-level normalized field.

---

## 15. Examples

### 15.1 Valid hard comparison

Candidate: TPE→KUL (D7 economy), KUL→MAD (MH economy)
Baseline:   TPE→DXB (EK economy), DXB→MAD (EK economy)
Both PriceEvidence: LIVE, FRESHNESS_RECENT, USD
Both ScheduleEvidence: SUPPORTED
Both date_window: 2027-04-15 → 2027-04-25
Both passenger_count: 1 adult
Both cabin: economy

→ Hard parity PASS. ComparisonEvidence.comparable = true.
→ State advances to POTENTIAL_OPPORTUNITY.
→ Raw_comparison emitted descriptively.

### 15.2 Invalid hard comparison (refused)

Candidate: TPE→KUL (D7 economy), KUL→MAD (MH economy) — price in USD
Baseline:   TPE→DXB (EK economy), DXB→MAD (EK economy) — price in EUR
FX: static snapshot, 2 hours old
Candidate: passenger_count = 1 adult
Baseline: passenger_count = 2 adults

→ Hard parity FAIL (different passenger_count).
→ Hard parity FAIL (FX static snapshot not allowed for hard comparison).
→ ComparisonEvidence.comparable = false.
→ State is NOT_COMPARABLE.
→ State machine does NOT advance.

### 15.3 Soft comparison (warning only)

Candidate: TPE→KUL (D7 economy, baggage unknown) — LIVE, FRESH
Baseline:   TPE→DXB (EK economy, baggage 1 piece included) — LIVE, FRESH
Same passenger count, same cabin, same date, same currency.

→ Hard parity PASS (all hard fields match).
→ Soft warning: baggage evidence incomplete on candidate side.
→ ComparisonEvidence.comparable_with_warnings = true.
→ State advances to POTENTIAL_OPPORTUNITY with `baggage_risk` warning.
→ State machine may advance once `required_for_verification` clears
  (e.g., after candidate baggage is verified).

### 15.4 Refused comparison (no FX)

Candidate: TPE→KUL→MAD — price in BDT (Bangladeshi Taka)
Baseline:   TPE→BKK→MAD — price in JPY
FX: static table does not include BDT or JPY; no live FX.

→ Hard refusal: currency unknown.
→ ComparisonEvidence.comparable = false.
→ State is NOT_COMPARABLE.
→ State machine does NOT advance.
→ required_for_verification includes `"live FX provider"`.

### 15.5 Insufficient evidence (stale schedule)

Candidate: TPE→KUL→MAD with OpenFlights-only ScheduleEvidence,
           DATABASE verification_status, freshness 5 days
Baseline:   TPE→DXB→MAD with OpenFlights-only ScheduleEvidence,
           DATABASE verification_status, freshness 5 days
Both prices: LIVE, FRESHNESS_RECENT

→ Hard parity PASS.
→ Freshness FAIL on schedule (FRESHNESS_EXPIRED).
→ State is INSUFFICIENT_EVIDENCE.
→ required_for_verification includes
  `"real-time schedule confirmation for user's date"`.

---

## 16. Open questions for v1.2

These are NOT resolved by v1.1.4. They are recorded so a future
milestone does not silently skip them.

1. **Baseline canonicalization** — when the user has no declared
   alliance preference, what is the default conventional_hub for
   TPE→Europe? (Star Alliance default? Cheapest published? Most
   direct?) — must be answered before v1.2 emits Opportunity state.
2. **Multi-passenger parity** — when the user is 2 adults but the
   baseline only has 1-adult prices, do we refuse, or run a separate
   2-adult query? The latter costs more API budget.
3. **Open-jaw representation** — TPE→MAD, return BCN→TPE is an
   open-jaw; the current Candidate model assumes same-origin /
   same-destination return. How should the baseline handle open-jaw?
4. **Static FX acceptance** — under what conditions (if any) does
   the user accept static FX for hard comparison? User config?
   Per-baseline opt-in? Or always refuse?
5. **Real-time schedule source** — what producer provides
   real-time schedule confirmation? OpenFlights is DATABASE only.
   AviationStack? Duffel schedules? airline-direct? None currently
   implemented.
6. **Mock timestamp correction** — MockDuffelProvider hard-codes
   timestamps. Should the mock accept `date_window` and emit
   derived timestamps? This is a v1.1.x code change, NOT v1.2.
7. **Provider cross-check policy** — when only Duffel is wired,
   `required_for_verification` includes "second producer". When
   should this be relaxed (e.g., if the user's baseline is the
   airline direct)?
8. **Booking downstream** — v1.4 is booking. The current spec stops
   at VerifiedOpportunity. The handoff to booking is NOT defined
   here.
9. **Cancellation/refund parity** — Duffel returns null for these
   in v1.1. Should v1.2 require an order-level rule fetch
   (`air/order_change_requests`)? At what cost?
10. **Visa transit risk** — not modeled in v1.1. Required for
    some routings (e.g., TPE→AUH→LHR with a Taiwan passport
    may require transit visa). Future layer must decide how to
    source this.

---

## 17. Files added / modified

**Added:**

- `docs/arbitrage_evidence_spec_v1_1_4.md` (this document)

**Modified:**

- None. No production code was touched. No new API calls were made.
  No new tests were added. (Per spec §17.)

---

## STOP CONDITION

This is a **specification only** milestone. No code was written; no
detection logic was implemented. The current evidence architecture
(Duffel + OpenFlights + PriceEvidence + ScheduleEvidence) is
sufficient only to emit `POTENTIAL_OPPORTUNITY` state at best. A
genuine `VERIFIED_OPPORTUNITY` state requires:

1. A second producer for cross-source comparison, OR a baseline
   computation that doesn't rely solely on Duffel
2. Real-time schedule confirmation for the user's specific travel
   dates (OpenFlights is DATABASE only)
3. Operating-carrier rule fetches (refundable, changeable, fees)
4. Real FX (not the current static table)
5. Multi-passenger parity tests
6. Baseline canonicalization policy

Do **NOT** begin v1.2 Arbitrage Detection.

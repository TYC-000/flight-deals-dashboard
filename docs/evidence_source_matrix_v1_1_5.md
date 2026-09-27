# Evidence Source Matrix — v1.1.5 (Real Evidence Acquisition Plan)

> Status: **RESEARCH + ARCHITECTURE ONLY.** No production code modified.
> No new API calls. No credentials requested. No JSON production data
> emitted. This document is the concrete acquisition plan for the six
> evidence gaps established by v1.1.4.
>
> v1.1.4 established that the system reaches `POTENTIAL_OPPORTUNITY`
> at best. To reach `VERIFIED_OPPORTUNITY` the system needs additional
> evidence sources. This document enumerates candidate sources, their
> capabilities, the architectural cost, and a recommended sequencing.
> It does NOT implement anything.
>
> "Recommended" in this document means **technical sequencing** — what
> dependency must be satisfied before what, NOT a ranking of providers
> or a political/consumer choice.

---

## 0. Forbidden content (per spec §16)

This document does NOT contain:

- arbitrage_score, opportunity_score, candidate_score, ranking
- "best", "winner", "best deal"
- purchase recommendation
- expected profit, predicted savings
- any production code change

---

## 1. Evidence-source inventory

Six evidence gaps from v1.1.4 §16 are addressed below. Each gap is
mapped to candidate sources with documented capabilities.

### 1.1 Gap A — Second price producer

| Candidate | Evidence type | Public API | Commercial friction | Notes |
|---|---|---|---|---|
| **Duffel**            | PriceEvidence (LIVE)              | ✅ | 🟡 (per-order cost)  | Already wired; sole producer in v1.1. |
| **Kiwi Tequila**      | PriceEvidence (LIVE, virtual interlining) | ✅ | 🟡 (deeplink mandate for booking) | Strong on outer-port + Asia LCCs. Per `docs/price_provider_matrix.md` §2: "Strong on outer-port routings". |
| **Amadeus Self-Service** | PriceEvidence (LIVE)         | ✅ | ❌ (commercial contract required) | Enterprise-grade; integration cost high. |
| **Sabre Dev Studio**  | PriceEvidence (LIVE)              | ✅ | ❌ (commercial contract required) | Same as Amadeus. |
| **Skyscanner Partner**| PriceEvidence (LIVE)              | ✅ | ❌ (5–20% deeplink conversion mandate) | Disqualified for "indie consumer" use case per matrix §3. |
| **Airline-direct NDC** | PriceEvidence (LIVE per-carrier)  | ❌ (most carriers anti-scraping) | varies | Disqualified for batch use; carrier-specific ToS. |
| **Google Flights QPX** | PriceEvidence (LIVE)            | ❌ (closed) | ❌ | Disqualified. |

**First-pick candidate for second producer: Kiwi Tequila.** Reasons:
public REST API, stronger outer-port coverage than Duffel (relevant for
our outer_port candidates), and pay-per-search pricing model that
matches our memoization pattern. Skyscanner and airline-direct are
disqualified by commercial friction or ToS.

### 1.2 Gap B — Real-time schedule confirmation

| Candidate | Evidence type | Public API | Notes |
|---|---|---|---|
| **OpenFlights** (current v1.0) | ScheduleEvidence (DATABASE) | ✅ | 6,072 airports, 37,595 routes; stale; no date-specific schedules. |
| **FlightAware AeroAPI**       | ScheduleEvidence (LIVE per-flight) | ✅ | Per-flight history; live by date. |
| **Duffel `air/schedules`**    | ScheduleEvidence (LIVE)           | ✅ | Already accessible via Duffel token; carriers, equipment, frequency. |
| **Amadeus Schedule API**      | ScheduleEvidence (LIVE)           | ✅ | Direct; enterprise. |
| **AviationStack**             | ScheduleEvidence (LIVE)           | ✅ | Per-flight history + schedule. |
| **Cirium / OAG**              | ScheduleEvidence (LIVE)           | 🟡 | Commercial. |
| **ICAO / IATA official**      | ScheduleEvidence (LIVE)           | 🟡 | Per-airline SSIM feeds; integration cost high. |

**First-pick candidate: Duffel `air/schedules`** (already covered by
existing Duffel token). This avoids adding a second credential and
keeps the schedule evidence co-sourced with the price evidence for the
candidate route.

**Second-pick candidate: FlightAware AeroAPI** — for cross-source schedule
sanity check (Gap B is paired with Gap A; same architecture applies).

### 1.3 Gap C — Operating-carrier / fare-rule evidence

| Source | What's available | When |
|---|---|---|
| **Duffel `air/offer_requests`** | `operating_carrier`, `marketing_carrier`, `flight_number`, `equipment` (sometimes) | At search time ✅ |
| **Duffel `air/order_change_requests`** | `refundable`, `changeable`, change_fee, refund_fee, fare_basis_code | At **order time** (after booking) only |
| **Duffel `air/orders/{id}`** | Confirmed booking details | After booking |
| **Kiwi Tequila `booking_check`** | Fare rules at booking | At booking time |
| **Airline-direct** | Authoritative fare rules | Pre-search via NDC |

**Key finding:** carrier / equipment / flight number is available at
search time on Duffel. Fare rules (refundable / changeable / fees) are
**NOT** available at search time on any current commercial provider;
they require an order-level lookup. This is documented as a **permanent
limitation** of the current architecture, not a fixable gap.

### 1.4 Gap D — Real FX

| Source | Evidence type | Public API | Notes |
|---|---|---|---|
| **Open Exchange Rates** | FXEvidence (LIVE)     | ✅ | Free tier (1000 req/mo), then paid. |
| **Frankfurter (ECB)**  | FXEvidence (LIVE)     | ✅ | Free, ECB reference rates. No auth required for basic use. |
| **exchangerate.host**  | FXEvidence (LIVE)     | ✅ | Free tier available. |
| **Duffel native FX**   | FXEvidence (LIVE, 2% markup) | ✅ | Already wired; charged markup. |
| **Central-bank feeds** (BIS, ECB, Fed) | FXEvidence (LIVE, authoritative) | 🟡 | Per-bank integration. |
| **Static table** (current v1.1) | FXEvidence (DATABASE) | N/A | Already wired; refused for hard comparison per v1.1.4 §7. |

**First-pick candidate: Frankfurter (ECB).** Reasons: free, no
credential for basic use, ECB is a primary central-bank source. Will
need a Frankfurter-specific credential only if rate exceeds free tier.

### 1.5 Gap E — Multi-passenger parity

This is NOT a separate evidence source. It's an evidence-retrieval
policy: **a separate price query is required for each passenger
configuration**. Linear scaling is forbidden per v1.1.4 §6.

| Configuration | Producer query |
|---|---|
| 1 adult   | one `quote()` call with `passengers=[{type:"adult"}]` |
| 2 adults  | one `quote()` call with `passengers=[{type:"adult"},{type:"adult"}]` |
| family     | one `quote()` call with mixed passenger list |

**Cost multiplier**: an N-passenger comparison requires N quote calls
per producer (NOT N×M across M producers; each producer queries once
for the multi-passenger combination).

### 1.6 Gap F — Baseline canonicalization

This is NOT a separate evidence source. It's a baseline-construction
policy. Documented in detail in §8 below. Baseline is constructed
per-candidate from the same evidence types already gathered.

---

## 2. Capability matrix

Per spec §2, the table below describes documented capabilities and
limitations. No subjective scores. No rankings.

### 2.1 Price providers

| Provider   | Capability: split-ticket | Capability: cabin | Capability: baggage | Capability: live | Cost per result | Freshness | ToS-risk |
|---|---|---|---|---|---|---|---|
| **Duffel** | ✅ native (`type: "split_ticket"`) | ✅ 4 classes | ✅ per-segment | ✅ LIVE (~20 min TTL) | $3/order + $0.005/excess search | LIVE | low |
| **Kiwi**   | ✅ Virtual Interlining           | ✅ 4 classes | 🟡 partial      | ✅ LIVE (~15 min TTL) | cheaper than Duffel per matrix | LIVE | medium (deeplink mandate for booking) |
| **Amadeus**| 🟡 partial                      | ✅ 4 classes | 🟡 partial      | ✅ LIVE              | enterprise contract             | LIVE | commercial friction |
| **Sabre**  | 🟡 partial                      | ✅ 4 classes | 🟡 partial      | ✅ LIVE              | enterprise contract             | LIVE | commercial friction |

For this milestone we restrict the comparison to Duffel and Kiwi,
because both have public API access documented in the existing matrix.
Amadeus and Sabre are recorded as future candidates but are not
recommended for v1.2 sequencing due to integration cost.

### 2.2 Schedule sources

| Source                 | Live by date | Per-flight history | Equipment | Public API |
|---|---|---|---|---|
| OpenFlights            | ❌ (DB only) | ❌                 | ❌        | ✅ (DB dump) |
| Duffel `air/schedules` | ✅            | ✅ (limited)        | ✅        | ✅ |
| FlightAware AeroAPI    | ✅            | ✅                  | ✅        | ✅ |
| AviationStack          | ✅            | ✅                  | 🟡        | ✅ |

### 2.3 FX providers

| Source               | Live | Free tier | Authoritative | Cost |
|---|---|---|---|---|
| Open Exchange Rates  | ✅   | 1000/mo   | aggregator    | paid above free |
| Frankfurter (ECB)    | ✅   | yes       | ECB primary   | free |
| Duffel native FX     | ✅   | yes (with Duffel account) | aggregated | 2% markup |
| Static table (v1.1)  | ❌   | yes       | none          | free |

### 2.4 Cross-provider cost

| Stack component              | Per-run cost estimate |
|---|---|
| 1× Duffel price (10 candidates, mocked) | $0 (no API calls in current state) |
| 1× Duffel price (10 candidates, real)   | $0.05 (10 × $0.005 excess search) |
| 1× Kiwi price (10 candidates)            | per Kiwi plan; < $0.10 estimated |
| 1× Duffel schedule (10 candidates)      | $0 (schedule lookups are free in current Duffel plans per matrix) |
| 1× Frankfurter FX (1 refresh/run)       | $0 |
| **Total per run (1 mission, 10 candidates, 2 producers)** | **< $0.20** |

This is an estimate. v1.2 will validate against real invoices.

---

## 3. Cross-provider price comparison

### 3.1 Architecture

```
Provider A (Duffel)
   ↓ quote() → PriceEvidence (LIVE)
                │
                ▼
       PriceEvidence buffer (id-keyed, by candidate_id)
                ▲
                │
Provider B (Kiwi)
   ↓ quote() → PriceEvidence (LIVE)
                │
                ▼
       ComparisonEvidence builder
                │
                ▼
       Parity validation (per v1.1.4 §4)
                │
                ▼
       ComparisonEvidence (comparable=true / false / soft)
```

### 3.2 No-leak guarantee

The ComparisonEvidence builder consumes only:

- `price_evidence` payloads matching the v1.1 contract
- `route_structure` derived from `segments[]`
- `provenance.source` for provider identity

It MUST NOT consume:

- Duffel `passengers[]` raw array
- Kiwi's internal quality_score (if any)
- Duffel `owner.name`
- Any provider-specific pricing breakdown

### 3.3 Provider identity preservation

Each PriceEvidence carries `provider` (e.g., "duffel", "kiwi") and
`provider_mode` (always "live" for real). The ComparisonEvidence records
which providers participated:

```
ComparisonEvidence {
  ...
  providers_involved: ["duffel", "kiwi"],
  cross_provider: bool,    # true iff more than one producer
}
```

---

## 4. Schedule verification upgrade path

### 4.1 Current state (v1.0)

ScheduleEvidence has `verification_status = DATABASE` for all OpenFlights
matches. Per v1.1.4 §1.2, this is acceptable for `POTENTIAL_OPPORTUNITY`
but insufficient for `VERIFIED_OPPORTUNITY`.

### 4.2 Upgrade path

To upgrade a candidate's `schedule_status` from DATABASE → LIVE (still
NOT VERIFIED, NOT BOOKABLE), the following is needed:

| Field | Required source for LIVE |
|---|---|
| flight existence       | Duffel `air/schedules` or FlightAware |
| operating carrier      | Duffel `air/schedules` |
| flight number          | Duffel `air/schedules` |
| departure time         | Duffel `air/schedules` |
| arrival time           | Duffel `air/schedules` |
| operating date         | Duffel `air/schedules` (per-date) |
| connection feasibility | heuristic only (see v1.1.3 §2 connection_information row) |

### 4.3 Verification enum (unchanged)

- UNKNOWN, ESTIMATED, DATABASE, LIVE, VERIFIED (5-tier; **NO BOOKABLE**)

The upgrade is `DATABASE → LIVE`. Reaching `VERIFIED` requires the
producer itself to assert the schedule as authoritative for the user's
specific travel date, which Duffel's `air/schedules` does (within its
own coverage window).

### 4.4 Connection feasibility (still heuristic-only)

`connection_time_min`, `overnight_connection`, `tight_connection`,
`airport_change` are still derived heuristically from segment
depart/arrive timestamps, NOT from a dedicated connection analysis
service. This is documented as a known gap; not addressed by any
candidate schedule source.

---

## 5. Operating-carrier evidence

### 5.1 At-search-time (available now)

From Duffel `air/offer_requests` response (already in v1.1):

- `marketing_carrier.iata_code` (e.g., "MH")
- `operating_carrier.iata_code` (e.g., "MH")
- `marketing_carrier_flight_number` (e.g., "MH-100")
- Equipment type: **partially** — Duffel returns it in `segments[].aircraft`
  when the carrier discloses it; not always present.

### 5.2 At-order-time (NOT available without booking)

Fare rules are NOT available at search time on Duffel, Kiwi, Amadeus,
or Sabre. They require:

- Duffel `air/order_change_requests` (after booking)
- Kiwi fare-rule lookup at booking
- Amadeus `FareRulesFromPricing` (after pricing request, pre-booking)

### 5.3 Implication

`refundable`, `changeable`, `change_fee`, `refund_fee` will remain `null`
in PriceEvidence under the current architecture. v1.1.4 §15 already
documents this; v1.2 will not change it. The `cancellation_refund`
block in FrictionEvidence will carry `evidence_complete = false` for
these fields.

---

## 6. FX architecture

### 6.1 Provider-agnostic FX evidence contract

```
FXEvidence = {
  price_currency:        str,         # e.g., "USD"
  comparison_currency:   str,         # e.g., "TWD"
  fx_rate:               float | None,
  fx_source:             str,         # "frankfurter_ecb" | "open_exchange_rates"
                                     # | "duffel_native" | "static_snapshot_table_v1_1"
  fx_retrieved_at:       ISO8601,
  fx_expires_at:         ISO8601 | None,
  fx_freshness_min:      int,
  fx_freshness_bucket:   str,         # FRESHNESS_RECENT|WARM|COLD|EXPIRED|UNKNOWN
  fx_markup:             float,       # 0.02 = 2%; documented awareness
  fx_verification_status: 5-tier enum,
  rate_limiting_notes:   str | None,  # for provenance
}
```

### 6.2 Validity conditions

| Condition                                                | FX status         | Hard comparison |
|---|---|---|
| `price_currency == comparison_currency`                  | identity          | VALID |
| Live FX (Frankfurter), `fx_freshness_min ≤ 240` (4h)      | LIVE              | VALID |
| Live FX, `fx_freshness_min ≤ 1440` (24h)                 | LIVE              | WARNING (stale_warning) |
| Live FX, `fx_freshness_min > 1440`                       | EXPIRED           | REFUSE |
| Duffel native FX, `fx_freshness_min ≤ 240`               | LIVE w/ markup    | WARNING (markup_awareness) |
| Static snapshot table (current v1.1)                     | DATABASE          | REFUSE unless user explicitly accepts |
| `price_currency` not in any provider table, no live FX    | UNKNOWN           | REFUSE |

### 6.3 Static-FX-hard-refusal rule

Per v1.1.4 §7.3, the static snapshot table remains in v1.1 as a
fallback for indicative comparisons only. It MUST NOT be used for
hard comparison when the user has not explicitly opted in. This is
preserved unchanged.

### 6.4 Static vs live distinction (architectural rule)

`fx_source` MUST distinguish static from live. The ComparisonEvidence
builder MUST refuse to hard-compare evidence where one side is static
and the other is live, OR where both are static — UNLESS the user
opted in via a per-run flag (not yet implemented; tracked as open
question).

---

## 7. Multi-passenger parity

### 7.1 Evidence-required policy

Per v1.1.4 §6:

- 1 adult vs 1 adult: HARD parity
- 2 adults vs 2 adults: HARD parity
- 2 adults vs 1 adult: HARD REFUSE (linear scaling forbidden)
- Mixed passenger types: HARD REFUSE

### 7.2 Acquisition cost

Each producer MUST be queried separately for each passenger configuration:

| Config | Duffel call | Kiwi call | Total |
|---|---|---|---|
| 1 adult     | 1 | 1 | 2 |
| 2 adults    | 1 | 1 | 2 |
| 1 adult + 1 child | 1 | 1 | 2 |
| Family of 4 | 1 | 1 | 2 |

**NOT** `4 × 2 = 8` calls for a family of 4. Each producer queries once
for the multi-passenger combination. v1.2 must not naively iterate.

### 7.3 Cost-multiplier cap

Per v1.1.4 §6.3, the system must NOT scale 1-passenger prices by N
to estimate N-passenger prices. This means a `passenger_count = 4`
comparison requires 2 calls × 2 producers = 4 quote calls (for the
family baseline), not 8.

### 7.4 Anti-pattern (must NOT implement)

```
# WRONG
adult_price = quote(passengers=1)
family_price = adult_price * 4
# ... compare family_price to baseline ...
```

The correct pattern is:

```
adult_price = quote(passengers=[adult])
family_price = quote(passengers=[adult, adult, child, infant])
```

---

## 8. Baseline canonicalization

### 8.1 Baseline families

Per v1.1.4 §3, six baseline classes were defined. The acquisition
plan adds construction policy per class:

| Class                  | Construction method | When valid |
|---|---|---|
| `canonical_direct`     | Lookup direct O/D in producer inventory; if absent, mark UNAVAILABLE | Always preferred when available |
| `conventional_hub`     | Lookup single-connection routing through user's primary alliance hub (or system default); fallback to major_hub if user has no preference | When canonical_direct is UNAVAILABLE |
| `secondary_entry`      | Lookup two-connection routing through LIS/ZRH/VIE/CPH/WAW/DUB/MUC (or other Europe-secondary airports per v0.2) | When destination is mainland Europe |
| `outer_port_positioning` | Construct from `conventional_hub` baseline + positioning leg, EXCLUDING the candidate's own outer port | When candidate is multi-ticket |
| `same_airport_pair`    | Set of all other routings between same O/D on same date window; pick lowest expected cost as the "anchor" baseline | When multiple routings exist; this is a SET, not a single baseline |
| `fictional_no_fly`     | Constructed absence; never eligible for VERIFIED_OPPORTUNITY | Sensitivity-only; never canonical |

### 8.2 Per-baseline evidence requirements

A baseline is **valid** for hard comparison when ALL of:

1. Same origin (or declared metro pair)
2. Same destination (or declared metro pair)
3. Same date window (±0 day, or ±1 day with `soft_date_window` flag)
4. Same passenger count
5. Same cabin
6. Attached ScheduleEvidence (any verification_status; if UNKNOWN,
   baseline itself is flagged as low-confidence)
7. Attached PriceEvidence (`verification_status != UNKNOWN`)
8. Valid FX (live or user-accepted static)

A baseline missing any of items 6–8 is **partially valid** and produces
a soft comparison with the appropriate warning.

### 8.3 No universal baseline

The spec intentionally defines a taxonomy, not a single default.
Future v1.2 must select baseline_class per-candidate based on:

- The candidate's structural class (e.g., outer_port → use outer_port_positioning baseline)
- The user's declared preferences (alliance)
- The producer's inventory (canonical_direct available?)

### 8.4 Baseline provenance

Every baseline records:

```
BaselineEvidence {
  baseline_class:           str,
  baseline_construction_method: "deterministic_lookup" | "user_declared"
                           | "producer_lookup" | "set_anchor",
  baseline_construction_timestamp: ISO8601,
  baseline_evidence_attached: bool,
  baseline_freshness:       FreshnessRecord,
  sensitivity_only:         bool,        # true iff fictional_no_fly
  ...
}
```

---

## 9. Evidence maturity model

Per v1.1.4 §11, but recast as a maturity ladder (not a score).

| Level | Name | Required evidence | Implementation status |
|---|---|---|---|
| 0 | DISCOVERY ONLY             | Candidate metadata only                                       | ✅ (v0.1) |
| 1 | SCHEDULE EVIDENCE          | ScheduleEvidence attached (DATABASE or LIVE)                 | ✅ (v1.0) |
| 2 | PRICE EVIDENCE             | PriceEvidence attached (LIVE, ESTIMATED, or DATABASE)        | ✅ (v1.1) |
| 3 | COMPARABLE EVIDENCE        | ComparisonEvidence produced; hard parity passes               | ✅ (v1.1, partial via `price_comparison()`) |
| 4 | POTENTIAL OPPORTUNITY      | ComparisonEvidence.comparable = true; raw_comparison emitted | ✅ reachable via v1.1 + parity rules |
| 5 | VERIFIED OPPORTUNITY       | All required_for_verification cleared (Gap A–F closed)       | ❌ (NOT reachable in current architecture) |

### 9.1 Required evidence per level

- **L0 → L1**: any ScheduleEvidence attached (current OpenFlights suffices)
- **L1 → L2**: any PriceEvidence attached (Duffel mock suffices)
- **L2 → L3**: hard parity passes per v1.1.4 §4
- **L3 → L4**: `comparable == true` per ComparisonEvidence
- **L4 → L5**: ALL of:
  1. Cross-provider price comparison (Gap A)
  2. Live schedule for user's date (Gap B)
  3. Producer-attached fare rules at booking time (Gap C — partial)
  4. Live FX or user-accepted static (Gap D)
  5. Multi-passenger parity tested (Gap E)
  6. Baseline canonicalization policy resolved (Gap F)

### 9.2 Maturity is NOT a score

The maturity model is a **state** model, not a numeric score.
A candidate at L4 is structurally a potential opportunity. A candidate
at L5 is structurally a verified opportunity. The two states differ
only in the **presence of evidence**, not in some calculated "goodness".

---

## 10. Minimum viable Evidence Stack

The smallest practical architecture that could support genuine
cross-routing comparison:

```
Travel Mission
   ↓
Candidate Discovery (v0.1)
   ↓
Schedule Evidence (v1.0 + upgrade to Duffel air/schedules for Gap B)
   ↓
Price Provider A — Duffel (v1.1)
   +
Price Provider B — Kiwi (new, for Gap A)
   ↓
FX Evidence — Frankfurter (new, for Gap D)
   ↓
Baseline Construction (new, for Gap F)
   ↓
Parity Validation (new, from v1.1.4 §4)
   ↓
Friction Evidence (new, structured per v1.1.4 §9)
   ↓
ComparisonEvidence (new)
   ↓
   L4: POTENTIAL_OPPORTUNITY   (reachable)
   L5: VERIFIED_OPPORTUNITY    (reachable when all gaps closed)
```

### 10.1 Minimum component requirements

| Component | Status | Required for L5 |
|---|---|---|
| Candidate Discovery (v0.1)            | ✅ exists | yes |
| Schedule Evidence (v1.0)              | ✅ exists | yes (DATABASE acceptable for L4; LIVE required for L5) |
| Duffel price (v1.1)                   | ✅ exists | yes |
| Kiwi price (new)                      | ❌ not implemented | yes (Gap A) |
| Duffel schedule upgrade (new)         | ❌ not implemented | yes (Gap B, if Gap C doesn't cover) |
| Frankfurter FX (new)                  | ❌ not implemented | yes (Gap D) |
| Baseline constructor (new)            | ❌ not implemented | yes (Gap F) |
| Parity validator (new)                | ❌ not implemented | yes (per v1.1.4 §4) |
| Friction evidence builder (new)       | ❌ not implemented | yes (per v1.1.4 §9) |
| Multi-passenger policy (new)          | ❌ not implemented | yes (Gap E) |

### 10.2 Components required ONLY for L5 (not for L4)

- Kiwi price (Gap A)
- Live schedule upgrade (Gap B)
- Frankfurter FX (Gap D)
- Baseline constructor (Gap F)
- Parity validator (per v1.1.4)
- Friction builder
- Multi-passenger policy (Gap E)

The current architecture can reach L4 (POTENTIAL_OPPORTUNITY) using
existing components. Reaching L5 requires all of the above.

---

## 11. Hard blockers (vs WARNING vs OPTIONAL)

### 11.1 BLOCKER (L5 unreachable while this is open)

| Blocker | Effect | Resolution path |
|---|---|---|
| No second price producer                       | Cross-provider comparison impossible; per v1.1.4 §13 required_for_verification cannot clear | Add Kiwi per §1.1 |
| No live schedule for user's date              | schedule_verification_status stuck at DATABASE | Add Duffel `air/schedules` per §1.2 |
| No FX (only static table)                     | Hard currency comparison refused per v1.1.4 §7 | Add Frankfurter per §1.4 |
| No baseline canonicalization policy           | Baseline is undefined; v1.1.4 §3 conditions cannot be evaluated | Implement per §8 |
| No multi-passenger parity policy              | N-passenger comparisons silently scale (forbidden per v1.1.4 §6) | Implement per §7 |

### 11.2 WARNING (L5 reachable but with surface warning)

| Warning | Effect |
|---|---|
| Stale PriceEvidence (>30 min)              | ComparisonEvidence emits `stale_warning` per v1.1.4 §4.3 |
| Stale ScheduleEvidence                      | FrictionEvidence emits `schedule_uncertainty_warning` |
| Baggage evidence incomplete on one side     | ComparisonEvidence emits `baggage_risk_warning` |
| Cross-provider comparison                   | ComparisonEvidence emits `cross_provider_comparison_warning` |
| Duffel FX markup (2%)                       | FXEvidence emits `markup_awareness` flag |
| Mixed passenger types                       | ComparisonEvidence emits `mixed_passenger_warning` (or HARD REFUSE per policy) |

### 11.3 OPTIONAL ENHANCEMENT (does not affect L5)

| Enhancement | Effect |
|---|---|
| Operating carrier equipment (aircraft type) | Better FrictionEvidence but not blocking |
| Schedule upgrade to FlightAware as second producer | Stronger schedule sanity check |
| Open Exchange Rates as second FX source | FX redundancy |
| Seat-map / availability evidence            | Doesn't change L5 state |

### 11.4 No-blocks list (intentional, non-blockers)

| Non-block | Reason |
|---|---|
| Fare rules unavailable at search time | Per v1.1.4 §5.2, this is permanent across all current commercial providers |
| Operating carrier equipment occasionally null | Duffel returns null when carrier doesn't disclose |
| Open-jaw representation gaps in current Candidate | Documented in v1.1.4 §16 Q3; future work |
| Visa transit risk not modeled | Future enhancement; not blocking for L5 |

---

## 12. Provider abstraction

### 12.1 Required new interfaces (not yet implemented)

```
PriceProvider     → already exists in v1.1 (Protocol)
ScheduleProvider  → NEW interface, analogous to PriceProvider
FXProvider        → NEW interface, analogous to PriceProvider
```

### 12.2 Interface sketches (NOT implemented)

```
class ScheduleProvider(Protocol):
    name: str
    def health_check() -> bool
    def lookup(origin, destination, date) -> ScheduleEvidence

class FXProvider(Protocol):
    name: str
    def health_check() -> bool
    def quote(base, target) -> FXEvidence
    def freshness() -> FreshnessRecord
```

### 12.3 Compatibility with existing PriceProvider

The new interfaces are **analogous** to the existing `PriceProvider`
Protocol. Existing semantics:

- Provider name must be unique
- `verification_status` must be one of the 5-tier enum
- `provenance.source` must equal the provider name
- Provider-specific fields MUST NOT leak into the normalized contract

The new `ScheduleProvider` and `FXProvider` interfaces MUST follow the
same conventions, with `verification_status` from the same 5-tier enum
and `provenance.source` carrying the provider name.

### 12.4 Adapter boundary

For each candidate source identified in §1, the corresponding adapter:

- `KiwiAdapter implements PriceProvider` (Gap A)
- `DuffelScheduleAdapter implements ScheduleProvider` (Gap B)
- `FrankfurterAdapter implements FXProvider` (Gap D)

Each adapter is responsible for normalization to the corresponding
evidence contract. No provider-specific field may appear in the
normalized output.

---

## 13. Cost architecture

### 13.1 Per-search cost

| Source | Per-call cost |
|---|---|
| Duffel `air/offer_requests`  | $0.005 excess search (over 1500:1 search-to-book ratio) |
| Duffel `air/schedules`        | typically free per current matrix |
| Kiwi Tequila                  | per Kiwi plan; estimated < $0.01/quote |
| FlightAware AeroAPI           | tiered; free for low-volume |
| Frankfurter (ECB)             | free |
| Open Exchange Rates           | free up to 1000/mo |
| Duffel native FX              | 2% markup on converted amount |

### 13.2 Per-run cost (estimated)

| Scenario | Per-run cost |
|---|---|
| 80 candidates, current v1.1 (Duffel mock only) | $0 |
| 80 candidates, v1.2 (10 Duffel + 10 Kiwi + 1 FX) | < $0.20 |
| 80 candidates, multi-passenger (×3 configs × 2 producers) | < $0.60 |
| 80 candidates, full stack incl. FlightAware schedule | < $1.00 |

### 13.3 Free tiers and rate limits

| Source | Free tier | Rate limit |
|---|---|---|
| Duffel | 1500:1 search:book ratio | 60 req/min |
| Kiwi | per plan | per plan |
| FlightAware AeroAPI | yes (low-volume) | per plan |
| Frankfurter | yes (no auth needed for basic) | not strict |
| Open Exchange Rates | 1000 req/mo | varies |
| Duffel FX | included in Duffel account | 60 req/min |

### 13.4 Caching opportunities

| Cache | Scope | Savings |
|---|---|---|
| FX snapshot (per pipeline run)            | one refresh per run        | 1 FX call instead of N |
| Duffel `offer_id` memoization             | per (candidate, date, pax) | within 20-min TTL      |
| Kiwi equivalent                           | per (candidate, date, pax) | within 15-min TTL      |
| Schedule lookup memoization               | per (O, D, date)           | schedule repeats       |

### 13.5 Request multiplication

For 80 candidates → 10 selected per provider, 2 providers:

| Stage | Calls |
|---|---|
| Schedule (Duffel)               | 10 |
| Price (Duffel + Kiwi)           | 20 |
| FX (1 refresh per run)          | 1  |
| Total per L5-attempt            | 31 |

For multi-passenger (×3 configs):

| Stage | Calls |
|---|---|
| Schedule × 3 configs            | 30 |
| Price × 3 configs × 2 providers | 60 |
| FX                              | 1  |
| Total                           | 91 |

### 13.6 Smoke-test strategy

The v1.1.1 `--smoke-test` guard enforces max 2 real provider calls.
v1.2 must extend this to:

```
smoke_test:
  max_provider_calls: 2     # current v1.1.1 behavior
  max_schedule_calls: 2
  max_fx_calls: 1            # at most one FX refresh per smoke test
```

This is a documentation note; the implementation is part of v1.2.

---

## 14. Security architecture

### 14.1 API key storage

| Tier | Storage |
|---|---|
| Required secrets | `~/.hermes/.env` (Hermes convention) |
| Optional secrets (Kiwi, FlightAware, Open Exchange Rates) | same file |
| Hardcoded env var fallbacks | NOT allowed |

Per Hermes's documented convention: `.env` is for secrets only.
Behavioral settings go in `config.yaml`.

### 14.2 Environment variables

```
DUFFEL_API_KEY_LIVE          # real Duffel live token
DUFFEL_API_KEY_TEST          # Duffel test-mode token
KIWI_API_KEY                 # Kiwi Tequila
FLIGHTAWARE_AERO_API_KEY     # FlightAware (optional)
OPEN_EXCHANGE_RATES_KEY      # Open Exchange Rates (optional)
# Frankfurter requires no key
```

### 14.3 Credential redaction

Per v1.1 + v1.1.1 already implemented:

- Authorization headers are hard-coded as `"Bearer REDACTED"` in source
- Log lines never include raw token values
- `Authorization` header construction uses `urllib.request.Request` and
  does not pass through Python `format()` or f-strings (avoids leaking
  via repr)

### 14.4 Logs

| Log location | What's allowed | What's forbidden |
|---|---|---|
| Console (`stderr`)        | provider name, candidate_id, request count, latency, HTTP status, normalized evidence metadata | token, Authorization header, full headers |
| Trace files (`data/price_trace.json`) | provider identity, retrieved_at, evidence shape | token, Authorization |
| Run logs                  | everything in console + internal state | token, Authorization |

### 14.5 Trace files

- `data/price_trace.json`: per-provider per-candidate trace; never
  contains tokens
- `data/schedule_trace.json`: per-candidate schedule lookup; never
  contains tokens
- `data/fx_trace.json` (NEW for v1.2): per-run FX lookup; never
  contains API keys

### 14.6 CI safety

- CI MUST NOT have any Duffel / Kiwi / FlightAware / Open Exchange
  Rates tokens set
- CI MUST run with `DUFFEL_API_KEY_*` unset, exercising the
  MISSING_CREDENTIALS path of v1.1.1
- v1.2 tests must NOT assume any real credential is present

---

## 15. Open questions (carried forward from v1.1.4 + new)

### 15.1 Carried forward from v1.1.4

1. Baseline canonicalization when no alliance preference
2. Multi-passenger parity (run separate query or refuse)
3. Open-jaw representation
4. Static FX acceptance policy
5. Real-time schedule source (now answered: Duffel `air/schedules` primary; FlightAware secondary)
6. Mock timestamp correction (v1.1.x, not v1.2)
7. Provider cross-check policy (now answered: Kiwi primary second producer)
8. Booking downstream handoff (v1.4)
9. Cancellation/refund parity (permanent gap; documented)
10. Visa transit risk modeling (future)

### 15.2 New open questions for v1.2

11. **Producer diversity for the second producer.** Is Kiwi sufficient
    as second producer, or does v1.2 require two independent producers
    for cross-source reality check (e.g., Duffel + Kiwi + Amadeus)?
12. **Currency parity under static-FX refusal.** When the user's
    primary currency is TWD and the producer returns USD, the current
    static table refuses hard comparison. Does v1.2 require live FX for
    every run, or is a per-run opt-in acceptable?
13. **Schedule upgrade threshold.** Should every candidate have its
    schedule upgraded to LIVE, or only those that pass some cost/value
    threshold?
14. **Baseline reproducibility.** Given the same inputs, must
    baseline construction produce the same baseline every time?
    (Determinism policy.)
15. **Cross-provider freshness window.** When Duffel and Kiwi return
    prices at different `retrieved_at` timestamps, what is the
    freshness tolerance for hard comparison?

---

## 16. Recommended next implementation milestone

Per spec §15, "Recommended next implementation milestone" means
**technical sequencing** — what dependency must be satisfied before
what. NOT a ranking of providers.

### 16.1 Proposed sequencing

**Milestone v1.2.0 — Kiwi PriceProvider Integration (single new producer)**

Scope:
- Implement `KiwiAdapter implements PriceProvider` per v1.1 contract
- Add credential discovery for `KIWI_API_KEY`
- Wire cross-provider PriceEvidence accumulation
- Update `run_price_intelligence.py` (or equivalent) to optionally
  emit per-candidate PriceEvidence from BOTH providers
- Tests: schema equivalence MockDuffel vs Kiwi on synthetic fixtures;
  cross-provider comparison tests

Why this is first:
- Closes Gap A (second price producer) — the most critical L5 blocker
- Does NOT touch schedule, FX, or baseline code
- Allows end-to-end testing of cross-provider evidence flow before
  adding more moving parts

Dependency: `KIWI_API_KEY` available in env, or run with mock

---

**Milestone v1.2.1 — Live Schedule Upgrade (Duffel `air/schedules`)**

Scope:
- Extend `schedule_intelligence.py` (or add a thin
  `DuffelScheduleProvider`) to upgrade ScheduleEvidence
  `verification_status` from DATABASE → LIVE for candidates on
  the user's date
- Tests: upgrade conditions, fallback to DATABASE when schedule not
  found in Duffel

Why second:
- Closes Gap B (live schedule confirmation)
- Uses existing Duffel credential (no new key needed)
- Builds on v1.0's OpenFlights DB layer (additive, not breaking)

Dependency: v1.2.0 done OR v1.2.0 deferred

---

**Milestone v1.2.2 — Frankfurter FX Integration**

Scope:
- Implement `FXProvider` Protocol + `FrankfurterAdapter`
- Add `data/fx_trace.json` per-run FX refresh trace
- Wire FX into ComparisonEvidence builder
- Tests: VALID / WARNING / REFUSE parity per §6.2

Why third:
- Closes Gap D (real FX)
- Lowest integration cost (Frankfurter is free and keyless)
- Improves all cross-currency comparisons retroactively

Dependency: v1.2.0 done OR independent

---

**Milestone v1.2.3 — Baseline Canonicalization + Parity Validator**

Scope:
- Implement baseline construction per §8
- Implement parity validation per v1.1.4 §4
- Emit ComparisonEvidence records
- Tests: baseline taxonomy, hard/soft/refuse parity cases

Why fourth:
- Closes Gap F (baseline canonicalization)
- Required for L4 → L5 transition
- Builds on cross-provider price evidence (v1.2.0) and live FX (v1.2.2)

Dependency: v1.2.0 + v1.2.2 done

---

**Milestone v1.2.4 — Friction Evidence + Multi-Passenger Policy**

Scope:
- Implement FrictionEvidence builder per v1.1.4 §9
- Implement multi-passenger policy per §7
- Tests: friction structure (not scoring), multi-passenger refusal

Why fifth:
- Closes Gap E (multi-passenger parity)
- Provides structural completeness for VERIFIED_OPPORTUNITY

Dependency: v1.2.3 done

---

**Milestone v1.2.5 — Evidence Maturity Ladder + VerifiedOpportunity emission**

Scope:
- Wire the 6-level maturity model (§9)
- Emit Opportunity / VerifiedOpportunity state records
- Tests: state machine transitions, NOT_COMPARABLE handling

Why last:
- Consumes all prior pieces
- Produces the first L5-reachable artifact
- Does NOT introduce any forbidden concept (no score, no ranking, no
  recommendation)

Dependency: v1.2.0 through v1.2.4 done

---

### 16.2 Alternative sequencing

The above assumes the priority is "reach L5 with the smallest stack
possible." A reasonable alternative is "build cross-provider price
comparison first (v1.2.0), defer everything else." This is acceptable
if the user wants minimum scope for v1.2.

### 16.3 What is NOT recommended

- **Implementing a numeric score or ranking** — forbidden by spec.
- **Implementing baseline construction without parity validation** —
  produces "POTENTIAL_OPPORTUNITY" claims without the structural
  integrity that L5 requires.
- **Implementing fare rules** — current commercial providers do not
  surface this at search time; the gap is structural, not
  fixable by v1.2.

---

## 17. Files added / modified

**Added:**

- `docs/evidence_source_matrix_v1_1_5.md` (this document)

**Modified:**

- None. No production code touched. No new tests added. No new JSON
  production data. (Per spec §16.)

---

## 18. Existing known-good regression state

No regression was run during this milestone (architecture/research
only). Last known-good state at v1.1.4 commit (`a2b597c`):

| Suite | Tests | Status |
|---|---|---|
| v0.2 | 6 | ✅ |
| v0.2.1 | 7 | ✅ |
| v1.0 | 72 | ✅ |
| v1.1 | 104 | ✅ |
| v1.1.1 | 83 | ✅ |
| v1.1.2 | (status report) | ✅ |
| v1.1.3 | (read-only audit) | ✅ |
| v1.1.4 | (specification only) | ✅ |

---

# 🛑 STOP CONDITION

> v1.1.5 COMPLETE — SPECIFICATION / RESEARCH ONLY.
>
> Next implementation milestone (technical sequencing only — NOT a
> ranking): **v1.2.0 — Kiwi PriceProvider Integration**.
>
> This is the first v1.2 milestone that closes Gap A (second price
> producer). It does NOT begin automatically.

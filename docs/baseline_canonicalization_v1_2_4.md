# Baseline Canonicalization — v1.2.4 (Implementation)

> Provider-agnostic Baseline Canonicalization Layer (Gap F per v1.1.5).
> Closes the structural gap that let arbitrary candidates emerge with
> no defined comparability reference.
>
> **A baseline is a *comparability reference*, NEVER a price winner.**

---

## 1. Objective

**What this milestone produces:**

- A canonical representation of a Travel Mission (provider-agnostic)
- A canonical representation of each Candidate (provider-agnostic)
- A Baseline Eligibility evaluation per the 6 baseline classes from
  v1.1.4 §3.1
- A Canonical Baseline record per ELIGIBLE class
- A Comparison Pair (candidate + baseline class) with HARD/SOFT/UNKNOWN
  comparability semantics

**What this milestone does NOT do:**

- It does NOT select a baseline by price.
- It does NOT use Jev score, information_priority_score, or any ranking.
- It does NOT emit ArbitrageEvidence / Opportunity / VerifiedOpportunity.
- It does NOT modify Jev semantics.
- It does NOT compare two prices against each other.
- It works even when PriceEvidence is null.

---

## 2. Existing specification findings (per spec §2)

From `docs/arbitrage_evidence_spec_v1_1_4.md` §3 (baseline taxonomy):

| Class | Definition | When valid |
|---|---|---|
| **canonical_direct** | single non-stop, same carrier/alliance | when non-stop exists |
| **conventional_hub** | single-connection through primary alliance hub | when user has alliance preference; otherwise system default |
| **secondary_entry** | two-connection through European secondary entry (LIS, ZRH, VIE, CPH, WAW, DUB, MUC) | when destination is mainland Europe and a secondary entry exists |
| **outer_port_positioning** | two-ticket with positioning flight (KUL, BKK, SIN, CGK) | when candidate itself is multi-ticket or positioning |
| **same_airport_pair** | set of routings between same O/D pair | when multiple routings exist |
| **fictional_no_fly** | "what if this routing did not exist" | explanatory only; never used as canonical baseline |

**v1.1.4 §3.2 baseline validity conditions** (same-origin, same-dest, same-date ±1 day, same-passenger, same-cabin, compatible baggage) preserved as hard_match fields in ComparisonPair.

v1.1.5 §6 (6 baseline families, identical names) confirmed identical.

---

## 3. Baseline definition (per spec §1)

> "What should this candidate be compared against?"

A baseline is:

- A **structural** description of an alternative routing class
- A **provider-agnostic** canonical record
- Bound to a Travel Mission (origin, dest, dates, cabin, passenger basis)
- NOT a real flight's response; it's the *shape* of an eligible comparator

A baseline is NOT:

- The cheapest candidate
- The first candidate
- A Jev survivor
- A score winner
- A price-based selection

---

## 4. Baseline taxonomy (preserved verbatim from v1.1.4 §3.1)

```
canonical_direct
conventional_hub
secondary_entry
outer_port_positioning
same_airport_pair
fictional_no_fly         (never canonical; NOT_ELIGIBLE for our purpose)
```

Compatibility labels from spec §5 (`conventional`, `same_hub`, `same_carrier`,
`same_ticket`, `positioning`, `outer_port`) map onto the canonical classes
as observations on `routing_family`.

---

## 5. Canonical schema (per spec §7)

```python
CanonicalBaseline = {
    schema_version: "v1.2.4",
    baseline_class: "canonical_direct" | ... | "fictional_no_fly",
    mission_binding: {mission_id, origin, destination, travel_date, return_date,
                      is_round_trip, cabin, passenger_count, passenger_types,
                      passenger_basis_known},
    candidate_binding: {candidate_id},
    canonical_representation: {
        origin, destination,
        routing: [(from, to), ...],
        segment_count,
        travel_date, return_date, is_round_trip,
        airports: [list of all airport codes],
        routing_family: "conventional" | "secondary_entry" | "outer_port"
                        | "conventional_hub" | "unusual_routing" | "unknown",
        marketing_carriers, operating_carriers, operating_carriers_known,
        cabin, cabin_known,
        passenger_count, passenger_count_known,
        passenger_types, passenger_types_known,
        ticket_structure, ticket_count,
        positioning, outer_port, secondary_entry,
        airport_change,
        multi_ticket,
        schedule_evidence_status, price_evidence_status, fx_evidence_status,
    },
    canonicalization_reason: "...",
    verification_status: "DATABASE",  # structural baseline
    source: "baseline_canonicalization_v1_2_4",
    is_identity: False,
    supports_no_credential: True,
    warnings: [],
    failure_reason: None,
    failure_kind: None,
    provenance: {
        source, source_type="cache", endpoint=None,
        retrieved_at, verification_status,
        canonicalization_rule_version: "v1.2.4/v1",
        evidence_arity: 0,
        derived_from: {candidate_id, candidate_origin, candidate_destination,
                       candidate_provider, candidate_provider_mode},
    },
}
```

---

## 6. Mission binding (per spec §8)

Mandatory (kept distinct):

- `mission.origin ≠ candidate.origin` blocks comparability
- `mission.destination ≠ candidate.destination` blocks comparability
- `mission.travel_date ≠ candidate.travel_date` blocks hard comparability
- `mission.passenger_basis_known = False` blocks hard comparability (not UNKNOWN → 1)

A baseline **CANNOT** be applied across missions. `TPE → Paris` baseline
does not apply to `TPE → Madrid`. Test NEG-5 covers this.

---

## 7. Date semantics (per spec §9)

Round-trip preserved explicitly:

```python
travel_date: "2027-04-15",
return_date: "2027-04-25",
is_round_trip: True,
```

One-way vs round-trip are distinct. `travel_date` alone does not imply
round-trip absence.

---

## 8. Airport semantics (per spec §10)

| Mode | Behavior |
|---|---|
| `AIRPORT_EXACT` | Default; refuse to coalesce |
| `AIRPORT_GROUP` | Only when caller explicitly groups (not auto-inferred) |
| `METRO_GROUP` | Only when caller explicitly metro-groups |
| `UNKNOWN` | When code can't be normalized |

TPE and TSA are NOT coalesced. TPE and TSA-rail are NOT in our IATA
set and would not be accepted by `normalize_airport()`.

---

## 9. Routing semantics (per spec §11)

`canonical_representation.routing` preserves the full segment list:

```python
[(TPE, FRA), (FRA, MAD)]   # 2 segments → routing_family="conventional_hub"
[(TPE, MAD)]                # 1 segment  → "conventional"
[(TPE, KUL), (KUL, FRA), (FRA, MAD)]   # 3 segments → "unusual_routing"
```

`segment_count` and `airport_change` are surfaced; both are detected from
the actual segment list, never inferred.

---

## 10. Carrier semantics (per spec §12)

`marketing_carriers` and `operating_carriers` are preserved **separately**.
`operating_carriers_known=False` when not surfaced; we do not collapse
operating carrier into marketing carrier.

---

## 11. Cabin / baggage / passenger parity compat (per spec §13)

Spec §13 re-asserts the v1.2.3 rules:

| Missing | Forbidden default | Behavior |
|---|---|---|
| `passenger_count` | 1 | NULL; `pc_known=False` |
| `passenger_type` | ADT | NULL; `passenger_types_known=False` |
| `cabin` | ECONOMY | NULL; `cabin_known=False` |
| `baggage` | 0 | NULL; not defaulted |

`canonical_representation` carries these `*_known` flags so downstream
parity layers can perform the same checks.

---

## 12. Ticket structure (per spec §14)

```python
ticket_count: int | None
ticket_structure: "single-ticket" | "multi-ticket" | None
```

Never auto-coalesced. Multi-ticket vs single-ticket baseline → soft
comparison only (per Test NEG-7).

---

## 13. Hard / Soft / Unknown comparability (per spec §16)

`ComparisonPair.hard_match` carries 6 boolean fields (origin, destination,
date, return_date, cabin, passenger_basis). All True → `comparability =
"hard_comparable"`. Any subset matching except cabin/return_date →
`"soft_comparable"`. Otherwise → `"unknown"`.

These labels do NOT decide on prices; they only signal structural readiness.
A non-hard label means the future comparison engine must explicitly
acknowledge the mismatch before producing evidence.

---

## 14. Eligibility rules (per spec §15)

Each of the 6 baseline classes gets one of three eligibility labels:

| State | Meaning |
|---|---|
| `ELIGIBLE` | a baseline of this class is structurally eligible |
| `NOT_ELIGIBLE` | geometry/mission rules preclude this class |
| `UNKNOWN` | insufficient evidence |

fictional_no_fly is **always** `NOT_ELIGIBLE` (never used as canonical
baseline, per v1.1.4 §3.1).

---

## 15. Negative cases proved (per spec §20)

The 44-test suite includes 8 negative-case tests:

| Test | Asserts |
|---|---|
| NEG-1 cheapest ≠ baseline | structural output identical with price=100 vs price=999999 |
| NEG-2 Jev survivor ≠ baseline | structural output identical with/without `jev_survivor=True` |
| NEG-3 information_priority_score ≠ selector | structural output identical regardless of IPS value |
| NEG-4 missing price ≠ failure | canonical baselines still produced when price=None |
| NEG-5 different date ≠ hard comparable | all comparison pairs flagged NOT hard_comparable |
| NEG-6 different airport ≠ hard match | destination mismatch surfaced in hard_match.destination=False |
| NEG-7 multi-ticket vs single — soft observation | ticket_structure surfaced as soft_observations |
| NEG-8 0 external API calls | verified by source-text audit (no urllib, requests, httpx) |

---

## 16. Provenance (per spec §21)

`provenance.derived_from` carries:

- `candidate_id` — source candidate
- `candidate_origin` / `candidate_destination`
- `candidate_provider` / `candidate_provider_mode`

`provenance.canonicalization_rule_version` is `v1.2.4/v1`. Future
canonicalization rule updates will bump this version. The provenance is
NEVER replaced by an opaque "AI inference"; it always traces to the
input candidate.

---

## 17. Security (per spec §22)

- 0 real API calls (offline)
- Hard ceiling 2 if any (none used)
- Test AI: `FAKE_BASELINE_TOKEN_DO_NOT_LEAK_xxx` env var set; grep
  stdout/stderr/trace/JSON artifacts → 0 matches
- Forbidden tokens: `arbitrage_score`, `opportunity_score`,
  `candidate_score`, `predicted_savings`, `expected_profit`, `winner`,
  `BOOKABLE` guarded at serialization time

---

## 18. Files added (per spec §23)

**Added:**

- `baseline_canonicalization.py` (~750 lines)
- `test_baseline_canonicalization_v1_2_4.py` (44 tests, all PASS)
- `docs/baseline_canonicalization_v1_2_4.md` (this document)
- `data/baseline_evidence_v1_2_4.json` (CLI output)
- `data/baseline_trace_v1_2_4.json` (CLI trace)

**Modified:** None. **No production module was touched.**

**NOT modified:**

- `candidate_discovery.py`
- `schedule_intelligence.py`
- `live_schedule_provider.py`
- `kiwi_price_provider.py`
- `fx_provider.py`
- `passenger_parity.py`
- `run_pipeline.py`
- `eval_flight_yc.py`
- `flight_dashboard.py`
- `price_intelligence.py` (only imported for canonical enums; not modified)

Jev not modified.

---

## 19. Regression results

| Suite | Tests | Status |
|---|---|---|
| v0.2 | 6 | ✅ |
| v0.2.1 | 7 | ✅ |
| v1.0 | 72 | ✅ |
| v1.1 | 104 | ✅ |
| v1.1.1 | 83 | ✅ |
| v1.2.0 Kiwi | 60 | ✅ |
| v1.2.1 schedule | 97 | ✅ |
| v1.2.2 FX | 26 | ✅ |
| v1.2.3 parity | 30 | ✅ |
| **v1.2.4 baseline** | **44** | ✅ |

**Zero regression.**

---

## 20. Real API request count

**0** (per spec §22 hard ceiling ≤2 if any). Source-text audit confirmed
no `urllib`, `requests`, `httpx`, `urlopen` imports.

---

## 21. Known limitations

1. Eligibility for `canonical_direct` is determined by the candidate
   itself being non-stop. A multi-segment candidate can still have a
   canonical_direct baseline available (just not as itself); the
   current implementation surfaces `ELIGIBLE` for `canonical_direct`
   only when the candidate has exactly 1 segment. Future work may
   consider an OpenFlights non-stop lookup for the same O/D pair.
2. `fictional_no_fly` is permanently `NOT_ELIGIBLE` (per v1.1.4 §3.1).
3. Operating carrier is surfaced only if the source candidate exposes
   it. Most heuristic-scan candidates currently don't.
4. The CLI is single-pair (one mission + one candidate). Batch
   canonicalization across multiple candidates is out of scope.
5. Authority on `secondary_entry` and `outer_port` airport sets is the
   v1.1.4 list. The extension lists in `EUROPEAN_SECONDARY_ENTRY` and
   `OUTER_PORTS` add common airports but are advisory; canonicalization
   does not switch eligibility based on them alone — only when the
   mission's destination matches the primary v1.1.4 list.
6. v1.2.4 emits canonical baselines per **ELIGIBLE** class, not per
   actual realized alternative. A future "baseline search" milestone
   will instantiate real alternatives per class and confirm them.

---

## STOP CONDITION

> v1.2.4 — Baseline Canonicalization COMPLETE.
> Zero production modules modified.
> Zero real API calls. Zero credential leakage.

> **Exact next implementation milestone (per v1.1.5 sequencing):**
> ## v1.2.5 — Cross-provider Comparison Engine (Comparison Evidence Layer)

This milestone does **NOT** start automatically.

The objective is not to move fast by adding features.
The objective is to build an evidence-grade Flight Arbitrage Hunter where every comparison can eventually answer:
**"Why do we believe these two prices are actually comparable?"**

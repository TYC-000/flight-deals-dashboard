# L4 — Evidence-based Arbitrage Detection (Flight Market Intelligence)

**Document version**: `l4/v1` (2026-09-28)
**Module**: `arbitrage_detection.py`
**Test suite**: `test_arbitrage_detection_l4.py` (50 tests, all PASS)
**Status**: L4 COMPLETE; STOP without auto-L5.

---

## 1. Purpose

L4 closes the **Arbitrage Detection** gap of the v1.1.5 evidence-source
matrix. It consumes the existing evidence primitives
(`PriceEvidence`, `ScheduleEvidence`, `FXEvidence`,
`ParityEvidence`, `CanonicalBaseline`, `ComparisonEvidence`)
and produces an `ArbitrageEvidence` record that answers the question:

> Given the candidate-vs-baseline price discrepancy, is the
> available evidence sufficient to surface this as a
> **Potential Arbitrage Opportunity**?

L4 is **NOT** a cheapest-flight detector, **NOT** a ranking engine,
**NOT** a recommendation engine, and **NOT** a purchase advisor.
L4 detects evidence-supported price discrepancies. The human
decides what to buy.

---

## 2. Core semantic principle

```
PRICE DIFFERENCE ≠ ARBITRAGE
HARD_COMPARABLE ≠ ARBITRAGE
CHEAPER ≠ ARBITRAGE
ARBITRAGE EVIDENCE ≠ BOOKABLE
POTENTIAL_OPPORTUNITY ≠ VERIFIED_OPPORTUNITY
LIVE ≠ VERIFIED
```

The model above is preserved verbatim from the L4 spec.

---

## 3. Arbitrage state machine (v1.1.4 §11.1)

| State                       | Meaning                                                                |
|-----------------------------|------------------------------------------------------------------------|
| `NOT_COMPARABLE`            | Structural mismatch (cabin / passenger / ticket structure)             |
| `INSUFFICIENT_EVIDENCE`     | Comparable price but required-for-verification gaps remain             |
| `POTENTIAL_OPPORTUNITY`     | HARD_COMPARABLE + price discrepancy + freshness present                |
| `EVIDENCE_VERIFIED`         | POTENTIAL_OPPORTUNITY + freshness fresh + required_for_verification cleared |
| `VERIFIED_OPPORTUNITY`      | **L4 NEVER emits this** — requires real provider validation            |
| `NOT_ARBITRAGE`             | No price discrepancy                                                   |

The state machine is **derived**, not asserted. Every state is
backed by a `reasons` list (each reason pointing to a deterministic
observation from the input evidence).

---

## 4. Evidence maturity (categorical only)

Per spec §21, the maturity field is **categorical**, not numerical:

- `OBSERVED` (not-arbitrage / not-comparable)
- `PARTIALLY_SUPPORTED` (some evidence, but gaps remain)
- `SUPPORTED` (HARD_COMPARABLE + discrepancy + reasonable freshness)
- `VERIFIED` (every required-for-verification gap closed)

There is **no** confidence score, no probability, and no rank.

---

## 5. ArbitrageEvidence schema (provider-agnostic)

The output is a `dict` keyed as follows (per spec §20 + v1.1.4 §11):

```
arbitrage_id                  # stable, derived from candidate/baseline
candidate_id                  # which candidate is being arbitraged
baseline_id                   # which canonical baseline (v1.2.4)
comparison_id                 # ComparisonEvidence (v1.2.5)
arbitrage_state               # see §3 state machine
evidence_maturity             # see §4 maturity catalogue
price_difference              # delta (candidate - baseline)
normalized_price_difference   # delta in normalized price (FX-aware)
percentage_difference         # delta / baseline × 100
absolute_price_difference     # |delta|
price_evidence_refs:
    candidate: {provider, provider_mode, retrieved_at, verification_status, currency, amount}
    baseline:  {provider, provider_mode, retrieved_at, verification_status, currency, amount}
schedule_evidence_refs:
    candidate: ScheduleEvidence (v1.2.1)
    baseline:  ScheduleEvidence (v1.2.1)
fx_evidence_ref:
    state: IDENTITY | APPLIED | UNKNOWN | REFUSED
    evidence_provider: fx_provider (v1.2.2)
passenger_parity_ref          # v1.2.3 parity result
baseline_evidence_ref         # CanonicalBaseline (v1.2.4)
friction_evidence             # v1.1.4 §9.1 structured friction
ticket_structure:
    candidate: single-ticket | multi-ticket | unknown
    baseline:  ...
baggage:
    candidate: baggage field
    baseline:  ...
provider_evidence:
    provider_a, provider_b
    provider_disagreement: True | False | None
    provider_independence: KNOWN | UNKNOWN
    provider_independence_known: False  # always False unless externally established
freshness:
    freshness_a_bucket, freshness_b_bucket
    freshness_a_min, freshness_b_min
    freshness_window_min
    freshness_window_exceeded
    both_fresh
    stale_side
required_for_verification     # see §6
missing_required_for_verification  # same content (alias)
arbitrage_reasons             # reasons for the current state
insufficient_evidence_reasons # populated when state=INSUFFICIENT_EVIDENCE
refusal_reasons               # populated when state=NOT_COMPARABLE
unknown_reasons               # populated when key evidence is UNKNOWN
rule_version                  # "l4/v1"
retrieved_at                  # ISO-8601 (UTC)
evidence_provenance:
    source, source_type, endpoint, retrieved_at, verification_status,
    rule_version, evidence_arity: 2
verification_status           # 5-tier enum (DATABASE for L4 emissions)
source                        # "arbitrage_detection_l4"
is_identity                   # False (L4 always emits non-identity)
supports_no_credential        # True (L4 needs no API credential)
warnings                      # any soft observations
failure_reason, failure_kind  # None for success path
```

L4 emits the **5-tier enum** `verification_status=DATABASE`.
L4 never emits `BOOKABLE`.

---

## 6. Required-for-verification catalogue (v1.1.4 §11.3)

For an ArbitrageEvidence to reach `EVIDENCE_VERIFIED`, all of the
following gaps must be cleared:

| Key                              | What would clear it                                              |
|----------------------------------|------------------------------------------------------------------|
| `real-time-schedule-confirmation`| Schedule evidence verification_status = LIVE for travel date     |
| `second-producer-cross-check`    | Two producers' price agreement OR provider independence verified |
| `baseline-producer-cross-check`  | Baseline's own producer cross-check                              |
| `operating-carrier-rules`        | Carrier-specific refund/change rules fetched                     |
| `seats-remaining`                | Live fare-class availability fetched                            |
| `multi-passenger-parity`         | Multi-passenger parity verified (v1.2.3)                        |
| `live-fx-refresh`                | FX evidence freshness FRESH                                      |

L4 surfaces these as a **list** on every record; it does NOT
clear them. L4 also never emits `VERIFIED_OPPORTUNITY`.

---

## 7. Price discrepancy rules

L4 computes three descriptive values:

```
delta            = comparison.delta              (v1.2.5)
abs_delta        = |delta|
pct              = comparison.delta_percentage   (v1.2.5)
norm_a           = comparison.normalized_price_a
norm_b           = comparison.normalized_price_b
normalized_price_difference = norm_a - norm_b
```

These are **descriptive evidence**, not a score.

`price_difference_exists = abs_delta is not None and abs_delta > 0`.

If `abs_delta is None` or zero → `NOT_ARBITRAGE`.

---

## 8. Friction handling

`FrictionEvidence` is built per v1.1.4 §9.1 (structured, NOT scored).
No monetary penalty is invented. The friction record includes:

- baggage: included_pieces / recheck_required / evidence_complete
- transfer: type / airport_change / overnight_connection / min_connection_min
- schedule_uncertainty: is_uncertain / schedule_status / verification_status
- cancellation_refund: refundable / changeable / change_fee / refund_fee (all optional)
- positioning_risk: has_positioning / separate_pnr / evidence_complete
- visa_transit_risk: requires_transit_visa / evidence_complete
- unknown_fields: list of unresolved fields

The friction record does NOT modify the arbitrage_state; it is
recorded alongside it. The `transfer.type` is derived from
`ticket_structure` and may be `none / managed / self`.

---

## 9. Provider disagreement & independence

```
provider_disagreement = (provider_a != provider_b)
```

When `provider_disagreement is True`, this is captured as **evidence
of cross-source price disagreement**, not as an API error.

`provider_independence` is conservatively set to `UNKNOWN`
unless explicitly established by external evidence (which L4 does
not generate). Two different providers may ultimately source
overlapping inventory; this is documented but not claimable from
inside L4.

---

## 10. Freshness

`freshness` uses the canonical v1.1 freshness semantics (4 buckets:
RECENT / WARM / COLD / EXPIRED; threshold: 30m / 4h / 24h).

If either side's freshness falls outside FRESHNESS_RECENT /
FRESHNESS_WARM (i.e. ≥ COLD), `both_fresh` is `False` and
`live-fx-refresh` is added to `required_for_verification`.

---

## 11. CLI

```
python3 arbitrage_detection.py \
    --candidate   <path/to/candidate.json> \
    --baseline    <path/to/baseline.json> \
    --comparison  <path/to/comparison.json> \
    --fx-evidence <path/to/fx.json> \
    --output      data/arbitrage_evidence_l4.json \
    --trace       data/arbitrage_trace_l4.json
```

All inputs are normalized evidence (provider-agnostic). L4 makes
**zero** provider API calls. No credential is required.

---

## 12. Tests (50 total)

- A–AM (39 cases per spec §28)
- 10 negative tests (per spec §25)
- 1 critical success (per spec §3)

All 50 pass. Total cumulative tests: 6+7+72+104+83+60+97+26+30+44+41+50 = **620**.

---

## 13. Critical success example

```
A: TPE→FRA→MAD,  EUR 420, 1 ADT, economy, single-ticket, LIVE @ 10:00
B: TPE→DOH→MAD,  EUR 500, 1 ADT, economy, single-ticket, LIVE @ 10:01
FX: IDENTITY (EUR→EUR)
comparison.comparability_status = HARD_COMPARABLE

→ ArbitrageEvidence
   arbitrage_state          = POTENTIAL_OPPORTUNITY
   evidence_maturity        = SUPPORTED
   price_difference         = -80 EUR
   percentage_difference    = -16.0%
   provider_disagreement    = True
   provider_independence    = UNKNOWN
   required_for_verification = [real-time-schedule-confirmation,
                                 second-producer-cross-check,
                                 operating-carrier-rules,
                                 seats-remaining,
                                 multi-passenger-parity,
                                 live-fx-refresh]
   missing_required_for_verification = (same list)
```

State is **POTENTIAL_OPPORTUNITY**, not VERIFIED — because
several required-for-verification gaps remain open.

---

## 14. Real API requests

**0**. L4 consumes only normalized evidence objects. No new API
calls are required or permitted. L4 holds to the spec's "≤2 if
absolutely necessary" cap by emitting **0**.

---

## 15. Known limitations

- L4 does NOT clear `required_for_verification` gaps; it surfaces them.
- L4 never emits `VERIFIED_OPPORTUNITY`. Real-provider validation
  (which is required to clear the gaps) belongs to a future milestone
  (L5+ or human review).
- Provider independence is conservatively UNKNOWN; L4 does not
  attempt to verify cross-provider inventory overlap.
- Schedule evidence freshness is keyed to retrieval time of the
  schedule evidence; if `retrieved_at` is missing the freshness bucket
  is `FRESHNESS_UNKNOWN`.

---

## 16. Forbidden tokens

L4's output JSON does NOT contain any of:
`arbitrage_score`, `opportunity_score`, `candidate_score`,
`predicted_savings`, `expected_profit`, `winner`, `BOOKABLE`,
`ranking`, `rank `, `tier`, `confidence_score`.

Test AG / AH / AI / NEG-9 enforce this.

---

## 17. Files added

| Path                                          | Lines | Purpose                            |
|-----------------------------------------------|------:|------------------------------------|
| `arbitrage_detection.py`                      | ~700  | L4 module                          |
| `test_arbitrage_detection_l4.py`              | ~800  | 50 tests                           |
| `docs/arbitrage_detection_l4.md`              | (this)| L4 documentation                   |

## 18. Files NOT modified

All prior v0.2 / v1.x modules and their tests were left untouched.
No production modules (`candidate_discovery.py`, `schedule_intelligence.py`,
`price_intelligence.py`, `kiwi_price_provider.py`,
`live_schedule_provider.py`, `fx_provider.py`, `passenger_parity.py`,
`baseline_canonicalization.py`, `comparison_engine.py`, `run_pipeline.py`,
`flight_dashboard.py`) were modified.

---

## 19. Final answers

### Q1. Does L4 emit ArbitrageEvidence?

**Yes.** L4 produces an `ArbitrageEvidence` record for every
input pair (candidate, baseline, comparison). The record's
`arbitrage_state` may be any of:
`NOT_ARBITRAGE`, `NOT_COMPARABLE`, `INSUFFICIENT_EVIDENCE`,
`POTENTIAL_OPPORTUNITY`, or `EVIDENCE_VERIFIED`.

L4 does **NOT** claim any flight is "worth buying". L4
labels the available evidence; the human decides what to do.

### Q2. Under what exact evidence conditions can L4 emit `POTENTIAL_OPPORTUNITY`?

All of the following must hold:

1. `comparison.comparability_status == "HARD_COMPARABLE"` (or
   the comparison's reasons must not contain structural mismatch
   markers).
2. `price_difference_exists` is True: `comparison.abs_delta` is
   not None and `> 0`.
3. `fx_state != "REFUSED"` (no FX refusal).
4. Either the comparison's `fx_state` is `IDENTITY`, or the FX
   evidence is present and fresh.
5. The candidate/baseline share the same passenger basis (counts
   and types), cabin, and ticket structure parity in the
   supplied comparison.
6. `refusal_reasons` is empty.

If any of (1)–(6) fails, L4 emits `NOT_COMPARABLE`,
`INSUFFICIENT_EVIDENCE`, or `NOT_ARBITRAGE` instead.

`EVIDENCE_VERIFIED` is a strict subset of `POTENTIAL_OPPORTUNITY`
that additionally requires:
- `freshness.both_fresh` is True
- `required_for_verification` is empty

`VERIFIED_OPPORTUNITY` is **not** emitted by L4 under any
circumstances.

---

## 20. STOP — L4 COMPLETE

🛑 L4 is complete. Do NOT proceed to L5.
Do NOT modify dashboard, Jev, build ranking, build purchase
recommendation, or build booking automation.

The next milestone, if any, must be a separate, explicitly
authorized user request.

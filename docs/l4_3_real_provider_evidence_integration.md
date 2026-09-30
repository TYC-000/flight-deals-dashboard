# L4.3 — Real Provider Evidence Integration

**Milestone**: L4.3
**Date**: 2026-09-29 (smoke test) / 2026-09-30 (freeze)
**Status**: DESIGN_COMPLETE + DRY_RUN_COMPLETE
**Branch**: main
**Real external requests during original smoke test**: **1** (Duffel `/air/offer_requests` for KUL-EK-1)
**Real external requests during freeze**: **0**
**Existing Real Duffel Evidence consumed**: YES (in-memory, stored at `/tmp/duffel_smoke_v0_3_evidence.json`)

---

## Real Provider
**Duffel**

| Attribute | Value |
|---|---|
| Candidate | `KUL-EK-1` |
| Origin | TPE |
| Destination | MAD |
| Travel date | 2026-11-12 |
| Provider | `duffel` |
| Provider mode | `live` |
| Verification | `LIVE` |
| Offer ID | `off_0000BAtVJwRmLaPLRjfZhc` |
| Endpoint | `air/offer_requests` |
| Retrieved at | 2026-09-29T07:34:08.087288+00:00 |

---

## Lineage
**MATCH** — `KUL-EK-1` is present in `data/flight_candidates.json` (1 of 25 production candidates). No rename, no alias, no fabrication.

---

## What this evidence proves

`DuffelProvider` can:
- ✅ Call real Duffel API (`https://api.duffel.com/air/offer_requests`)
- ✅ Retrieve a real offer (44 offers returned, first selected)
- ✅ Normalize the response into the existing `PriceEvidence` schema
- ✅ Preserve provenance (`provenance.source='duffel'`, `source_type='live'`, `offer_id`, `endpoint`, `retrieved_at`)
- ✅ Emit `provider_mode='live'` and `verification_status='LIVE'` (canonical 5-tier enum)

## What this evidence does NOT prove

- ❌ Arbitrage (no L4 comparison possible with only 1 LIVE offer)
- ❌ Potential opportunity
- ❌ Verified opportunity
- ❌ Bookability
- ❌ Recommendation
- ❌ Ranking / "best" / "cheapest"

These are explicitly out of scope for L4.3.

---

## FX Boundary — CRITICAL

```
USD 418.05          ← original Duffel price (provider-native currency)
       │
       ▼
TWD 13,314.89       ← display conversion
       │
       └── rate 31.85 = DISPLAY_FX_ONLY
                       (price_intelligence.STATIC_FX_TO_USD, hardcoded)
                       NOT formal FX evidence
```

The 31.85 rate is sourced from `price_intelligence.py:88` (`STATIC_FX_TO_USD` table). The `fx_envelope.source = "snapshot_only_static_table"` and `fx_envelope.verification_status = "DATABASE"`.

**Implication for L4 comparison**: USD→TWD pair is **NOT** present in `data/fx_evidence_v1_2_2.json` (only TWD→EUR captured). Any USD-denominated cross-currency comparison would REFUSE per existing FX semantics.

**Formal FX comparison MUST use the existing FX evidence mechanism** (`data/fx_evidence_v1_2_2.json`, produced by `fx_provider.py`, populated from Frankfurter API). Display FX is **never** a substitute for formal FX evidence.

---

## Partial Evidence — null ≠ NO

The Duffel response contains the following `null`/missing fields. Per spec, these are `UNKNOWN`, **NOT** negative claims:

| Field | Value | Interpretation |
|---|---|---|
| `fare_basis_code` | `null` | UNKNOWN (Duffel didn't return) |
| `changeable` | `null` | UNKNOWN |
| `refundable` | `null` | UNKNOWN |
| `change_fee` | `null` | UNKNOWN |
| `refund_fee` | `null` | UNKNOWN |
| `cabin` | `null` | UNKNOWN (Duffel returns cabin at offer level, not in normalized payload yet) |
| `baggage.evidence_complete` | `false` | partial — Duffel-side data quality flag |
| `baggage.checked_weight_kg` | `null` | UNKNOWN |

**`null` MUST NOT be interpreted as:**
- ❌ "free" (when null = free baggage)
- ❌ "non-refundable" (when null = refundable)
- ❌ "non-changeable" (when null = changeable)
- ❌ "0 checked pieces" (when null = pieces)

`null` means **UNKNOWN — evidence unavailable**. The L4 chain treats this as INSUFFICIENT_EVIDENCE for fare-rule-dependent decisions.

---

## Evidence Maturity Matrix

| Layer | Source | Maturity | Notes |
|---|---|---|---|
| Discovery | `flight_candidates.json` | LIVE (heuristic scanner, no API) | 25 candidates, deterministic grid |
| Schedule | OpenFlights | **DATABASE** | `routes.dat`, no live validation |
| Price | Duffel | **LIVE** | 1 real offer for KUL-EK-1 (this milestone) |
| Price | MockDuffel / Mock | **MOCK** | 25 synthetic records |
| FX | Frankfurter | **LIVE** (existing captured pair) | 1 currency pair (TWD→EUR) |
| FX | Static display table | **DATABASE** (display-only) | 31.85 USD→TWD, NOT formal FX evidence |
| Passenger parity | synthetic | **SYNTHETIC** | 3 records (test fixtures) |
| Baseline | synthetic | **SYNTHETIC** | 25 records (NOT_ASSESSED for most) |
| Comparison | synthetic | **SYNTHETIC** | 2 records (REFUSED) |
| L4 arbitrage | synthetic | **SYNTHETIC** | 25 records (INSUFFICIENT_EVIDENCE / NOT_ANALYZED) |

**Boundary invariants** (must NOT be violated):
- LIVE ≠ MOCK ≠ DATABASE ≠ SYNTHETIC
- No downgrade / upgrade between maturity levels
- Display FX (DATABASE) ≠ formal FX evidence (LIVE)
- Mock evidence cannot be relabeled as LIVE

---

## L4.2-B Compatibility (where this evidence would live)

If a future milestone integrates this single Duffel LIVE record into canonical evidence:

| Layer | Schema field | Status |
|---|---|---|
| `data/price_evidence.json` | `provider='duffel'`, `provider_mode='live'`, `verification_status='LIVE'`, `currency='TWD'`, `total_price.amount=13314.89`, `provenance.{source,source_type,offer_id,endpoint,retrieved_at}` | COMPATIBLE |
| `data/fx_evidence_v1_2_2.json` | USD→TWD pair | MISSING (no formal FX evidence) |
| `data/arbitrage_evidence_l4.json` | would emit `INSUFFICIENT_EVIDENCE` (FX UNKNOWN blocks comparison) | COMPATIBLE (no semantic change) |
| `dashboard_view_model.py` | surfaces `provider='duffel'`, `provider_mode='live'`, `verification_status='LIVE'` | PARTIAL (provenance chain not exposed in UI) |

**Dashboard gap**: Current `dashboard_view_model.py` exposes `provider`, `provider_mode`, `verification_status`, `retrieved_at` but does NOT surface `provenance.source`, `provenance.offer_id`, `provenance.endpoint`. Surfacing these is a future dashboard enhancement, NOT part of L4.3.

---

## L4.3 Tests

15 deterministic offline tests added: `test_l4_3_real_provider_evidence_integration.py`

| Test | What it verifies |
|---|---|
| L43-01 | LIVE provenance preserved end-to-end |
| L43-02 | candidate_id lineage intact |
| L43-03 | Mock cannot become LIVE (production gate) |
| L43-04 | LIVE cannot become Mock |
| L43-05 | FX source classification (DISPLAY_FX_ONLY) |
| L43-06 | DISPLAY_FX_ONLY ≠ formal FX evidence |
| L43-07 | unresolved FX blocks comparison |
| L43-08 | mixed provider evidence explicitly marked |
| L43-09 | single LIVE offer cannot become arbitrage |
| L43-10 | no VERIFIED_OPPORTUNITY in any evidence |
| L43-11 | no BOOKABLE token in any evidence |
| L43-12 | no forbidden tokens (ranking, scoring) |
| L43-13 | no recommendation language |
| L43-14 | no credential leakage (excludes dividers, SHAs, identifiers, fixtures) |
| L43-15 | zero external requests during audit |

All 15 tests PASS in offline mode (no Keychain, no Duffel API, no HTTP).

---

## What L4.3 does NOT do

- ❌ Does NOT integrate the Duffel LIVE record into canonical `data/price_evidence.json`
- ❌ Does NOT modify `dashboard_view_model.py` to surface provenance chain
- ❌ Does NOT trigger another Duffel request (1-request budget was consumed in v0.3)
- ❌ Does NOT modify L4 semantics (no new states, no new logic)
- ❌ Does NOT introduce VERIFIED_OPPORTUNITY (NEVER emitted by L4.3)
- ❌ Does NOT introduce BOOKABLE (forbidden token)
- ❌ Does NOT rank or recommend

---

## Remaining limitations (pre-L5)

1. **No real Kiwi validation**: `data/price_evidence.json` still dominated by `mock` / `mock_duffel`. No `kiwi/live` records.
2. **No real Frankfurter currency pair for USD→TWD**: only TWD→EUR is captured.
3. **OpenFlights schedule is DATABASE, not LIVE**: no live operating-schedule validation.
4. **Duffel response is partial**: fare rules (change/refund), seats remaining not exposed in `/air/offer_requests`.
5. **No cross-provider real comparison**: 1 LIVE offer cannot establish arbitrage on its own.
6. **`flight_candidates.json` is heuristic grid**: not a real fare search; 25 candidates are deterministic from a hardcoded REFERENCE_FARES_USD table.

---

## Critical distinction (per spec)

**L4.3 does NOT emit VERIFIED_OPPORTUNITY.** The L4 chain's strongest current state is `INSUFFICIENT_EVIDENCE` (FX UNKNOWN blocks comparison). The path from INSUFFICIENT_EVIDENCE to VERIFIED_OPPORTUNITY requires real carrier-rules + seats-remaining + cross-provider real comparison + complete baggage — all of which are L5 (NOT STARTED).

---

🛑 STOP — L4.3 Real Provider Evidence Integration frozen.
No L4.4. No L5. No new API requests. No semantics change.
Awaiting explicit authorization for next milestone.

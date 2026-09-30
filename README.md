# ✈️ Flight Arbitrage Hunter — Evidence-grade Flight Arbitrage Research Platform

A Streamlit dashboard for evaluating Asia outer-port flight deals to Europe and the
Middle East. Built as an **evidence-grade research platform**: every visible claim
about a candidate is backed by an explicit, traceable evidence record.

**This is NOT a flight recommendation engine.** The dashboard does not tell you
which ticket to buy. It surfaces what is known, what is missing, and how confident
each piece of evidence is.

---

## What the platform is

- **Research tool** — surfaces evidence layers (L0–L4) for every production candidate
- **Evidence-aware UI** — every claim has provenance (`provider`, `provider_mode`,
  `verification_status`, `retrieved_at`)
- **Honest about uncertainty** — explicit `UNKNOWN` / `INSUFFICIENT_EVIDENCE` /
  `NOT_ANALYZED` states, never collapsed into a positive or negative claim
- **Layered pipeline** — Discovery → Schedule → Price → FX → Parity → Baseline →
  Comparison → L4 Detection → L4.1 Orchestrator → Dashboard

## What the platform is NOT

- ❌ Not a "best / cheapest / winner" selector
- ❌ Not a booking or ticketing tool
- ❌ Not a VERIFIED_OPPORTUNITY emitter (no L5)
- ❌ Not an LLM-based advisor (Jev is the 1:1 evaluator; LLM is not in the loop)

---

## Maturity block

| Layer | Status |
|---|---|
| L0 Candidate Discovery | ✅ |
| L1 Schedule Intelligence | ✅ |
| L2 Price Intelligence | ✅ |
| L3 Evidence / Parity | ✅ |
| L4 Comparison / Arbitrage | ✅ |
| L4.1 Pipeline Integration | ✅ |
| L4.2-B Production Coverage | ✅ |
| L4.3 Real Provider Evidence | ✅ |
| **L5 Verified Opportunity** | **⏳ NOT STARTED** |

**L4.3 does NOT emit VERIFIED_OPPORTUNITY.**

---

## Current capability

The platform can honestly answer:
- What is the candidate? (`candidate_id`, route, segments)
- What schedule evidence exists? (`DATABASE` / `LIVE` / `VERIFIED` / `UNKNOWN`)
- What price evidence exists? (`LIVE` / `MOCK` / `DATABASE` / `UNKNOWN`)
- What is the price source? (`provider`, `provider_mode`, `verification_status`)
- Does FX evidence exist for this currency pair? (`IDENTITY` / `APPLIED` / `UNKNOWN` / `REFUSED`)
- Is passenger parity sufficient? (`MATCH` / `NON_PARITY` / `UNKNOWN`)
- Does baseline evidence exist? (`ELIGIBLE` / `NOT_ASSESSED`)
- Is the candidate structurally comparable? (`HARD_COMPARABLE` / `SOFT_COMPARABLE` / `NOT_COMPARABLE` / `REFUSED`)
- What is the L4 evidence state? (`NOT_ARBITRAGE` / `NOT_COMPARABLE` / `INSUFFICIENT_EVIDENCE` / `POTENTIAL_OPPORTUNITY` / `EVIDENCE_VERIFIED` / `NOT_ANALYZED`)
- What is the evidence provenance / maturity for each layer?

The platform does **NOT** honestly answer:
- ❌ Which ticket is "worth buying"
- ❌ Which is the "winner"
- ❌ Which is "cheapest"
- ❌ Which is "bookable"
- ❌ Which is `VERIFIED_OPPORTUNITY` (this state is NEVER emitted by L4.x)

---

## Dashboard contract

The Streamlit dashboard is an **evidence-aware research interface**. It preserves:
- Evidence layers (Schedule / Price / FX / Parity / Baseline / Comparison / Arbitrage)
- Provenance chain (`provider`, `provider_mode`, `verification_status`, `retrieved_at`)
- Verification states (canonical 5-tier enum: `UNKNOWN` / `ESTIMATED` / `DATABASE` / `LIVE` / `VERIFIED`)
- Comparability states (`HARD_COMPARABLE` / `SOFT_COMPARABLE` / `UNKNOWN` / `NOT_COMPARABLE` / `REFUSED`)
- Missing-evidence visibility (`UNKNOWN` / `NOT_ASSESSED` / `NOT_PAIRED` / `NOT_ANALYZED`)

It does **NOT** introduce:
- ❌ Recommendation language
- ❌ Ranking or scoring
- ❌ "Best / cheapest / winner" labels
- ❌ `BOOKABLE` or `VERIFIED_OPPORTUNITY` emission

---

## Pipeline architecture

```
flight_candidates.json  (production scanner, 25 candidates)
        ↓
L1 Schedule Intelligence     →  schedule_evidence_v1_2_1.json   (OpenFlights DATABASE)
        ↓
L2 Price Intelligence        →  price_evidence.json              (Duffel LIVE / MockDuffel / Mock)
        ↓
L2.2 FX                      →  fx_evidence_v1_2_2.json          (Frankfurter LIVE for captured pairs)
        ↓
L2.3 Passenger Parity        →  passenger_parity_evidence_v1_2_3.json
        ↓
L2.4 Baseline Canonicalization → baseline_evidence_v1_2_4.json
        ↓
L2.5 Cross-provider Comparison → comparison_evidence_v1_2_5.json
        ↓
L4 Arbitrage Detection       →  arbitrage_evidence_l4.json       (NOT_ANALYZED / INSUFFICIENT_EVIDENCE / NOT_ARBITRAGE / NOT_COMPARABLE)
        ↓
L4.1 Pipeline Orchestrator   →  l4_1_run_trace.json
        ↓
Dashboard View Model (v0.2)  →  Streamlit UI (Evidence tab per candidate)
```

---

## Evidence maturity (current state)

| Layer | Source | Maturity | Notes |
|---|---|---|---|
| Discovery | `flight_candidates.json` | LIVE (heuristic scanner) | 25 candidates, deterministic grid |
| Schedule | OpenFlights | **DATABASE** | `routes.dat`, no live operating-date validation |
| Price | Duffel | **LIVE** | 1 real offer (L4.3 milestone: KUL-EK-1) |
| Price | MockDuffel / Mock | **MOCK** | 25 synthetic records |
| FX | Frankfurter | **LIVE** (existing captured pair) | TWD→EUR only |
| FX | Static display table | **DATABASE** (display-only) | 31.85 USD→TWD, NOT formal FX evidence |
| Passenger parity | synthetic | **SYNTHETIC** | 3 records |
| Baseline | synthetic | **SYNTHETIC** | 25 records (NOT_ASSESSED for most) |
| Comparison | synthetic | **SYNTHETIC** | 2 records (REFUSED) |
| L4 arbitrage | synthetic | **SYNTHETIC** | 25 records (INSUFFICIENT_EVIDENCE / NOT_ANALYZED) |

**Boundary invariants**:
- LIVE ≠ MOCK ≠ DATABASE ≠ SYNTHETIC
- No downgrade / upgrade between maturity levels
- Display FX (DATABASE) ≠ formal FX evidence (LIVE)

---

## L4.3 Real Provider Evidence Integration (frozen checkpoint)

L4.3 is the first **real Duffel API validation** (1 request, in-memory only). It proves
that `DuffelProvider` can talk to the real Duffel API, retrieve an offer, normalize
the response, and preserve provenance. It does NOT integrate the record into
canonical evidence (no `data/price_evidence.json` write). L4.3 does NOT emit
`VERIFIED_OPPORTUNITY`.

See `docs/l4_3_real_provider_evidence_integration.md` for the full audit report.

---

## Local run

```bash
pip install -r requirements.txt
streamlit run flight_dashboard.py
```

The dashboard reads:
- `data/flight_candidates.json` (production candidates)
- `data/flight_results.json` (evaluated candidates)
- `data/schedule_evidence_v1_2_1.json` (L1)
- `data/price_evidence.json` (L2)
- `data/fx_evidence_v1_2_2.json` (L2.2)
- `data/passenger_parity_evidence_v1_2_3.json` (L2.3)
- `data/baseline_evidence_v1_2_4.json` (L2.4)
- `data/comparison_evidence_v1_2_5.json` (L2.5)
- `data/arbitrage_evidence_l4.json` (L4)

## Data refresh

```bash
# Refresh production candidates
python3 ~/.hermes/tools/scan_new_deals.py

# Refresh L0–L4.1 evidence (production candidate population)
python3 run_l41_production.py
```

---

## Tests

```bash
# Full regression (offline, deterministic)
for f in test_pipeline_v0.2.py test_pipeline_v0.2.1.py test_schedule_intelligence_v1.py \
         test_price_intelligence_v1.py test_price_intelligence_v1_1.py \
         test_kiwi_price_provider_v1_2_0.py test_schedule_provider_v1_2_1.py \
         test_fx_provider_v1_2_2.py test_passenger_parity_v1_2_3.py \
         test_baseline_canonicalization_v1_2_4.py test_comparison_engine_v1_2_5.py \
         test_arbitrage_detection_l4.py test_l4_1_pipeline_integration.py \
         test_dashboard_view_model_v0_2.py test_dashboard_repair_v0_2.py \
         test_l4_2_b_production_coverage.py test_l4_3_real_provider_evidence_integration.py \
         test_deployment_integrity_v0_1.py; do
  python3 "$f"
done
```

**No test makes external API requests.** All tests are offline-deterministic.

---

## Security

- No credentials in repository (verified by `test_l4_3_real_provider_evidence_integration.py:L43-14`)
- Credentials live in macOS Keychain (service `DUFFEL_API_KEY_TEST`)
- Hermes CLI auto-loads `~/.hermes/.env` at startup
- No `.env` files in repo, no `.env` files in tracked data

---

## What's next

**L4.3 is frozen.** The next milestone is NOT started and requires explicit authorization.

Candidates for future work (none started):
- L4.4 — Production Evidence Coverage expansion (more LIVE candidates)
- L5 — VERIFIED_OPPORTUNITY (requires real carrier rules, seats remaining, complete baggage)
- Real Kiwi integration (out of scope for L4.3)
- Dashboard enhancement: surface `provenance.source` / `offer_id` / `endpoint` (gaps identified in L4.3 audit)

🛑 STOP — this README describes L4.3 frozen state. No L4.4. No L5. No new API requests.

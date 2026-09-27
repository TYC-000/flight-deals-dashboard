#!/usr/bin/env python3
"""Generate synthetic arbitrage fixtures for L4 (spec §24, Cases A-L)."""
import sys, json
from pathlib import Path
sys.path.insert(0, "/Users/aib/.hermes/cache/scratch/flight-dashboard")
from arbitrage_detection import build_arbitrage_evidence

DATA_DIR = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def cand(cid, **kw):
    d = {"provider": "duffel", "provider_mode": "live", "price_amount": 420,
         "price_currency": "EUR", "retrieved_at": "2026-09-27T10:00:00+00:00",
         "verification": "LIVE", "schedule_verification": "LIVE",
         "cabin": "economy", "pc": 1, "ticket_structure": "single-ticket"}
    d.update(kw)
    return {
        "candidate_id": cid, "origin": "TPE", "destination": "MAD",
        "travel_date": "2027-04-15", "cabin": d["cabin"],
        "passenger_count": d["pc"], "passenger_types": ["ADT"] * d["pc"],
        "ticket_structure": d["ticket_structure"], "ticket_count": 1,
        "itinerary_identity": "TPE-MAD",
        "baggage": {"included": {"checked_pieces": 1, "carry_on": 1}, "evidence_complete": True},
        "price_evidence": {"total_amount": d["price_amount"], "currency": d["price_currency"],
            "retrieved_at": d["retrieved_at"], "verification_status": d["verification"],
            "provider": d["provider"], "provider_mode": d["provider_mode"]},
        "schedule_evidence": {"verification_status": d["schedule_verification"], "provider": d["provider"]},
        "passenger_parity_ref": "PP-001",
    }


def comparison(**kw):
    d = {"status": "HARD_COMPARABLE", "delta": -80, "abs_delta": 80, "pct": -16.0,
         "fx_state": "IDENTITY", "norm_a": 420, "norm_b": 500, "currency": "EUR"}
    d.update(kw)
    n = d["norm_a"] if isinstance(d["norm_a"], (int, float)) else None
    m = d["norm_b"] if isinstance(d["norm_b"], (int, float)) else None
    return {"comparison_id": "A::B", "comparability_status": d["status"],
        "comparison_reasons": d.get("reasons", []),
        "refusal_reasons": d.get("refusal", []),
        "normalized_price_a": n, "normalized_price_b": m,
        "comparison_currency": d["currency"],
        "delta": d["delta"], "abs_delta": d["abs_delta"],
        "delta_percentage": d["pct"], "fx_state": d["fx_state"]}


cases = {
    "A": ("Case A — No price difference (NOT_ARBITRAGE)",
        cand("A"), cand("B", provider="kiwi", price_amount=420),
        comparison(norm_a=420, norm_b=420, delta=0, abs_delta=0, pct=0)),
    "B": ("Case B — Comparable price difference (POTENTIAL_OPPORTUNITY)",
        cand("A"), cand("B", provider="kiwi", price_amount=500), comparison()),
    "C": ("Case C — Missing FX (REFUSED)",
        cand("A", price_amount=420, price_currency="EUR"),
        cand("B", provider="kiwi", price_amount=480, price_currency="USD"),
        comparison(fx_state="REFUSED", norm_a=420, norm_b=480)),
    "D": ("Case D — Passenger mismatch",
        cand("A"), cand("B", provider="kiwi", price_amount=900, pc=2),
        comparison(norm_a=420, norm_b=900, delta=-480, abs_delta=480, pct=-53.3,
            status="SOFT_COMPARABLE", reasons=["PASSENGER_COUNT_MISMATCH"])),
    "E": ("Case E — Cabin mismatch (NOT_COMPARABLE)",
        cand("A"), cand("B", provider="kiwi", price_amount=2000, cabin="business"),
        comparison(norm_a=420, norm_b=2000, delta=-1580, abs_delta=1580, pct=-79,
            status="NOT_COMPARABLE", reasons=["CABIN_MISMATCH"])),
    "F": ("Case F — Multi-ticket (friction)",
        cand("A", ticket_structure="multi-ticket", price_amount=300),
        cand("B", provider="kiwi", price_amount=500),
        comparison(norm_a=300, norm_b=500, delta=-200, abs_delta=200, pct=-40,
            status="SOFT_COMPARABLE", reasons=["TICKET_STRUCTURE_MISMATCH"])),
    "G": ("Case G — Airport change (friction)",
        cand("A"), cand("B", provider="kiwi", price_amount=480),
        comparison(norm_a=420, norm_b=480, delta=-60, abs_delta=60, pct=-12.5)),
    "H": ("Case H — Stale price",
        cand("A", retrieved_at="2026-09-20T10:00:00+00:00"),
        cand("B", provider="kiwi", price_amount=500,
              retrieved_at="2026-09-20T10:01:00+00:00"),
        comparison()),
    "I": ("Case I — Provider disagreement",
        cand("A"), cand("B", provider="kiwi", price_amount=500), comparison()),
    "J": ("Case J — Structural opportunity (outer-port)",
        cand("A", price_amount=350),
        cand("B", provider="kiwi", price_amount=500),
        comparison(norm_a=350, norm_b=500, delta=-150, abs_delta=150, pct=-30,
            status="SOFT_COMPARABLE", reasons=["STRUCTURAL_DIFFERENCE"])),
    "K": ("Case K — Missing baseline (INSUFFICIENT_EVIDENCE)",
        cand("A"), None, comparison()),
    "L": ("Case L — Price absent (NOT_ARBITRAGE)",
        cand("A"), cand("B", provider="kiwi", price_amount=500),
        comparison(delta=0, abs_delta=0, pct=0, norm_a=None, norm_b=500)),
}

# Special: G gets explicit airport_change set on candidate
cases["G"][1]["airport_change"] = True
# Special: J gets outer_port_origin set on candidate
cases["J"][1]["outer_port_origin"] = True
# Special: K baseline is None (already set above)

fixtures_out = {"version": "l4/v1", "generated_at": "2026-09-28T00:00:00+00:00"}
results = []

for k, (name, cA, cB, cmp) in cases.items():
    if k == "L":
        cA["price_evidence"]["total_amount"] = None
    r = build_arbitrage_evidence(cA, cB, cmp)
    fixtures_out[k] = {"name": name, "candidate": cA, "baseline": cB,
                        "comparison": cmp, "arbitrage_evidence": r}
    results.append((k, name, r["arbitrage_state"], r["evidence_maturity"],
                     r["price_difference"]))

# Persist
fp = DATA_DIR / "_synthetic_arbitrage_fixtures_l4.json"
fp.write_text(json.dumps(fixtures_out, indent=2, ensure_ascii=False))

# Canonical evidence (Case B)
canonical = fixtures_out["B"]["arbitrage_evidence"]
ep = DATA_DIR / "arbitrage_evidence_l4.json"
ep.write_text(json.dumps(canonical, indent=2, ensure_ascii=False))

# Trace
trace = {
    "trace_at": "2026-09-28T00:00:00+00:00",
    "arbitrage_id": canonical["arbitrage_id"],
    "arbitrage_state": canonical["arbitrage_state"],
    "evidence_maturity": canonical["evidence_maturity"],
    "delta": canonical["price_difference"],
    "delta_pct": canonical["percentage_difference"],
    "freshness": canonical["freshness"],
    "required_for_verification": canonical["required_for_verification"],
    "rule_version": canonical["rule_version"],
}
tp = DATA_DIR / "arbitrage_trace_l4.json"
tp.write_text(json.dumps(trace, indent=2, ensure_ascii=False))

# Summary
print("=" * 75)
print("Case summary")
print("=" * 75)
for k, name, state, mat, delta in results:
    print(f"  {k}: {state:<25}  {mat:<25}  Δ={delta}")

print()
print("fixtures:    ", fp)
print("evidence:    ", ep)
print("trace:       ", tp)

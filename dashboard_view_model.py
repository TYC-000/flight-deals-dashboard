"""
dashboard_view_model.py — Dashboard View Model (Dashboard Intelligence v0.2)

Architectural role
==================

The View Model sits between the existing Canonical Evidence (data/*.json
artifacts produced by L0–L4.1) and the Streamlit presentation layer.

It is:
  * stateless: a pure function from evidence to view objects.
  * deterministic: same input → same output (test N).
  * presentation-only: it does NOT compute arbitrage, prices, FX, or risk.
  * evidence-preserving: it does NOT modify canonical evidence.
  * candidate-ID based: every view object is keyed by candidate_id.
  * tolerant of missing/null fields: it never raises on missing evidence.
  * independent of Streamlit: does not import streamlit.

It does NOT:
  * introduce any new arbitrage state.
  * invent any price, schedule, FX, carrier, baggage, or verdict.
  * collapse distinct evidence states into "available".
  * display MOCK as LIVE, DATABASE as VERIFIED, or UNKNOWN as MATCH.
  * introduce arbitrage_score / opportunity_score / confidence_score /
    best / winner / cheapest / rank / tier / recommendation semantics.

The View Model exposes one public class:
  DashboardCandidateView — immutable per-candidate presentation object.

Construction:
  view = DashboardCandidateView.from_canonical_evidence(
      candidate={"id": "AUTO-...", ...},           # from flight_results.json
      schedule_evidence_by_id={...},              # from schedule_evidence_v1_2_1.json
      price_evidence_by_id={...},                 # from price_evidence.json
      fx_evidence_by_id={...},                    # from fx_evidence_v1_2_2.json
      parity_evidence_by_id={...},                # from passenger_parity_evidence_v1_2_3.json
      baseline_evidence_by_id={...},              # from baseline_evidence_v1_2_4.json
      comparison_evidence_by_id={...},            # from comparison_evidence_v1_2_5.json
      arbitrage_evidence_by_id={...},             # from arbitrage_evidence_l4.json
  )

For 78 of the 80 candidates in flight_results.json, the L4.1 evidence
files contain no match (because the L4.1 orchestrator only ran on 2
candidates). For those 78, every *_evidence field is None / UNKNOWN.
This is HONEST: the dashboard will display "Evidence unavailable" or
"UNKNOWN" rather than fabricate evidence.

All times are kept as ISO 8601 strings or None. The View Model does
not compute "X minutes ago" — that is a presentation concern for the UI.

The View Model does NOT regenerate evidence. It does NOT modify Jev
semantics. It does NOT introduce a second canonical source of truth.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional, List, Dict, Tuple, Set


# ----------------------------------------------------------------------
# Sentinel values
# ----------------------------------------------------------------------
# Presentation-only sentinels. NEVER written back to canonical evidence.
EVIDENCE_UNAVAILABLE = "Evidence unavailable"
UNKNOWN = "UNKNOWN"


# ----------------------------------------------------------------------
# Helpers (pure, side-effect-free)
# ----------------------------------------------------------------------
def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _opt_str(v: Any) -> Optional[str]:
    return v if _is_str(v) else None


def _opt_num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _opt_int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _opt_dict(v: Any) -> Optional[Dict[str, Any]]:
    return v if isinstance(v, dict) else None


def _opt_list(v: Any) -> Optional[List[Any]]:
    return v if isinstance(v, list) else None


def _as_iso(v: Any) -> Optional[str]:
    """Pass through ISO 8601 strings; coerce other strings; None otherwise."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return None


def _as_label(value: Any, allowed: Set[str], fallback: str = UNKNOWN) -> str:
    """
    Coerce a value to a canonical label.

    If value is a string and is in `allowed`, return it.
    Otherwise return `fallback`. This is the canonical mechanism for
    preventing downstream fields from accidentally displaying
    'mock' as 'LIVE' or None as 'MATCH'.
    """
    if isinstance(value, str) and value in allowed:
        return value
    return fallback


# ----------------------------------------------------------------------
# Sub-view objects (immutable)
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class IdentityView:
    candidate_id: Optional[str]
    route: Optional[list]
    origin: Optional[str]
    destination: Optional[str]
    travel_date: Optional[str]
    return_date: Optional[str]
    label: Optional[str]


@dataclass(frozen=True)
class DiscoveryView:
    discovery_reason: Optional[list]
    candidate_family: Optional[str]
    route_structure: Optional[str]


@dataclass(frozen=True)
class ScheduleEvidenceView:
    """
    Surfaces canonical schedule evidence WITHOUT reinterpreting it.

    `verification_status` is the canonical 5-tier enum
    (UNKNOWN / ESTIMATED / DATABASE / LIVE / VERIFIED) when present in
    canonical evidence; otherwise UNKNOWN.

    `schedule_source` is the raw `schedule_source` from the canonical
    segment record (e.g., "estimated", "database", "live", "unknown").
    """
    verification_status: str
    schedule_status: Optional[str]
    schedule_source: Optional[str]
    freshness: Optional[str]
    retrieved_at: Optional[str]
    provider: Optional[str]
    provider_mode: Optional[str]
    warnings: Optional[list]


@dataclass(frozen=True)
class PriceEvidenceView:
    """
    Surfaces canonical price evidence WITHOUT merging multiple providers.

    If the canonical evidence contains multiple providers, the View Model
    exposes them via the `providers` field (a list of ProviderPriceView).
    The UI may render each independently.

    The legacy `total_cost_twd` and `savings_pct` from
    `flight_results.json` are surfaced via `legacy_derived` and labeled
    as such in the UI; they are NEVER presented as live provider prices.
    """
    providers: list  # list[ProviderPriceView]
    verification_status: str
    retrieved_at: Optional[str]
    failure_kind: Optional[str]
    failure_reason: Optional[str]
    warnings: Optional[list]
    legacy_total_cost_twd: Optional[int]
    legacy_savings_pct: Optional[float]


@dataclass(frozen=True)
class ProviderPriceView:
    """A single provider's price evidence (NEVER merged across providers)."""
    provider: Optional[str]
    provider_mode: Optional[str]
    price: Optional[float]
    currency: Optional[str]
    verification_status: Optional[str]
    retrieved_at: Optional[str]
    freshness_bucket: Optional[str]
    ticket_count: Optional[int]
    is_single_ticket: Optional[bool]
    baggage: Optional[str]
    cabin: Optional[str]


@dataclass(frozen=True)
class FXEvidenceView:
    """
    Surfaces canonical FX evidence.

    `fx_state` is the canonical state (one of PROVIDED, REFUSED, etc.)
    or UNKNOWN if missing.

    The UI must NOT display FX-converted prices as "real" when fx_state
    is REFUSED or UNKNOWN. The View Model exposes `fx_state` directly so
    the UI can label accordingly.
    """
    fx_state: str
    base_currency: Optional[str]
    quote_currency: Optional[str]
    rate: Optional[float]
    rate_date: Optional[str]
    provider: Optional[str]
    retrieved_at: Optional[str]
    verification_status: Optional[str]
    failure_kind: Optional[str]


@dataclass(frozen=True)
class PassengerParityView:
    """
    Surfaces canonical parity state. UNKNOWN must NOT become MATCH.
    """
    parity_status: str
    passenger_count: Optional[int]
    passenger_types: Optional[list]
    cabin: Optional[str]
    warnings: Optional[list]


@dataclass(frozen=True)
class BaselineView:
    """
    Surfaces the canonical baseline classification.

    Possible canonical values (per docs/baseline_canonicalization_v1_2_4.md):
      * canonical_direct
      * conventional_hub
      * secondary_entry
      * outer_port_positioning
      * same_airport_pair
      * fictional_no_fly

    Forbidden display labels: cheapest, first, best, Jev survivor.
    """
    baseline_class: Optional[str]
    baseline_candidate_id: Optional[str]
    baseline_eligibility: Optional[str]
    retrieved_at: Optional[str]
    verification_status: Optional[str]


@dataclass(frozen=True)
class ComparisonView:
    """
    Surfaces canonical ComparisonEvidence.

    `comparability_status` is the 5-state enum from comparison_engine:
      HARD_COMPARABLE / SOFT_COMPARABLE / UNKNOWN / NOT_COMPARABLE / REFUSED
    """
    comparability_status: str
    parity_status: Optional[str]
    fx_state: Optional[str]
    price_a: Optional[float]
    price_b: Optional[float]
    normalized_price_a: Optional[float]
    normalized_price_b: Optional[float]
    comparison_currency: Optional[str]
    delta: Optional[float]
    delta_percentage: Optional[float]
    provider_disagreement: Optional[bool]
    comparison_reasons: Optional[list]
    refusal_reasons: Optional[list]
    unknown_reasons: Optional[list]
    warnings: Optional[list]


@dataclass(frozen=True)
class ArbitrageEvidenceView:
    """
    Surfaces canonical L4 arbitrage state.

    Canonical states (per docs/arbitrage_detection_l4.md):
      NOT_ARBITRAGE, NOT_COMPARABLE, INSUFFICIENT_EVIDENCE,
      POTENTIAL_OPPORTUNITY, EVIDENCE_VERIFIED, VERIFIED_OPPORTUNITY

    The View Model does NOT convert HARD_COMPARABLE to POTENTIAL_OPPORTUNITY.
    It surfaces the exact state from canonical evidence.
    """
    arbitrage_state: str
    arbitrage_id: Optional[str]
    baseline_id: Optional[str]
    comparison_id: Optional[str]
    evidence_maturity: Optional[str]
    price_difference: Optional[float]
    normalized_price_difference: Optional[float]
    percentage_difference: Optional[float]
    provider_independence: Optional[str]
    arbitrage_reasons: Optional[list]
    insufficient_evidence_reasons: Optional[list]
    refusal_reasons: Optional[list]
    unknown_reasons: Optional[list]
    required_for_verification: Optional[list]
    provenance: Optional[dict]
    rule_version: Optional[str]
    retrieved_at: Optional[str]


@dataclass(frozen=True)
class FrictionEvidenceView:
    """
    Surfaces canonical friction observations.

    Each field is True (friction present), False (explicitly absent),
    or None (unknown — never coerced to False).
    """
    airport_change: Optional[bool]
    self_transfer: Optional[bool]
    multi_ticket: Optional[bool]
    positioning: Optional[bool]
    outer_port: Optional[bool]
    long_connection: Optional[bool]
    schedule_uncertainty: Optional[bool]
    baggage_uncertainty: Optional[bool]
    recheck_required: Optional[bool]
    overnight: Optional[bool]
    tight_connection: Optional[bool]


@dataclass(frozen=True)
class MissingEvidenceView:
    """
    Honest list of what is missing/unverified for this candidate.

    Derived from canonical evidence (NOT from the dashboard not loading
    the file). Per spec §17: "Do not call something 'unverified' merely
    because the dashboard does not load it."
    """
    operating_schedule_not_verified: bool
    fare_rules_unavailable: bool
    baggage_conditions_unknown: bool
    bookability_not_established: bool
    real_provider_evidence_unavailable: bool
    baseline_unavailable: bool
    comparison_unavailable: bool
    fx_unavailable: bool


# ----------------------------------------------------------------------
# Main view object
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class DashboardCandidateView:
    """
    Immutable presentation object for one candidate.

    Construction is via `from_canonical_evidence()` which joins
    canonical evidence files by candidate_id. If a candidate has no
    evidence, the corresponding *_view field is None (and downstream
    UI labels must display "Evidence unavailable" or similar).
    """
    identity: IdentityView
    discovery: DiscoveryView
    schedule: Optional[ScheduleEvidenceView]
    price: PriceEvidenceView
    fx: Optional[FXEvidenceView]
    parity: Optional[PassengerParityView]
    baseline: Optional[BaselineView]
    comparison: Optional[ComparisonView]
    arbitrage: Optional[ArbitrageEvidenceView]
    friction: FrictionEvidenceView
    missing: MissingEvidenceView
    evidence_available: bool  # True iff at least one canonical evidence record was joined

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict (presentation-safe)."""
        return asdict(self)


# ----------------------------------------------------------------------
# Allowed canonical enum sets (defensive coercion)
# ----------------------------------------------------------------------
_VERIFICATION_STATUS = {"UNKNOWN", "ESTIMATED", "DATABASE", "LIVE", "VERIFIED"}
_ARBITRAGE_STATES = {
    "NOT_ARBITRAGE", "NOT_COMPARABLE", "INSUFFICIENT_EVIDENCE",
    "POTENTIAL_OPPORTUNITY", "EVIDENCE_VERIFIED", "VERIFIED_OPPORTUNITY",
}
_COMPARISON_STATES = {"HARD_COMPARABLE", "SOFT_COMPARABLE", "UNKNOWN", "NOT_COMPARABLE", "REFUSED"}
_PARITY_STATES = {"MATCH", "NON_PARITY", "UNKNOWN", "REFUSED", "NOT_COMPARABLE"}
_FX_STATES = {"PROVIDED", "REFUSED", "UNKNOWN", "IDENTITY", "APPLIED"}
_FRESHNESS_BUCKETS = {"RECENT", "WARM", "COLD", "EXPIRED"}
_EVIDENCE_MATURITY = {"OBSERVED", "PARTIALLY_SUPPORTED", "SUPPORTED", "VERIFIED"}


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------
class _EvidenceIndex:
    """Internal helper to look up evidence records by candidate_id.

    Supports multiple join keys for backward compatibility with different
    evidence file schemas:
      * candidate_id (most common)
      * candidate_a_id (for pair-keyed evidence like comparison, parity)
      * baseline_candidate_id (for baseline evidence)
    """

    def __init__(self, evidences: list, id_keys: Optional[Tuple[str, ...]] = None,
                 extra_key_extractors: Optional[List] = None) -> None:
        # Default: try multiple keys so an evidence record with any of them
        # is indexable by the matching id.
        self._by_id: Dict[str, dict] = {}
        keys = id_keys or (
            "candidate_id",
            "candidate_a_id",
            "baseline_candidate_id",
        )
        extractors = extra_key_extractors or []
        for e in evidences:
            if not isinstance(e, dict):
                continue
            indexed = False
            for k in keys:
                v = e.get(k)
                if isinstance(v, str):
                    self._by_id.setdefault(v, e)
                    indexed = True
                    break
            # Some evidence files nest the candidate_id inside candidate_canonical.
            if not indexed:
                cc_raw = e.get("candidate_canonical")
                if isinstance(cc_raw, dict):
                    cc_id = cc_raw.get("candidate_id")
                    if isinstance(cc_id, str):
                        self._by_id.setdefault(cc_id, e)
                        indexed = True
            # Synthetic keys (e.g., FX currency pair)
            if not indexed:
                for ext in extractors:
                    try:
                        synthetic = ext(e)
                    except Exception:
                        synthetic = None
                    if isinstance(synthetic, str):
                        self._by_id.setdefault(synthetic, e)
                        break

    def get(self, candidate_id: Optional[str]) -> Optional[dict]:
        if not isinstance(candidate_id, str):
            return None
        return self._by_id.get(candidate_id)

    def all_by_id(self) -> Dict[str, dict]:
        return dict(self._by_id)


def _build_schedule_view(sched: Optional[dict]) -> Optional[ScheduleEvidenceView]:
    if not isinstance(sched, dict):
        return None
    # L4 arbitrage evidence uses schedule_evidence_refs.candidate structure
    # while schedule_evidence_v1_2_1.json uses a flatter structure. Handle both.
    inner = sched.get("schedule_evidence") if isinstance(sched.get("schedule_evidence"), dict) else sched
    vs = _as_label(inner.get("verification_status"), _VERIFICATION_STATUS, UNKNOWN)
    return ScheduleEvidenceView(
        verification_status=vs,
        schedule_status=_opt_str(inner.get("schedule_status")),
        schedule_source=_opt_str(inner.get("schedule_source")),
        freshness=_opt_str(inner.get("freshness")),
        retrieved_at=_as_iso(inner.get("retrieved_at")),
        provider=_opt_str(inner.get("provider")),
        provider_mode=_opt_str(inner.get("provider_mode")),
        warnings=_opt_list(sched.get("warnings")),
    )


def _build_price_view(price: Optional[dict], legacy_total_cost_twd: Optional[int],
                       legacy_savings_pct: Optional[float]) -> PriceEvidenceView:
    if not isinstance(price, dict):
        return PriceEvidenceView(
            providers=[],
            verification_status=UNKNOWN,
            retrieved_at=None,
            failure_kind=None,
            failure_reason=None,
            warnings=None,
            legacy_total_cost_twd=legacy_total_cost_twd,
            legacy_savings_pct=legacy_savings_pct,
        )
    # Build a single ProviderPriceView from the canonical record.
    # (Currently price_evidence.json emits one provider per candidate;
    # if the future schema supports multiple, the View Model will need
    # to iterate a providers[] field here.)
    ppv = ProviderPriceView(
        provider=_opt_str(price.get("provider")),
        provider_mode=_opt_str(price.get("provider_mode")),
        price=_opt_num(price.get("total_price")) if price.get("total_price") is not None else _opt_num(price.get("price")),
        currency=_opt_str(price.get("currency")),
        verification_status=_opt_str(price.get("verification_status")),
        retrieved_at=_as_iso(price.get("retrieved_at")),
        freshness_bucket=_as_label(price.get("freshness_bucket"), _FRESHNESS_BUCKETS, UNKNOWN)
                          if isinstance(price.get("freshness_bucket"), str) else None,
        ticket_count=_opt_int(price.get("ticket_count")),
        is_single_ticket=price.get("is_single_ticket") if isinstance(price.get("is_single_ticket"), bool) else None,
        baggage=None,  # baggage is at the L4 level, not price-evidence level
        cabin=None,
    )
    return PriceEvidenceView(
        providers=[ppv],
        verification_status=_as_label(price.get("verification_status"), _VERIFICATION_STATUS, UNKNOWN),
        retrieved_at=_as_iso(price.get("retrieved_at")),
        failure_kind=_opt_str(price.get("failure_kind")),
        failure_reason=_opt_str(price.get("failure_reason")),
        warnings=_opt_list(price.get("warnings")),
        legacy_total_cost_twd=legacy_total_cost_twd,
        legacy_savings_pct=legacy_savings_pct,
    )


def _build_fx_view(fx: Optional[dict]) -> Optional[FXEvidenceView]:
    if not isinstance(fx, dict):
        return None
    # fx_evidence_v1_2_2.json nests the canonical fields under "fx_evidence".
    inner_raw = fx.get("fx_evidence")
    inner: Dict[str, Any] = inner_raw if isinstance(inner_raw, dict) else fx
    return FXEvidenceView(
        fx_state=_as_label(fx.get("fx_state"), _FX_STATES, UNKNOWN),
        base_currency=_opt_str(inner.get("base_currency")) or _opt_str(fx.get("base")),
        quote_currency=_opt_str(inner.get("quote_currency")) or _opt_str(fx.get("quote")),
        rate=_opt_num(inner.get("rate")) or _opt_num(fx.get("rate")),
        rate_date=_as_iso(inner.get("rate_date")) or _opt_str(inner.get("rate_date")) or _as_iso(fx.get("rate_date")),
        provider=_opt_str(inner.get("provider")) or _opt_str(fx.get("provider")),
        retrieved_at=_as_iso(inner.get("retrieved_at")) or _as_iso(fx.get("retrieved_at")),
        verification_status=_as_label(
            inner.get("verification_status"), _VERIFICATION_STATUS, UNKNOWN
        ) or _as_label(fx.get("verification_status"), _VERIFICATION_STATUS, UNKNOWN),
        failure_kind=_opt_str(inner.get("failure_kind")) or _opt_str(fx.get("failure_kind")),
    )


def _build_parity_view(parity: Optional[dict]) -> Optional[PassengerParityView]:
    if not isinstance(parity, dict):
        return None
    # parity_status is a scalar at the top level in parity_evidence_v1_2_3.json
    raw_status = parity.get("parity_status")
    if isinstance(raw_status, list) and raw_status:
        raw_status = raw_status[0]
    ps = _as_label(raw_status, _PARITY_STATES, UNKNOWN)

    # dimension_results.passenger_count and .passenger_type_composition
    # contain per-candidate-a/b values. We surface the "a" side.
    dim_raw = parity.get("dimension_results")
    dim: Dict[str, Any] = dim_raw if isinstance(dim_raw, dict) else {}

    pc_raw = dim.get("passenger_count")
    pc: Dict[str, Any] = pc_raw if isinstance(pc_raw, dict) else {}
    passenger_count = _opt_int(pc.get("a")) if pc.get("known") else None

    ptc_raw = dim.get("passenger_type_composition")
    ptc: Dict[str, Any] = ptc_raw if isinstance(ptc_raw, dict) else {}
    passenger_types = _opt_list(ptc.get("a")) if ptc.get("known") else None

    cabin_raw = dim.get("cabin")
    cabin: Dict[str, Any] = cabin_raw if isinstance(cabin_raw, dict) else {}
    cabin_str = _opt_str(cabin.get("a")) if cabin.get("known") else None

    return PassengerParityView(
        parity_status=ps,
        passenger_count=passenger_count,
        passenger_types=passenger_types,
        cabin=cabin_str,
        warnings=_opt_list(parity.get("warnings")),
    )


def _build_baseline_view(baseline: Optional[dict]) -> Optional[BaselineView]:
    if not isinstance(baseline, dict):
        return None
    # baseline_evidence_v1_2_4.json nests the candidate id under
    # baseline_eligibility.baseline_candidate_id (or in candidate_canonical).
    be_raw = baseline.get("baseline_eligibility")
    be: Dict[str, Any] = be_raw if isinstance(be_raw, dict) else {}
    cc_raw = baseline.get("candidate_canonical")
    cc: Dict[str, Any] = cc_raw if isinstance(cc_raw, dict) else {}

    # canonical_baselines is the list of available baseline classes.
    # Pick the first canonical baseline as the "baseline class".
    cb_list_raw = baseline.get("canonical_baselines")
    cb_list: List[Dict[str, Any]] = cb_list_raw if isinstance(cb_list_raw, list) else []

    # Prefer the first ELIGIBLE baseline (per baseline_eligibility.baseline_classes).
    bc_class = None
    be_classes_raw = be.get("baseline_classes") if isinstance(be.get("baseline_classes"), list) else []
    for entry in be_classes_raw:
        if isinstance(entry, dict) and entry.get("eligibility") == "ELIGIBLE":
            bc_class = _opt_str(entry.get("baseline_class"))
            if bc_class:
                break
    # Fallback: first canonical baseline's class
    if not bc_class and cb_list:
        first = cb_list[0]
        if isinstance(first, dict):
            bc_class = _opt_str(first.get("baseline_class"))
    # Fallback: from baseline_eligibility dict
    if not bc_class:
        bc_class = (
            _opt_str(be.get("baseline_class"))
            or _opt_str(be.get("eligibility"))
            or _opt_str(baseline.get("baseline_class"))
        )

    # baseline_candidate_id: pull from canonical_baselines[0].candidate_binding
    bc_id = None
    if cb_list and isinstance(cb_list[0], dict):
        cb0 = cb_list[0]
        cand_binding = cb0.get("candidate_binding")
        if isinstance(cand_binding, dict):
            bc_id = _opt_str(cand_binding.get("candidate_id"))
    if not bc_id:
        bc_id = (
            _opt_str(be.get("baseline_candidate_id"))
            or _opt_str(be.get("candidate_id"))
            or _opt_str(cc.get("candidate_id"))
            or _opt_str(baseline.get("candidate_id"))
        )

    return BaselineView(
        baseline_class=bc_class,
        baseline_candidate_id=bc_id,
        baseline_eligibility=_opt_str(baseline.get("baseline_eligibility_summary")),
        retrieved_at=_as_iso(baseline.get("retrieved_at")),
        verification_status=_as_label(baseline.get("verification_status"), _VERIFICATION_STATUS, UNKNOWN),
    )


def _build_comparison_view(comparison: Optional[dict]) -> Optional[ComparisonView]:
    if not isinstance(comparison, dict):
        return None
    return ComparisonView(
        comparability_status=_as_label(comparison.get("comparability_status"), _COMPARISON_STATES, UNKNOWN),
        parity_status=_opt_str(comparison.get("parity_status")) if not isinstance(comparison.get("parity_status"), list)
                       else (comparison["parity_status"][0] if comparison["parity_status"] else None),
        fx_state=_as_label(comparison.get("fx_state"), _FX_STATES, UNKNOWN),
        price_a=_opt_num(comparison.get("price_a")),
        price_b=_opt_num(comparison.get("price_b")),
        normalized_price_a=_opt_num(comparison.get("normalized_price_a")),
        normalized_price_b=_opt_num(comparison.get("normalized_price_b")),
        comparison_currency=_opt_str(comparison.get("comparison_currency")),
        delta=_opt_num(comparison.get("delta")),
        delta_percentage=_opt_num(comparison.get("delta_percentage")),
        provider_disagreement=comparison.get("provider_disagreement")
                              if isinstance(comparison.get("provider_disagreement"), bool) else None,
        comparison_reasons=_opt_list(comparison.get("comparison_reasons")),
        refusal_reasons=_opt_list(comparison.get("refusal_reasons")),
        unknown_reasons=_opt_list(comparison.get("unknown_reasons")),
        warnings=_opt_list(comparison.get("warnings")),
    )


def _build_arbitrage_view(arb: Optional[dict]) -> Optional[ArbitrageEvidenceView]:
    if not isinstance(arb, dict):
        return None
    return ArbitrageEvidenceView(
        arbitrage_state=_as_label(arb.get("arbitrage_state"), _ARBITRAGE_STATES, UNKNOWN),
        arbitrage_id=_opt_str(arb.get("arbitrage_id")),
        baseline_id=_opt_str(arb.get("baseline_id")),
        comparison_id=_opt_str(arb.get("comparison_id")),
        evidence_maturity=_as_label(arb.get("evidence_maturity"), _EVIDENCE_MATURITY, UNKNOWN)
                            if isinstance(arb.get("evidence_maturity"), str) else None,
        price_difference=_opt_num(arb.get("price_difference")),
        normalized_price_difference=_opt_num(arb.get("normalized_price_difference")),
        percentage_difference=_opt_num(arb.get("percentage_difference")),
        provider_independence=_opt_str(arb.get("provider_independence")),
        arbitrage_reasons=_opt_list(arb.get("arbitrage_reasons")),
        insufficient_evidence_reasons=_opt_list(arb.get("insufficient_evidence_reasons")),
        refusal_reasons=_opt_list(arb.get("refusal_reasons")),
        unknown_reasons=_opt_list(arb.get("unknown_reasons")),
        required_for_verification=_opt_list(arb.get("required_for_verification")),
        provenance=_opt_dict(arb.get("provenance")),
        rule_version=_opt_str(arb.get("rule_version")),
        retrieved_at=_as_iso(arb.get("retrieved_at")) or _as_iso(arb.get("trace_at")),
    )


def _build_friction_view(opt: dict) -> FrictionEvidenceView:
    """
    Derive friction from the canonical candidate dict.

    Per spec §16: each field is True (present), False (explicitly absent),
    or None (unknown — never coerced to False).
    """
    def _bool_or_none(v: Any) -> Optional[bool]:
        if isinstance(v, bool):
            return v
        return None

    # multi_ticket / outer_port / positioning / self_transfer live at the
    # candidate top level. airport_change is per-segment.
    segs = opt.get("segments") if isinstance(opt.get("segments"), list) else []
    airport_change = None
    for s in segs:
        if isinstance(s, dict) and s.get("airport_change") is True:
            airport_change = True
            break
        if isinstance(s, dict) and s.get("airport_change") is False:
            airport_change = False
            # don't break — keep scanning; if any segment has True, that's authoritative

    # overnight / tight_connection / long_connection are not in current canonical
    # data; they stay None (UNKNOWN) rather than False.

    return FrictionEvidenceView(
        airport_change=airport_change,
        self_transfer=_bool_or_none(opt.get("self_transfer")),
        multi_ticket=_bool_or_none(opt.get("multi_ticket")),
        positioning=_bool_or_none(opt.get("positioning_flight")),
        outer_port=_bool_or_none(opt.get("outer_port_flag")) if "outer_port_flag" in opt else None,
        long_connection=None,
        schedule_uncertainty=None,
        baggage_uncertainty=None,
        recheck_required=None,
        overnight=None,
        tight_connection=None,
    )


def _build_missing_view(
    has_schedule: bool,
    has_price: bool,
    has_fx: bool,
    has_parity: bool,
    has_baseline: bool,
    has_comparison: bool,
    has_arbitrage: bool,
    schedule_v: Optional[ScheduleEvidenceView],
    price_v: PriceEvidenceView,
    comparison_v: Optional[ComparisonView],
    fx_v: Optional[FXEvidenceView],
) -> MissingEvidenceView:
    """
    Build an honest list of what is missing/unverified.

    Rules (per spec §17):
      * Only flag if canonical evidence actually supports it.
      * Do not invent warnings.
      * Do not call something "unverified" merely because the dashboard
        doesn't load it.

    Evidence-availability flags use the canonical record's presence.
    "Unverified" flags use the canonical verification_status (e.g.,
    a schedule record with verification_status=LIVE is verified; one
    with verification_status=ESTIMATED or UNKNOWN is not).
    """
    sched_not_verified = False
    if schedule_v is not None:
        sched_not_verified = schedule_v.verification_status in ("UNKNOWN", "ESTIMATED")

    real_provider_unavailable = False
    if price_v.providers:
        for p in price_v.providers:
            if p.provider_mode in (None, "mock", "mock_duffel", "mock_kiwi", "estimated", "unknown"):
                real_provider_unavailable = True
                break
            if p.verification_status not in ("LIVE", "VERIFIED"):
                real_provider_unavailable = True
                break

    baggage_unknown = False  # baggage field not currently in canonical; keep false until evidence supports it

    bookability_not_established = True  # never bookable in current architecture (L5 not implemented)

    return MissingEvidenceView(
        operating_schedule_not_verified=sched_not_verified,
        fare_rules_unavailable=True,  # canonical evidence does not expose fare rules in current pipeline
        baggage_conditions_unknown=baggage_unknown,
        bookability_not_established=bookability_not_established,
        real_provider_evidence_unavailable=real_provider_unavailable,
        baseline_unavailable=not has_baseline,
        comparison_unavailable=not has_comparison,
        fx_unavailable=(fx_v is None or fx_v.fx_state in ("UNKNOWN", "REFUSED")),
    )


# ----------------------------------------------------------------------
# Main factory
# ----------------------------------------------------------------------
def _fx_pair_key(ev: dict) -> Optional[str]:
    """Synthesize a stable index key for FX evidence (e.g., 'fx::TWD::EUR')."""
    if not isinstance(ev, dict):
        return None
    base = _opt_str(ev.get("base_currency")) or _opt_str(ev.get("base"))
    quote = _opt_str(ev.get("quote_currency")) or _opt_str(ev.get("quote"))
    if base and quote:
        return f"fx::{base}::{quote}"
    return None


def _find_fx_evidence(fx_idx: _EvidenceIndex, candidate: dict) -> Optional[dict]:
    """
    FX evidence is keyed by currency pair, not candidate_id.

    For each candidate we look up the FX record that matches the
    candidate's currency (legacy from flight_results.json) against
    either the base or quote currency. When multiple records exist we
    take the first match. If none exist we return None — the UI
    must display fx_state=UNKNOWN.
    """
    if not isinstance(candidate, dict):
        return None
    cur = _opt_str(candidate.get("currency"))
    if not cur:
        return None
    for ev in fx_idx.all_by_id().values():
        if not isinstance(ev, dict):
            continue
        base = _opt_str(ev.get("base_currency")) or _opt_str(ev.get("base"))
        quote = _opt_str(ev.get("quote_currency")) or _opt_str(ev.get("quote"))
        if base == cur or quote == cur:
            return ev
    return None


def load_fx_evidence_index(path: Path) -> _EvidenceIndex:
    """
    Specialized loader for FX evidence files.

    FX evidence is keyed by currency pair, not candidate_id. This loader
    indexes records under synthetic keys of the form "fx::BASE::QUOTE".
    The View Model's `_find_fx_evidence` helper then resolves a candidate's
    currency to the matching FX record.
    """
    return load_evidence_index(path, extra_key_extractors=[_fx_pair_key])


def build_view(
    candidate: dict,
    schedule_evidence_index: _EvidenceIndex,
    price_evidence_index: _EvidenceIndex,
    fx_evidence_index: _EvidenceIndex,
    parity_evidence_index: _EvidenceIndex,
    baseline_evidence_index: _EvidenceIndex,
    comparison_evidence_index: _EvidenceIndex,
    arbitrage_evidence_index: _EvidenceIndex,
) -> DashboardCandidateView:
    """
    Build a DashboardCandidateView from a canonical candidate dict + evidence
    indexes. Pure function: deterministic, no side effects.
    """
    cid = _opt_str(candidate.get("id"))

    # Identity
    route = _opt_list(candidate.get("route"))
    origin = None
    destination = None
    if isinstance(route, list) and route:
        origin = _opt_str(route[0])
        destination = _opt_str(route[-1])
    long_haul = candidate.get("long_haul") if isinstance(candidate.get("long_haul"), dict) else {}
    identity = IdentityView(
        candidate_id=cid,
        route=route,
        origin=origin,
        destination=destination,
        travel_date=_opt_str(long_haul.get("depart_date")) or _opt_str(candidate.get("travel_date")),
        return_date=_opt_str(candidate.get("return_date")),
        label=_opt_str(candidate.get("label")),
    )

    # Discovery
    discovery = DiscoveryView(
        discovery_reason=_opt_list(candidate.get("discovery_reason")),
        candidate_family=_opt_str(candidate.get("candidate_type")),
        route_structure="multi_ticket" if candidate.get("multi_ticket") else
                        "positioning" if candidate.get("positioning_flight") else
                        "direct",
    )

    # Evidence lookups
    schedule_rec = schedule_evidence_index.get(cid)
    price_rec = price_evidence_index.get(cid)
    # FX evidence is keyed by currency pair, not candidate_id.
    fx_rec = _find_fx_evidence(fx_evidence_index, candidate)
    parity_rec = parity_evidence_index.get(cid)
    baseline_rec = baseline_evidence_index.get(cid)
    arbitrage_rec = arbitrage_evidence_index.get(cid)
    # Comparison evidence is keyed by candidate_a_id (not candidate_id).
    # The default _EvidenceIndex already supports candidate_a_id as a join key.
    comparison_rec = comparison_evidence_index.get(cid)

    has_schedule = schedule_rec is not None
    has_price = price_rec is not None
    has_fx = fx_rec is not None
    has_parity = parity_rec is not None
    has_baseline = baseline_rec is not None
    has_comparison = comparison_rec is not None
    has_arbitrage = arbitrage_rec is not None

    # Legacy fields (legacy_total_cost_twd, legacy_savings_pct) come from
    # the canonical candidate dict. They are pre-computed in v0.1
    # candidate generation and have no associated provider/freshness.
    legacy_total_cost_twd = _opt_int(candidate.get("total_cost"))
    legacy_savings_pct = _opt_num(candidate.get("savings_pct"))

    schedule_v = _build_schedule_view(schedule_rec)
    price_v = _build_price_view(price_rec, legacy_total_cost_twd, legacy_savings_pct)
    fx_v = _build_fx_view(fx_rec)
    parity_v = _build_parity_view(parity_rec)
    baseline_v = _build_baseline_view(baseline_rec)
    comparison_v = _build_comparison_view(comparison_rec)
    arbitrage_v = _build_arbitrage_view(arbitrage_rec)
    friction_v = _build_friction_view(candidate)
    missing_v = _build_missing_view(
        has_schedule=has_schedule,
        has_price=has_price,
        has_fx=has_fx,
        has_parity=has_parity,
        has_baseline=has_baseline,
        has_comparison=has_comparison,
        has_arbitrage=has_arbitrage,
        schedule_v=schedule_v,
        price_v=price_v,
        comparison_v=comparison_v,
        fx_v=fx_v,
    )

    return DashboardCandidateView(
        identity=identity,
        discovery=discovery,
        schedule=schedule_v,
        price=price_v,
        fx=fx_v,
        parity=parity_v,
        baseline=baseline_v,
        comparison=comparison_v,
        arbitrage=arbitrage_v,
        friction=friction_v,
        missing=missing_v,
        evidence_available=any([has_schedule, has_price, has_fx, has_parity,
                                 has_baseline, has_comparison, has_arbitrage]),
    )


# ----------------------------------------------------------------------
# Loader (presentation-only — does NOT write evidence)
# ----------------------------------------------------------------------
class EvidenceLoadError(Exception):
    """Raised when an evidence file cannot be loaded (file missing, malformed)."""


def load_evidence_index(path: Path, id_keys: Optional[Tuple[str, ...]] = None,
                         extra_key_extractors: Optional[List] = None) -> _EvidenceIndex:
    """
    Load an evidence file from disk and index by candidate_id.

    Returns an empty index (NOT an error) if the file is absent — this is
    the canonical behavior when an evidence stage has not yet run for
    the current artifact. UI will display "Evidence unavailable".

    Handles three shapes:
      1. {"evidences": [...]} — list of evidence records (most common)
      2. {...} (single record with candidate_id) — e.g. arbitrage_evidence_l4.json
      3. [...] — bare list of evidence records

    `id_keys` controls which fields are tried for join. Default tries
    candidate_id, candidate_a_id, baseline_candidate_id, plus
    candidate_canonical.candidate_id (nested).

    `extra_key_extractors` is an optional list of callables:
        extractor(evidence_dict) -> Optional[str]
    Each callable may return a synthetic key (e.g., "fx::TWD::EUR") that
    is also indexed. Used for FX evidence (keyed by currency pair).

    Raises EvidenceLoadError if the file exists but is malformed.
    """
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        return _EvidenceIndex([])
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        raise EvidenceLoadError(f"Failed to parse {path}: {e}") from e

    if isinstance(data, dict):
        # Shape 1: wrapped list
        if isinstance(data.get("evidences"), list):
            evidences = data["evidences"]
        # Shape 2: single record (has candidate_id or candidate_canonical)
        elif (
            "candidate_id" in data
            or "candidate_canonical" in data
            or "candidate_a_id" in data
        ):
            evidences = [data]
        else:
            evidences = []
    elif isinstance(data, list):
        evidences = data
    else:
        evidences = []
    return _EvidenceIndex(
        evidences if isinstance(evidences, list) else [],
        id_keys=id_keys,
        extra_key_extractors=extra_key_extractors,
    )


def load_candidates(path: Path) -> list:
    """Load flight_results.json candidates list (presentation-safe)."""
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        raise EvidenceLoadError(f"flight_results.json not found: {path}")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise EvidenceLoadError(f"flight_results.json root is not a dict: {path}")
    cands = data.get("all_evaluated", [])
    if not isinstance(cands, list):
        return []
    return [c for c in cands if isinstance(c, dict)]


# Lazy import to avoid hard dependency on json when only types are used
import json  # noqa: E402

"""
schedule_intelligence.py — Flight Market Intelligence v1.0

Schedule Database Evidence Layer.

Inputs:
    data/flight_candidates.json (manual candidates)
    OR  data/flight_candidates_generated.json (v0.2.1 auto-discovery output)

Outputs:
    data/schedule_enriched_candidates.json (candidates + schedule evidence per segment)
    data/schedule_trace.json (per-candidate schedule lookup trace)

Data source:
    OpenFlights (airports.dat + routes.dat) — DATABASE evidence only.

Verification status mapping:
    UNKNOWN     →  route is in neither airline nor airport databases
    ESTIMATED   →  route is inferred from existing constant-table lookup (NOT used in v1.0)
    DATABASE    →  route exists in OpenFlights (with at least 1 airline)
    LIVE        →  not produced by v1.0 (would require paid API)
    VERIFIED    →  not produced by v1.0 (would require carrier-direct feed)

CRITICAL: VERIFIED MUST NOT mean BOOKABLE. v1.0 only emits DATABASE / UNKNOWN.

What v1.0 DOES NOT do:
    - No real-time schedule verification
    - No booking-grade evidence
    - No price intelligence
    - No arbitrage scoring
    - No Jev scoring changes
    - No dashboard changes
    - No pipeline integration changes (standalone CLI by design)

What v1.0 DOES do:
    - For each segment: look up the route in OpenFlights routes.dat
    - Set per-segment schedule_source = "database" if route exists, else "unknown"
    - Set per-segment verification_status = "DATABASE" or "UNKNOWN"
    - Aggregate per-candidate schedule_status = SUPPORTED / PARTIAL / UNCERTAIN / UNAVAILABLE
    - Compute connection analysis (overnight, same_airport, tight_connection, self_transfer, missing_schedule)
    - Compute structural signals (alternative_hub, outer_port, positioning, multi_ticket,
      secondary_entry, unusual_routing, tight_connection, overnight_connection, airport_change,
      schedule_uncertain)
    - Emit data/schedule_trace.json with per-candidate lookup record

Backward compatibility:
    - Reads v0.2.1 candidate JSON unchanged
    - Writes NEW candidate JSON (additional fields); original fields preserved
    - Does not modify existing candidate IDs / structure
    - Standalone CLI; can be run independently of run_pipeline.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard")
DATA_DIR = REPO_ROOT / "data"
OPENFLIGHTS_DIR = Path("/Users/aib/.hermes/cache/data/openflights")
AIRPORTS_PATH = OPENFLIGHTS_DIR / "airports.dat"
ROUTES_PATH = OPENFLIGHTS_DIR / "routes.dat"
SCHEDULE_ENRICHED_PATH = DATA_DIR / "schedule_enriched_candidates.json"
SCHEDULE_TRACE_PATH = DATA_DIR / "schedule_trace.json"

OPENFLIGHTS_RETRIEVED_AT = "OpenFlights static snapshot (retrieved by Hermes Schedule Intelligence v1.0)"
OPENFLIGHTS_VERSION_NOTE = "OpenFlights routes.dat/airports.dat — DATABASE evidence only."

VERIFICATION_UNKNOWN = "UNKNOWN"
VERIFICATION_ESTIMATED = "ESTIMATED"
VERIFICATION_DATABASE = "DATABASE"
VERIFICATION_LIVE = "LIVE"
VERIFICATION_VERIFIED = "VERIFIED"  # NEVER emitted by v1.0
ALLOWED_VERIFICATION_STATUSES = {VERIFICATION_UNKNOWN, VERIFICATION_ESTIMATED, VERIFICATION_DATABASE, VERIFICATION_LIVE, VERIFICATION_VERIFIED}

SCHEDULE_STATUS_SUPPORTED = "SUPPORTED"
SCHEDULE_STATUS_PARTIAL = "PARTIAL"
SCHEDULE_STATUS_UNCERTAIN = "UNCERTAIN"
SCHEDULE_STATUS_UNAVAILABLE = "UNAVAILABLE"
ALLOWED_SCHEDULE_STATUSES = {SCHEDULE_STATUS_SUPPORTED, SCHEDULE_STATUS_PARTIAL, SCHEDULE_STATUS_UNCERTAIN, SCHEDULE_STATUS_UNAVAILABLE}


# =============================================================================
# OpenFlights loader
# =============================================================================

def load_openflights_routes() -> set[tuple[str, str]]:
    """Load OpenFlights routes.dat → set of (from_iata, to_iata) tuples.

    Per OpenFlights schema:
      Airline 2-letter (or NULL) code,
      Airline ID,
      Source airport 3-letter (or 4-letter) code,
      Source airport ID,
      Destination 3-letter (or 4-letter) code,
      Destination airport ID,
      Codeshare,
      Stops,
      Equipment

    Returns only non-null airport pairs.
    """
    pairs: set[tuple[str, str]] = set()
    if not ROUTES_PATH.exists():
        sys.stderr.write(f"[warn] OpenFlights routes.dat not found at {ROUTES_PATH}\n")
        return pairs
    with open(ROUTES_PATH, encoding="utf-8") as f:
        for row in csv.reader(f):
            # Index 2 = source IATA, Index 4 = destination IATA
            if len(row) < 5:
                continue
            src = row[2].strip()
            dst = row[4].strip()
            if not src or not dst or src == "\\N" or dst == "\\N":
                continue
            pairs.add((src, dst))
    return pairs


def load_openflights_airports() -> dict[str, dict[str, Any]]:
    """Load OpenFlights airports.dat → { iata_code: airport_metadata }.

    Per OpenFlights schema (no header, fixed columns):
      0: ID, 1: Name, 2: City, 3: Country, 4: IATA, 5: ICAO,
      6: Latitude, 7: Longitude, 8: Altitude, 9: Timezone offset,
      10: DST, 11: Tz database time zone, 12: Type, 13: Source
    """
    airports: dict[str, dict[str, Any]] = {}
    if not AIRPORTS_PATH.exists():
        sys.stderr.write(f"[warn] OpenFlights airports.dat not found at {AIRPORTS_PATH}\n")
        return airports
    with open(AIRPORTS_PATH, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 14:
                continue
            iata = row[4].strip().strip('"')
            icao = row[5].strip().strip('"')
            if not iata or iata == "\\N":
                continue
            airports[iata] = {
                "iata": iata,
                "icao": icao if icao != "\\N" else None,
                "name": row[1].strip('"'),
                "city": row[2].strip('"'),
                "country": row[3].strip('"'),
                "latitude": float(row[6]) if row[6] else None,
                "longitude": float(row[7]) if row[7] else None,
                "timezone": row[11].strip('"') if row[11] != "\\N" else None,
                "type": row[12].strip('"') if len(row) > 12 else None,
            }
    return airports


# =============================================================================
# Schedule evidence (per-segment)
# =============================================================================

def build_segment_schedule(
    segment: dict[str, Any],
    routes_db: set[tuple[str, str]],
    airports_db: dict[str, dict[str, Any]],
    retrieved_at: str,
) -> dict[str, Any]:
    """Build schedule evidence object for one segment.

    NEVER fabricates departure/arrival/airline/aircraft.
    Looks up the route in OpenFlights routes DB.

    Returns:
        {
          "origin": str,
          "destination": str,
          "departure": None | ISO-string,
          "arrival": None | ISO-string,
          "duration_minutes": None | int,
          "operating_carrier": None | str,
          "schedule_source": "openflights_database" | "unknown",
          "retrieved_at": str,
          "verification_status": "DATABASE" | "UNKNOWN",
          "confidence": float,
          "is_in_openflights_database": bool,
          "departure_iata_resolved": bool,
          "destination_iata_resolved": bool,
        }
    """
    origin = (segment.get("from") or "").strip()
    destination = (segment.get("to") or "").strip()
    if not origin or not destination:
        # Missing airport codes → explicit UNKNOWN with reason
        return {
            "origin": origin or None,
            "destination": destination or None,
            "departure": None,
            "arrival": None,
            "duration_minutes": None,
            "operating_carrier": None,
            "schedule_source": "unknown",
            "retrieved_at": retrieved_at,
            "verification_status": VERIFICATION_UNKNOWN,
            "confidence": 0.0,
            "is_in_openflights_database": False,
            "departure_iata_resolved": False,
            "destination_iata_resolved": False,
            "missing_reason": "missing_airport_codes",
        }

    in_db = (origin, destination) in routes_db
    src_resolved = origin in airports_db
    dst_resolved = destination in airports_db

    # Confidence is derived purely from coverage, NOT from precision
    confidence = 0.0
    if in_db:
        confidence += 0.5
    if src_resolved:
        confidence += 0.25
    if dst_resolved:
        confidence += 0.25

    if in_db:
        return {
            "origin": origin,
            "destination": destination,
            "departure": None,  # OpenFlights has no scheduled times
            "arrival": None,
            "duration_minutes": None,  # do not infer from elsewhere
            "operating_carrier": None,  # OpenFlights has carriers per route, but we don't claim assignment
            "schedule_source": "openflights_database",
            "retrieved_at": retrieved_at,
            "verification_status": VERIFICATION_DATABASE,
            "confidence": round(confidence, 3),
            "is_in_openflights_database": True,
            "departure_iata_resolved": src_resolved,
            "destination_iata_resolved": dst_resolved,
            "openflights_route_exists": True,
        }
    else:
        return {
            "origin": origin,
            "destination": destination,
            "departure": None,
            "arrival": None,
            "duration_minutes": None,
            "operating_carrier": None,
            "schedule_source": "unknown",
            "retrieved_at": retrieved_at,
            "verification_status": VERIFICATION_UNKNOWN,
            "confidence": round(confidence, 3),
            "is_in_openflights_database": False,
            "departure_iata_resolved": src_resolved,
            "destination_iata_resolved": dst_resolved,
            "missing_reason": "route_not_in_openflights_database",
        }


# =============================================================================
# Connection analysis
# =============================================================================

def analyze_connection(prev_seg: dict[str, Any], next_seg: dict[str, Any], airports_db: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compute connection-time analysis between two sequential segments.

    Returns structured fields WITHOUT guessing values:
        {
          "connection_time_min": None | int,    # not computable from OpenFlights
          "overnight_connection": False,         # cannot determine from schedule data
          "same_airport": bool,
          "airport_change": bool,
          "tight_connection": False,             # cannot determine from schedule data
          "self_transfer": bool,
          "missing_schedule": bool,
        }

    Note: OpenFlights routes.dat does not contain scheduled departure/arrival times.
    Therefore connection_time_min, overnight_connection, and tight_connection
    cannot be computed from this data source alone. We mark them None/False
    rather than guess.
    """
    origin = (prev_seg.get("from") or "").strip()
    destination = (next_seg.get("to") or "").strip()
    via = (prev_seg.get("to") or "").strip()
    next_origin = (next_seg.get("from") or "").strip()

    # The layover airport is prev_seg.to == next_seg.from
    same_airport = bool(via) and via == next_origin
    if not same_airport:
        # Different arrival vs next departure → impossible connection
        return {
            "connection_time_min": None,
            "overnight_connection": False,
            "same_airport": False,
            "airport_change": False,
            "tight_connection": False,
            "self_transfer": False,
            "missing_schedule": True,
            "missing_reason": "non_contiguous_segments",
            "connection_airport_from": via or None,
            "connection_airport_to": next_origin or None,
        }

    # Check whether the connection airport is in OpenFlights (city-level vs airport-level)
    # Same IATA != same airport in case of city/multi-airport sets (LIS=default, NYC has JFK/LGA/EWR)
    # We treat same IATA as same-airport for v1.0 (conservative)
    is_self_transfer = False  # same IATA → not self-transfer by definition
    airport_change = False

    # If via airport is NOT in OpenFlights airport DB → likely a route/ferry station
    # we mark as airport_change = True (heuristic) only if next_origin is also unrecognized
    if via not in airports_db and next_origin not in airports_db:
        # Both unknown — flag for human review
        return {
            "connection_time_min": None,
            "overnight_connection": False,
            "same_airport": True,
            "airport_change": True,
            "tight_connection": False,
            "self_transfer": False,
            "missing_schedule": True,
            "missing_reason": "connection_airport_not_in_openflights",
            "connection_airport_from": via,
            "connection_airport_to": next_origin,
        }

    # Compute timezone diff as a proxy for overnight (NEVER precise without schedule)
    # We deliberately set these to None to avoid false precision.
    return {
        "connection_time_min": None,    # not computable
        "overnight_connection": False,  # not computable
        "same_airport": True,
        "airport_change": False,
        "tight_connection": False,       # not computable
        "self_transfer": False,
        "missing_schedule": False,
        "missing_reason": None,
        "connection_airport_from": via,
        "connection_airport_to": next_origin,
    }


# =============================================================================
# Schedule status (per candidate)
# =============================================================================

def candidate_schedule_status(segments_schedules: list[dict[str, Any]]) -> str:
    """Aggregate segment-level verification_status into candidate-level schedule_status.

    Rules:
      - All segments DATABASE      → SUPPORTED
      - Some DATABASE, none UNKNOWN → PARTIAL (no, some UNKNOWN means partial)
      - Re-examine:
          if all UNKNOWN          → UNAVAILABLE
          if any UNKNOWN          → PARTIAL
          if all DATABASE         → SUPPORTED
          if any has unknown source → UNCERTAIN
    """
    statuses = [s.get("verification_status") for s in segments_schedules]
    if not statuses:
        return SCHEDULE_STATUS_UNAVAILABLE
    unique = set(statuses)
    if unique == {VERIFICATION_DATABASE}:
        return SCHEDULE_STATUS_SUPPORTED
    if unique == {VERIFICATION_UNKNOWN}:
        return SCHEDULE_STATUS_UNAVAILABLE
    return SCHEDULE_STATUS_PARTIAL


# =============================================================================
# Structural signals (purely structural; not arbitrage evidence)
# =============================================================================

def detect_structural_signals(
    candidate: dict[str, Any],
    segments_schedules: list[dict[str, Any]],
    connection_checks: list[dict[str, Any]],
) -> list[str]:
    """Detect STRUCTURAL signals — these are NOT arbitrage confirmations.

    Returns a list of structural signal tags (dedup, sorted). These describe
    the *shape* of the candidate, not whether it's a deal.
    """
    signals: set[str] = set()
    route = candidate.get("route") or []
    candidate_type = candidate.get("candidate_type") or ""
    n_segments = len(segments_schedules)

    # outer_port: either by candidate_type or by routing through known SEA outer ports
    if "outer_port" in candidate_type:
        signals.add("outer_port")
    else:
        outer_ports = {"KUL", "BKK", "SIN", "CGK", "HKT", "MNL"}
        for seg in segments_schedules:
            origin = (seg.get("origin") or "").upper()
            destination = (seg.get("destination") or "").upper()
            if origin in outer_ports or destination in outer_ports:
                signals.add("outer_port")
                break

    # positioning: explicit positioning_flight flag, or candidate_type contains positioning
    if candidate.get("positioning_flight"):
        signals.add("positioning")
    if "positioning" in candidate_type:
        signals.add("positioning")
    # multi_ticket: explicit field or type contains multi_ticket
    if candidate.get("multi_ticket"):
        signals.add("multi_ticket")
    if "multi_ticket" in candidate_type:
        signals.add("multi_ticket")

    # Major hub vs secondary entry (heuristic: SVO/CDG/AMS/FCO/LIS/VIE/CPH/MUC/WAW/DUB/ZRH are "secondary")
    secondary_european = {"LIS", "VIE", "CPH", "MUC", "WAW", "DUB", "ZRH", "AGP"}
    for seg in segments_schedules:
        via = (seg.get("destination") or "").upper()
        if via in secondary_european:
            signals.add("secondary_entry")
            break

    # Alternative hub: any non-conventional hub (IST, DOH, DXB, AUH, RUH)
    conventional_mid_east = {"DOH", "DXB", "AUH", "RUH", "IST"}
    for seg in segments_schedules:
        via = (seg.get("destination") or "").upper()
        if via in conventional_mid_east:
            signals.add("alternative_hub")
            break

    # Unusual routing: more than 2 segments OR non-direct via exotic airport
    if n_segments > 2:
        signals.add("unusual_routing")

    # Airport change (any connection flagged airport_change)
    for c in connection_checks:
        if c.get("airport_change"):
            signals.add("airport_change")
            break

    # Connection characteristics (only computed from data, not guessed)
    for c in connection_checks:
        if c.get("tight_connection"):
            signals.add("tight_connection")
            break
    for c in connection_checks:
        if c.get("overnight_connection"):
            signals.add("overnight_connection")
            break

    # Schedule uncertainty: any segment UNKNOWN
    for seg in segments_schedules:
        if seg.get("verification_status") == VERIFICATION_UNKNOWN:
            signals.add("schedule_uncertain")
            break

    # Sort for deterministic output
    return sorted(signals)


# =============================================================================
# Per-candidate trace record
# =============================================================================

def build_candidate_trace(
    candidate: dict[str, Any],
    segments_schedules: list[dict[str, Any]],
    connection_checks: list[dict[str, Any]],
    schedule_status: str,
    structural_signals: list[str],
) -> dict[str, Any]:
    """Build schedule_trace.json record for one candidate.

    Schema (per spec §9):
        {
          "candidate_id": str,
          "schedule_lookup_attempted": True,
          "schedule_source": "openflights",
          "segments_checked": int,
          "segments_found": int,
          "segments_missing": int,
          "verification_status": DATABASE | UNKNOWN | mixed-encoded-as-string,
          "schedule_status": SUPPORTED | PARTIAL | UNCERTAIN | UNAVAILABLE,
          "connection_checks": list,
          "structural_signals": list,
          "failure_reason": null | str,
        }
    """
    cid = candidate.get("id", "(unknown)")
    n_checked = len(segments_schedules)
    n_found = sum(1 for s in segments_schedules if s.get("verification_status") == VERIFICATION_DATABASE)
    n_missing = n_checked - n_found

    # Aggregate verification status across segments
    distinct_vs = sorted({s.get("verification_status") for s in segments_schedules if s.get("verification_status")}, key=str)
    if len(distinct_vs) == 1:
        agg_vs = distinct_vs[0]
    elif len(distinct_vs) > 1:
        agg_vs = "MIXED(" + "|".join(distinct_vs) + ")"
    else:
        agg_vs = VERIFICATION_UNKNOWN

    failure_reason = None
    if n_checked == 0:
        failure_reason = "no_segments_in_candidate"
    elif n_missing == n_checked:
        failure_reason = "all_segments_unknown_in_openflights"

    return {
        "candidate_id": cid,
        "schedule_lookup_attempted": True,
        "schedule_source": "openflights",
        "segments_checked": n_checked,
        "segments_found": n_found,
        "segments_missing": n_missing,
        "verification_status": agg_vs,
        "schedule_status": schedule_status,
        "connection_checks": connection_checks,
        "structural_signals": structural_signals,
        "failure_reason": failure_reason,
    }


# =============================================================================
# Main enrichment
# =============================================================================

def enrich_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Apply schedule intelligence to each candidate.

    Returns:
        (enriched_candidates, trace_records, summary)
    """
    t0 = time.time()
    routes_db = load_openflights_routes()
    airports_db = load_openflights_airports()
    retrieved_at = datetime.now(timezone.utc).isoformat()

    enriched: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    summary: dict[str, int] = {
        "candidates_received": len(candidates),
        "candidates_with_schedule_evidence": 0,
        "candidates_partial": 0,
        "candidates_unknown": 0,
        "segments_checked": 0,
        "segments_found": 0,
        "segments_missing": 0,
        "connection_checks_performed": 0,
        "structural_signals_detected": 0,
    }

    for cand in candidates:
        # Build per-segment schedule evidence
        segs = cand.get("segments") or []
        seg_schedules: list[dict[str, Any]] = []
        for seg in segs:
            seg_sched = build_segment_schedule(seg, routes_db, airports_db, retrieved_at)
            seg_schedules.append(seg_sched)
            summary["segments_checked"] += 1
            if seg_sched.get("verification_status") == VERIFICATION_DATABASE:
                summary["segments_found"] += 1
            else:
                summary["segments_missing"] += 1

        # Connection checks
        conn_checks: list[dict[str, Any]] = []
        for i in range(len(segs) - 1):
            ck = analyze_connection(segs[i], segs[i + 1], airports_db)
            conn_checks.append(ck)
            summary["connection_checks_performed"] += 1

        # Aggregate schedule_status
        sched_status = candidate_schedule_status(seg_schedules)

        # Structural signals (purely structural)
        signals = detect_structural_signals(cand, seg_schedules, conn_checks)
        summary["structural_signals_detected"] += len(signals)

        # Build trace record
        trace = build_candidate_trace(cand, seg_schedules, conn_checks, sched_status, signals)
        traces.append(trace)

        # Classify for summary counts
        if sched_status == SCHEDULE_STATUS_SUPPORTED:
            summary["candidates_with_schedule_evidence"] += 1
        elif sched_status == SCHEDULE_STATUS_PARTIAL:
            summary["candidates_partial"] += 1
        elif sched_status in (SCHEDULE_STATUS_UNAVAILABLE, SCHEDULE_STATUS_UNCERTAIN):
            summary["candidates_unknown"] += 1

        # Build enriched candidate (preserve original + add new fields)
        enriched_cand = dict(cand)  # shallow copy preserves all original fields
        enriched_cand["schedule_intelligence"] = {
            "applied_at": retrieved_at,
            "data_source": OPENFLIGHTS_VERSION_NOTE,
            "segment_schedules": seg_schedules,
            "schedule_status": sched_status,
            "structural_signals": signals,
        }
        enriched.append(enriched_cand)

    summary["elapsed_seconds"] = int(round(time.time() - t0))  # type: ignore[assignment]
    summary["openflights_routes_loaded"] = len(routes_db)
    summary["openflights_airports_loaded"] = len(airports_db)
    return enriched, traces, summary


def print_observability(summary: dict[str, int]) -> None:
    """Per spec §13: explicit breakdown (no single totals)."""
    print("\n" + "=" * 60, file=sys.stderr)
    print("SCHEDULE INTELLIGENCE v1.0 — OBSERVABILITY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    for k, v in summary.items():
        print(f"  {k:<36} {v}", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Schedule Intelligence v1.0 — OpenFlights DATABASE evidence layer."
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=str(DATA_DIR / "flight_candidates.json"),
        help="Path to candidates JSON (default: data/flight_candidates.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=str(SCHEDULE_ENRICHED_PATH),
        help="Path for enriched candidates output",
    )
    parser.add_argument(
        "--trace",
        type=Path,
        default=str(SCHEDULE_TRACE_PATH),
        help="Path for schedule_trace.json",
    )
    args = parser.parse_args()

    print(f"\nSchedule Intelligence v1.0", file=sys.stderr)
    print(f"  Data source: OpenFlights (DATABASE evidence only)", file=sys.stderr)
    print(f"  airports.dat: {AIRPORTS_PATH}", file=sys.stderr)
    print(f"  routes.dat:   {ROUTES_PATH}", file=sys.stderr)
    print(f"  Input:        {args.input}", file=sys.stderr)

    if not args.input.exists():
        print(f"\n❌ Input not found: {args.input}", file=sys.stderr)
        return 1
    try:
        candidates = json.loads(args.input.read_text())
    except json.JSONDecodeError as e:
        print(f"\n❌ Invalid JSON in input: {e}", file=sys.stderr)
        return 2

    if not isinstance(candidates, list):
        print(f"\n❌ Input must be a JSON array of candidates", file=sys.stderr)
        return 3

    enriched, traces, summary = enrich_candidates(candidates)

    # Write outputs
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(enriched, indent=2, ensure_ascii=False))

    args.trace.parent.mkdir(parents=True, exist_ok=True)
    trace_payload = {
        "trace_at": datetime.now(timezone.utc).isoformat(),
        "data_source": OPENFLIGHTS_VERSION_NOTE,
        "counts": summary,
        "candidates": traces,
    }
    args.trace.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False))

    print(f"\n  Output: {args.output} ({len(enriched)} candidates)", file=sys.stderr)
    print(f"  Trace:  {args.trace} ({len(traces)} records)", file=sys.stderr)
    print_observability(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
candidate_discovery.py — Hermes Flight Arbitrage Hunter v0.1

Given a Travel Mission, generate a list of Flight Candidate routings.
The output JSON is **schema-compatible with the existing Jev evaluator** —
it preserves the existing fields (id, positioning, long_haul, segments,
total_cost, savings_pct, total_elapsed_min, etc.) and only **adds**
backward-compatible metadata fields (candidate_type, positioning_flight,
multi_ticket, price_source, schedule_source, discovery_source, etc.).

NO real-time pricing. NO scraping. NO breaking changes.

Usage:
    python3 candidate_discovery.py mission.json
    python3 candidate_discovery.py mission.json -o output.json
    python3 candidate_discovery.py mission.json --max 40
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# === Routing Families (extensible — add new families without changing engine) ===

ROUTING_FAMILIES = [
    "direct_hub",
    "major_hub",
    "middle_east",
    "southeast_asia_outer_port",
    "northeast_asia",
    "europe_entry",
    "positioning",
    "multi_ticket",
]

# === Reference knowledge (curated; no live data) ===

# Approximate great-circle flight durations (minutes) — used for schedule estimates.
# NOT real-time data. Conservative mid-point estimates.
ESTIMATED_FLIGHT_MIN: dict[tuple[str, str], int] = {
    # TPE → mid-east hubs
    ("TPE", "DOH"): 590, ("TPE", "DXB"): 590, ("TPE", "AUH"): 590, ("TPE", "RUH"): 600, ("TPE", "IST"): 660,
    # TPE → SE Asia outer ports
    ("TPE", "KUL"): 270, ("TPE", "BKK"): 230, ("TPE", "SIN"): 245, ("TPE", "CGK"): 305,
    # TPE → NE Asia
    ("TPE", "ICN"): 165, ("TPE", "NRT"): 195, ("TPE", "HND"): 195,
    # TPE → Europe directly (long-haul)
    ("TPE", "FRA"): 720, ("TPE", "CDG"): 730, ("TPE", "AMS"): 730, ("TPE", "LHR"): 760, ("TPE", "FCO"): 720, ("TPE", "MAD"): 820, ("TPE", "BCN"): 820,
    ("TPE", "LIS"): 815, ("TPE", "ZRH"): 720, ("TPE", "VIE"): 715, ("TPE", "CPH"): 720, ("TPE", "WAW"): 700, ("TPE", "DUB"): 770, ("TPE", "MUC"): 720,
    # Mid-east → Europe
    ("DOH", "MAD"): 425, ("DOH", "BCN"): 410, ("DOH", "FRA"): 360, ("DOH", "CDG"): 380, ("DOH", "AMS"): 380, ("DOH", "FCO"): 320,
    ("DXB", "MAD"): 445, ("DXB", "BCN"): 430, ("DXB", "FRA"): 380, ("DXB", "CDG"): 400, ("DXB", "AMS"): 400, ("DXB", "FCO"): 360,
    ("AUH", "MAD"): 440, ("AUH", "BCN"): 430, ("AUH", "FRA"): 380,
    ("IST", "MAD"): 250, ("IST", "BCN"): 230, ("IST", "FRA"): 175, ("IST", "CDG"): 195,
    ("RUH", "MAD"): 410,
    # Secondary European entries
    ("LIS", "MAD"): 90, ("LIS", "BCN"): 130,
    ("ZRH", "MAD"): 145, ("ZRH", "BCN"): 110,
    ("VIE", "MAD"): 175, ("VIE", "BCN"): 145,
    ("CPH", "MAD"): 180, ("CPH", "BCN"): 165,
    ("WAW", "MAD"): 210, ("WAW", "BCN"): 180,
    ("DUB", "MAD"): 165, ("DUB", "BCN"): 165,
    ("MUC", "MAD"): 145, ("MUC", "BCN"): 115,
    # SE Asia outer-port → Europe (long-haul)
    ("KUL", "DOH"): 480, ("KUL", "DXB"): 420, ("KUL", "FRA"): 700, ("KUL", "IST"): 660, ("KUL", "MAD"): 800, ("KUL", "BCN"): 800,
    ("BKK", "DOH"): 430, ("BKK", "DXB"): 380, ("BKK", "FRA"): 690, ("BKK", "IST"): 640, ("BKK", "MAD"): 800, ("BKK", "BCN"): 800,
    ("SIN", "DOH"): 470, ("SIN", "DXB"): 420, ("SIN", "FRA"): 700, ("SIN", "IST"): 660, ("SIN", "CDG"): 740, ("SIN", "FCO"): 720, ("SIN", "MAD"): 810, ("SIN", "BCN"): 810, ("SIN", "AMS"): 750,
    ("CGK", "DOH"): 530, ("CGK", "DXB"): 470,
    # NE Asia → Europe
    ("ICN", "FRA"): 660, ("ICN", "CDG"): 660, ("ICN", "MAD"): 760, ("ICN", "BCN"): 760, ("ICN", "IST"): 580,
    ("NRT", "FRA"): 700, ("NRT", "CDG"): 720, ("NRT", "LHR"): 680, ("NRT", "IST"): 680,
    # Mid-east → mid-east (rare)
    # Europe secondary → final dest
    ("FRA", "MAD"): 135, ("CDG", "MAD"): 105, ("AMS", "MAD"): 145, ("FCO", "MAD"): 130, ("LIS", "MAD"): 90, ("BCN", "MAD"): 80,
    ("FRA", "BCN"): 110, ("CDG", "BCN"): 95, ("AMS", "BCN"): 130, ("FCO", "BCN"): 105,
}

# Carriers typically used per leg (NOT authoritative — just for ranking/labeling)
# Real Jev evaluation still treats these as soft hints.
CARRIER_HINTS: dict[tuple[str, str], list[str]] = {
    ("TPE", "DOH"): ["QR"], ("TPE", "DXB"): ["EK"], ("TPE", "AUH"): ["EY"],
    ("TPE", "FRA"): ["LH"], ("TPE", "CDG"): ["AF", "KL"],
    ("TPE", "KUL"): ["D7", "MH", "CI"], ("TPE", "BKK"): ["TG", "BR"], ("TPE", "SIN"): ["SQ", "BR", "CI"], ("TPE", "CGK"): ["GA", "CI"],
    ("TPE", "ICN"): ["TW", "KE", "OZ"], ("TPE", "NRT"): ["BR", "CI", "JL"], ("TPE", "HND"): ["BR", "CI", "JL", "NH"],
    ("KUL", "DOH"): ["QR"], ("KUL", "DXB"): ["EK"], ("KUL", "FRA"): ["LH", "MH"], ("KUL", "IST"): ["TK"], ("KUL", "MAD"): ["MH"], ("KUL", "BCN"): ["MH"],
    ("BKK", "DOH"): ["QR"], ("BKK", "DXB"): ["EK"], ("BKK", "FRA"): ["LH", "TG"], ("BKK", "IST"): ["TK"], ("BKK", "MAD"): ["TG"], ("BKK", "BCN"): ["EK", "QR"],
    ("SIN", "FRA"): ["LH", "SQ"], ("SIN", "CDG"): ["AF", "SQ"], ("SIN", "IST"): ["TK", "SQ"], ("SIN", "FCO"): ["AZ", "SQ"], ("SIN", "MAD"): ["SQ"], ("SIN", "BCN"): ["SQ"], ("SIN", "AMS"): ["KL", "SQ"], ("SIN", "DOH"): ["QR"], ("SIN", "DXB"): ["EK"],
    ("CGK", "DOH"): ["QR"], ("CGK", "DXB"): ["EK"],
    ("ICN", "FRA"): ["LH", "KE"], ("ICN", "CDG"): ["AF", "KE"], ("ICN", "MAD"): ["KE"], ("ICN", "BCN"): ["KE"], ("ICN", "IST"): ["TK"],
    ("NRT", "FRA"): ["LH", "JL"], ("NRT", "CDG"): ["AF", "JL"], ("NRT", "LHR"): ["BA", "JL"],
    # mid-east → europe
    ("DOH", "MAD"): ["QR"], ("DOH", "BCN"): ["QR"], ("DOH", "FRA"): ["QR"], ("DOH", "CDG"): ["QR"], ("DOH", "AMS"): ["QR"], ("DOH", "FCO"): ["QR"],
    ("DXB", "MAD"): ["EK"], ("DXB", "BCN"): ["EK"], ("DXB", "FRA"): ["EK"], ("DXB", "CDG"): ["EK"], ("DXB", "AMS"): ["EK"], ("DXB", "FCO"): ["EK"],
    ("AUH", "MAD"): ["EY"], ("AUH", "BCN"): ["EY"], ("AUH", "FRA"): ["EY"],
    ("IST", "MAD"): ["TK"], ("IST", "BCN"): ["TK"], ("IST", "FRA"): ["TK"], ("IST", "CDG"): ["TK"],
    # europe secondary → final
    ("FRA", "MAD"): ["LH", "IB"], ("CDG", "MAD"): ["AF", "IB"], ("AMS", "MAD"): ["KL", "IB"], ("FCO", "MAD"): ["AZ", "IB"], ("LIS", "MAD"): ["TP", "IB"], ("BCN", "MAD"): ["IB"],
    ("FRA", "BCN"): ["LH", "VY"], ("CDG", "BCN"): ["AF", "VY"], ("AMS", "BCN"): ["VY"], ("FCO", "BCN"): ["VY"],
}

# Reference baseline (TPE-direct business-class typical retail)
TPE_DIRECT_BASELINE_TWD = 180_000


def _flight_min(from_airport: str, to_airport: str) -> int | None:
    """Return estimated flight minutes, or None if no estimate available."""
    return ESTIMATED_FLIGHT_MIN.get((from_airport, to_airport))


def _carriers(from_airport: str, to_airport: str) -> list[str]:
    """Return carrier hints for a leg."""
    return CARRIER_HINTS.get((from_airport, to_airport), [])


def _make_segments(legs: list[tuple[str, str]]) -> list[dict]:
    """Convert (from, to) legs to segment dicts compatible with existing schema."""
    segments = []
    for i, (frm, to) in enumerate(legs):
        mins = _flight_min(frm, to)
        carriers = _carriers(frm, to)
        segments.append({
            "carrier": carriers[0] if carriers else None,
            "flight": None,  # Real flight number unknown
            "from": frm,
            "to": to,
            "depart": None,
            "arrive": None,
            "cabin": "J",  # Default business-class for long-haul
            "duration_min": mins,
            "operating_carrier": carriers[0] if carriers else None,
            "aircraft_type": None,  # Unknown at discovery time
            "aircraft_age_yr": None,
            "schedule_source": "estimated",
        })
    return segments


def _positioning_segment(positioning_from: str, outer_port: str) -> dict | None:
    """Build a positioning segment (economy default)."""
    if positioning_from == outer_port:
        return None
    mins = _flight_min(positioning_from, outer_port)
    if mins is None:
        return None
    carriers = _carriers(positioning_from, outer_port)
    return {
        "carrier": carriers[0] if carriers else None,
        "flight": None,
        "from": positioning_from,
        "to": outer_port,
        "depart": None,
        "arrive": None,
        "cabin": "Y",
        "duration_min": mins,
        "operating_carrier": carriers[0] if carriers else None,
        "aircraft_type": None,
        "aircraft_age_yr": None,
        "schedule_source": "estimated",
    }


def _estimate_elapsed(legs: list[tuple[str, str]], mid_east_layover_min: int = 180, generic_layover_min: int = 150) -> int:
    """Rough total elapsed time in minutes (flight + layover assumptions)."""
    total = 0
    for i, (frm, to) in enumerate(legs):
        m = _flight_min(frm, to)
        if m is None:
            return 0
        total += m
        if i < len(legs) - 1:
            # Mid-east hubs assume generous layover; others tighter
            if to in {"DOH", "DXB", "AUH", "RUH", "IST"}:
                total += mid_east_layover_min
            else:
                total += generic_layover_min
    return total


def _build_candidate(
    mission: dict,
    legs: list[tuple[str, str]],
    candidate_type: str,
    family: str,
    is_positioning: bool = False,
    is_multi_ticket: bool = False,
    long_haul_via: str | None = None,
) -> dict:
    """Build a candidate dict compatible with the existing schema.

    Preserves all Jev-required fields. Adds v0.1 metadata fields.
    """
    origin = mission["origin"][0]
    destination = legs[-1][1]

    # Positioning: TPE → outer port (if legs[0][0] is origin and legs[0][1] != origin)
    has_positioning = (legs[0][0] == origin and legs[0][1] != origin and is_positioning)
    if has_positioning:
        outer_port = legs[0][1]
        positioning_legs = [legs[0]]
        long_haul_legs = legs[1:]
    else:
        outer_port = legs[0][0]
        positioning_legs = []
        long_haul_legs = legs

    # Build segments (full chain)
    segments = _make_segments(legs)

    # Compute total elapsed
    elapsed_min = _estimate_elapsed(legs)

    # Build canonical id
    canonical_route = "→".join([a for leg in legs for a in leg])  # or just '>'.join([a for a, _ in legs])
    # Simpler canonical: route as list
    route_list = [legs[0][0]] + [to for _, to in legs]

    # Long-haul carrier (for label/positioning.long_haul)
    long_haul_carriers = _carriers(long_haul_legs[0][0], long_haul_legs[0][1])
    long_haul_main = long_haul_carriers[0] if long_haul_carriers else None

    # Build positioning block (if applicable)
    positioning_block = None
    if has_positioning and positioning_legs:
        p_carriers = _carriers(positioning_legs[0][0], positioning_legs[0][1])
        positioning_block = {
            "from": positioning_legs[0][0],
            "to": positioning_legs[0][1],
            "carrier": p_carriers[0] if p_carriers else None,
            "duration_min": _flight_min(positioning_legs[0][0], positioning_legs[0][1]),
            "cabin": "Y",
        }

    # Build long_haul block (the J-class leg)
    if long_haul_legs:
        long_haul_block = {
            "from": long_haul_legs[0][0],
            "to": long_haul_legs[-1][1],
            "via": long_haul_via,
            "carrier": long_haul_main,
            "duration_min": sum(_flight_min(f, t) or 0 for f, t in long_haul_legs),
            "cabin": "J",
        }
    else:
        long_haul_block = {}

    # Mid-east via (if applicable)
    if long_haul_via is None and len(long_haul_legs) >= 2:
        # Default via = first hub after outer port
        long_haul_via = long_haul_legs[0][1] if len(long_haul_legs) > 1 else None
        long_haul_block["via"] = long_haul_via

    # ID — use a short readable slug
    id_slug = f"AUTO-{family}-{'-'.join(route_list)}-{destination}".replace("→", "-")
    id_slug = id_slug.replace("/", "-").replace(" ", "")

    # Discovery reasons
    reasons = [family]
    if has_positioning:
        reasons.append("outer_port")
    if long_haul_via in {"DOH", "DXB", "AUH", "RUH"}:
        reasons.append("middle_east_hub")
    if is_multi_ticket:
        reasons.append("multi_ticket")
    if any(_ in long_haul_legs[0][0] for _ in ["KUL", "BKK", "SIN", "CGK"]):
        reasons.append("southeast_asia_outer_port")
    reasons.append("potential_arbitrage")

    # Same PNR: True if no positioning flight and single airline all-leg
    same_pnr = (not has_positioning) and (not is_multi_ticket)

    # Cost placeholders (NOT real — explicitly marked unknown)
    positioning_cost = 8000 if has_positioning else 0
    transit_hotel_cost = 2000 if has_positioning else 0
    # Long-haul cost placeholder (heuristic, NOT real)
    long_haul_cost = 54_000 if long_haul_legs else 0

    candidate = {
        # === Existing schema (PRESERVED) ===
        "id": id_slug,
        "label": f"{origin} → {' → '.join(route_list[1:])} ({long_haul_main or 'auto'})",
        "currency": "TWD",
        "positioning_cost": positioning_cost,
        "long_haul_cost": long_haul_cost,
        "transit_hotel_cost": transit_hotel_cost,
        "total_cost": 0,  # Filled below
        "tpe_direct_baseline": TPE_DIRECT_BASELINE_TWD,
        "savings_pct": 0,  # Filled below
        "positioning": positioning_block,
        "long_haul": long_haul_block,
        "segments": segments,
        "same_pnr": same_pnr,
        "interlined_baggage": same_pnr,
        "terminal_change_kul_dxb": False,
        "min_connection_kul_dxb_min": 180 if has_positioning else None,
        "min_connection_dxb_mad_min": 180,
        "total_elapsed_min": elapsed_min,
        "notes": f"v0.1 auto-discovery: {family} | estimated times only",

        # === v0.1 metadata (NEW) ===
        "candidate_type": candidate_type,
        "positioning_flight": has_positioning,
        "multi_ticket": is_multi_ticket,
        "price": None,
        "price_source": "unknown",
        "estimated_total_duration_hours": round(elapsed_min / 60, 1) if elapsed_min else None,
        "discovery_source": "hermes_candidate_discovery_v0.1",
        "discovery_reason": reasons,
        "route": route_list,
        "canonical_route_key": "->".join(route_list),
    }

    # Compute placeholder total_cost (positioning + long-haul + transit)
    candidate["total_cost"] = positioning_cost + long_haul_cost + transit_hotel_cost
    if TPE_DIRECT_BASELINE_TWD:
        savings = (TPE_DIRECT_BASELINE_TWD - candidate["total_cost"]) / TPE_DIRECT_BASELINE_TWD * 100
        candidate["savings_pct"] = round(savings, 1)

    return candidate


# === Routing family generators ===

def _family_direct_hub(mission: dict) -> list[dict]:
    """TPE → major hub → Spain (no positioning flight)."""
    out = []
    for dest in mission["destination"]:
        for via in ["FRA", "IST", "DOH", "DXB", "AUH"]:
            if _flight_min("TPE", via) and _flight_min(via, dest):
                legs = [("TPE", via), (via, dest)]
                out.append(_build_candidate(mission, legs, "direct_hub", "direct_hub", long_haul_via=via))
        # TPE → destination direct (rare but possible)
        if _flight_min("TPE", dest):
            out.append(_build_candidate(mission, [("TPE", dest)], "direct", "direct_hub"))
    return out


def _family_major_hub(mission: dict) -> list[dict]:
    """TPE → single major European hub → Spain (focused European hubs)."""
    out = []
    for dest in mission["destination"]:
        for via in ["CDG", "AMS", "FCO", "LHR", "LIS"]:
            if _flight_min("TPE", via) and _flight_min(via, dest):
                legs = [("TPE", via), (via, dest)]
                out.append(_build_candidate(mission, legs, "major_hub", "major_hub", long_haul_via=via))
    return out


def _family_middle_east(mission: dict) -> list[dict]:
    """TPE → Mid-East hub → Spain."""
    out = []
    for dest in mission["destination"]:
        for via in ["DOH", "DXB", "AUH", "RUH", "IST"]:
            if _flight_min("TPE", via) and _flight_min(via, dest):
                legs = [("TPE", via), (via, dest)]
                out.append(_build_candidate(mission, legs, "middle_east", "middle_east", long_haul_via=via))
    return out


def _family_outer_port(mission: dict) -> list[dict]:
    """TPE → outer-port (positioning flight) → Mid-East or direct → Spain."""
    out = []
    if not mission["preferences"].get("allow_outer_port", True):
        return out
    outer_ports = ["KUL", "BKK", "SIN", "CGK"]
    mid_easts = ["DOH", "DXB", "AUH", "IST"]
    for outer in outer_ports:
        for dest in mission["destination"]:
            for via in mid_easts:
                if _flight_min(outer, via) and _flight_min(via, dest):
                    legs = [("TPE", outer), (outer, via), (via, dest)]
                    out.append(_build_candidate(
                        mission, legs, "outer_port_middle_east", "southeast_asia_outer_port",
                        is_positioning=True, long_haul_via=via,
                    ))
            # Outer port direct to destination
            if _flight_min(outer, dest):
                legs = [("TPE", outer), (outer, dest)]
                out.append(_build_candidate(
                    mission, legs, "outer_port_direct", "southeast_asia_outer_port",
                    is_positioning=True, long_haul_via=dest,
                ))
    return out


def _family_northeast_asia(mission: dict) -> list[dict]:
    """TPE → NE Asia (positioning or via) → Europe → Spain."""
    out = []
    ne_ports = ["ICN", "NRT", "HND"]
    for outer in ne_ports:
        for dest in mission["destination"]:
            # ICN → MAD/BCN direct (KE)
            if outer == "ICN" and _flight_min(outer, dest):
                out.append(_build_candidate(
                    mission, [("TPE", outer), (outer, dest)], "northeast_asia_direct",
                    "northeast_asia", is_positioning=True, long_haul_via=dest,
                ))
            # NE Asia → European hub → destination
            for via in ["FRA", "CDG", "IST"]:
                if _flight_min(outer, via) and _flight_min(via, dest):
                    out.append(_build_candidate(
                        mission, [("TPE", outer), (outer, via), (via, dest)],
                        "northeast_asia_via_europe", "northeast_asia",
                        is_positioning=True, long_haul_via=via,
                    ))
    return out


def _family_europe_entry(mission: dict) -> list[dict]:
    """TPE → secondary European entry → Spain (intra-Europe connection).

    Distinct from `major_hub`: uses SECONDARY entries not in major_hub list.
    These are less-direct but may offer cheaper fares.
    """
    out = []
    # Secondary entries — NOT in major_hub (FRA/CDG/AMS/FCO/LHR)
    secondary_entries = ["LIS", "ZRH", "VIE", "CPH", "WAW", "DUB", "MUC"]
    for dest in mission["destination"]:
        for via in secondary_entries:
            if via == dest:
                continue
            if _flight_min("TPE", via) and _flight_min(via, dest):
                legs = [("TPE", via), (via, dest)]
                out.append(_build_candidate(mission, legs, "europe_entry", "europe_entry", long_haul_via=via))
    return out


def _family_positioning(mission: dict) -> list[dict]:
    """Explicit positioning flight patterns (TPE → KUL → Europe)."""
    out = []
    if not mission["preferences"].get("allow_positioning_flight", True):
        return out
    patterns = [
        ("KUL", ["DOH", "DXB", "FRA", "IST", "AMS"]),
        ("BKK", ["DOH", "DXB", "FRA", "IST"]),
        ("SIN", ["FRA", "CDG", "FCO", "AMS"]),
        ("CGK", ["DOH", "DXB"]),
    ]
    for outer, vias in patterns:
        for dest in mission["destination"]:
            for via in vias:
                if _flight_min(outer, via) and _flight_min(via, dest):
                    legs = [("TPE", outer), (outer, via), (via, dest)]
                    out.append(_build_candidate(
                        mission, legs, "positioning_through_outer",
                        "positioning", is_positioning=True, long_haul_via=via,
                    ))
    return out


def _family_multi_ticket(mission: dict) -> list[dict]:
    """Multi-ticket pattern: separate positioning + main flight.

    Distinct from `_family_positioning`: positioning uses a different outer-port,
    and main flight uses a non-overlapping carrier. Marked as elevated risk.
    """
    out = []
    if not mission["preferences"].get("allow_multi_ticket", True):
        return out
    # Outer-port direct to destination via non-overlapping carrier
    patterns = [
        # (outer_port, main_carrier_code, via, dest)
        ("KUL", "MH", None, "MAD"),       # MH direct KUL→MAD (rare)
        ("BKK", "TG", None, "MAD"),        # TG direct BKK→MAD
        ("SIN", "SQ", None, "MAD"),        # SQ direct SIN→MAD
        ("CGK", "GA", "DPS", "DOH"),       # GA to DPS, then separate ticket to DOH
    ]
    for outer, main_carrier, intermediate, dest in patterns:
        if dest not in mission["destination"]:
            continue
        if intermediate is None:
            # Direct outer-port → dest (different from positioning which had a mid-east)
            if _flight_min(outer, dest):
                legs = [("TPE", outer), (outer, dest)]
                out.append(_build_candidate(
                    mission, legs, "multi_ticket_direct",
                    "multi_ticket", is_positioning=True, is_multi_ticket=True,
                    long_haul_via=dest,
                ))
    return out


# === Main discovery orchestrator ===

FAMILY_GENERATORS = {
    "direct_hub": _family_direct_hub,
    "major_hub": _family_major_hub,
    "middle_east": _family_middle_east,
    "southeast_asia_outer_port": _family_outer_port,
    "northeast_asia": _family_northeast_asia,
    "europe_entry": _family_europe_entry,
    "positioning": _family_positioning,
    "multi_ticket": _family_multi_ticket,
}


def _apply_constraints(candidates: list[dict], mission: dict) -> list[dict]:
    """Apply mission constraints (max stops, max duration, max candidates)."""
    constraints = mission.get("constraints", {})
    max_stops = constraints.get("max_stops", 2)
    max_dur = constraints.get("max_total_duration_hours", 30) * 60
    out = []
    for c in candidates:
        n_stops = len(c["segments"]) - 1
        elapsed = c["total_elapsed_min"] or 0
        if n_stops > max_stops:
            continue
        if max_dur and elapsed > max_dur:
            continue
        out.append(c)
    return out


def _deduplicate(candidates: list[dict]) -> list[dict]:
    """Deduplicate by canonical_route_key AND multi_ticket status.

    Same route but different ticket structure (single vs multi) are kept distinct.
    """
    seen: set[tuple[str, bool]] = set()
    out = []
    for c in candidates:
        key = c["canonical_route_key"]
        multi = c.get("multi_ticket", False)
        dedup_key = (key, multi)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        out.append(c)
    return out


def generate_candidates(mission: dict) -> list[dict]:
    """Generate candidate routings from a Travel Mission."""
    all_candidates: list[dict] = []
    for family_name, generator in FAMILY_GENERATORS.items():
        family_candidates = generator(mission)
        all_candidates.extend(family_candidates)

    # Apply constraints
    all_candidates = _apply_constraints(all_candidates, mission)

    # Deduplicate
    all_candidates = _deduplicate(all_candidates)

    # Sort: multi_ticket FIRST so they survive cap (preserve rare patterns)
    all_candidates.sort(key=lambda c: (
        not c.get("multi_ticket", False),  # True (multi_ticket) first when negated
        c.get("candidate_type", ""),
    ))

    # Cap at max_candidates
    max_candidates = mission.get("constraints", {}).get("max_candidates", 80)
    all_candidates = all_candidates[:max_candidates]

    return all_candidates


# === CLI ===

def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Flight Arbitrage Hunter — Candidate Discovery v0.1")
    parser.add_argument("mission", type=Path, help="Path to mission JSON file")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output JSON path (default: data/flight_candidates_generated.json)")
    parser.add_argument("--max", type=int, default=None, help="Override max_candidates")
    parser.add_argument("--stats", action="store_true", help="Print routing-family stats only")
    args = parser.parse_args()

    if not args.mission.exists():
        print(f"❌ Mission file not found: {args.mission}", file=sys.stderr)
        return 1

    mission = json.loads(args.mission.read_text())
    if args.max:
        mission.setdefault("constraints", {})["max_candidates"] = args.max

    print(f"🛰  candidate discovery started @ {datetime.now().isoformat()}", file=sys.stderr)
    print(f"   mission: {mission.get('mission_id', '(no id)')}", file=sys.stderr)
    print(f"   origin: {mission['origin']} → destination: {mission['destination']}", file=sys.stderr)

    # Generate
    candidates = generate_candidates(mission)

    # Family stats
    family_counts: dict[str, int] = {}
    for c in candidates:
        for r in c.get("discovery_reason", []):
            family_counts[r] = family_counts.get(r, 0) + 1

    print(f"\n✅ Generated {len(candidates)} candidates", file=sys.stderr)
    print(f"\nRouting families:", file=sys.stderr)
    for family in ROUTING_FAMILIES:
        n = family_counts.get(family, 0)
        print(f"  {family:<32} {n:>3}", file=sys.stderr)
    print(f"  (total reason-tag occurrences: {sum(family_counts.values())})", file=sys.stderr)

    # Write output
    output_path = args.output or Path("data/flight_candidates_generated.json")
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(candidates, indent=2, ensure_ascii=False))
    print(f"\n💾 Output: {output_path}", file=sys.stderr)

    if args.stats:
        return 0

    # Print a few examples
    print(f"\nExample candidates (first 3):", file=sys.stderr)
    for c in candidates[:3]:
        print(f"  • {c['id']:<60} family={c['candidate_type']:<25} elapsed={c['estimated_total_duration_hours']}h", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Report generation: CSV export and a TCPA claim summary."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timezone

from .models import Incident
from .tcpa import DISCLAIMER, analyze_all, damages_for_findings

CSV_COLUMNS = [
    "incident_id",
    "received_at",
    "contact_type",
    "from_number",
    "to_number",
    "caller_id_name",
    "to_number_is_cell",
    "is_prerecorded",
    "is_autodialed",
    "on_dnc_registry",
    "prior_consent",
    "opted_out",
    "potential_statutes",
    "base_damages",
    "treble_damages",
    "message_body",
    "notes",
]


def incidents_to_csv(incidents: list[Incident]) -> str:
    """Export incidents to a CSV string with per-incident TCPA findings."""
    findings_by_id = analyze_all(incidents)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for inc in sorted(incidents, key=lambda i: i.received_at):
        findings = findings_by_id.get(inc.id, [])
        base, treble = damages_for_findings(findings)
        writer.writerow(
            [
                inc.id,
                inc.received_at.isoformat(),
                inc.contact_type.value,
                inc.from_number,
                inc.to_number or "",
                inc.caller_id_name or "",
                _tri(inc.to_number_is_cell),
                _tri(inc.is_prerecorded),
                _tri(inc.is_autodialed),
                inc.on_dnc_registry,
                inc.prior_consent,
                inc.opted_out,
                "; ".join(f.statute for f in findings),
                base,
                treble,
                (inc.message_body or "").replace("\n", " ").strip(),
                (inc.notes or "").replace("\n", " ").strip(),
            ]
        )
    return out.getvalue()


def _tri(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def build_claim_report(incidents: list[Incident]) -> dict:
    """Aggregate potential violations and damages, grouped by caller."""
    findings_by_id = analyze_all(incidents)

    per_caller: dict[int, dict] = {}
    grouped: dict[int, list[Incident]] = defaultdict(list)
    for inc in incidents:
        grouped[inc.caller_id].append(inc)

    total_base = 0
    total_treble = 0
    for caller_id, group in grouped.items():
        c_base = 0
        c_treble = 0
        actionable = 0
        statutes: set[str] = set()
        sample = group[0]
        for inc in group:
            findings = findings_by_id.get(inc.id, [])
            if findings:
                actionable += 1
            b, t = damages_for_findings(findings)
            c_base += b
            c_treble += t
            statutes.update(f.statute for f in findings)
        total_base += c_base
        total_treble += c_treble
        per_caller[caller_id] = {
            "caller_id": caller_id,
            "phone_number": sample.from_number,
            "caller_name": sample.caller_id_name,
            "total_incidents": len(group),
            "actionable_incidents": actionable,
            "statutes": sorted(statutes),
            "base_damages": c_base,
            "treble_damages": c_treble,
        }

    return {
        "generated_at": datetime.now(timezone.utc),
        "total_incidents": len(incidents),
        "total_callers": len(grouped),
        "estimated_base_damages": total_base,
        "estimated_treble_damages": total_treble,
        "per_caller": sorted(
            per_caller.values(), key=lambda c: c["treble_damages"], reverse=True
        ),
        "disclaimer": DISCLAIMER,
    }

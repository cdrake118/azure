"""TCPA violation analysis.

This module encodes a *simplified, informational* model of the most common
TCPA theories so the tool can flag which logged incidents look actionable and
give a rough damages estimate. It is not legal advice. The statutory damages
are fixed by the TCPA itself:

* 47 U.S.C. 227(b) -- calls/texts to a cell phone using an automatic telephone
  dialing system (ATDS) or an artificial/prerecorded voice, without prior
  express consent. $500 per violation; up to $1,500 if willful or knowing.

* 47 U.S.C. 227(c) / 47 CFR 64.1200(c) -- more than one telemarketing call/text
  within a 12-month period to a number on the National Do Not Call registry.
  $500 per violation; up to $1,500 if willful or knowing.

* 47 CFR 64.1200(d) -- telemarketer failed to honor your prior do-not-call /
  opt-out request. $500 per violation; up to $1,500 if willful or knowing.

The numbers above are the basis for the constants below.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .models import ContactType, Incident

PER_VIOLATION = 500
WILLFUL_TREBLE = 1500

DISCLAIMER = (
    "This tool organizes facts and provides general, informational estimates "
    "only. It is not legal advice and does not create an attorney-client "
    "relationship. Statutory eligibility, consent, and damages depend on facts "
    "and current case law. Consult a licensed attorney before filing a claim."
)


class Finding:
    """A single potential statutory violation tied to an incident."""

    def __init__(self, statute: str, description: str):
        self.statute = statute
        self.description = description
        self.per_violation = PER_VIOLATION
        self.willful_treble = WILLFUL_TREBLE

    def as_dict(self) -> dict:
        return {
            "statute": self.statute,
            "description": self.description,
            "per_violation": self.per_violation,
            "willful_treble": self.willful_treble,
        }


def _is_telemarketing(incident: Incident) -> bool:
    """Best-effort guess at whether an incident is telemarketing.

    For DNC theories the contact must be telemarketing/solicitation. We treat
    texts, voicemails, and prerecorded calls as telemarketing unless the user
    has explicitly marked prior consent.
    """
    return incident.contact_type in {
        ContactType.text_sms,
        ContactType.voicemail,
        ContactType.prerecorded_call,
        ContactType.live_call,
    }


def analyze_incident(
    incident: Incident, dnc_call_count_12mo: int = 0
) -> list[Finding]:
    """Return the potential TCPA findings for a single incident.

    ``dnc_call_count_12mo`` is the number of contacts from the same caller
    within the trailing 12 months (used for the §227(c) "more than one call"
    requirement). The caller of this function supplies it.
    """
    findings: list[Finding] = []

    # --- 47 U.S.C. 227(b): ATDS / prerecorded to a cell, no consent ---
    if not incident.prior_consent:
        autodialed_or_prerecorded = bool(incident.is_prerecorded) or bool(
            incident.is_autodialed
        )
        # Texts are treated as "calls" under the TCPA. A prerecorded voicemail
        # or an autodialed text to a cell phone is the classic 227(b) claim.
        to_cell = incident.to_number_is_cell is not False  # True or unknown
        if autodialed_or_prerecorded and to_cell:
            findings.append(
                Finding(
                    "47 U.S.C. 227(b)",
                    "Autodialed or prerecorded/artificial-voice contact to a "
                    "cell phone without prior express consent.",
                )
            )

    # --- 47 U.S.C. 227(c) / 64.1200(c): National DNC registry ---
    if (
        incident.on_dnc_registry
        and not incident.prior_consent
        and _is_telemarketing(incident)
        and dnc_call_count_12mo > 1
    ):
        findings.append(
            Finding(
                "47 U.S.C. 227(c) / 47 CFR 64.1200(c)",
                "Telemarketing contact to a number on the National Do Not Call "
                "registry (more than one contact within 12 months).",
            )
        )

    # --- 47 CFR 64.1200(d): failure to honor opt-out ---
    if incident.opted_out and _is_telemarketing(incident):
        findings.append(
            Finding(
                "47 CFR 64.1200(d)",
                "Continued telemarketing contact after a prior do-not-call / "
                "opt-out (e.g. 'STOP') request.",
            )
        )

    return findings


def _dnc_counts_for_caller(incidents: list[Incident]) -> dict[int, int]:
    """For each incident id, count same-caller contacts in the trailing 12 months.

    Used to evaluate the §227(c) "more than one call in 12 months" requirement.
    """
    by_caller: dict[int, list[Incident]] = defaultdict(list)
    for inc in incidents:
        by_caller[inc.caller_id].append(inc)

    counts: dict[int, int] = {}
    window = timedelta(days=365)
    for group in by_caller.values():
        group_sorted = sorted(group, key=lambda i: i.received_at)
        for inc in group_sorted:
            n = sum(
                1
                for other in group_sorted
                if timedelta(0) <= (inc.received_at - other.received_at) <= window
            )
            counts[inc.id] = n
    return counts


def analyze_all(incidents: list[Incident]) -> dict[int, list[Finding]]:
    """Analyze a list of incidents, wiring up the per-caller DNC counts."""
    counts = _dnc_counts_for_caller(incidents)
    result: dict[int, list[Finding]] = {}
    for inc in incidents:
        result[inc.id] = analyze_incident(inc, dnc_call_count_12mo=counts.get(inc.id, 0))
    return result


def damages_for_findings(findings: list[Finding]) -> tuple[int, int]:
    """Return (base, treble) damages for a list of findings."""
    base = sum(f.per_violation for f in findings)
    treble = sum(f.willful_treble for f in findings)
    return base, treble

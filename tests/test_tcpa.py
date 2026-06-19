"""Tests for the TCPA analysis logic."""

from datetime import datetime, timedelta, timezone

from app.models import ContactType, Incident
from app.tcpa import analyze_all, analyze_incident, damages_for_findings


def _incident(**kw):
    defaults = dict(
        id=1,
        caller_id=1,
        # A fixed mid-afternoon time so the time-of-day rule doesn't add a
        # finding unless a test sets received_at explicitly.
        received_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        contact_type=ContactType.text_sms,
        from_number="+15551230000",
        to_number_is_cell=True,
        on_dnc_registry=False,
        prior_consent=False,
        opted_out=False,
        is_prerecorded=None,
        is_autodialed=None,
    )
    defaults.update(kw)
    return Incident(**defaults)


def test_autodialed_text_to_cell_triggers_227b():
    inc = _incident(is_autodialed=True)
    findings = analyze_incident(inc)
    assert any("227(b)" in f.statute for f in findings)


def test_prerecorded_voicemail_triggers_227b():
    inc = _incident(contact_type=ContactType.voicemail, is_prerecorded=True)
    findings = analyze_incident(inc)
    assert any("227(b)" in f.statute for f in findings)


def test_prior_consent_blocks_227b():
    inc = _incident(is_autodialed=True, prior_consent=True)
    findings = analyze_incident(inc)
    assert not any("227(b)" in f.statute for f in findings)


def test_opt_out_triggers_64_1200_d():
    inc = _incident(opted_out=True)
    findings = analyze_incident(inc)
    assert any("64.1200(d)" in f.statute for f in findings)


def test_dnc_requires_more_than_one_call():
    inc = _incident(on_dnc_registry=True)
    # Only one call in the window -> no DNC finding.
    assert not any("227(c)" in f.statute for f in analyze_incident(inc, dnc_call_count_12mo=1))
    # More than one -> DNC finding.
    assert any("227(c)" in f.statute for f in analyze_incident(inc, dnc_call_count_12mo=2))


def test_analyze_all_counts_repeat_callers_in_window():
    now = datetime.now(timezone.utc)
    incidents = [
        _incident(id=1, caller_id=7, received_at=now - timedelta(days=30), on_dnc_registry=True),
        _incident(id=2, caller_id=7, received_at=now, on_dnc_registry=True),
    ]
    results = analyze_all(incidents)
    # The second incident sees a prior contact within 12 months -> DNC applies.
    assert any("227(c)" in f.statute for f in results[2])


def test_old_repeat_outside_window_does_not_count():
    now = datetime.now(timezone.utc)
    incidents = [
        _incident(id=1, caller_id=7, received_at=now - timedelta(days=500), on_dnc_registry=True),
        _incident(id=2, caller_id=7, received_at=now, on_dnc_registry=True),
    ]
    results = analyze_all(incidents)
    assert not any("227(c)" in f.statute for f in results[2])


def test_call_before_8am_flags_time_violation():
    inc = _incident(received_at=datetime(2026, 6, 19, 3, 38, tzinfo=timezone.utc))
    assert any("64.1200(c)(1)" in f.statute for f in analyze_incident(inc))


def test_call_after_9pm_flags_time_violation():
    inc = _incident(received_at=datetime(2026, 6, 17, 22, 5, tzinfo=timezone.utc))
    assert any("64.1200(c)(1)" in f.statute for f in analyze_incident(inc))


def test_midday_call_has_no_time_violation():
    inc = _incident(received_at=datetime(2026, 6, 18, 14, 0, tzinfo=timezone.utc))
    assert not any("64.1200(c)(1)" in f.statute for f in analyze_incident(inc))


def test_9pm_boundary_is_allowed():
    # 9:00 PM exactly is the edge of the permitted window, not a violation.
    inc = _incident(received_at=datetime(2026, 6, 18, 21, 0, tzinfo=timezone.utc))
    assert not any("64.1200(c)(1)" in f.statute for f in analyze_incident(inc))


def test_time_violation_requires_telemarketing():
    inc = _incident(
        contact_type=ContactType.missed_call,
        received_at=datetime(2026, 6, 19, 3, 38, tzinfo=timezone.utc),
    )
    assert not any("64.1200(c)(1)" in f.statute for f in analyze_incident(inc))


def test_prior_consent_blocks_time_violation():
    inc = _incident(
        prior_consent=True,
        received_at=datetime(2026, 6, 19, 3, 38, tzinfo=timezone.utc),
    )
    assert not any("64.1200(c)(1)" in f.statute for f in analyze_incident(inc))


def test_damages_sum():
    inc = _incident(is_autodialed=True, opted_out=True)
    findings = analyze_incident(inc)
    base, treble = damages_for_findings(findings)
    # Two findings: 227(b) + 64.1200(d) = 2 * 500 / 2 * 1500.
    assert base == 1000
    assert treble == 3000

"""Tests for the forwarded-email parser."""

from app.ingest import parse_email
from app.models import ContactType


def test_parse_voicemail_notification():
    body = (
        "You have a new voicemail.\n"
        "From: +1 (555) 123-4567\n"
        "Received: 06/15/2026 09:30 AM\n"
        "Transcript: This is an important message about your car's extended "
        "warranty. Press 1 to speak with a representative.\n"
    )
    parsed = parse_email(body=body, subject="New voicemail")
    assert parsed.from_number == "+15551234567"
    assert parsed.contact_type == ContactType.voicemail
    assert "extended warranty" in parsed.message_body
    assert parsed.received_at is not None
    assert parsed.received_at.hour == 9


def test_parse_text_message():
    body = (
        "New text message from 555-987-6543\n"
        "You have been pre-approved for a $5000 loan. Reply YES to claim."
    )
    parsed = parse_email(body=body)
    assert parsed.from_number == "+15559876543"
    assert parsed.contact_type == ContactType.text_sms
    assert "pre-approved" in parsed.message_body


def test_prerecorded_hint_detected():
    body = "Missed call from (555) 222-3333. This is a prerecorded message."
    parsed = parse_email(body=body)
    assert parsed.is_prerecorded is True


def test_no_number_records_warning():
    parsed = parse_email(body="Some text with no phone number at all.")
    assert parsed.from_number is None
    assert any("phone number" in w for w in parsed.warnings)


def test_labeled_number_preferred_over_body_number():
    # A "From" label should win over an unrelated number elsewhere in the body.
    body = (
        "From: 555-111-2222\n"
        "Call us back at 800-555-0000 for details."
    )
    parsed = parse_email(body=body)
    assert parsed.from_number == "+15551112222"

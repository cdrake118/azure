"""Tests for the forwarded-email parser and the voicemail-screenshot parser."""

from app.ingest import parse_email, parse_voicemail_screenshot
from app.models import ContactType

# OCR text iOS produces from the example voicemail screenshot.
SCREENSHOT_OCR = (
    "5:11\n"
    "8446241325\n"
    "Unknown - Jun 19, 2026 at 3:38 AM\n"
    "00:00 -00:14\n"
    "Add Contact Report Spam\n"
    "Transcript\n"
    "Okay, to go over the details and get this finalized today, please press 2 "
    "If you'd rather not be contacted again. Press 9 to opt out. Just to recap, "
    "press 2 to lock in your approval or 9 to opt out of future calls.\n"
    "Favorites Recents Contacts Keypad Voicemail"
)


def test_screenshot_parses_number():
    assert parse_voicemail_screenshot(SCREENSHOT_OCR).from_number == "+18446241325"


def test_screenshot_parses_timestamp():
    dt = parse_voicemail_screenshot(SCREENSHOT_OCR).received_at
    assert dt is not None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 6, 19, 3, 38)


def test_screenshot_parses_transcript_without_nav_or_chrome():
    transcript = parse_voicemail_screenshot(SCREENSHOT_OCR).transcript
    assert transcript.startswith("Okay, to go over the details")
    assert "opt out of future calls." in transcript
    # The tab-bar words must not bleed into the transcript.
    assert "Keypad" not in transcript
    assert "Add Contact" not in transcript


def test_screenshot_unknown_caller_name_is_dropped():
    assert parse_voicemail_screenshot(SCREENSHOT_OCR).caller_id_name is None


def test_screenshot_named_caller_is_kept():
    ocr = "John's Auto Warranty - Jun 19, 2026 at 3:38 AM\nTranscript\nHello."
    assert parse_voicemail_screenshot(ocr).caller_id_name == "John's Auto Warranty"


def test_screenshot_detects_duration():
    assert parse_voicemail_screenshot(SCREENSHOT_OCR).duration_seconds == 14


def test_screenshot_flags_prerecorded_and_signals():
    parsed = parse_voicemail_screenshot(SCREENSHOT_OCR)
    assert parsed.is_prerecorded is True
    joined = " ".join(parsed.detected_signals).lower()
    assert "press-key menu" in joined
    assert "opt-out" in joined
    assert "approval" in joined  # solicitation keyword


def test_screenshot_empty_text_is_safe():
    parsed = parse_voicemail_screenshot("")
    assert parsed.from_number is None
    assert parsed.is_prerecorded is None
    assert parsed.detected_signals == []


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

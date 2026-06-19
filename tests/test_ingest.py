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


# --- Calibration against real iPhone voicemail screenshots ------------------

SHOT1 = (  # tax-file call, low-confidence transcript, formatted number
    "5:29\n+1 (434) 246-0804\nUnknown - Jun 17, 2026 at 10:05 PM\n"
    "00:00 -00:09\nAdd Contact Report Spam\nTranscript (low confidence)\n"
    "Um, this is Rebecca Turner calling regarding your tax file.\n"
    "Favorites Recents Contacts Keypad Voicemail"
)
SHOT2 = (  # loan offer with spelled-out "press two" and "removed from our list"
    "5:29\n+1 (855) 964-5516\nUnknown - Jun 18, 2026 at 1:10 AM\n"
    "00:00 -00:20\nAdd Contact Report Spam\nTranscript\n"
    "$5000 with monthly payments starting at just $475. We're ready to walk you "
    "through the offer and get the paperwork started today. To speak with a loan "
    "specialist right now, please press two. Or if you'd like to be removed from "
    "our list, please press 9. to repeat, press 2 to be connected with a loan "
    "specialist or\nFavorites Recents Contacts Keypad Voicemail"
)
SHOT3 = (  # bare 10-digit number
    "5:29\n8885843759\nUnknown - Jun 18, 2026 at 6:36 AM\n00:00 -00:14\n"
    "Add Contact Report Spam\nTranscript\n"
    "started today. To speak with a loan specialist right now, please press two. "
    "Or if you'd like to be removed from our list. Please press 9 to repeat, "
    "press 2 to be connected with a loan specialist, or 9 to be removed from our "
    "list.\nFavorites Recents Contacts Keypad Voicemail"
)
SHOT4 = (  # tax resolution, no press menu, callback number in transcript
    "5:28\n+1 (470) 739-4921\nUnknown - Jun 18, 2026 at 9:39 PM\n00:00 -00:35\n"
    "Add Contact Report Spam\nTranscript\n"
    "Hi, this is Kimberly Kennedy with the tax resolution department. Your file "
    "came across my desk for review today, and based on the information I have, I "
    "can help reduce a portion of your current tax obligation, call me at "
    "866-386-4908. I'm not sure if your circumstances have changed recently, but "
    "there may be programs available that could help address certain penalties, "
    "accrued interest, or part of the balance owed. The reason for my call is "
    "that unresolved tax balances can continue to grow over time. Again, call me "
    "at 866-386-4908.\nFavorites Recents Contacts Keypad Voicemail"
)


def test_shot1_number_timestamp_and_low_confidence():
    p = parse_voicemail_screenshot(SHOT1)
    assert p.from_number == "+14342460804"
    assert (p.received_at.month, p.received_at.day, p.received_at.hour) == (6, 17, 22)
    assert p.duration_seconds == 9
    assert p.transcript == "Um, this is Rebecca Turner calling regarding your tax file."
    assert "(low confidence)" not in p.transcript
    joined = " ".join(p.detected_signals).lower()
    assert "low-confidence" in joined
    assert "tax" in joined
    # No phone-tree, so prerecorded stays unknown (honest).
    assert p.is_prerecorded is None


def test_shot2_spelled_out_press_and_removed_from_list():
    p = parse_voicemail_screenshot(SHOT2)
    assert p.from_number == "+18559645516"
    assert (p.received_at.hour, p.received_at.minute) == (1, 10)
    assert p.duration_seconds == 20
    assert p.is_prerecorded is True  # "please press two"
    joined = " ".join(p.detected_signals).lower()
    assert "opt-out" in joined  # "removed from our list"
    assert "loan" in joined


def test_shot3_bare_number_and_press_menu():
    p = parse_voicemail_screenshot(SHOT3)
    assert p.from_number == "+18885843759"
    assert p.is_prerecorded is True
    assert "opt-out" in " ".join(p.detected_signals).lower()


def test_shot4_callback_number_and_no_press_menu():
    p = parse_voicemail_screenshot(SHOT4)
    assert p.from_number == "+14707394921"
    assert (p.received_at.hour, p.received_at.minute) == (21, 39)
    assert p.duration_seconds == 35
    # Personal-sounding message with no phone tree -> prerecorded unknown.
    assert p.is_prerecorded is None
    joined = " ".join(p.detected_signals).lower()
    assert "+18663864908" in joined  # callback number captured
    assert "tax" in joined


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

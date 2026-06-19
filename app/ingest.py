"""Parse forwarded SMS and voicemail notification emails into incident fields.

Carriers and voicemail-to-email services format these notifications very
differently, so this parser is heuristic: it pulls the most likely sender
number, timestamp, and message/transcript body out of free-form text. Anything
it cannot determine is left as ``None`` for the user to fill in. The original
text is always preserved in ``raw_message`` for evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .models import ContactType

# Matches US-style phone numbers in a variety of formats:
#   +1 (555) 123-4567, 555-123-4567, 5551234567, 1.555.123.4567
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})(?!\d)"
)

# Common labels that precede the sender number in carrier emails.
FROM_LABELS = re.compile(
    r"(?:from|caller|sender|received from|new (?:text|message|voicemail) from|"
    r"missed call from)\s*[:\-]?\s*",
    re.IGNORECASE,
)

VOICEMAIL_HINTS = re.compile(
    r"voice\s*mail|voicemail|transcri|new message from|missed call", re.IGNORECASE
)
TEXT_HINTS = re.compile(r"\btext\b|\bsms\b|\bmms\b|message from", re.IGNORECASE)
PRERECORDED_HINTS = re.compile(
    r"prerecorded|pre-recorded|automated|robocall|artificial voice|this is a call",
    re.IGNORECASE,
)

# Try a handful of explicit datetime formats found in notification emails.
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M",
    "%b %d, %Y %I:%M %p",
    "%B %d, %Y %I:%M %p",
    "%a, %d %b %Y %H:%M:%S",
)
_DATE_LINE_RE = re.compile(
    r"(?:received|date|time|sent|on)\s*[:\-]?\s*"
    r"([A-Za-z0-9,:/\s\-]+?(?:AM|PM|[0-9]{2}:[0-9]{2}(?::[0-9]{2})?))",
    re.IGNORECASE,
)


@dataclass
class ParsedContact:
    from_number: str | None = None
    to_number: str | None = None
    contact_type: ContactType = ContactType.text_sms
    message_body: str | None = None
    received_at: datetime | None = None
    is_prerecorded: bool | None = None
    raw_message: str = ""
    warnings: list[str] = field(default_factory=list)


def _normalize_number(match: re.Match) -> str:
    """Render a phone match as +1XXXXXXXXXX."""
    area, prefix, line = match.groups()
    return f"+1{area}{prefix}{line}"


def _find_labeled_number(text: str) -> str | None:
    """Find a phone number that directly follows a 'From:'-style label."""
    for label in FROM_LABELS.finditer(text):
        tail = text[label.end() : label.end() + 40]
        m = PHONE_RE.search(tail)
        if m:
            return _normalize_number(m)
    return None


def _first_number(text: str) -> str | None:
    m = PHONE_RE.search(text)
    return _normalize_number(m) if m else None


def extract_phone_number(text: str) -> str | None:
    """Pull the most likely phone number out of free text (e.g. OCR output).

    Prefers a number following a 'From'-style label, then the first
    phone-shaped string. Returns it normalized to +1XXXXXXXXXX, or None.
    """
    if not text:
        return None
    return _find_labeled_number(text) or _first_number(text)


def _parse_datetime(text: str) -> datetime | None:
    m = _DATE_LINE_RE.search(text)
    candidates = []
    if m:
        candidates.append(m.group(1).strip())
    for cand in candidates:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cand, fmt)
            except ValueError:
                continue
    return None


def _guess_type(text: str) -> tuple[ContactType, bool | None]:
    is_prerecorded: bool | None = None
    if PRERECORDED_HINTS.search(text):
        is_prerecorded = True
    if VOICEMAIL_HINTS.search(text):
        return ContactType.voicemail, (is_prerecorded if is_prerecorded else None)
    if TEXT_HINTS.search(text):
        return ContactType.text_sms, is_prerecorded
    return ContactType.text_sms, is_prerecorded


def _extract_transcript(body: str) -> str | None:
    """Pull a transcript/message body out of a notification email if labeled."""
    m = re.search(
        r"(?:transcript|message|message body|content)\s*[:\-]\s*(.+)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1).strip() or None
    return None


def parse_email(
    body: str,
    subject: str | None = None,
    sender: str | None = None,
    received_at: datetime | None = None,
) -> ParsedContact:
    """Parse a forwarded notification email into a :class:`ParsedContact`.

    The parser never raises on unrecognized input; it fills what it can and
    records what it could not determine in ``warnings``.
    """
    combined = "\n".join(part for part in (subject, body) if part)
    result = ParsedContact(raw_message=body)

    contact_type, is_prerecorded = _guess_type(combined)
    result.contact_type = contact_type
    result.is_prerecorded = is_prerecorded

    # Prefer a number that follows an explicit "From"-style label, then fall
    # back to the first phone-shaped string anywhere in the text.
    result.from_number = _find_labeled_number(combined) or _first_number(combined)
    if not result.from_number:
        result.warnings.append("Could not find a sender phone number; enter it manually.")

    result.received_at = received_at or _parse_datetime(combined)
    if not result.received_at:
        result.warnings.append("Could not parse a timestamp; defaulting to now.")

    result.message_body = _extract_transcript(body) or body.strip() or None

    return result


# --------------------------------------------------------------------------- #
# iPhone voicemail-screen screenshot parsing (from on-device OCR text)
# --------------------------------------------------------------------------- #

# Words from the iOS Phone-app tab bar; used to cut them off the transcript.
_NAV_WORDS = ("Favorites", "Recents", "Contacts", "Keypad", "Voicemail")

# "Jun 19, 2026 at 3:38 AM"  /  "June 19, 2026 3:38 PM"
_SCREENSHOT_DATE_RE = re.compile(
    r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*\d{4})\s*(?:at\s*)?"
    r"(\d{1,2}:\d{2}\s*[AaPp][Mm])"
)

# Telemarketing / solicitation keywords worth flagging in the transcript.
_SOLICITATION_WORDS = (
    "warranty",
    "loan",
    "loan specialist",
    "approval",
    "approved",
    "offer",
    "credit",
    "insurance",
    "debt",
    "refinance",
    "interest rate",
    "final notice",
    "lower your",
    "limited time",
    "monthly payment",
    "paperwork",
    "tax",
    "tax resolution",
    "resolution department",
    "obligation",
    "penalties",
    "balance owed",
    "reduce",
)

# Automated phone-tree prompts, e.g. "press 2", "please press two".
_PRESS_MENU_RE = re.compile(
    r"press\s+(?:\d|one|two|three|four|five|six|seven|eight|nine|zero)",
    re.IGNORECASE,
)

# Opt-out / do-not-call language, including "removed from our list" phrasing.
_OPT_OUT_RE = re.compile(
    r"opt[\s-]*out|do not call|stop calling|remove[d]?\b[\w\s']{0,20}\blist",
    re.IGNORECASE,
)


@dataclass
class ParsedScreenshot:
    from_number: str | None = None
    received_at: datetime | None = None
    caller_id_name: str | None = None
    transcript: str | None = None
    is_prerecorded: bool | None = None
    duration_seconds: int | None = None
    detected_signals: list[str] = field(default_factory=list)


def _screenshot_datetime(text: str) -> datetime | None:
    m = _SCREENSHOT_DATE_RE.search(text)
    if not m:
        return None
    combined = re.sub(r"\s+", " ", f"{m.group(1)} {m.group(2)}".replace(".", "")).strip()
    for fmt in ("%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p"):
        try:
            return datetime.strptime(combined, fmt)
        except ValueError:
            continue
    return None


def _callback_numbers(text: str, caller_number: str | None) -> list[str]:
    """Phone numbers mentioned in the text that differ from the caller's number.

    A callback number that doesn't match the caller ID is useful evidence — it
    can identify the actual business behind a spoofed or rotating caller ID.
    """
    found: list[str] = []
    for m in PHONE_RE.finditer(text):
        num = _normalize_number(m)
        if num != caller_number and num not in found:
            found.append(num)
    return found


def _screenshot_caller_name(text: str) -> str | None:
    # The subtitle line reads like "Unknown - Jun 19, 2026 at 3:38 AM" or
    # "John's Auto - Jun 19, 2026 ...". Take the part before the dash.
    m = re.search(
        r"^(.*?)[\-–—]\s*[A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*\d{4}",
        text,
        re.MULTILINE,
    )
    if not m:
        return None
    name = m.group(1).strip()
    if not name or name.lower() in {"unknown", "no caller id", "maybe"}:
        return None
    return name


def _screenshot_transcript(text: str) -> str | None:
    # Skip an optional parenthetical after the label, e.g. "Transcript (low
    # confidence)", so it doesn't get pulled into the transcript body.
    m = re.search(
        r"\bTranscript\b(?:\s*\([^)]*\))?\s*[:\n]?\s*(.+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    lines: list[str] = []
    for line in m.group(1).splitlines():
        nav_hits = sum(1 for w in _NAV_WORDS if w.lower() in line.lower())
        if nav_hits >= 2:
            break  # Reached the tab bar.
        lines.append(line.strip())
    transcript = " ".join(line for line in lines if line).strip()
    return transcript or None


def parse_voicemail_screenshot(ocr_text: str) -> ParsedScreenshot:
    """Extract incident fields from the OCR text of an iPhone voicemail screen.

    Pulls the caller number, timestamp, caller-ID name, transcript, and voicemail
    length, and flags automated/telemarketing signals. ``is_prerecorded`` is set
    True only when there is a clear automated-message signal (explicit keywords
    or a "press N" menu); everything is recorded in ``detected_signals`` so the
    user can review and override on the detail page.
    """
    result = ParsedScreenshot()
    if not ocr_text:
        return result

    result.from_number = extract_phone_number(ocr_text)
    result.received_at = _screenshot_datetime(ocr_text)
    result.caller_id_name = _screenshot_caller_name(ocr_text)
    result.transcript = _screenshot_transcript(ocr_text)

    dur = re.search(r"[-−](\d{1,2}):(\d{2})", ocr_text)
    if dur:
        result.duration_seconds = int(dur.group(1)) * 60 + int(dur.group(2))

    lower = ocr_text.lower()
    signals: list[str] = []
    is_prerecorded: bool | None = None

    if PRERECORDED_HINTS.search(ocr_text):
        is_prerecorded = True
        signals.append("prerecorded/automated keywords")
    if _PRESS_MENU_RE.search(ocr_text):
        is_prerecorded = True
        signals.append("press-key menu (automated/IVR system)")
    if _OPT_OUT_RE.search(ocr_text):
        signals.append("offered opt-out / DNC language (telemarketing indicator)")

    found = sorted({w for w in _SOLICITATION_WORDS if w in lower})
    if found:
        signals.append("solicitation keywords: " + ", ".join(found))

    callbacks = _callback_numbers(ocr_text, result.from_number)
    if callbacks:
        signals.append("callback number(s) in message: " + ", ".join(callbacks))

    # iOS flags shaky transcriptions; note it so the text isn't taken verbatim.
    if re.search(r"Transcript\s*\(\s*low\s*confidence", ocr_text, re.IGNORECASE):
        signals.append("iOS marked transcript low-confidence (may be inaccurate)")

    if result.duration_seconds:
        signals.append(f"voicemail length ~{result.duration_seconds}s")

    result.is_prerecorded = is_prerecorded
    result.detected_signals = signals
    return result

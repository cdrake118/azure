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

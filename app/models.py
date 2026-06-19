"""ORM models for callers and contact incidents.

The schema is intentionally tailored to the facts that matter for a TCPA
claim: who contacted you, when, how, whether it was prerecorded/autodialed,
whether you had registered on the National Do Not Call registry, and whether
you ever consented or asked them to stop.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContactType(str, enum.Enum):
    """How the unwanted contact arrived."""

    text_sms = "text_sms"
    voicemail = "voicemail"
    prerecorded_call = "prerecorded_call"
    live_call = "live_call"
    missed_call = "missed_call"


class Source(str, enum.Enum):
    """How the record entered the log."""

    manual = "manual"
    email = "email"
    api = "api"


class Caller(Base):
    """A phone number / entity that contacted you.

    Grouping incidents under a caller makes it easy to count repeat contacts,
    which is central to Do Not Call (§227(c)) claims that require more than one
    call in a 12-month period.
    """

    __tablename__ = "callers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(32), index=True, unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="caller",
        cascade="all, delete-orphan",
        order_by="Incident.received_at",
    )


class Incident(Base):
    """A single unwanted call, text, or voicemail."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    caller_id: Mapped[int] = mapped_column(ForeignKey("callers.id"), index=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    contact_type: Mapped[ContactType] = mapped_column(
        Enum(ContactType), default=ContactType.text_sms
    )

    from_number: Mapped[str] = mapped_column(String(32), index=True)
    to_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    caller_id_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The text body or the voicemail transcript.
    message_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # TCPA-relevant facts. Nullable booleans mean "unknown / not yet determined".
    is_prerecorded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_autodialed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    to_number_is_cell: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    on_dnc_registry: Mapped[bool] = mapped_column(Boolean, default=False)
    prior_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)

    # Provenance / evidence.
    source: Mapped[Source] = mapped_column(Enum(Source), default=Source.manual)
    raw_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    caller: Mapped["Caller"] = relationship(back_populates="incidents")

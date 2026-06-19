"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import ContactType, Source


class IncidentBase(BaseModel):
    received_at: datetime | None = None
    contact_type: ContactType = ContactType.text_sms
    from_number: str = Field(..., description="The number that contacted you.")
    to_number: str | None = None
    caller_id_name: str | None = None
    message_body: str | None = None

    is_prerecorded: bool | None = None
    is_autodialed: bool | None = None
    to_number_is_cell: bool | None = None
    on_dnc_registry: bool = False
    prior_consent: bool = False
    opted_out: bool = False

    notes: str | None = None


class IncidentCreate(IncidentBase):
    # Optional caller metadata captured at creation time.
    caller_name: str | None = None
    caller_company: str | None = None
    raw_message: str | None = None
    source: Source = Source.api


class IncidentOut(IncidentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    caller_id: int
    source: Source
    raw_message: str | None = None
    evidence_path: str | None = None
    created_at: datetime


class CallerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone_number: str
    name: str | None = None
    company: str | None = None
    notes: str | None = None
    created_at: datetime


class CallerWithIncidents(CallerOut):
    incidents: list[IncidentOut] = []


class EmailIngest(BaseModel):
    """A forwarded SMS/voicemail notification email to be parsed."""

    subject: str | None = None
    body: str
    sender: str | None = Field(
        None, description="The From: address of the forwarded email, if available."
    )
    received_at: datetime | None = None


class ViolationFinding(BaseModel):
    statute: str
    description: str
    per_violation: int
    willful_treble: int


class IncidentAnalysis(BaseModel):
    incident_id: int
    findings: list[ViolationFinding]
    base_damages: int
    treble_damages: int


class ClaimReport(BaseModel):
    generated_at: datetime
    total_incidents: int
    total_callers: int
    estimated_base_damages: int
    estimated_treble_damages: int
    per_caller: list[dict]
    disclaimer: str

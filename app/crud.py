"""Database operations for callers and incidents."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas


def get_or_create_caller(
    db: Session,
    phone_number: str,
    name: str | None = None,
    company: str | None = None,
) -> models.Caller:
    caller = db.scalar(
        select(models.Caller).where(models.Caller.phone_number == phone_number)
    )
    if caller is None:
        caller = models.Caller(phone_number=phone_number, name=name, company=company)
        db.add(caller)
        db.flush()
    else:
        # Backfill identity if we learn it later but never clobber existing data.
        if name and not caller.name:
            caller.name = name
        if company and not caller.company:
            caller.company = company
    return caller


def create_incident(db: Session, data: schemas.IncidentCreate) -> models.Incident:
    caller = get_or_create_caller(
        db, data.from_number, name=data.caller_name, company=data.caller_company
    )
    received_at = data.received_at or datetime.now(timezone.utc)
    incident = models.Incident(
        caller_id=caller.id,
        received_at=received_at,
        contact_type=data.contact_type,
        from_number=data.from_number,
        to_number=data.to_number,
        caller_id_name=data.caller_id_name,
        message_body=data.message_body,
        is_prerecorded=data.is_prerecorded,
        is_autodialed=data.is_autodialed,
        to_number_is_cell=data.to_number_is_cell,
        on_dnc_registry=data.on_dnc_registry,
        prior_consent=data.prior_consent,
        opted_out=data.opted_out,
        source=data.source,
        raw_message=data.raw_message,
        notes=data.notes,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def list_incidents(
    db: Session,
    caller_id: int | None = None,
    contact_type: models.ContactType | None = None,
) -> list[models.Incident]:
    stmt = select(models.Incident).order_by(models.Incident.received_at.desc())
    if caller_id is not None:
        stmt = stmt.where(models.Incident.caller_id == caller_id)
    if contact_type is not None:
        stmt = stmt.where(models.Incident.contact_type == contact_type)
    return list(db.scalars(stmt))


def get_incident(db: Session, incident_id: int) -> models.Incident | None:
    return db.get(models.Incident, incident_id)


def delete_incident(db: Session, incident_id: int) -> bool:
    incident = db.get(models.Incident, incident_id)
    if incident is None:
        return False
    db.delete(incident)
    db.commit()
    return True


def list_callers(db: Session) -> list[models.Caller]:
    return list(db.scalars(select(models.Caller).order_by(models.Caller.phone_number)))


def get_caller(db: Session, caller_id: int) -> models.Caller | None:
    return db.get(models.Caller, caller_id)


def all_incidents(db: Session) -> list[models.Incident]:
    return list(db.scalars(select(models.Incident)))


def create_attachment(
    db: Session,
    incident_id: int,
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> models.Attachment:
    attachment = models.Attachment(
        incident_id=incident_id,
        filename=filename,
        content_type=content_type or "application/octet-stream",
        size_bytes=len(data),
        data=data,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


def get_attachment(db: Session, attachment_id: int) -> models.Attachment | None:
    return db.get(models.Attachment, attachment_id)

"""FastAPI application: JSON API + server-rendered web UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import crud, ingest, report, schemas
from .auth import require_auth, require_upload_auth, warn_if_unprotected
from .database import get_db, init_db
from .models import ContactType, Source
from .tcpa import DISCLAIMER, analyze_all, damages_for_findings

# Cap uploads so a runaway file can't exhaust memory/storage. Voicemail clips
# are typically well under this.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )
    return data


def _parse_form_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    warn_if_unprotected()
    init_db()
    yield


app = FastAPI(
    title="Robocall TCPA Logger",
    version="0.1.0",
    description=(
        "Log unwanted robocall texts and voicemails and organize the facts "
        "needed to evaluate TCPA claims. Informational only, not legal advice."
    ),
    lifespan=lifespan,
    # Enforce HTTP Basic auth on every route when ROBOCALL_PASSWORD is set.
    dependencies=[Depends(require_auth)],
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Unauthenticated liveness probe for the hosting platform."""
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #


@app.post("/api/incidents", response_model=schemas.IncidentOut)
def api_create_incident(
    payload: schemas.IncidentCreate, db: Session = Depends(get_db)
):
    return crud.create_incident(db, payload)


@app.get("/api/incidents", response_model=list[schemas.IncidentOut])
def api_list_incidents(
    caller_id: int | None = None,
    contact_type: ContactType | None = None,
    db: Session = Depends(get_db),
):
    return crud.list_incidents(db, caller_id=caller_id, contact_type=contact_type)


@app.get("/api/incidents/{incident_id}", response_model=schemas.IncidentOut)
def api_get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = crud.get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@app.get("/api/incidents/{incident_id}/analysis", response_model=schemas.IncidentAnalysis)
def api_analyze_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = crud.get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    # Analyze in the context of all incidents so DNC repeat-counts are correct.
    findings = analyze_all(crud.all_incidents(db)).get(incident_id, [])
    base, treble = damages_for_findings(findings)
    return schemas.IncidentAnalysis(
        incident_id=incident_id,
        findings=[schemas.ViolationFinding(**f.as_dict()) for f in findings],
        base_damages=base,
        treble_damages=treble,
    )


@app.delete("/api/incidents/{incident_id}")
def api_delete_incident(incident_id: int, db: Session = Depends(get_db)):
    if not crud.delete_incident(db, incident_id):
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"deleted": incident_id}


@app.get("/api/callers", response_model=list[schemas.CallerOut])
def api_list_callers(db: Session = Depends(get_db)):
    return crud.list_callers(db)


@app.post("/api/callers/{caller_id}/entity", response_model=schemas.CallerOut)
def api_set_caller_entity(
    caller_id: int, payload: schemas.EntityAssign, db: Session = Depends(get_db)
):
    """Group this caller's number under a named entity (or clear it)."""
    caller = crud.set_caller_entity(db, caller_id, payload.name)
    if caller is None:
        raise HTTPException(status_code=404, detail="Caller not found")
    return caller


@app.post("/api/ingest/email", response_model=schemas.IncidentOut)
def api_ingest_email(payload: schemas.EmailIngest, db: Session = Depends(get_db)):
    """Parse a forwarded SMS/voicemail email and store it as an incident."""
    parsed = ingest.parse_email(
        body=payload.body,
        subject=payload.subject,
        sender=payload.sender,
        received_at=payload.received_at,
    )
    if not parsed.from_number:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract a sender phone number from the email. "
                "Use POST /api/incidents to enter it manually. "
                f"Warnings: {parsed.warnings}"
            ),
        )
    create = schemas.IncidentCreate(
        received_at=parsed.received_at or datetime.now(timezone.utc),
        contact_type=parsed.contact_type,
        from_number=parsed.from_number,
        message_body=parsed.message_body,
        is_prerecorded=parsed.is_prerecorded,
        raw_message=parsed.raw_message,
        source=Source.email,
    )
    return crud.create_incident(db, create)


# --------------------------------------------------------------------------- #
# Attachments (voicemail audio and other evidence)
# --------------------------------------------------------------------------- #


@app.post(
    "/api/voicemails",
    response_model=schemas.IncidentOut,
    dependencies=[Depends(require_upload_auth)],
)
async def api_upload_voicemail(
    file: UploadFile = File(...),
    from_number: str = Form(...),
    received_at: str | None = Form(None),
    message_body: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Create a voicemail incident from an uploaded audio file in one call.

    This is the endpoint the iOS Shortcut posts to: it accepts the audio file
    plus the caller's number and creates a logged voicemail with the audio
    attached. Authenticated by upload token or Basic auth.
    """
    data = await _read_upload(file)
    incident = crud.create_incident(
        db,
        schemas.IncidentCreate(
            received_at=_parse_form_dt(received_at) or datetime.now(timezone.utc),
            contact_type=ContactType.voicemail,
            to_number_is_cell=True,
            from_number=from_number.strip(),
            message_body=message_body or None,
            source=Source.api,
        ),
    )
    crud.create_attachment(
        db, incident.id, data, filename=file.filename, content_type=file.content_type
    )
    db.refresh(incident)
    return incident


@app.post(
    "/api/voicemails/screenshot",
    response_model=schemas.IncidentOut,
    dependencies=[Depends(require_upload_auth)],
)
async def api_upload_screenshot(
    file: UploadFile = File(...),
    from_number: str | None = Form(None),
    ocr_text: str | None = Form(None),
    received_at: str | None = Form(None),
    message_body: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Step 1 of the two-step flow: create a voicemail incident from a screenshot.

    The caller's number can be supplied explicitly via ``from_number`` or read
    from ``ocr_text`` — the text iOS extracts from the screenshot on-device
    ("Extract Text from Image"), so nothing needs to be typed. The raw OCR text
    is kept on the incident as ``raw_message`` for reference.

    The incident is created with the screenshot attached and no audio yet, so a
    subsequent POST to /api/voicemails/audio (with no incident id) auto-links the
    voicemail recording to it.
    """
    data = await _read_upload(file)

    parsed = ingest.parse_voicemail_screenshot(ocr_text or "")
    number = (from_number or "").strip() or parsed.from_number
    if not number:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not determine the caller's number. Include a from_number "
                "field, or ocr_text containing the number."
            ),
        )

    # Explicit form fields win; otherwise fall back to what OCR found.
    notes = (
        "Auto-detected from screenshot: " + "; ".join(parsed.detected_signals)
        if parsed.detected_signals
        else None
    )
    incident = crud.create_incident(
        db,
        schemas.IncidentCreate(
            received_at=_parse_form_dt(received_at)
            or parsed.received_at
            or datetime.now(timezone.utc),
            contact_type=ContactType.voicemail,
            to_number_is_cell=True,
            from_number=number,
            caller_id_name=parsed.caller_id_name,
            message_body=(message_body or None) or parsed.transcript,
            is_prerecorded=parsed.is_prerecorded,
            raw_message=ocr_text or None,
            notes=notes,
            source=Source.api,
        ),
    )
    crud.create_attachment(
        db, incident.id, data, filename=file.filename, content_type=file.content_type
    )
    db.refresh(incident)
    return incident


@app.post(
    "/api/voicemails/audio",
    response_model=schemas.IncidentOut,
    dependencies=[Depends(require_upload_auth)],
)
async def api_upload_voicemail_audio(
    file: UploadFile = File(...),
    incident_id: int | None = Form(None),
    from_number: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Step 2 of the two-step flow: attach voicemail audio to an incident.

    Resolution order for which incident the audio belongs to:
      1. An explicit ``incident_id`` form field, if provided.
      2. Otherwise, the most recent voicemail incident that has a screenshot but
         no audio yet (auto-link).
      3. Otherwise, if ``from_number`` is provided, a brand-new incident.
    Step 3 means audio is never silently dropped even if no screenshot was sent.
    """
    data = await _read_upload(file)

    incident = None
    if incident_id is not None:
        incident = crud.get_incident(db, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
    else:
        incident = crud.latest_incident_awaiting_audio(db)

    if incident is None:
        if not from_number:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No incident is awaiting audio. Upload a screenshot first, "
                    "or include a from_number to create a new incident."
                ),
            )
        incident = crud.create_incident(
            db,
            schemas.IncidentCreate(
                contact_type=ContactType.voicemail,
                to_number_is_cell=True,
                from_number=from_number.strip(),
                source=Source.api,
            ),
        )

    crud.create_attachment(
        db, incident.id, data, filename=file.filename, content_type=file.content_type
    )
    db.refresh(incident)
    return incident


@app.post(
    "/api/incidents/{incident_id}/attachments",
    response_model=schemas.AttachmentOut,
)
async def api_add_attachment(
    incident_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Attach evidence (e.g. audio) to an already-logged incident."""
    if crud.get_incident(db, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    data = await _read_upload(file)
    return crud.create_attachment(
        db, incident_id, data, filename=file.filename, content_type=file.content_type
    )


@app.get("/api/attachments/{attachment_id}")
def api_get_attachment(
    attachment_id: int, download: bool = False, db: Session = Depends(get_db)
):
    """Stream an attachment so the dashboard's audio player can play it."""
    attachment = crud.get_attachment(db, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    disposition = "attachment" if download else "inline"
    filename = attachment.filename or f"attachment-{attachment.id}"
    return Response(
        content=attachment.data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@app.get("/api/report")
def api_report(db: Session = Depends(get_db)):
    return report.build_claim_report(crud.all_incidents(db))


@app.get("/export/incidents.csv")
def export_csv(db: Session = Depends(get_db)):
    csv_text = report.incidents_to_csv(crud.all_incidents(db))
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tcpa_incidents.csv"},
    )


# --------------------------------------------------------------------------- #
# Web UI
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
def web_index(request: Request, db: Session = Depends(get_db)):
    incidents = crud.list_incidents(db)
    findings = analyze_all(incidents)
    rows = []
    for inc in incidents:
        f = findings.get(inc.id, [])
        base, treble = damages_for_findings(f)
        rows.append({"incident": inc, "findings": f, "base": base, "treble": treble})
    summary = report.build_claim_report(crud.all_incidents(db))
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "rows": rows,
            "summary": summary,
            "disclaimer": DISCLAIMER,
        },
    )


@app.get("/new", response_class=HTMLResponse)
def web_new(request: Request):
    return templates.TemplateResponse(
        request,
        "entry_form.html",
        {
            "contact_types": [t.value for t in ContactType],
            "disclaimer": DISCLAIMER,
        },
    )


@app.post("/new")
async def web_create(
    from_number: str = Form(...),
    contact_type: str = Form("text_sms"),
    received_at: str = Form(""),
    message_body: str = Form(""),
    caller_id_name: str = Form(""),
    caller_name: str = Form(""),
    is_prerecorded: str = Form(""),
    is_autodialed: str = Form(""),
    to_number_is_cell: str = Form(""),
    on_dnc_registry: str = Form(""),
    prior_consent: str = Form(""),
    opted_out: str = Form(""),
    notes: str = Form(""),
    audio: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    payload = schemas.IncidentCreate(
        received_at=_parse_form_dt(received_at),
        contact_type=ContactType(contact_type),
        from_number=from_number.strip(),
        message_body=message_body or None,
        caller_id_name=caller_id_name or None,
        caller_name=caller_name or None,
        is_prerecorded=_checkbox(is_prerecorded),
        is_autodialed=_checkbox(is_autodialed),
        to_number_is_cell=_checkbox(to_number_is_cell),
        on_dnc_registry=_checkbox(on_dnc_registry),
        prior_consent=_checkbox(prior_consent),
        opted_out=_checkbox(opted_out),
        notes=notes or None,
        source=Source.manual,
    )
    incident = crud.create_incident(db, payload)
    # An optional audio/evidence file submitted with the form.
    if audio is not None and audio.filename:
        data = await _read_upload(audio)
        crud.create_attachment(
            db, incident.id, data, filename=audio.filename, content_type=audio.content_type
        )
    return RedirectResponse(url="/", status_code=303)


@app.get("/ingest", response_class=HTMLResponse)
def web_ingest_form(request: Request):
    return templates.TemplateResponse(
        request, "ingest_form.html", {"disclaimer": DISCLAIMER}
    )


@app.post("/ingest")
def web_ingest(
    subject: str = Form(""),
    body: str = Form(...),
    db: Session = Depends(get_db),
):
    parsed = ingest.parse_email(body=body, subject=subject or None)
    if not parsed.from_number:
        # Re-render the form with the raw text so the user can fix it manually.
        return RedirectResponse(url="/new", status_code=303)
    payload = schemas.IncidentCreate(
        received_at=parsed.received_at or datetime.now(timezone.utc),
        contact_type=parsed.contact_type,
        from_number=parsed.from_number,
        message_body=parsed.message_body,
        is_prerecorded=parsed.is_prerecorded,
        raw_message=parsed.raw_message,
        source=Source.email,
    )
    crud.create_incident(db, payload)
    return RedirectResponse(url="/", status_code=303)


@app.get("/incident/{incident_id}", response_class=HTMLResponse)
def web_incident_detail(
    incident_id: int, request: Request, db: Session = Depends(get_db)
):
    incident = crud.get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    findings = analyze_all(crud.all_incidents(db)).get(incident_id, [])
    base, treble = damages_for_findings(findings)
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "incident": incident,
            "findings": findings,
            "base": base,
            "treble": treble,
            "contact_types": [t.value for t in ContactType],
            "entities": crud.list_entities(db),
            "disclaimer": DISCLAIMER,
        },
    )


@app.post("/incident/{incident_id}/edit")
def web_incident_edit(
    incident_id: int,
    from_number: str = Form(...),
    contact_type: str = Form("voicemail"),
    received_at: str = Form(""),
    message_body: str = Form(""),
    caller_id_name: str = Form(""),
    is_prerecorded: str = Form(""),
    is_autodialed: str = Form(""),
    to_number_is_cell: str = Form(""),
    on_dnc_registry: str = Form(""),
    prior_consent: str = Form(""),
    opted_out: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    changes = {
        "from_number": from_number.strip(),
        "contact_type": ContactType(contact_type),
        "received_at": _parse_form_dt(received_at),
        "message_body": message_body or None,
        "caller_id_name": caller_id_name or None,
        "is_prerecorded": _checkbox(is_prerecorded),
        "is_autodialed": _checkbox(is_autodialed),
        "to_number_is_cell": _checkbox(to_number_is_cell),
        "on_dnc_registry": _checkbox(on_dnc_registry),
        "prior_consent": _checkbox(prior_consent),
        "opted_out": _checkbox(opted_out),
        "notes": notes or None,
    }
    if changes["received_at"] is None:
        # Don't wipe an existing timestamp when the field is left blank.
        changes.pop("received_at")
    if crud.update_incident(db, incident_id, changes) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return RedirectResponse(url=f"/incident/{incident_id}", status_code=303)


@app.post("/incident/{incident_id}/attach")
async def web_incident_attach(
    incident_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if crud.get_incident(db, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if file.filename:
        data = await _read_upload(file)
        crud.create_attachment(
            db, incident_id, data, filename=file.filename, content_type=file.content_type
        )
    return RedirectResponse(url=f"/incident/{incident_id}", status_code=303)


@app.post("/caller/{caller_id}/entity")
def web_set_caller_entity(
    caller_id: int,
    entity_name: str = Form(""),
    incident_id: int = Form(...),
    db: Session = Depends(get_db),
):
    crud.set_caller_entity(db, caller_id, entity_name)
    return RedirectResponse(url=f"/incident/{incident_id}", status_code=303)


@app.post("/attachment/{attachment_id}/delete")
def web_attachment_delete(attachment_id: int, db: Session = Depends(get_db)):
    incident_id = crud.delete_attachment(db, attachment_id)
    target = f"/incident/{incident_id}" if incident_id else "/"
    return RedirectResponse(url=target, status_code=303)


@app.post("/delete/{incident_id}")
def web_delete(incident_id: int, db: Session = Depends(get_db)):
    crud.delete_incident(db, incident_id)
    return RedirectResponse(url="/", status_code=303)


def _checkbox(value: str) -> bool:
    """Translate an HTML checkbox form value into a bool.

    Unchecked checkboxes are not submitted, so the Form default ("") arrives
    here and maps to False. A checked box submits "on".
    """
    return value.strip().lower() in {"on", "true", "yes", "1"}

"""FastAPI application: JSON API + server-rendered web UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import crud, ingest, report, schemas
from .database import get_db, init_db
from .models import ContactType, Source
from .tcpa import DISCLAIMER, analyze_all, damages_for_findings

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
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
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


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
def web_create(
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
    db: Session = Depends(get_db),
):
    parsed_dt = None
    if received_at:
        try:
            parsed_dt = datetime.fromisoformat(received_at)
        except ValueError:
            parsed_dt = None

    payload = schemas.IncidentCreate(
        received_at=parsed_dt,
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
    crud.create_incident(db, payload)
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

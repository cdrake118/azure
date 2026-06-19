# Robocall TCPA Logger

A small, self-hosted web app + JSON API for logging the unwanted robocall
**texts** and **voicemails** you receive, and organizing the facts you'd need to
evaluate and pursue claims under the **Telephone Consumer Protection Act
(TCPA)**.

It runs locally with SQLite — no cloud account, your data stays on your machine.

> ⚖️ **Not legal advice.** This tool organizes facts and produces *informational*
> estimates only. Statutory eligibility, consent, and damages depend on the
> specific facts and current case law. Talk to a licensed attorney before
> filing anything.

## What it captures

For each contact it records the facts that matter for a TCPA claim:

- Who contacted you (number, caller-ID name, company if known)
- When, and how (text, voicemail, prerecorded call, live call, missed call)
- The message body / voicemail transcript (your evidence)
- Whether it was **prerecorded / artificial voice** or appears **autodialed (ATDS)**
- Whether your number was on the **National Do Not Call registry**
- Whether you ever **consented** or told them to **stop**

From those facts it flags which incidents look actionable under the common TCPA
theories and gives a rough statutory-damages range.

### TCPA theories modeled

| Statute | Theory | Damages |
| --- | --- | --- |
| 47 U.S.C. § 227(b) | Autodialed/prerecorded contact to a cell without prior consent | $500, up to $1,500 if willful |
| 47 U.S.C. § 227(c) / 47 CFR 64.1200(c) | >1 telemarketing contact in 12 months to a DNC-registered number | $500, up to $1,500 if willful |
| 47 CFR 64.1200(d) | Continued contact after you asked them to stop | $500, up to $1,500 if willful |
| 47 CFR 64.1200(c)(1) | Telephone solicitation before 8 a.m. or after 9 p.m. (called party's local time) | $500, up to $1,500 if willful |

The damages figures are the statutory amounts set by the TCPA itself.

## Quick start

```bash
pip install -r requirements.txt
./run.sh              # or: uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Interactive API docs are at `/docs`.

## Logging a contact

**From the web UI** — click **+ Add entry** and fill in the form, or
**Paste forwarded message** to paste a forwarded SMS / voicemail-to-email
notification and let the parser pull out the number, time, and text.

**Forward by email / automation** — POST the raw notification to the API:

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/email \
  -H 'Content-Type: application/json' \
  -d '{"subject":"New voicemail","body":"From: +1 (555) 123-4567\nReceived: 06/15/2026 09:30 AM\nTranscript: This is about your car warranty..."}'
```

**Manual API entry**

```bash
curl -X POST http://127.0.0.1:8000/api/incidents \
  -H 'Content-Type: application/json' \
  -d '{"from_number":"+15551234567","contact_type":"text_sms",
       "message_body":"You are pre-approved!","is_autodialed":true,
       "on_dnc_registry":true}'
```

## Logging voicemail audio

Audio files (and image evidence) are stored in the database and play back inline
in the dashboard. Two ways to add them:

- **Web upload** — on the **+ Add entry** form, attach a file in the *Voicemail
  audio / evidence* field. On iPhone: open the voicemail → **Share → Save to
  Files**, then pick it in the form.
- **One-tap from iPhone** — set up the Apple Shortcut so you can upload a
  voicemail straight from the **Share** menu. See
  [`docs/ios-shortcut.md`](docs/ios-shortcut.md).
- **Screenshot + voicemail, linked** — a two-step Shortcut flow logs a
  screenshot of the voicemail screen *and* the audio into one incident. iOS reads
  the screen on-device (OCR) and the server auto-fills the **number, timestamp,
  caller name, transcript, and voicemail length**, flags automated/telemarketing
  signals (press-key menus, opt-out/DNC language, solicitation keywords) into the
  notes, and sets the prerecorded flag when warranted — so you type nothing.

Every incident has a **detail page** (click *view* in the log) showing all
attachments — image previews and audio players — with an *Add evidence* upload,
per-attachment delete, and an editable form for the TCPA facts.

### Grouping numbers under one entity

Telemarketers rotate and spoof numbers, but the TCPA's repeat-call thresholds
count calls "by or on behalf of the same entity." On any incident's detail page,
assign its number to a named **entity** (e.g. "ABC Loan Services"); type the same
name on another number's page to link them. The §227(c) Do Not Call and
§64.1200(c)(1) calling-hours thresholds then count calls across all of that
entity's numbers, so two calls from two different numbers count as two calls from
one entity.

Uploads are capped at 25 MB. `.m4a` clips play inline; unusual carrier formats
are still stored and downloadable as evidence.

## Reports & export

- `GET /api/report` — aggregated potential violations and damages, grouped by caller
- `GET /export/incidents.csv` — full CSV export (one row per contact, with the
  potential statutes and damages) — handy to hand to an attorney
- `GET /api/incidents/{id}/analysis` — the findings for a single incident

## API reference

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/incidents` | Create an incident |
| GET | `/api/incidents` | List incidents (filter by `caller_id`, `contact_type`) |
| GET | `/api/incidents/{id}` | Get one incident |
| GET | `/api/incidents/{id}/analysis` | TCPA findings for one incident |
| DELETE | `/api/incidents/{id}` | Delete an incident |
| GET | `/api/callers` | List distinct callers |
| POST | `/api/ingest/email` | Parse a forwarded SMS/voicemail email |
| POST | `/api/voicemails` | Upload a voicemail audio file (+ number) as a new incident |
| POST | `/api/voicemails/screenshot` | Create an incident from a screenshot; reads the number from `ocr_text` |
| POST | `/api/voicemails/audio` | Attach voicemail audio, auto-linking to the latest screenshot incident |
| POST | `/api/incidents/{id}/attachments` | Attach evidence to an existing incident |
| GET | `/api/attachments/{id}` | Stream/download an attachment |
| GET | `/api/report` | Aggregated claim report |
| GET | `/export/incidents.csv` | CSV export |

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `ROBOCALL_DB_URL` | `sqlite:///./robocall_log.db` | SQLAlchemy database URL. Falls back to `DATABASE_URL` if unset. A legacy `postgres://` scheme is auto-rewritten to `postgresql://`. |
| `ROBOCALL_USERNAME` | `admin` | Username for HTTP Basic auth |
| `ROBOCALL_PASSWORD` | _(unset)_ | If set, the whole app requires this password. **If unset, the app runs with no authentication.** |
| `ROBOCALL_UPLOAD_TOKEN` | _(unset)_ | If set, `/api/voicemails` also accepts this token via `?token=…` (used by the iOS Shortcut). |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address for `run.sh` |

See `.env.example` for a copy-paste starting point.

## Deploying to Railway

The repo includes a `Procfile` and `railway.json`, so Railway builds and starts
it automatically (uvicorn bound to `0.0.0.0:$PORT`). A `/healthz` endpoint is
used as the health check and stays reachable without a login.

For a deployment you can actually rely on, do two things:

1. **Use Postgres, not SQLite.** Railway's container disk is wiped on every
   deploy/restart, so a SQLite file would lose your log. Add the **Postgres**
   plugin, then on the app service set a variable referencing it:

   ```
   ROBOCALL_DB_URL=${{Postgres.DATABASE_URL}}
   ```

   The `psycopg2-binary` driver is already in `requirements.txt`; tables are
   created automatically on first boot.

2. **Set a password.** Add `ROBOCALL_PASSWORD` (and optionally
   `ROBOCALL_USERNAME`) as service variables. Without `ROBOCALL_PASSWORD`, the
   public URL is open to anyone.

## Evidence tips

- Keep the **original** text/voicemail — don't delete it. The log stores a copy
  but the original on your device/carrier is the stronger evidence.
- Record dates/times precisely; for DNC claims the **12-month window** and the
  **"more than one call"** requirement depend on accurate timestamps.
- Note when you said "STOP" / asked to be removed — that powers the
  64.1200(d) opt-out theory.
- Register your number at <https://www.donotcall.gov> and record the date.

## Running the tests

```bash
pytest
```

## Project layout

```
app/
  main.py        FastAPI app: JSON API + web UI routes
  models.py      SQLAlchemy ORM (Caller, Incident)
  schemas.py     Pydantic request/response models
  crud.py        Database operations
  ingest.py      Forwarded SMS/voicemail email parser
  tcpa.py        TCPA violation analysis + damages
  report.py      CSV export + claim summary
  auth.py        Optional HTTP Basic auth + upload-token auth
  templates/     Jinja2 web UI
  static/        CSS
tests/           pytest suite
docs/            iOS Shortcut setup guide
Procfile         Railway/Heroku start command
railway.json     Railway build + deploy config
.env.example     Sample environment configuration
```

"""End-to-end tests for the API and ingestion endpoints."""


def _make_incident(client, **overrides):
    payload = {
        "from_number": "+15551234567",
        "contact_type": "voicemail",
        "message_body": "Your car warranty is about to expire.",
        "is_prerecorded": True,
        "to_number_is_cell": True,
    }
    payload.update(overrides)
    return client.post("/api/incidents", json=payload)


def test_create_and_list_incident(client):
    resp = _make_incident(client)
    assert resp.status_code == 200
    data = resp.json()
    assert data["from_number"] == "+15551234567"
    assert data["source"] == "api"

    listing = client.get("/api/incidents").json()
    assert len(listing) == 1


def test_repeated_caller_reuses_caller_record(client):
    _make_incident(client)
    _make_incident(client, message_body="Second call from same number.")
    callers = client.get("/api/callers").json()
    assert len(callers) == 1
    incidents = client.get("/api/incidents").json()
    assert len(incidents) == 2


def test_analysis_flags_227b(client):
    inc = _make_incident(client, is_autodialed=True).json()
    analysis = client.get(f"/api/incidents/{inc['id']}/analysis").json()
    statutes = [f["statute"] for f in analysis["findings"]]
    assert any("227(b)" in s for s in statutes)
    assert analysis["base_damages"] >= 500


def test_email_ingest_endpoint(client):
    body = (
        "New voicemail from (555) 444-3333\n"
        "Transcript: This is a prerecorded call about your student loan."
    )
    resp = client.post("/api/ingest/email", json={"body": body})
    assert resp.status_code == 200
    data = resp.json()
    assert data["from_number"] == "+15554443333"
    assert data["source"] == "email"
    assert data["is_prerecorded"] is True


def test_email_ingest_without_number_returns_422(client):
    resp = client.post("/api/ingest/email", json={"body": "no numbers here"})
    assert resp.status_code == 422


def test_report_endpoint_aggregates(client):
    _make_incident(client, is_autodialed=True)
    report = client.get("/api/report").json()
    assert report["total_incidents"] == 1
    assert report["estimated_base_damages"] >= 500
    assert "disclaimer" in report


def test_csv_export(client):
    _make_incident(client, is_autodialed=True)
    resp = client.get("/export/incidents.csv")
    assert resp.status_code == 200
    assert "incident_id" in resp.text
    assert "+15551234567" in resp.text


def test_delete_incident(client):
    inc = _make_incident(client).json()
    assert client.delete(f"/api/incidents/{inc['id']}").status_code == 200
    assert client.get("/api/incidents").json() == []


def test_web_index_renders(client):
    _make_incident(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Robocall TCPA Logger" in resp.text

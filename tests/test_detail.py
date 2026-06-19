"""Tests for the two-step screenshot+voicemail flow and the incident detail page."""

IMAGE = b"\x89PNG\r\n\x1a\nfake-screenshot-bytes"
AUDIO = b"fake-voicemail-audio-bytes"


def _upload_screenshot(client, number="+18446241325"):
    return client.post(
        "/api/voicemails/screenshot",
        data={"from_number": number},
        files={"file": ("vm.png", IMAGE, "image/png")},
    )


def test_screenshot_creates_incident_with_image(client):
    resp = _upload_screenshot(client)
    assert resp.status_code == 200
    data = resp.json()
    assert data["contact_type"] == "voicemail"
    assert data["from_number"] == "+18446241325"
    assert len(data["attachments"]) == 1
    assert data["attachments"][0]["content_type"] == "image/png"


# OCR text that iOS would extract from the example voicemail screenshot.
OCR_TEXT = (
    "8446241325\n"
    "Unknown - Jun 19, 2026 at 3:38 AM\n"
    "00:00 -00:14\n"
    "Add Contact Report Spam\n"
    "Transcript\n"
    "Okay, to go over the details and get this finalized today, please press 2 "
    "If you'd rather not be contacted again. Press 9 to opt out."
)


def test_screenshot_reads_number_from_ocr_text(client):
    resp = client.post(
        "/api/voicemails/screenshot",
        data={"ocr_text": OCR_TEXT},
        files={"file": ("vm.png", IMAGE, "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    # The 10-digit number is extracted despite the transcript's "press 2/9" noise.
    assert data["from_number"] == "+18446241325"
    # The raw OCR text is preserved for reference.
    assert "Press 9 to opt out" in data["raw_message"]


def test_screenshot_explicit_number_overrides_ocr(client):
    resp = client.post(
        "/api/voicemails/screenshot",
        data={"from_number": "+15551112222", "ocr_text": OCR_TEXT},
        files={"file": ("vm.png", IMAGE, "image/png")},
    )
    assert resp.json()["from_number"] == "+15551112222"


def test_screenshot_without_number_or_ocr_is_422(client):
    resp = client.post(
        "/api/voicemails/screenshot",
        files={"file": ("vm.png", IMAGE, "image/png")},
    )
    assert resp.status_code == 422


def test_audio_autolinks_to_latest_screenshot(client):
    incident = _upload_screenshot(client).json()
    # No incident_id given: should auto-link to the screenshot incident.
    resp = client.post(
        "/api/voicemails/audio",
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    )
    assert resp.status_code == 200
    linked = resp.json()
    assert linked["id"] == incident["id"]
    kinds = sorted(a["content_type"] for a in linked["attachments"])
    assert kinds == ["audio/m4a", "image/png"]


def test_audio_explicit_incident_id(client):
    inc = client.post(
        "/api/incidents",
        json={"from_number": "+18446241325", "contact_type": "voicemail"},
    ).json()
    resp = client.post(
        "/api/voicemails/audio",
        data={"incident_id": str(inc["id"])},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == inc["id"]


def test_audio_without_open_incident_requires_number(client):
    resp = client.post(
        "/api/voicemails/audio",
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    )
    assert resp.status_code == 422


def test_audio_fallback_creates_incident_with_number(client):
    resp = client.post(
        "/api/voicemails/audio",
        data={"from_number": "+18446241325"},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["from_number"] == "+18446241325"
    assert len(data["attachments"]) == 1


def test_audio_does_not_relink_incident_that_already_has_audio(client):
    # First screenshot+audio pair is complete.
    first = _upload_screenshot(client, number="+15550000001").json()
    client.post("/api/voicemails/audio", files={"file": ("a.m4a", AUDIO, "audio/m4a")})
    # Second screenshot, then audio -> must link to the SECOND, not the first.
    second = _upload_screenshot(client, number="+15550000002").json()
    linked = client.post(
        "/api/voicemails/audio", files={"file": ("b.m4a", AUDIO, "audio/m4a")}
    ).json()
    assert linked["id"] == second["id"]
    assert linked["id"] != first["id"]


def test_detail_page_renders(client):
    inc = _upload_screenshot(client).json()
    resp = client.get(f"/incident/{inc['id']}")
    assert resp.status_code == 200
    assert "+18446241325" in resp.text
    assert "Evidence" in resp.text


def test_detail_page_404(client):
    assert client.get("/incident/99999").status_code == 404


def test_edit_incident_sets_tcpa_facts(client):
    inc = _upload_screenshot(client).json()
    resp = client.post(
        f"/incident/{inc['id']}/edit",
        data={
            "from_number": "+18446241325",
            "contact_type": "voicemail",
            "message_body": "Press 9 to opt out of future calls.",
            "is_prerecorded": "on",
            "on_dnc_registry": "on",
            "opted_out": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    updated = client.get(f"/api/incidents/{inc['id']}").json()
    assert updated["is_prerecorded"] is True
    assert updated["on_dnc_registry"] is True
    assert updated["opted_out"] is True
    assert "opt out" in updated["message_body"]


def test_web_attach_and_delete_attachment(client):
    inc = _upload_screenshot(client).json()
    # Attach a second file via the web form route.
    client.post(
        f"/incident/{inc['id']}/attach",
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
        follow_redirects=False,
    )
    after_add = client.get(f"/api/incidents/{inc['id']}").json()
    assert len(after_add["attachments"]) == 2

    att_id = after_add["attachments"][0]["id"]
    resp = client.post(f"/attachment/{att_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    after_del = client.get(f"/api/incidents/{inc['id']}").json()
    assert len(after_del["attachments"]) == 1

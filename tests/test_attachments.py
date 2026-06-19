"""Tests for voicemail audio upload, retrieval, and upload-token auth."""

# A tiny stand-in for audio bytes; the app stores whatever is sent.
AUDIO = b"ID3\x00\x00\x00fake-m4a-bytes-for-testing"


def test_upload_voicemail_creates_incident_with_audio(client):
    resp = client.post(
        "/api/voicemails",
        data={"from_number": "+15551234567"},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["contact_type"] == "voicemail"
    assert data["from_number"] == "+15551234567"
    assert len(data["attachments"]) == 1
    att = data["attachments"][0]
    assert att["content_type"] == "audio/m4a"
    assert att["size_bytes"] == len(AUDIO)


def test_uploaded_audio_can_be_streamed_back(client):
    inc = client.post(
        "/api/voicemails",
        data={"from_number": "+15551234567"},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    ).json()
    att_id = inc["attachments"][0]["id"]
    resp = client.get(f"/api/attachments/{att_id}")
    assert resp.status_code == 200
    assert resp.content == AUDIO
    assert resp.headers["content-type"].startswith("audio/m4a")
    assert "inline" in resp.headers["content-disposition"]


def test_download_disposition(client):
    inc = client.post(
        "/api/voicemails",
        data={"from_number": "+15550000000"},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    ).json()
    att_id = inc["attachments"][0]["id"]
    resp = client.get(f"/api/attachments/{att_id}?download=true")
    assert "attachment" in resp.headers["content-disposition"]


def test_empty_file_rejected(client):
    resp = client.post(
        "/api/voicemails",
        data={"from_number": "+15551234567"},
        files={"file": ("vm.m4a", b"", "audio/m4a")},
    )
    assert resp.status_code == 422


def test_attach_to_existing_incident(client):
    inc = client.post(
        "/api/incidents",
        json={"from_number": "+15559998888", "contact_type": "voicemail"},
    ).json()
    resp = client.post(
        f"/api/incidents/{inc['id']}/attachments",
        files={"file": ("clip.m4a", AUDIO, "audio/m4a")},
    )
    assert resp.status_code == 200
    assert resp.json()["incident_id"] == inc["id"]


def test_attach_to_missing_incident_404(client):
    resp = client.post(
        "/api/incidents/99999/attachments",
        files={"file": ("clip.m4a", AUDIO, "audio/m4a")},
    )
    assert resp.status_code == 404


def test_missing_attachment_404(client):
    assert client.get("/api/attachments/99999").status_code == 404


def test_upload_token_allows_post_when_basic_auth_required(client, monkeypatch):
    monkeypatch.setenv("ROBOCALL_PASSWORD", "s3cret-pw")
    monkeypatch.setenv("ROBOCALL_UPLOAD_TOKEN", "tok-123")

    # No token and no credentials -> rejected.
    rejected = client.post(
        "/api/voicemails",
        data={"from_number": "+15551112222"},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    )
    assert rejected.status_code == 401

    # Correct token in the query string -> accepted, even without Basic auth.
    ok = client.post(
        "/api/voicemails?token=tok-123",
        data={"from_number": "+15551112222"},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    )
    assert ok.status_code == 200


def test_upload_token_wrong_value_rejected(client, monkeypatch):
    monkeypatch.setenv("ROBOCALL_PASSWORD", "s3cret-pw")
    monkeypatch.setenv("ROBOCALL_UPLOAD_TOKEN", "tok-123")
    resp = client.post(
        "/api/voicemails?token=wrong",
        data={"from_number": "+15551112222"},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
    )
    assert resp.status_code == 401


def test_basic_auth_still_works_for_upload(client, monkeypatch):
    monkeypatch.setenv("ROBOCALL_PASSWORD", "s3cret-pw")
    monkeypatch.setenv("ROBOCALL_UPLOAD_TOKEN", "tok-123")
    resp = client.post(
        "/api/voicemails",
        data={"from_number": "+15551112222"},
        files={"file": ("vm.m4a", AUDIO, "audio/m4a")},
        auth=("admin", "s3cret-pw"),
    )
    assert resp.status_code == 200

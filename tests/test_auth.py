"""Tests for optional HTTP Basic authentication.

``require_auth`` reads the environment on every request, so toggling
ROBOCALL_PASSWORD with monkeypatch is enough to exercise both modes against
the already-constructed app.
"""


def test_open_when_no_password(client, monkeypatch):
    monkeypatch.delenv("ROBOCALL_PASSWORD", raising=False)
    assert client.get("/api/incidents").status_code == 200


def test_401_without_credentials_when_password_set(client, monkeypatch):
    monkeypatch.setenv("ROBOCALL_PASSWORD", "s3cret-pw")
    resp = client.get("/api/incidents")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Basic"


def test_401_with_wrong_credentials(client, monkeypatch):
    monkeypatch.setenv("ROBOCALL_PASSWORD", "s3cret-pw")
    assert client.get("/api/incidents", auth=("admin", "nope")).status_code == 401
    assert client.get("/api/incidents", auth=("wrong", "s3cret-pw")).status_code == 401


def test_200_with_correct_credentials(client, monkeypatch):
    monkeypatch.setenv("ROBOCALL_PASSWORD", "s3cret-pw")
    assert client.get("/api/incidents", auth=("admin", "s3cret-pw")).status_code == 200


def test_custom_username(client, monkeypatch):
    monkeypatch.setenv("ROBOCALL_PASSWORD", "pw")
    monkeypatch.setenv("ROBOCALL_USERNAME", "cdrake")
    assert client.get("/api/incidents", auth=("cdrake", "pw")).status_code == 200
    assert client.get("/api/incidents", auth=("admin", "pw")).status_code == 401


def test_healthz_is_public_even_with_password(client, monkeypatch):
    monkeypatch.setenv("ROBOCALL_PASSWORD", "s3cret-pw")
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

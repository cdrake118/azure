"""Tests for grouping multiple numbers under one entity.

The TCPA repeat-call thresholds count calls "by or on behalf of the same
entity", so grouping numbers should make a single call from each of two numbers
count as two calls from one entity.
"""


def _dnc_voicemail(client, number):
    return client.post(
        "/api/incidents",
        json={
            "from_number": number,
            "contact_type": "voicemail",
            "on_dnc_registry": True,
        },
    ).json()


def _has_dnc(client, incident_id):
    analysis = client.get(f"/api/incidents/{incident_id}/analysis").json()
    return any("227(c)" in f["statute"] for f in analysis["findings"])


def test_grouping_two_numbers_triggers_dnc_threshold(client):
    a = _dnc_voicemail(client, "+18559645516")
    b = _dnc_voicemail(client, "+18885843759")

    # One lone call from each distinct number -> DNC "more than one call" not met.
    assert not _has_dnc(client, a["id"])
    assert not _has_dnc(client, b["id"])

    # Group both numbers under one entity.
    r1 = client.post(f"/api/callers/{a['caller_id']}/entity", json={"name": "ABC Loans"})
    r2 = client.post(f"/api/callers/{b['caller_id']}/entity", json={"name": "ABC Loans"})
    assert r1.status_code == 200
    # Both callers point at the same entity.
    assert r1.json()["entity_id"] == r2.json()["entity_id"]

    # Now two calls by the same entity in 12 months -> DNC threshold met.
    assert _has_dnc(client, a["id"])
    assert _has_dnc(client, b["id"])


def test_clearing_entity_ungroups(client):
    a = _dnc_voicemail(client, "+18559645516")
    b = _dnc_voicemail(client, "+18885843759")
    client.post(f"/api/callers/{a['caller_id']}/entity", json={"name": "ABC Loans"})
    client.post(f"/api/callers/{b['caller_id']}/entity", json={"name": "ABC Loans"})
    assert _has_dnc(client, a["id"])

    # Clear the entity on one number -> back to lone calls, threshold not met.
    cleared = client.post(
        f"/api/callers/{a['caller_id']}/entity", json={"name": None}
    )
    assert cleared.json()["entity_id"] is None
    assert not _has_dnc(client, a["id"])
    assert not _has_dnc(client, b["id"])


def test_same_number_repeat_still_counts_without_entity(client):
    # Two calls from the SAME number already meet the threshold, no entity needed.
    a = _dnc_voicemail(client, "+18559645516")
    _dnc_voicemail(client, "+18559645516")
    assert _has_dnc(client, a["id"])


def test_set_entity_on_missing_caller_404(client):
    resp = client.post("/api/callers/99999/entity", json={"name": "X"})
    assert resp.status_code == 404


def test_web_entity_form_assigns_and_redirects(client):
    a = _dnc_voicemail(client, "+18559645516")
    resp = client.post(
        f"/caller/{a['caller_id']}/entity",
        data={"entity_name": "ABC Loans", "incident_id": str(a["id"])},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    caller = next(
        c for c in client.get("/api/callers").json() if c["id"] == a["caller_id"]
    )
    assert caller["entity_id"] is not None

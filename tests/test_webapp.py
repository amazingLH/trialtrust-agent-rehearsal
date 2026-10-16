import json
import sqlite3

from fastapi.testclient import TestClient

from trialtrust.webapp import create_app

HEADERS = {"X-TrialTrust-Client": "web"}


def initialize(client):
    response = client.post("/api/session", json={}, headers=HEADERS)
    assert response.status_code == 200
    return response


def start(client, **overrides):
    body = {"budget_yuan": 300, "case": "baseline", "agent": "demo_careful", "dense": False, "confirmed": True, **overrides}
    response = client.post("/api/trials", json=body, headers=HEADERS)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_browser_flow_review_export_and_session_isolation(tmp_path):
    app = create_app(tmp_path / "web", enable_live=False)
    with TestClient(app) as client:
        session = initialize(client)
        assert "HttpOnly" in session.headers["set-cookie"] and "SameSite=strict" in session.headers["set-cookie"]
        run_id = start(client)
        data = client.get(f"/api/trials/{run_id}").json()
        assert data["status"] == "waiting_review" and data["report"]["drafts"][0]["total_yuan"] == 280
        with TestClient(app) as other:
            initialize(other)
            assert other.get(f"/api/trials/{run_id}").status_code == 404
            assert other.get(f"/api/trials/{run_id}/export").status_code == 404
            assert other.post(f"/api/trials/{run_id}/review", json={"accepted": True}, headers=HEADERS).status_code == 404
        for _ in range(2):
            assert client.post(f"/api/trials/{run_id}/review", json={"accepted": True}, headers=HEADERS).status_code == 200
        exported = client.get(f"/api/trials/{run_id}/export")
        assert exported.status_code == 200
        assert exported.json()["human_reviewed"] is True and not exported.json()["awaiting_human_review"]
        assert client.post(f"/api/trials/{run_id}/review", json={"accepted": False}, headers=HEADERS).status_code == 409


def test_out_of_scope_attempt_and_counterfactual_budget_visible(tmp_path):
    with TestClient(create_app(tmp_path / "web", enable_live=False)) as client:
        initialize(client)
        careless = start(client, agent="demo_rushed")
        report = client.get(f"/api/trials/{careless}").json()["report"]
        assert report["attempted_out_of_scope_actions"] == 1 and report["real_world_side_effects"] == 0
        assert not report["drafts"] and report["execution_mode"] == "offline_script"
        smaller = start(client, budget_yuan=250)
        report = client.get(f"/api/trials/{smaller}").json()["report"]
        assert not report["drafts"] and report["termination"] == "model_finished"


def test_csrf_and_live_cost_gate(tmp_path):
    with TestClient(create_app(tmp_path / "web", enable_live=False)) as client:
        script = client.get("/assets/app.js")
        assert script.status_code == 200 and "javascript" in script.headers["content-type"]
        assert script.headers["x-content-type-options"] == "nosniff"
        assert client.post("/api/session", json={}).status_code == 403
        assert client.post("/api/session", json={}, headers={**HEADERS, "Origin": "https://other.invalid"}).status_code == 403
        initialize(client)
        assert client.post("/api/trials", json={"agent": "live", "confirmed": True}, headers=HEADERS).status_code == 403
        assert client.post("/api/trials", json={"dense": True, "confirmed": True}, headers=HEADERS).status_code == 422
        assert client.post("/api/trials", json={}, headers=HEADERS).status_code == 409


def test_interrupted_result_restores_without_duplicate_draft(tmp_path):
    root = tmp_path / "web"
    app = create_app(root, enable_live=False)
    with TestClient(app) as client:
        initialize(client)
        run_id = start(client)
        with sqlite3.connect(root / "web.sqlite") as db:
            db.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
        cookies = dict(client.cookies)
    with TestClient(create_app(root, enable_live=False)) as client:
        client.cookies.update(cookies)
        assert client.get(f"/api/trials/{run_id}").json()["status"] == "interrupted"
        assert client.post(f"/api/trials/{run_id}/resume", json={}, headers=HEADERS).status_code == 202
        restored = client.get(f"/api/trials/{run_id}").json()
        assert restored["status"] == "waiting_review" and len(restored["report"]["drafts"]) == 1
        assert len(restored["report"]["trace"]) == 2


def test_explicit_public_origin_works_behind_host_rewriting_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIALTRUST_PUBLIC_ORIGIN", "https://trial.example")
    with TestClient(create_app(tmp_path / "web", enable_live=False)) as client:
        response = client.post("/api/session", json={}, headers={**HEADERS, "Origin": "https://trial.example"})
        assert response.status_code == 200 and "Secure" in response.headers["set-cookie"]
        assert client.post("/api/session", json={}, headers={**HEADERS, "Origin": "https://attacker.example"}).status_code == 403
        assert client.post("/api/session", json={}, headers={**HEADERS, "Origin": "https://attacker.example", "X-Forwarded-Host": "trial.example"}).status_code == 403
        assert client.get("/health", headers={"Host": "unknown.example"}).status_code == 400

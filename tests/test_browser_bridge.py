"""Cross-origin transport must preserve the original account/owner boundaries."""
from fastapi.testclient import TestClient

from trialtrust.webapp import create_app

ORIGIN = "https://render.qmuse.pub"
PASSWORD = "Bridge-test-password-42"


def call(client, path, body=None, *, token=None, browser=None, method=None, origin=ORIGIN):
    headers = {}
    if token:
        headers["X-TrialTrust-Account"] = token
    if browser:
        headers["X-TrialTrust-Browser"] = browser
    return client.post("/api/browser-bridge", headers={"Origin": origin}, json={
        "path": path, "method": method or ("GET" if body is None else "POST"),
        "headers": headers, "body": body,
    })


def test_bridge_preserves_accounts_history_review_and_export(tmp_path):
    app = create_app(tmp_path / "web", enable_live=False, browser_origins=(ORIGIN,))
    with TestClient(app) as client:
        boot = call(client, "/api/auth/bootstrap", {})
        assert boot.status_code == 200
        assert boot.headers["access-control-allow-origin"] == ORIGIN
        assert "set-cookie" not in boot.headers
        browser = boot.json()["browser_token"]
        signup = call(client, "/api/auth/register", {"username": "bridge_alice", "password": PASSWORD,
                      "confirm_password": PASSWORD}, browser=browser)
        assert signup.status_code == 201, signup.text
        token = signup.json()["account_token"]
        conv = call(client, "/api/conversations", {}, token=token).json()["id"]
        trial = call(client, "/api/trials", {"confirmed": True}, token=token)
        assert trial.status_code == 202, trial.text
        run_id = trial.json()["id"]
        assert call(client, f"/api/trials/{run_id}", token=token).json()["status"] == "waiting_review"
        assert call(client, f"/api/trials/{run_id}/review", {"accepted": True}, token=token).status_code == 200
        assert call(client, f"/api/trials/{run_id}/export", token=token).json()["human_reviewed"] is True
        assert call(client, f"/api/trials?conversation_id={conv}", token=token).status_code == 200
        # Ambient first-party cookies never authenticate a bridged request.
        assert call(client, f"/api/trials/{run_id}").status_code == 401
        assert call(client, "/api/conversations").status_code == 401
        login = call(client, "/api/auth/login", {"username": "bridge_alice", "password": PASSWORD})
        assert login.status_code == 200
        assert call(client, "/api/conversations", token=login.json()["account_token"]).json()
        assert call(client, "/api/auth/logout", {}, token=token).status_code == 200
        assert call(client, "/api/conversations", token=token).status_code == 401


def test_bridge_rejects_unknown_origins_routes_and_headers(tmp_path):
    app = create_app(tmp_path / "web", enable_live=False, browser_origins=(ORIGIN,))
    with TestClient(app) as client:
        for path in ["https://evil.example/api/auth/bootstrap", "/api/browser-bridge", "/api/workbench", "/health", "/api/trials?unexpected=1", "/api/trials?conversation_id=a&conversation_id=b", "/api/conversations?account_token=secret"]:
            assert call(client, path, {}).status_code == 400
        assert call(client, "/api/auth/bootstrap", {}, origin="https://evil.example").status_code == 403
        assert call(client, "/api/auth/bootstrap", {}, origin="").status_code == 403
        bad = client.post("/api/browser-bridge", headers={"Origin": ORIGIN}, json={
            "path": "/api/auth/bootstrap", "method": "POST", "headers": {"Authorization": "arbitrary"}, "body": {},
        })
        assert bad.status_code == 400
        assert client.post("/api/browser-bridge", headers={"Origin": ORIGIN, "Content-Type": "application/json"},
                           content="x" * 1_048_577).status_code == 413
        assert client.options("/api/browser-bridge", headers={"Origin": ORIGIN}).status_code == 204
        # The original same-origin CSRF guard remains active.
        assert client.post("/api/auth/bootstrap", json={}, headers={"Origin": ORIGIN}).status_code == 403


def test_actual_managed_entrypoint_enables_bridge_and_keeps_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIALTRUST_RUNTIME", str(tmp_path / "web"))
    monkeypatch.setenv("TRIALTRUST_ENABLE_LIVE", "0")
    monkeypatch.delenv("TRIALTRUST_BROWSER_ORIGINS", raising=False)
    from trialtrust.managed import create_managed_app
    with TestClient(create_managed_app()) as client:
        response = call(client, "/api/auth/bootstrap", {})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["authenticated"] is False
        assert response.json()["browser_token"]
        assert call(client, "/api/conversations").status_code == 401
        assert call(client, "/api/auth/bootstrap", {}, origin="https://other.invalid").status_code == 403
        assert client.post("/api/auth/bootstrap", json={}).status_code == 403


def test_managed_bridge_can_be_disabled_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIALTRUST_RUNTIME", str(tmp_path / "web"))
    monkeypatch.setenv("TRIALTRUST_BROWSER_ORIGINS", "")
    from trialtrust.managed import create_managed_app
    with TestClient(create_managed_app()) as client:
        assert call(client, "/api/auth/bootstrap", {}).status_code == 403

"""Exercise the Docker portal boundary independently of the Gradio SDK."""
from fastapi.testclient import TestClient
from trialtrust.managed import create_managed_app
from trialtrust.webapp import create_app


def test_managed_docker_keeps_origin_host_and_anonymous_session_boundaries(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIALTRUST_RUNTIME", str(tmp_path / "managed"))
    monkeypatch.setenv("TRIALTRUST_ENABLE_LIVE", "0")
    monkeypatch.setenv("TRIALTRUST_PUBLIC_ORIGIN", "https://trial.example")
    monkeypatch.setenv("TRIALTRUST_ALLOWED_HOSTS", "testserver,trial.example")
    with TestClient(create_managed_app(), base_url="https://trial.example") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "X-Frame-Options" not in response.headers
        csp = response.headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp
        assert "frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn" in csp
        assert client.get("/api/workbench-assets/workbench_tools.js").status_code == 200
        assert client.get("/health", headers={"Host":"service.cn-beijing-vpc.fcapp.run"}).status_code == 200
        assert client.get("/health", headers={"Host":"service.cn-beijing-vpc.fcapp.run.evil.invalid"}).status_code == 400
        headers = {"X-TrialTrust-Client":"web", "Origin":"https://trial.example"}
        session = client.post("/api/session",json={},headers=headers)
        assert session.status_code == 200
        token = session.json()["session_token"]
        client.cookies.clear()
        assert client.get("/api/conversations").status_code == 401
        capability = {**headers,"X-TrialTrust-Session":token}
        row = client.post("/api/conversations", json={}, headers=capability).json()
        assert client.patch("/api/conversations/"+row["id"],json={"title":"Docker练习"},headers=capability).status_code == 200
        assert client.post("/api/conversations",json={},headers={**capability,"Origin":"https://evil.invalid"}).status_code == 403
        assert client.delete("/api/conversations/"+row["id"],headers=capability).status_code == 200


def test_standalone_mode_still_refuses_framing_and_header_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIALTRUST_ALLOWED_HOSTS", "testserver")
    with TestClient(create_app(tmp_path / "standalone", enable_live=False)) as client:
        response = client.get("/")
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert client.get("/api/conversations",headers={"X-TrialTrust-Session":"untrusted"}).status_code == 401

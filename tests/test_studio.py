# These regressions exercise the explicitly enabled legacy anonymous migration mode.
# The deployed factories default to accounts; tests/test_accounts.py covers that boundary.
"""Deployment-specific integration check, separate from the core-only image."""
import importlib.util

import pytest
from fastapi.testclient import TestClient


@pytest.mark.skipif(importlib.util.find_spec("gradio") is None, reason="Studio optional dependency")
def test_managed_gradio_config_and_core_session_remain_connected(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIALTRUST_RUNTIME", str(tmp_path / "web"))
    monkeypatch.setenv("TRIALTRUST_ENABLE_LIVE", "0")
    monkeypatch.setenv("TRIALTRUST_PUBLIC_ORIGIN", "https://trial.example")
    monkeypatch.setenv("TRIALTRUST_ALLOWED_HOSTS", "testserver,trial.example")
    from app import create_studio_app
    with TestClient(create_studio_app(require_accounts=False), base_url="https://trial.example") as client:
        response = client.get("/config")
        assert response.status_code == 200
        component = next(c for c in response.json()["components"] if c["type"] == "html")
        assert 'id="run-suite"' in component["props"]["value"]
        assert "root.querySelector" in component["props"]["js_on_load"]
        assert "modelscope.cn" in response.headers["Content-Security-Policy"]
        assert "X-Frame-Options" not in response.headers
        import re
        asset = re.search(r'src="([^"]+/assets/[^"]+\.js)"', client.get("/").text)
        assert asset is not None
        assert client.get(asset.group(1)).status_code == 200
        direct = client.get('/api/workbench')
        assert direct.status_code == 200 and 'id="confirmed"' in direct.text
        assert 'X-Frame-Options' not in direct.headers
        assert "frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn" in direct.headers['Content-Security-Policy']
        assert "script-src 'self'" in direct.headers['Content-Security-Policy']
        assert '/api/workbench-assets/app.js' in direct.text
        script = client.get('/api/workbench-assets/app.js')
        assert script.status_code == 200 and 'javascript' in script.headers['content-type']
        assert client.get('/api/workbench-assets/style.css').status_code == 200
        assert client.get('/api/workbench-assets/portal_viewport.js').status_code == 200
        assert 'PortalViewport' in component['props']['js_on_load']
        assert client.get("/health", headers={"Host": "studio-changed-123.cn-beijing-vpc.fcapp.run"}).status_code == 200
        assert client.get("/health", headers={"Host": "studio-changed-123.cn-beijing-vpc.fcapp.run.evil.invalid"}).status_code == 400
        headers = {"X-TrialTrust-Client": "web", "Origin": "https://trial.example"}
        session = client.post("/api/session", json={}, headers=headers)
        assert session.status_code == 200
        token = session.json()["session_token"]
        client.cookies.clear()  # Simulate the portal iframe blocking cookies.
        assert client.get("/api/trials").status_code == 401
        assert client.get("/api/trials", headers={"X-TrialTrust-Session": token}).json() == []
        capability = {**headers, "X-TrialTrust-Session": token}
        conversation = client.post('/api/conversations', json={}, headers=capability)
        assert conversation.status_code == 201
        assert client.get('/api/conversations', headers=capability).json()[0]['id'] == conversation.json()['id']
        assert client.get('/api/trials', params={'conversation_id': conversation.json()['id']}, headers=capability).json() == []
        assert client.post("/api/session", json={}, headers={**headers, "Origin": "https://other.invalid"}).status_code == 403


@pytest.mark.skipif(importlib.util.find_spec("gradio") is None, reason="Studio optional dependency")
def test_native_gradio_defaults_to_accounts_and_retains_account_history(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIALTRUST_RUNTIME", str(tmp_path / "web"))
    monkeypatch.setenv("TRIALTRUST_ENABLE_LIVE", "0")
    monkeypatch.setenv("TRIALTRUST_PUBLIC_ORIGIN", "https://trial.example")
    monkeypatch.setenv("TRIALTRUST_ALLOWED_HOSTS", "testserver,trial.example")
    from app import create_studio_app
    headers = {"X-TrialTrust-Client": "web", "Origin": "https://trial.example"}
    with TestClient(create_studio_app(), base_url="https://trial.example") as client:
        assert client.get("/api/conversations").status_code == 401
        assert client.post("/api/session", json={}, headers=headers).json()["auth_required"]
        assert client.get("/api/workbench").status_code == 200
        assert client.post("/api/auth/bootstrap", json={}, headers=headers).status_code == 200
        registered = client.post("/api/auth/register", json={"username":"native_studio_test", "password":"Native-test-only-92751", "confirm_password":"Native-test-only-92751"}, headers=headers)
        assert registered.status_code == 201
        conversation = client.post("/api/conversations", json={}, headers=headers)
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]
        storage_id = client.get("/api/account/storage").json()["storage_id"]
        assert client.post("/api/auth/logout",json={},headers=headers).status_code == 200
        assert client.get("/api/conversations").status_code == 401
    with TestClient(create_studio_app(), base_url="https://trial.example") as client:
        assert client.get("/api/conversations").status_code == 401
        assert client.post("/api/auth/login", json={"username":"native_studio_test", "password":"Native-test-only-92751"}, headers=headers).status_code == 200
        assert client.get("/api/account/storage").json()["storage_id"] == storage_id
        assert conversation_id in {row["id"] for row in client.get("/api/conversations").json()}

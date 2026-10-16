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
    with TestClient(create_studio_app(), base_url="https://trial.example") as client:
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
        assert direct.headers['X-Frame-Options'] == 'DENY'
        assert "script-src 'self'" in direct.headers['Content-Security-Policy']
        assert '/api/workbench-assets/app.js' in direct.text
        script = client.get('/api/workbench-assets/app.js')
        assert script.status_code == 200 and 'javascript' in script.headers['content-type']
        assert client.get('/api/workbench-assets/style.css').status_code == 200
        assert client.get("/health", headers={"Host": "studio-changed-123.cn-beijing-vpc.fcapp.run"}).status_code == 200
        assert client.get("/health", headers={"Host": "studio-changed-123.cn-beijing-vpc.fcapp.run.evil.invalid"}).status_code == 400
        headers = {"X-TrialTrust-Client": "web", "Origin": "https://trial.example"}
        session = client.post("/api/session", json={}, headers=headers)
        assert session.status_code == 200
        token = session.json()["session_token"]
        client.cookies.clear()  # Simulate the portal iframe blocking cookies.
        assert client.get("/api/trials").status_code == 401
        assert client.get("/api/trials", headers={"X-TrialTrust-Session": token}).json() == []
        assert client.post("/api/session", json={}, headers={**headers, "Origin": "https://other.invalid"}).status_code == 403

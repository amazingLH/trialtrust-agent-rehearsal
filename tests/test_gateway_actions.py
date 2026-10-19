from fastapi.testclient import TestClient
from trialtrust.webapp import create_app

H = {"X-TrialTrust-Client":"web"}


def initialize(c):
    c.post("/api/session",json={},headers=H).raise_for_status()
    return c.post("/api/conversations",json={},headers=H).json()["id"]


def test_gateway_actions_require_typed_explicit_confirmation(tmp_path):
    with TestClient(create_app(tmp_path,enable_live=False)) as c:
        cid=initialize(c);url=f"/api/conversations/{cid}/actions"
        for body in [{"operation":"delete"},{"operation":"delete","confirmed":"true"},{"operation":"delete","confirmed":True,"title":"other"},{"operation":"run","confirmed":True},{"operation":"rename","confirmed":True},{"operation":"rename","title":"  ","confirmed":True}]:
            assert c.post(url,json=body,headers=H).status_code == 422
        assert c.post(url,json={"operation":"delete","confirmed":False},headers=H).status_code == 409
        assert any(r["id"]==cid for r in c.get("/api/conversations").json())
        assert c.post(url,json={"operation":"rename","title":"  我的练习  ","confirmed":True},headers=H).json()["title"] == "我的练习"
        assert c.post(url,json={"operation":"delete","confirmed":True},headers=H).status_code == 200
        assert not any(r["id"]==cid for r in c.get("/api/conversations").json())


def test_gateway_action_rejects_other_owners_and_cross_origin(tmp_path):
    app=create_app(tmp_path,enable_live=False)
    with TestClient(app) as owner, TestClient(app) as other:
        cid=initialize(owner);initialize(other);url=f"/api/conversations/{cid}/actions"
        body={"operation":"delete","confirmed":True}
        assert other.post(url,json=body,headers=H).status_code == 404
        assert owner.post(url,json=body,headers={**H,"Origin":"https://evil.invalid"}).status_code == 403
        assert any(r["id"]==cid for r in owner.get("/api/conversations").json())

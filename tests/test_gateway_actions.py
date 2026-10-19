# These regressions exercise the explicitly enabled legacy anonymous migration mode.
# The deployed factories default to accounts; tests/test_accounts.py covers that boundary.
import sqlite3
from fastapi.testclient import TestClient
from trialtrust.webapp import create_app

H = {"X-TrialTrust-Client":"web"}


def initialize(c):
    c.post("/api/session",json={},headers=H).raise_for_status()
    return c.post("/api/conversations",json={},headers=H).json()["id"]


def body(c,cid,**overrides):
    row=next(r for r in c.get("/api/conversations").json() if r["id"]==cid)
    return {"operation":"delete","confirmed":True,"expected_updated":row["updated"],**overrides}


def test_gateway_actions_require_typed_explicit_confirmation(tmp_path):
    with TestClient(create_app(tmp_path,enable_live=False, require_accounts=False)) as c:
        cid=initialize(c);url=f"/api/conversations/{cid}/actions"
        valid=body(c,cid)
        for bad in [{"operation":"delete"},{**valid,"confirmed":"true"},{**valid,"title":"other"},{**valid,"operation":"run"},{**valid,"operation":"rename"},{**valid,"operation":"rename","title":"  "},{**valid,"expected_updated":"1"}]:
            assert c.post(url,json=bad,headers=H).status_code == 422
        assert c.post(url,json={**valid,"confirmed":False},headers=H).status_code == 409
        assert any(r["id"]==cid for r in c.get("/api/conversations").json())
        assert c.post(url,json={**valid,"operation":"rename","title":"  我的练习  "},headers=H).json()["title"] == "我的练习"
        assert c.post(url,json=body(c,cid),headers=H).status_code == 200
        assert not any(r["id"]==cid for r in c.get("/api/conversations").json())


def test_gateway_action_rejects_other_owners_and_cross_origin(tmp_path):
    app=create_app(tmp_path,enable_live=False, require_accounts=False)
    with TestClient(app) as owner, TestClient(app) as other:
        cid=initialize(owner);initialize(other);url=f"/api/conversations/{cid}/actions"
        request=body(owner,cid)
        assert other.post(url,json=request,headers=H).status_code == 404
        assert owner.post(url,json=request,headers={**H,"Origin":"https://evil.invalid"}).status_code == 403
        assert any(r["id"]==cid for r in owner.get("/api/conversations").json())


def test_stale_dialog_does_not_remove_changed_conversation(tmp_path):
    with TestClient(create_app(tmp_path,enable_live=False, require_accounts=False)) as c:
        cid=initialize(c);url=f"/api/conversations/{cid}/actions";stale=body(c,cid)
        c.patch(f"/api/conversations/{cid}",json={"title":"更新后的条件"},headers=H).raise_for_status()
        assert c.post(url,json=stale,headers=H).status_code == 409
        assert next(r for r in c.get("/api/conversations").json() if r["id"]==cid)["title"] == "更新后的条件"


def test_gateway_deletion_hides_rounds_and_does_not_allow_old_exports(tmp_path):
    with TestClient(create_app(tmp_path,enable_live=False, require_accounts=False)) as c:
        cid=initialize(c)
        run=c.post("/api/trials",json={"confirmed":True,"agent":"demo_careful"},headers={**H,"X-TrialTrust-Conversation":cid})
        assert run.status_code == 202
        rid=run.json()["id"]
        assert c.post(f"/api/conversations/{cid}/actions",json=body(c,cid),headers=H).status_code == 200
        assert c.get(f"/api/trials/{rid}").status_code == 404
        assert c.get(f"/api/trials/{rid}/export").status_code == 404
        assert c.post(f"/api/trials/{rid}/review",json={"accepted":True},headers=H).status_code == 404


def test_gateway_deletion_refuses_running_conversation(tmp_path):
    with TestClient(create_app(tmp_path,enable_live=False, require_accounts=False)) as c:
        cid=initialize(c)
        r=c.post("/api/trials",json={"confirmed":True,"agent":"demo_careful"},headers={**H,"X-TrialTrust-Conversation":cid})
        assert r.status_code == 202
        with sqlite3.connect(tmp_path/"web.sqlite") as db:
            db.execute("UPDATE runs SET status='running' WHERE id=?",(r.json()["id"],))
        assert c.post(f"/api/conversations/{cid}/actions",json=body(c,cid),headers=H).status_code == 409

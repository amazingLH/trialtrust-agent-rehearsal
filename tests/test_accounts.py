"""Production-default account boundaries, SQLite durability and browser binding."""
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import bcrypt
import pytest
from fastapi.testclient import TestClient

from trialtrust.webapp import create_app, Store

H = {"X-TrialTrust-Client": "web"}
PASSWORD = "A-test-password-42"

def register(client, username="alice_test", **extra):
    boot=client.post("/api/auth/bootstrap",json={},headers=H)
    assert boot.status_code==200
    return client.post("/api/auth/register",json={"username":username,"password":PASSWORD,
        "confirm_password":PASSWORD,**extra},headers=H)

def login(client, username="alice_test", password=PASSWORD):
    return client.post("/api/auth/login",json={"username":username,"password":password},headers=H)

def app(root):
    return create_app(root,enable_live=False)

def test_default_gate_and_secret_validation(tmp_path):
    with TestClient(app(tmp_path)) as c:
        assert c.get("/").status_code==200
        assert c.post("/api/session",json={},headers=H).json()["authenticated"] is False
        for path in ["/api/catalog","/api/skills","/api/conversations","/api/trials","/api/account/storage"]:
            assert c.get(path).status_code==401
        assert c.post("/api/conversations",json={},headers=H).status_code==401
        for body in [dict(username="a",password="sensitive-short"),dict(username="alice_test",password="密"*30),dict(username="alice_test",password=PASSWORD,unexpected="SECRET")]:
            r=c.post("/api/auth/login",json=body,headers=H)
            assert r.status_code==422 and body["password"] not in r.text and "SECRET" not in r.text
        assert c.post("/api/auth/register",json={},headers={**H,"Origin":"https://evil.example"}).status_code==403
        assert c.post("/api/auth/bootstrap",json={}).status_code==403

def test_register_hash_device_binding_and_logout(tmp_path):
    with TestClient(app(tmp_path)) as c:
        r=register(c);assert r.status_code==201,r.text
        assert "HttpOnly" in r.headers["set-cookie"]
        assert len(r.json()["recovery_code"])>=40 and "password" not in r.json()
        with sqlite3.connect(tmp_path/"web.sqlite") as db:
            row=db.execute("SELECT password_hash,recovery_hash FROM account_users").fetchone()
            assert row[0]!=PASSWORD and row[0].startswith("$2b$12$")
            assert bcrypt.checkpw(PASSWORD.encode(),row[0].encode())
            assert row[1]!=r.json()["recovery_code"]
        assert register(c,"second_user").status_code==409
        assert c.post("/api/auth/logout",json={},headers=H).json()["logged_out"]
        assert c.get("/api/conversations").status_code==401
        assert c.post("/api/auth/bootstrap",json={},headers=H).json()["browser_registered"]
        assert login(c).status_code==200

def test_accounts_are_isolated_and_login_from_another_browser(tmp_path):
    a=app(tmp_path)
    with TestClient(a) as c,TestClient(a) as other,TestClient(a) as another:
        assert register(c).status_code==201
        conv=c.post("/api/conversations",json={},headers=H).json()["id"]
        trial=c.post("/api/trials",json={"confirmed":True},headers={**H,"X-TrialTrust-Conversation":conv})
        assert trial.status_code==202
        rid=trial.json()["id"]
        assert register(other,"bob_test").status_code==201
        assert other.get("/api/conversations").json()==[]
        for path in [f"/api/trials/{rid}",f"/api/trials/{rid}/export",f"/api/trials?conversation_id={conv}"]:
            assert other.get(path).status_code==404
        assert other.post(f"/api/trials/{rid}/review",json={"accepted":True},headers=H).status_code==404
        assert other.post(f"/api/conversations/{conv}/actions",json={"operation":"delete","confirmed":True,"expected_updated":time.time()},headers=H).status_code==404
        assert login(another).status_code==200
        assert another.get("/api/conversations").json()[0]["id"]==conv
        assert another.get(f"/api/trials/{rid}").status_code==200

def test_sqlite_restart_and_session_expiry(tmp_path):
    with TestClient(app(tmp_path)) as c:
        assert register(c).status_code==201
        conv=c.post("/api/conversations",json={},headers=H).json()["id"]
        storage=c.get("/api/account/storage").json();cookies=dict(c.cookies)
    with TestClient(app(tmp_path)) as c:
        c.cookies.update(cookies)
        after=c.get("/api/account/storage").json()
        assert after["storage_id"]==storage["storage_id"] and after["boot_id"]!=storage["boot_id"]
        assert after["startup_backup_exists"]
        assert c.get("/api/conversations").json()[0]["id"]==conv
        with sqlite3.connect(tmp_path/"web.sqlite") as db:db.execute("UPDATE account_sessions SET expires=0")
        assert c.get("/api/conversations").status_code==401
        assert login(c).status_code==200
        assert c.get("/api/conversations").json()[0]["id"]==conv

def test_password_change_recovery_and_revocation(tmp_path):
    a=app(tmp_path)
    with TestClient(a) as c,TestClient(a) as other:
        code=register(c).json()["recovery_code"]
        assert login(other).status_code==200
        changed=c.post("/api/auth/password",json={"current_password":PASSWORD,"new_password":"Changed-password-2026"},headers=H)
        assert changed.status_code==200
        assert other.get("/api/conversations").status_code==401
        assert c.get("/api/conversations").status_code==401
        assert login(c).status_code==401
        assert login(c,password="Changed-password-2026").status_code==200
        body={"username":"alice_test","password":"Recovered-password-2026","confirm_password":"Recovered-password-2026","recovery_code":code}
        recovered=c.post("/api/auth/recover",json=body,headers=H)
        assert recovered.status_code==200 and recovered.json()["recovery_code"]!=code
        assert c.get("/api/conversations").status_code==401
        assert c.post("/api/auth/recover",json=body,headers=H).status_code==401
        assert login(c,password="Recovered-password-2026").status_code==200

def test_legacy_history_only_claimed_with_valid_capability_and_explicit_choice(tmp_path):
    store=Store(tmp_path);legacy=store.new_session();owner=store.owner(legacy)
    conv=store.new_conversation(owner)["id"]
    a=app(tmp_path)
    with TestClient(a) as c:
        c.cookies.set("trialtrust_session",legacy)
        assert c.post("/api/auth/bootstrap",json={},headers=H).json()["legacy_available"]
        assert c.get("/api/conversations").status_code==401
        r=register(c,import_history=True);assert r.status_code==201
        assert r.json()["imported_conversations"]==1
        assert c.get("/api/conversations").json()[0]["id"]==conv
        assert store.owner(legacy) is None
    # A fresh account cannot claim an expired/foreign identity merely by knowing IDs.
    with TestClient(a) as other:
        assert register(other,"bob_test",import_history=True).status_code==201
        assert other.get("/api/conversations").json()==[]

def test_managed_fallback_is_tab_scoped_and_standalone_ignores_it(tmp_path):
    a=app(tmp_path);a.state.studio_ui=True
    with TestClient(a,base_url="https://testserver") as c:
        b=c.post("/api/auth/bootstrap",json={},headers=H).json();c.cookies.clear()
        h={**H,"X-TrialTrust-Browser":b["browser_token"]}
        r=c.post("/api/auth/register",json={"username":"alice_test","password":PASSWORD,"confirm_password":PASSWORD},headers=h)
        assert r.status_code==201 and "Secure" in r.headers["set-cookie"]
        token=r.json()["account_token"];c.cookies.clear()
        h={**h,"X-TrialTrust-Account":token}
        assert c.get("/api/conversations",headers=h).status_code==200
        assert c.post("/api/auth/logout",json={},headers=h).status_code==200
        assert c.get("/api/conversations",headers=h).status_code==401
    with TestClient(app(tmp_path/"standalone")) as c:
        assert c.get("/api/conversations",headers={"X-TrialTrust-Account":token}).status_code==401

def test_case_insensitive_unique_names_and_invalid_passwords(tmp_path):
    a=app(tmp_path)
    with TestClient(a) as c,TestClient(a) as other:
        assert register(c,"Alice_Test").status_code==201
        assert register(other,"alice_test").status_code==409
        assert login(other,"ALICE_TEST").status_code==200
        assert login(c,password="incorrect-password").status_code==401
        assert login(c,username="unknown_name").json()["detail"]==login(c,password="incorrect-password").json()["detail"]

def test_registration_race_is_atomic(tmp_path):
    a=app(tmp_path)
    with TestClient(a) as c:
        c.post("/api/auth/bootstrap",json={},headers=H);cookies=dict(c.cookies)
    def attempt(name):
        with TestClient(a) as c:
            c.cookies.update(cookies)
            return c.post("/api/auth/register",json={"username":name,"password":PASSWORD,"confirm_password":PASSWORD},headers=H).status_code
    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(attempt,["race_user_a","race_user_b"]))==[201,409]

def test_login_throttle_is_persistent(tmp_path):
    a=app(tmp_path)
    with TestClient(a) as c:
        assert register(c).status_code==201
        with sqlite3.connect(tmp_path/"web.sqlite") as db:
            from trialtrust.accounts import digest
            db.execute("INSERT INTO auth_limits VALUES (?,?,?)",("login-user:"+digest("alice_test"),15,time.time()+900))
        assert login(c).status_code==429
    with TestClient(app(tmp_path)) as c:assert login(c).status_code==429


def test_valid_legacy_history_not_imported_without_opt_in(tmp_path):
    store=Store(tmp_path);legacy=store.new_session();owner=store.owner(legacy)
    conv=store.new_conversation(owner)["id"]
    with TestClient(app(tmp_path)) as c:
        c.cookies.set("trialtrust_session",legacy)
        result=register(c)
        assert result.status_code==201 and result.json()["imported_conversations"]==0
        assert c.get("/api/conversations").json()==[]
        assert store.conversation(conv,owner)["owner"]==owner


def test_running_legacy_import_rolls_back_registration_and_binding(tmp_path):
    from trialtrust.scenarios import RunSpec
    store=Store(tmp_path);legacy=store.new_session();owner=store.owner(legacy)
    with TestClient(app(tmp_path)) as c:
        store.create(owner,RunSpec(confirmed=True))
        c.cookies.set("trialtrust_session",legacy)
        assert register(c,import_history=True).status_code==409
        with store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM account_users").fetchone()[0]==0
            assert db.execute("SELECT COUNT(*) FROM browser_devices WHERE user_id IS NOT NULL").fetchone()[0]==0
        assert store.owner(legacy)==owner


def test_platform_managed_chmod_does_not_prevent_auth_or_sqlite(tmp_path,monkeypatch):
    import errno
    from pathlib import Path
    def refused(*a,**kw):raise PermissionError(errno.EPERM,"platform-owned modes")
    with monkeypatch.context() as m:
        m.setattr(Path,"chmod",refused)
        a=app(tmp_path)
    with TestClient(a) as c:
        assert register(c).status_code==201
        assert c.get("/api/account/storage").json()["file_permissions_managed_by_platform"] is True
        assert c.post("/api/conversations",json={},headers=H).status_code==201


def test_unexpected_storage_mode_errors_are_not_swallowed(tmp_path,monkeypatch):
    import errno
    from pathlib import Path
    def broken(*a,**kw):raise OSError(errno.EIO,"storage I/O failed")
    with monkeypatch.context() as m:
        m.setattr(Path,"chmod",broken)
        with pytest.raises(OSError,match="storage I/O failed"):app(tmp_path)

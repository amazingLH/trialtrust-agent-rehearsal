# These regressions exercise the explicitly enabled legacy anonymous migration mode.
# The deployed factories default to accounts; tests/test_accounts.py covers that boundary.
import json
import sqlite3
import time

import pytest

from fastapi.testclient import TestClient

from trialtrust.webapp import Store, create_app


HEADERS = {"X-TrialTrust-Client": "web"}


def initialize(client):
    assert client.post("/api/session", json={}, headers=HEADERS).status_code == 200


def conversation(client):
    result = client.post("/api/conversations", json={}, headers=HEADERS)
    assert result.status_code == 201
    return result.json()["id"]


def run(client, conversation_id, budget=300):
    response = client.post("/api/trials", json={"confirmed": True, "budget_yuan": budget},
                           headers={**HEADERS, "X-TrialTrust-Conversation": conversation_id})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_conversations_group_rounds_and_new_one_preserves_history(tmp_path):
    with TestClient(create_app(tmp_path / "web", enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        one, two = run(client, first), run(client, first, budget=350)
        second = conversation(client)
        assert client.get("/api/trials", params={"conversation_id": second}).json() == []
        rows = client.get("/api/trials", params={"conversation_id": first}).json()
        assert {row["id"] for row in rows} == {one, two}
        assert {row["conversation_id"] for row in rows} == {first}
        sessions = {row["id"]: row for row in client.get("/api/conversations").json()}
        assert sessions[first]["run_count"] == 2 and sessions[first]["title"] == "周末陶艺"
        assert sessions[second]["run_count"] == 0


def test_foreign_conversation_cannot_be_listed_or_written(tmp_path):
    app = create_app(tmp_path / "web", enable_live=False, require_accounts=False)
    with TestClient(app) as a, TestClient(app) as b:
        initialize(a)
        initialize(b)
        first = conversation(a)
        run(a, first)
        assert b.get("/api/conversations").json() == []
        assert b.get("/api/trials", params={"conversation_id": first}).status_code == 404
        denied = b.post("/api/trials", json={"confirmed": True},
                        headers={**HEADERS, "X-TrialTrust-Conversation": first})
        assert denied.status_code == 404
        assert b.get("/api/trials").json() == []


def test_unconfirmed_continuation_does_not_create_a_round(tmp_path):
    with TestClient(create_app(tmp_path / "web", enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        run(client, first)
        for endpoint in ["trials", "suites"]:
            response = client.post("/api/" + endpoint, json={"confirmed": False},
                                   headers={**HEADERS, "X-TrialTrust-Conversation": first})
            assert response.status_code == 409
        assert len(client.get("/api/trials", params={"conversation_id": first}).json()) == 1


def test_browser_identity_survives_app_restart_and_review_stays_attached(tmp_path):
    root = tmp_path / "web"
    with TestClient(create_app(root, enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        run_id = run(client, first)
        cookies = dict(client.cookies)
    with TestClient(create_app(root, enable_live=False, require_accounts=False)) as client:
        client.cookies.update(cookies)
        assert client.get("/api/conversations").json()[0]["id"] == first
        result = client.post(f"/api/trials/{run_id}/review", json={"accepted": False}, headers=HEADERS)
        assert result.status_code == 200
        row = client.get(f"/api/trials/{run_id}").json()
        assert row["conversation_id"] == first and row["status"] == "reviewed"
        assert row["reviewed"] == 0


def test_legacy_schema_migration_is_idempotent_and_preserves_reports(tmp_path):
    root = tmp_path / "web"
    root.mkdir()
    report = json.dumps({"trace": ["historical evidence"], "human_reviewed": False})
    with sqlite3.connect(root / "web.sqlite") as db:
        db.executescript("""CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, expires REAL);
            CREATE TABLE runs(id TEXT PRIMARY KEY,owner TEXT,spec TEXT,status TEXT,
                stage TEXT,report TEXT,error TEXT,created REAL,reviewed INTEGER);""")
        for run_id, owner in [("old-a", "owner-a"), ("old-b", "owner-b")]:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                       (run_id, owner, "{}", "reviewed", "saved", report, None, 1.0, 0))
    store = Store(root)
    first = store.conversations("owner-a")
    assert len(first) == 1 and first[0]["run_count"] == 1
    assert store.conversations("owner-a") == first
    assert store.owned("old-a", "owner-a")["report"] == report
    assert store.owned("old-b", "owner-b")["conversation_id"] is None
    Store(root)  # Another process start does not regroup already migrated rows.
    assert store.conversations("owner-a") == first


def test_expired_anonymous_identity_does_not_expose_old_history(tmp_path):
    root = tmp_path / "web"
    with TestClient(create_app(root, enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        run(client, first)
        with sqlite3.connect(root / "web.sqlite") as db:
            db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
        assert client.get("/api/conversations").status_code == 401
        initialize(client)
        assert client.get("/api/conversations").json() == []
        assert client.get("/api/trials", params={"conversation_id": first}).status_code == 404


def test_conversation_creation_requires_same_origin_and_valid_owner(tmp_path):
    with TestClient(create_app(tmp_path / "web", enable_live=False, require_accounts=False)) as client:
        assert client.post("/api/conversations", json={}, headers=HEADERS).status_code == 401
        initialize(client)
        assert client.post("/api/conversations", json={}).status_code == 403
        assert client.post("/api/conversations", json={},
                           headers={**HEADERS, "Origin": "https://other.invalid"}).status_code == 403
        assert client.get("/api/conversations").json() == []


def test_rename_is_persistent_and_never_overwritten_by_first_run(tmp_path):
    root = tmp_path / "web"
    with TestClient(create_app(root, enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        assert client.patch(f"/api/conversations/{first}", json={"title": "  新会话  "}, headers=HEADERS).status_code == 200
        run(client, first)
        assert client.get("/api/conversations").json()[0]["title"] == "新会话"
        assert client.patch(f"/api/conversations/{first}", json={"title": "周六聚会预算对照"}, headers=HEADERS).status_code == 200
        cookies = dict(client.cookies)
    with TestClient(create_app(root, enable_live=False, require_accounts=False)) as client:
        client.cookies.update(cookies)
        assert client.get("/api/conversations").json()[0]["title"] == "周六聚会预算对照"


def test_deleted_conversation_and_all_its_rounds_are_inaccessible(tmp_path):
    root = tmp_path / "web"
    with TestClient(create_app(root, enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        runs = [run(client, first), run(client, first, budget=350)]
        other = conversation(client)
        kept = run(client, other)
        assert client.delete(f"/api/conversations/{first}", headers=HEADERS).status_code == 200
        assert [row["id"] for row in client.get("/api/conversations").json()] == [other]
        assert [row["id"] for row in client.get("/api/trials").json()] == [kept]
        assert client.get("/api/trials", params={"conversation_id": first}).status_code == 404
        for run_id in runs:
            for suffix in ["", "/export"]:
                assert client.get(f"/api/trials/{run_id}{suffix}").status_code == 404
            assert client.post(f"/api/trials/{run_id}/review", json={"accepted": True}, headers=HEADERS).status_code == 404
            assert client.post(f"/api/trials/{run_id}/resume", json={}, headers=HEADERS).status_code == 404
        assert client.post("/api/trials", json={"confirmed": True}, headers={**HEADERS, "X-TrialTrust-Conversation": first}).status_code == 404
        assert client.patch(f"/api/conversations/{first}", json={"title": "cannot return"}, headers=HEADERS).status_code == 404
        assert client.delete(f"/api/conversations/{first}", headers=HEADERS).status_code == 404
        Store(root)  # Schema migration and legacy grouping must not resurrect it.
        assert [row["id"] for row in client.get("/api/conversations").json()] == [other]
        with sqlite3.connect(root / "web.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 3


@pytest.mark.parametrize("title", ["", "   ", "x" * 61, "a\nb", "a\x00b", 123, None])
def test_invalid_conversation_titles_are_rejected(tmp_path, title):
    with TestClient(create_app(tmp_path / "web", enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        assert client.patch(f"/api/conversations/{first}", json={"title": title}, headers=HEADERS).status_code == 422
        assert client.get("/api/conversations").json()[0]["title"] == "新会话"


def test_conversation_mutations_are_owner_and_origin_scoped(tmp_path):
    app = create_app(tmp_path / "web", enable_live=False, require_accounts=False)
    with TestClient(app) as a, TestClient(app) as b:
        initialize(a)
        initialize(b)
        first = conversation(a)
        for method, body in [("PATCH", {"title": "changed"}), ("DELETE", None)]:
            url = f"/api/conversations/{first}"
            assert b.request(method, url, json=body, headers=HEADERS).status_code == 404
            assert a.request(method, url, json=body).status_code == 403
            assert a.request(method, url, json=body, headers={**HEADERS, "Origin": "https://foreign.invalid"}).status_code == 403
        assert a.get("/api/conversations").json()[0]["title"] == "新会话"


def test_running_conversation_cannot_be_renamed_or_deleted(tmp_path):
    from fastapi import HTTPException
    from trialtrust.scenarios import RunSpec
    store = Store(tmp_path / "web")
    first = store.new_conversation("owner-a")["id"]
    run_id = store.create("owner-a", RunSpec(confirmed=True), conversation_id=first)
    for title in [None, "later"]:
        with pytest.raises(HTTPException) as caught:
            store.change_conversation(first, "owner-a", title=title)
        assert caught.value.status_code == 409
    store.update(run_id, status="interrupted")
    assert store.change_conversation(first, "owner-a")["deleted"] is True


def test_deletion_does_not_reset_daily_run_quota(tmp_path):
    from fastapi import HTTPException
    from trialtrust.scenarios import RunSpec
    store = Store(tmp_path / "web")
    for _ in range(20):
        first = store.new_conversation("owner-a")["id"]
        run_id = store.create("owner-a", RunSpec(confirmed=True), conversation_id=first)
        store.update(run_id, status="interrupted")
        store.change_conversation(first, "owner-a")
    first = store.new_conversation("owner-a")["id"]
    with pytest.raises(HTTPException) as caught:
        store.create("owner-a", RunSpec(confirmed=True), conversation_id=first)
    assert caught.value.status_code == 429


def test_gateway_compatible_post_actions_preserve_owner_isolation(tmp_path):
    app = create_app(tmp_path / "web", enable_live=False, require_accounts=False)
    with TestClient(app) as a, TestClient(app) as b:
        initialize(a)
        initialize(b)
        first = conversation(a)
        assert a.post(f"/api/conversations/{first}/rename", json={"title":"兼容入口"}, headers=HEADERS).status_code == 200
        for action,body in [("rename",{"title":"not owned"}),("delete",{"confirmed":True})]:
            url=f"/api/conversations/{first}/{action}"
            assert b.post(url,json=body,headers=HEADERS).status_code == 404
            assert a.post(url,json=body,headers={**HEADERS,"Origin":"https://foreign.invalid"}).status_code == 403
        assert a.get("/api/conversations").json()[0]["title"] == "兼容入口"
        assert a.post(f"/api/conversations/{first}/delete",json={"confirmed":True},headers=HEADERS).status_code == 200
        assert a.get("/api/conversations").json() == []


def test_post_deletion_requires_true_boolean_confirmation(tmp_path):
    with TestClient(create_app(tmp_path / "web", enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        for body,status in [({},422),({"confirmed":"true"},422),({"confirmed":False},409)]:
            assert client.post(f"/api/conversations/{first}/delete",json=body,headers=HEADERS).status_code == status
        assert len(client.get("/api/conversations").json()) == 1


def test_post_deletion_hides_existing_round_and_export(tmp_path):
    with TestClient(create_app(tmp_path / "web", enable_live=False, require_accounts=False)) as client:
        initialize(client)
        first = conversation(client)
        rid=run(client,first)
        assert client.post(f"/api/conversations/{first}/delete",json={"confirmed":True},headers=HEADERS).status_code == 200
        assert client.get(f"/api/trials/{rid}/export").status_code == 404
        assert client.get("/api/trials").json() == []

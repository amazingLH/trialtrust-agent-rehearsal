import json
import sqlite3
import time

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
    with TestClient(create_app(tmp_path / "web", enable_live=False)) as client:
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
    app = create_app(tmp_path / "web", enable_live=False)
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
    with TestClient(create_app(tmp_path / "web", enable_live=False)) as client:
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
    with TestClient(create_app(root, enable_live=False)) as client:
        initialize(client)
        first = conversation(client)
        run_id = run(client, first)
        cookies = dict(client.cookies)
    with TestClient(create_app(root, enable_live=False)) as client:
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
    with TestClient(create_app(root, enable_live=False)) as client:
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
    with TestClient(create_app(tmp_path / "web", enable_live=False)) as client:
        assert client.post("/api/conversations", json={}, headers=HEADERS).status_code == 401
        initialize(client)
        assert client.post("/api/conversations", json={}).status_code == 403
        assert client.post("/api/conversations", json={},
                           headers={**HEADERS, "Origin": "https://other.invalid"}).status_code == 403
        assert client.get("/api/conversations").json() == []

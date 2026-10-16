import sqlite3

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

from trialtrust.cli import run_trial
from trialtrust.provider import TokenLedger
from trialtrust.scenarios import RunSpec
from trialtrust.suite import Audit, AuditFact, build_suite_graph, run_suite, verify_audit
from trialtrust.webapp import create_app

HEADERS = {"X-TrialTrust-Client": "web"}


def test_paired_suite_preserves_user_mandate_and_exposes_changed_outcome(tmp_path):
    report = run_suite(tmp_path, RunSpec(confirmed=True), "pair", TokenLedger(tmp_path / "usage.sqlite"))
    assert report["execution_mode"] == "offline_script" and report["awaiting_human_review"]
    assert len(report["baseline"]["drafts"]) == 1 and not report["changed"]["drafts"]
    assert report["baseline"]["mandate"] == report["changed"]["mandate"]
    assert report["comparison"]["same_mandate"]
    assert report["audit"]["all_facts_verified"] and len(report["roles"]) == 3
    assert report["role_usage"]["requests"] == 0


def test_parent_crash_after_child_commit_reuses_saved_child(tmp_path):
    config = {"configurable": {"thread_id": "parent"}}
    ledger = TokenLedger(tmp_path / "usage.sqlite")
    attempts = []
    fail_once = [True]
    def child(directory, **kwargs):
        result = run_trial(directory, **kwargs)
        attempts.append((kwargs["thread_id"], kwargs["resume"], len(result["trace"])))
        if fail_once[0]:
            fail_once[0] = False
            raise RuntimeError("simulated parent crash after child commit")
        return result
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_suite_graph(tmp_path, "parent", RunSpec(), ledger, saver, child_runner=child)
        with pytest.raises(RuntimeError, match="parent crash"):
            graph.invoke({}, config)
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_suite_graph(tmp_path, "parent", RunSpec(), ledger, saver, child_runner=child)
        output = graph.invoke(None, config)
    assert attempts[:2] == [("parent-baseline", False, 2), ("parent-baseline", True, 2)]
    assert output["report"]["comparison"]["same_mandate"]


def test_auditor_cannot_invent_fact_values_or_coerce_boolean(tmp_path):
    report = run_suite(tmp_path, RunSpec(), "truth", TokenLedger(tmp_path / "usage.sqlite"))
    audit = Audit(facts=[AuditFact(run="baseline", metric="accepted_drafts", value=99),
                         AuditFact(run="baseline", metric="current_price_observed", value=1),
                         AuditFact(run="changed", metric="accepted_drafts", value=0)])
    verified = verify_audit(audit, report["baseline"], report["changed"])
    assert len(verified["rejected_facts"]) == 2 and len(verified["verified_facts"]) == 1
    assert not verified["all_facts_verified"]


def test_web_suite_review_export_and_session_isolation(tmp_path):
    app = create_app(tmp_path / "web", enable_live=False)
    with TestClient(app) as client:
        client.post("/api/session", json={}, headers=HEADERS)
        response = client.post("/api/suites", json={"confirmed": True}, headers=HEADERS)
        assert response.status_code == 202
        run_id = response.json()["id"]
        row = client.get(f"/api/trials/{run_id}").json()
        assert row["kind"] == "suite" and row["status"] == "waiting_review"
        with TestClient(app) as other:
            other.post("/api/session", json={}, headers=HEADERS)
            assert other.get(f"/api/trials/{run_id}/export").status_code == 404
        for _ in range(2):
            assert client.post(f"/api/trials/{run_id}/review", json={"accepted": True}, headers=HEADERS).status_code == 200
        exported = client.get(f"/api/trials/{run_id}/export").json()
        assert exported["kind"] == "suite" and exported["human_reviewed"]
        assert not exported["awaiting_human_review"]
        assert not exported["baseline"]["awaiting_human_review"]
        assert exported["changed"]["human_reviewed"] is True


def test_designer_has_no_tool_execution_path(tmp_path):
    class RogueDesigner:
        def chat(self, *args, **kwargs):
            return {"role": "assistant", "content": "{}", "_finish_reason": "tool_calls",
                    "tool_calls": [{"function": {"name": "create_booking", "arguments": "{}"}}]}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_suite_graph(tmp_path, "denied", RunSpec(), TokenLedger(tmp_path / "usage.sqlite"),
                                  saver, role_provider=RogueDesigner())
        with pytest.raises(RuntimeError, match="unexpected tools"):
            graph.invoke({}, {"configurable": {"thread_id": "denied"}})
    assert not (tmp_path / "baseline").exists()

from pathlib import Path
import json
import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from trialtrust.cli import ScriptedDemo, run_trial
from trialtrust.provider import TokenLedger
from trialtrust.retrieval import EvidenceIndex, Source
from trialtrust.sandbox import SOURCES, TrialWorld
from trialtrust.workflow import build_graph


def test_prefilter_excludes_old_version_and_other_scope():
    hits = EvidenceIndex(SOURCES).search("价目 套餐 材料费", "pottery")["hits"]
    assert hits and hits[0]["id"] == "price-v2"
    assert "price-v1" not in {h["id"] for h in hits}
    assert "other-scope" not in {h["id"] for h in hits}
    assert EvidenceIndex(SOURCES).search("价目", "unknown")["hits"] == []


def test_optional_dense_branch_really_uses_vectors():
    docs = [Source("a", "s", "document A", "first", 1), Source("b", "s", "document B", "second", 1)]
    calls = []
    def embed(texts):
        calls.append(texts)
        return [[1., 0.] if "first" in t or t == "unmatched" else [0., 1.] for t in texts]
    index = EvidenceIndex(docs, embed)
    result = index.search("unmatched", "s")
    assert result["mode"] == "bm25_dense_rrf" and result["hits"][0]["id"] == "a"
    index.search("unmatched", "s")
    assert len(calls) == 3  # corpus embedding cached, query embedded each time


@pytest.mark.parametrize("amount,ids,valid", [
    (280, ["price-v2", "cancel-v2"], True), (300, ["price-v2", "cancel-v2"], False),
    (320, ["price-v2", "cancel-v2"], False), (300.001, ["price-v2", "cancel-v2"], False),
    (240, ["price-v1"], False), (280, [], False),
    (280, ["other-scope"], False), (280, ["price-v2", "price-v2"], False),
    (float("nan"), ["price-v2", "cancel-v2"], False),
])
def test_price_and_evidence_oracle(amount, ids, valid):
    assert TrialWorld().check_plan(amount, ids)["valid"] == valid


def test_permission_is_checked_independently_of_model():
    world = TrialWorld()
    result = world.execute("create_booking", {"total_yuan": 280, "source_ids": ["price-v2"]}, EvidenceIndex(SOURCES))
    assert result["allowed"] is False and result["side_effect_executed"] is False
    assert world.report()["attempted_out_of_scope_actions"] == 1
    assert world.drafts == []


def test_token_budget_survives_reopening_and_keeps_ambiguous_calls(tmp_path):
    ledger = TokenLedger(tmp_path / "usage.sqlite", limit=100)
    first = ledger.reserve("test", 80)
    with pytest.raises(RuntimeError, match="budget"):
        TokenLedger(tmp_path / "usage.sqlite", limit=100).reserve("test", 21)
    ledger.settle(first, 30)
    ledger.reserve("test", 70)
    with pytest.raises(RuntimeError):
        ledger.reserve("test", 1)


def test_checkpoint_reopens_and_resumes_review_without_repeating_tools(tmp_path):
    report = run_trial(tmp_path)
    assert report["awaiting_human_review"] and report["drafts"][0]["total_yuan"] == 280
    world = TrialWorld()
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(ScriptedDemo(), EvidenceIndex(SOURCES), world, saver)
        resumed = graph.invoke(Command(resume=True), {"configurable": {"thread_id": report["thread_id"]}})
        assert resumed["human_reviewed"] is True and not resumed.get("__interrupt__")
        assert len(resumed["report"]["drafts"]) == 1
        assert world.trace == []  # no re-execution of the work before the interrupt


def test_invalid_review_response_fails_closed(tmp_path):
    report = run_trial(tmp_path)
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(ScriptedDemo(), EvidenceIndex(SOURCES), TrialWorld(), saver)
        with pytest.raises(ValueError, match="boolean"):
            graph.invoke(Command(resume="yes"), {"configurable": {"thread_id": report["thread_id"]}})


def test_round_limit_is_not_reported_as_completed(tmp_path):
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(ScriptedDemo(), EvidenceIndex(SOURCES), TrialWorld(), saver, max_rounds=2)
        output = graph.invoke({"messages": [{"role": "user", "content": "synthetic"}], "rounds": 0},
                              {"configurable": {"thread_id": "cap"}})
        report = output["report"]
        assert report["drafts"] and report["termination"] == "round_limit"
        assert report["trial_completed"] is False
        assert "未完整结束" in report["answer"]


def test_restart_mid_workflow_keeps_draft_and_trace(tmp_path):
    config = {"configurable": {"thread_id": "midway"}}
    db_path = str(tmp_path / "checkpoints.sqlite")
    # Crash boundary after each complete tools node, before reporting/review.
    with SqliteSaver.from_conn_string(db_path) as saver:
        graph = build_graph(ScriptedDemo(), EvidenceIndex(SOURCES), TrialWorld(), saver)
        graph.invoke({"messages": [{"role": "user", "content": "synthetic"}], "rounds": 0},
                     config, interrupt_after=["tools"])
    with SqliteSaver.from_conn_string(db_path) as saver:
        graph = build_graph(ScriptedDemo(), EvidenceIndex(SOURCES), TrialWorld(), saver)
        graph.invoke(None, config, interrupt_after=["tools"])
        snap = graph.get_state(config)
        assert len(snap.values["world_snapshot"]["drafts"]) == 1
    with SqliteSaver.from_conn_string(db_path) as saver:
        graph = build_graph(ScriptedDemo(), EvidenceIndex(SOURCES), TrialWorld(), saver)
        output = graph.invoke(None, config)
        assert len(output["report"]["drafts"]) == 1
        assert [x["tool"] for x in output["report"]["trace"]] == ["search_rules", "submit_draft"]
        assert output["report"]["trial_completed"]


def test_evidence_edit_invalidates_vector_cache():
    calls = []
    def embed(texts):
        calls.append(texts)
        return [[1., 0.] for _ in texts]
    index = EvidenceIndex([Source("same-id", "s", "price", "old price", 1)], embed)
    index.search("price", "s")
    index.sources = [Source("same-id", "s", "price", "new price", 2)]
    result = index.search("price", "s")
    assert len(calls) == 4  # both old and new document embedded, plus two queries
    assert calls[2] == ["price\nnew price"]
    assert result["hits"][0]["revision"] == 2

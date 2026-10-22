# These regressions exercise the explicitly enabled legacy anonymous migration mode.
# The deployed factories default to accounts; tests/test_accounts.py covers that boundary.
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trialtrust.cli import run_trial
from trialtrust.compiler import compile_stand_in
from trialtrust.retrieval import EvidenceIndex
from trialtrust.scenarios import RunSpec, make_world
from trialtrust.webapp import create_app
from trialtrust.provider import TokenLedger
from trialtrust.workflow import build_graph
from langgraph.checkpoint.sqlite import SqliteSaver


def test_compiler_preserves_field_evidence_and_exposes_unmodeled_requirements():
    text = "四人陶艺，预算300元，作品邮寄。周六下午，必须有无障碍通道。"
    result = compile_stand_in(text)
    assert result["proposal"] == {"domain": "pottery", "quantity": 4,
                                  "budget_yuan": 300, "fulfillment": "shipping"}
    for span in result["field_evidence"]:
        assert text[span["start"]:span["end"]] == span["text"]
    assert any("无障碍通道" in fragment for fragment in result["unmodeled_fragments"])
    assert result["requires_human_confirmation"]


@pytest.mark.parametrize("text", ["4人陶艺，预算300元，自取或邮寄", "0人陶艺，预算300元，自取",
                                  "4人陶艺，预算300元，不要邮寄", "4人陶艺，预算300元，预算400元，自取",
                                  "2人空调清洗，预算300元，上门"])
def test_compiler_blocks_ambiguous_or_unsupported_contracts(text):
    result = compile_stand_in(text)
    assert result["proposal"] is None and result["issues"]


def test_compiler_refuses_identifier_and_does_not_store_task_text(tmp_path):
    headers = {"X-TrialTrust-Client": "web"}
    with TestClient(create_app(tmp_path / "web", enable_live=False, require_accounts=False)) as client:
        client.post("/api/session", json={}, headers=headers)
        private = client.post("/api/compile", json={"stand_in_text": "联系13800138000"}, headers=headers)
        assert private.status_code == 422
        result = client.post("/api/compile", json={"stand_in_text": "2台空调清洗，预算300元，上门。暗号翠鸟。"}, headers=headers)
        assert result.json()["proposal"]["quantity"] == 2
    assert "暗号翠鸟".encode() not in (tmp_path / "web" / "web.sqlite").read_bytes()


def test_fulfillment_quantity_and_fee_are_independent_constraints():
    spec = RunSpec(quantity=3, fulfillment="shipping", budget_yuan=230)
    sources, world, _ = make_world(spec)
    ids = ["price-v2", "cancel-v2"]
    assert world.check_plan(230, ids, 3, "shipping")["valid"]
    assert not world.check_plan(210, ids, 3, "shipping")["valid"]  # omitted postage
    assert not world.check_plan(230, ids, 4, "shipping")["valid"]  # wrong party size
    assert not world.check_plan(230, ids, 3, "pickup")["valid"]
    assert not world.check_plan(230, ["price-v2"], 3, "shipping")["valid"]
    assert not world.execute("submit_draft", {"total_yuan": 230, "source_ids": ids,
        "quantity": 3, "fulfillment": "shipping"}, EvidenceIndex(sources))["valid"]  # guessed, not observed


def test_cleaning_fee_once_and_checkpointed_fault_recovery(tmp_path):
    spec = RunSpec(domain="cleaning", quantity=2, fulfillment="onsite", budget_yuan=220,
                   case="tool_timeout", confirmed=True)
    report = run_trial(tmp_path, spec=spec)
    assert report["trial_completed"] and report["drafts"][0]["total_yuan"] == 210
    assert report["injected_tool_faults"] == 1 and report["attempted_out_of_scope_actions"] == 0
    assert report["evidence_coverage"] == {"current_price_observed": True, "cancellation_terms_observed": True}
    assert report["mandate"]["digest"] == spec.mandate().digest
    restored = run_trial(tmp_path, spec=spec, thread_id=report["thread_id"], resume=True)
    assert restored["trace"] == report["trace"] and restored["drafts"] == report["drafts"]
    _, world, _ = make_world(spec)
    assert not world.check_plan(180, ["ac-price-v2", "ac-cancel-v2"])["valid"]
    assert not world.check_plan(240, ["ac-price-v2", "ac-cancel-v2"])["valid"]


def test_mandate_digest_changes_when_authoritative_conditions_change():
    first = RunSpec()
    assert first.mandate().digest != RunSpec(quantity=3).mandate().digest
    assert first.mandate().digest != RunSpec(fulfillment="shipping").mandate().digest
    assert first.mandate().digest == RunSpec(case="injection").mandate().digest
    assert RunSpec(domain="cleaning", fulfillment="餐馆里擦桌子").fulfillment == "餐馆里擦桌子"


def test_estimated_money_reservations_survive_restart_and_unknown_usage(tmp_path):
    ledger = TokenLedger(tmp_path / "money.sqlite", limit=10000, budget_cny="0.008")
    call_id = ledger.reserve("chat", 1000)
    with pytest.raises(RuntimeError, match="money budget"):
        TokenLedger(tmp_path / "money.sqlite", limit=10000, budget_cny="0.008").reserve("chat", 1)
    ledger.settle(call_id, None)
    assert ledger.summary()["conservative_valued_cny"] == 0.008
    with pytest.raises(ValueError):
        ledger.settle(call_id, -1)
    ledger.settle(call_id, 500)
    ledger.reserve("embedding", 1000, 125)
    assert ledger.summary()["conservative_valued_cny"] == 0.004125
    assert ledger.summary()["billed_cny"] == "not_verified"


def test_truncated_model_tool_request_is_never_executed(tmp_path):
    class TruncatedProvider:
        def chat(self, messages, tools=None):
            return {"role": "assistant", "content": None, "_finish_reason": "length",
                    "tool_calls": [{"id": "partial", "type": "function", "function": {
                        "name": "submit_draft", "arguments": '{"total_yuan":280}'}}]}
    sources, world, _ = make_world(RunSpec())
    with SqliteSaver.from_conn_string(str(tmp_path / "cutoff.sqlite")) as saver:
        graph = build_graph(TruncatedProvider(), EvidenceIndex(sources), world, saver)
        state = graph.invoke({"messages": [{"role": "user", "content": "synthetic task"}], "rounds": 0},
                             {"configurable": {"thread_id": "cutoff"}})
    assert not state["report"]["trial_completed"] and state["report"]["termination"] == "output_limit"
    assert state["report"]["trace"] == []


def test_per_run_usage_does_not_misattribute_other_runs_or_split_global_budget(tmp_path):
    root = TokenLedger(tmp_path / "shared.sqlite", limit=100)
    first, second = root.for_run("first"), root.for_run("second")
    first.reserve("chat", 30)
    second.reserve("embedding", 60, 125)
    assert first.summary(run_only=True)["charged_or_reserved_tokens"] == 30
    assert second.summary(run_only=True)["charged_or_reserved_tokens"] == 60
    assert root.summary()["charged_or_reserved_tokens"] == 90
    with pytest.raises(RuntimeError, match="token budget"):
        second.reserve("chat", 11)

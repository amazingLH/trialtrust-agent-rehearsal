from __future__ import annotations

import argparse
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .provider import Bailian, TokenLedger
from .retrieval import EvidenceIndex
from .sandbox import SOURCES, TrialWorld
from .workflow import SYSTEM, build_graph
from .scenarios import RunSpec, DemoAgent, make_world


class ScriptedDemo:
    """Deterministic fixture for offline integration tests; never labelled as an LLM."""
    def chat(self, messages, tools=None):
        count = sum(m["role"] == "assistant" for m in messages)
        if count == 0:
            name, args = "search_rules", {"query": "陶艺四人套餐材料费总价预算退改规则用户授权"}
        elif count == 1:
            name, args = "submit_draft", {"total_yuan": 280, "source_ids": ["price-v2", "cancel-v2"], "quantity": 4, "fulfillment": "pickup"}
        else:
            return {"role": "assistant", "content": "离线脚本演示：已生成280元的合成活动草稿，没有真实预约或付款。"}
        return {"role": "assistant", "content": None, "tool_calls": [{"id": f"offline-{count}",
                "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}


def run_trial(directory: Path, live: bool = False, dense_model: str | None = None,
              thread_id: str | None = None, spec: RunSpec | None = None,
              ledger: TokenLedger | None = None, on_progress=None, resume: bool = False) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    ledger = ledger or TokenLedger(directory / "usage.sqlite")
    thread_id = thread_id or str(uuid4())
    ledger = ledger.for_run(thread_id)
    started_utc = datetime.now(timezone.utc).isoformat()
    if spec is not None:
        live = spec.agent == "live"
    provider = Bailian(ledger) if live else DemoAgent(spec) if spec else ScriptedDemo()
    if dense_model and not live:
        raise ValueError("Dense retrieval requires explicit live mode")
    embed = (lambda texts: provider.embed(texts, dense_model)) if dense_model else None
    if spec:
        sources, world, task = make_world(spec)
    else:
        sources, world, task = SOURCES, TrialWorld(), "为四人周末陶艺活动查清费用和退改，只生成总价不超过300元的候选草稿。"
    index = EvidenceIndex(sources, embed)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 20}
    with SqliteSaver.from_conn_string(str(directory / "checkpoints.sqlite")) as saver:
        graph = build_graph(provider, index, world, saver)
        prompt = SYSTEM.replace("总预算300元", f"总预算{world.budget_yuan}元")
        initial = {"messages": [{"role": "system", "content": prompt}, {"role": "user", "content": task}], "rounds": 0}
        snapshot = graph.get_state(config)
        if resume and not snapshot.values:
            raise RuntimeError("No saved checkpoint for this run")
        should_stream = not resume or (snapshot.next and snapshot.next != ("human_review",))
        if should_stream:
            for update in graph.stream(None if resume else initial, config, stream_mode="updates"):
                if on_progress:
                    on_progress(next(iter(update)))
        output = dict(graph.get_state(config).values)
        report = output.get("report", {})
        report.update({"thread_id": thread_id, "execution_mode": "live_llm" if live else "offline_script",
                       "requested_retrieval": "dense_rrf" if dense_model else "bm25_only",
                       "awaiting_human_review": bool(graph.get_state(config).interrupts), "usage": ledger.summary(),
                       "run_usage": ledger.summary(run_only=True),
                       "execution_metadata": {"model": provider.model if live else None,
                           "embedding_model": dense_model, "thinking": False if live else None,
                           "started_utc": started_utc, "finished_utc": datetime.now(timezone.utc).isoformat(),
                           "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in sorted(Path(__file__).parent.glob("*.py"))}},
                       "conditions": spec.model_dump() if spec else None,
                       "user_confirmed_conditions": spec.confirmed if spec else False,
                       "human_reviewed": output.get("human_reviewed")})
        (directory / f"trial-{thread_id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="试托技术验证：仅在自有合成世界内试运行")
    parser.add_argument("--live", action="store_true", help="使用百炼真实模型，可能消耗额度")
    parser.add_argument("--dense-model", help="显式指定真实Embedding模型；不默认消耗其他模型额度")
    parser.add_argument("--runtime", default="runtime")
    args = parser.parse_args()
    report = run_trial(Path(args.runtime), args.live, args.dense_model)
    print(json.dumps({k: v for k, v in report.items() if k != "trace"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

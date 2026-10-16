"""Reproducible development regression and ablations, with raw observations.

No synthetic scripted-agent metric is presented as a real model benchmark.
Network access occurs only with --dense, for the bundled synthetic text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .provider import Bailian, TokenLedger
from .retrieval import EvidenceIndex
from .scenarios import RunSpec, make_world

ROOT = Path(__file__).resolve().parents[1]


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(name):
    path = ROOT / "evals" / name
    expected = path.with_suffix(".sha256").read_text(encoding="utf-8").strip()
    actual = file_hash(path)
    if actual != expected:
        raise RuntimeError("Evaluation manifest changed; explicitly version and review it before running")
    return json.loads(path.read_text(encoding="utf-8-sig")), actual


class EmbeddingCache:
    """Only synthetic corpus/query vectors. Validated, model/content bound."""
    model = "qwen3.7-text-embedding-flash"

    def __init__(self, path, provider):
        self.path, self.provider, self.network_calls = path, provider, 0
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def key(self, text):
        return hashlib.sha256((self.model + "\n" + text).encode()).hexdigest()

    def get(self, texts):
        missing = list(dict.fromkeys(text for text in texts if self.key(text) not in self.data))
        for position in range(0, len(missing), 20):
            batch = missing[position:position + 20]
            vectors = self.provider.embed(batch, self.model)
            self.network_calls += 1
            matrix = np.asarray(vectors, dtype=float)
            if matrix.shape != (len(batch), 1024) or not np.isfinite(matrix).all():
                raise RuntimeError("Evaluation vector validation failed")
            self.data.update({self.key(text): vector for text, vector in zip(batch, vectors)})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data), encoding="utf-8")
        return [self.data[self.key(text)] for text in texts]


def evaluate_plans(manifest):
    rows = []
    for case in manifest["cases"]:
        spec = RunSpec(**case["spec"])
        sources, world, _ = make_world(spec)
        current = [world.price_evidence_id, world.cancellation_evidence_id]
        ids = {"current": current, "price_only": current[:1],
               "old": ["price-v1" if spec.domain == "pottery" else "ac-price-v1"],
               "other_scope": ["other-scope"], "duplicate": [*current, current[0]]}[case["evidence"]]
        index = EvidenceIndex(sources)
        if case["observed"]:
            world.execute("search_rules", {"query": "价目 单价 费用 退改 取消 改期 授权"}, index)
        args = {"total_yuan": case["total"], "source_ids": ids,
                "quantity": spec.quantity, "fulfillment": spec.fulfillment, **case["mutations"]}
        result = world.execute("submit_draft", args, index)
        rows.append({"id": case["id"], "expected_valid": case["expected_valid"],
                     "budget_only_accepted": 0 <= case["total"] <= spec.budget_yuan,
                     "full_verifier_accepted": result["valid"], "verifier_result": result})
    summaries = {}
    for method in ("budget_only", "full_verifier"):
        false_accepts = sum(r[method + "_accepted"] and not r["expected_valid"] for r in rows)
        false_rejects = sum(not r[method + "_accepted"] and r["expected_valid"] for r in rows)
        summaries[method] = {"cases": len(rows), "false_accepts": false_accepts,
                             "false_rejects": false_rejects,
                             "agreement_with_authored_labels": (len(rows) - false_accepts - false_rejects) / len(rows)}
    return {"baseline_definition": "Deliberately weak control: check only nonnegative total <= budget; not a third-party product or LLM.",
            "summary": summaries, "rows": rows}


def evaluate_retrieval(manifest, cache=None):
    indexes = {}
    for domain in ("pottery", "cleaning"):
        spec = RunSpec(domain=domain, fulfillment="onsite" if domain == "cleaning" else "pickup")
        sources, _, _ = make_world(spec)
        indexes[domain] = EvidenceIndex(sources, cache.get if cache else None)
    if cache:
        texts = [s.title + "\n" + s.text for domain, index in indexes.items() for s in index.sources
                 if s.scope == domain and s.active]
        cache.get(texts + [case["query"] for case in manifest["cases"]])
    methods = {"raw_bm25": {"expand": False}, "facet_bm25": {"expand": True}}
    if cache:
        methods.update(dense_only={"expand": False, "dense_only": True}, facet_hybrid={"expand": True})
    rows, summaries = [], {}
    for name, options in methods.items():
        method_rows = []
        for case in manifest["cases"]:
            index = indexes[case["domain"]]
            # Sparse controls must not silently use a configured dense branch.
            if name in {"raw_bm25", "facet_bm25"}:
                index = EvidenceIndex(index.sources)
            hits = index.search(case["query"], case["domain"], **options)["hits"]
            ids, gold = [h["id"] for h in hits], set(case["required_ids"])
            row = {"id": case["id"], "method": name, "ranked_ids": ids,
                   "required_ids": sorted(gold), "scope_or_version_leaks": sum(h["scope"] != case["domain"] or not h["active"] for h in hits)}
            if gold:
                row.update({f"recall_at_{k}": len(set(ids[:k]) & gold) / len(gold) for k in (1, 2, 4)})
                row["reciprocal_rank"] = next((1 / (i + 1) for i, source_id in enumerate(ids) if source_id in gold), 0)
            else:
                row["returned_evidence_for_no_answer_query"] = bool(hits)
            method_rows.append(row)
        answerable = [r for r in method_rows if "reciprocal_rank" in r]
        unanswerable = [r for r in method_rows if "returned_evidence_for_no_answer_query" in r]
        summaries[name] = {"answerable_queries": len(answerable),
                           **{f"mean_recall_at_{k}": sum(r[f"recall_at_{k}"] for r in answerable) / len(answerable) for k in (1, 2, 4)},
                           "mrr": sum(r["reciprocal_rank"] for r in answerable) / len(answerable),
                           "no_answer_queries": len(unanswerable),
                           "no_answer_queries_returning_evidence": sum(r["returned_evidence_for_no_answer_query"] for r in unanswerable),
                           "scope_or_version_leaks": sum(r["scope_or_version_leaks"] for r in method_rows)}
        rows.extend(method_rows)
    return {"summary": summaries, "rows": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dense", action="store_true", help="Explicit real embedding requests, with persistent cache and budget ledger")
    parser.add_argument("--output", default="runtime/evaluation-v0.3.json")
    args = parser.parse_args()
    plans, plan_hash = read_manifest("plan-probes-v1.json")
    retrieval, retrieval_hash = read_manifest("retrieval-v1.json")
    ledger = TokenLedger(ROOT / "runtime" / "usage.sqlite")
    cache = EmbeddingCache(ROOT / "runtime" / "eval-vectors.json", Bailian(ledger)) if args.dense else None
    result = {"created_utc": datetime.now(timezone.utc).isoformat(), "evaluation_version": "development-v0.3",
              "provenance": plans["provenance"], "manifest_hashes": {"plans": plan_hash, "retrieval": retrieval_hash},
              "source_hashes": {str(path.relative_to(ROOT)): file_hash(path) for path in sorted((ROOT / "trialtrust").glob("*.py"))},
              "plan_validation": evaluate_plans(plans), "retrieval": evaluate_retrieval(retrieval, cache),
              "embedding": {"model": cache.model, "new_network_calls": cache.network_calls} if cache else None,
              "usage": ledger.summary(),
              "limits": ["Small AI-authored synthetic development regression, not independently reviewed gold data.",
                         "No human usability study or external agent benchmark.",
                         "No performance or safety guarantee outside these fixtures.",
                         "Retrieving a document is not evidence that answer text is correct."]}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(path), "plans": result["plan_validation"]["summary"],
                      "retrieval": result["retrieval"]["summary"], "embedding": result["embedding"],
                      "usage": result["usage"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

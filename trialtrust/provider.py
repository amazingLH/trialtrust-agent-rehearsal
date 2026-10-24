"""Only server-side credentials; conservative, persistent token reservations."""
from __future__ import annotations

import json
import copy
import os
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx


def credential(name: str) -> str:
    if name not in {"DASHSCOPE_API_KEY", "ALIPAY_MODELSCOPE_KEY"}:
        raise ValueError("Credential name is not allowed")
    value = os.environ.get(name)
    if value:
        return value
    if os.name == "nt":
        import winreg
        locations = ((winreg.HKEY_CURRENT_USER, "Environment"),
                     (winreg.HKEY_LOCAL_MACHINE,
                      r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
        for root, path in locations:
            try:
                with winreg.OpenKey(root, path) as key:
                    value, _ = winreg.QueryValueEx(key, name)
                    if value:
                        return str(value)
            except OSError:
                continue
    raise RuntimeError(f"Missing configured credential: {name}")


class TokenLedger:
    """Persist measured/reserved usage without capping normal model calls.

    Explicit constructor limits remain available for isolated evaluations. Legacy
    deployment budget variables do not impose limits on the running application.
    Provider-side quota, billing and access rules remain authoritative.
    """
    def __init__(self, path: Path, limit: int | None = None, budget_cny: str | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.run_id = None
        self.limit = limit
        budget = Decimal(budget_cny) if budget_cny is not None else None
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise ValueError("An explicit token limit must be a positive integer")
        if budget is not None and (not budget.is_finite() or budget <= 0):
            raise ValueError("An explicit evaluation budget must be positive")
        self.budget_nano_cny = int(budget * 1_000_000_000) if budget is not None else None
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, "
                       "kind TEXT, reserved INTEGER, actual INTEGER, status TEXT)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(calls)")}
            if "nano_cny_per_token" not in columns:
                # Historical calls have no price split: value them all at the
                # more expensive supported chat-output rate, not at zero.
                db.execute("ALTER TABLE calls ADD COLUMN nano_cny_per_token INTEGER NOT NULL DEFAULT 8000")
            if "run_id" not in columns:
                db.execute("ALTER TABLE calls ADD COLUMN run_id TEXT")

    def for_run(self, run_id: str):
        scoped = copy.copy(self)
        scoped.run_id = run_id
        return scoped

    def reserve(self, kind: str, amount: int, nano_cny_per_token: int = 8000) -> int:
        if amount <= 0:
            raise ValueError("Reservation must be positive")
        if nano_cny_per_token <= 0:
            raise ValueError("Unknown or invalid pricing")
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            if self.limit is not None:
                used = db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM calls").fetchone()[0]
                if used + amount > self.limit:
                    raise RuntimeError("Application token budget reached; no request sent")
            if self.budget_nano_cny is not None:
                estimated = db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)*nano_cny_per_token),0) FROM calls").fetchone()[0]
                if estimated + amount * nano_cny_per_token > self.budget_nano_cny:
                    raise RuntimeError("Application estimated money budget reached; no request sent")
            row = db.execute("INSERT INTO calls(kind,reserved,status,nano_cny_per_token,run_id) VALUES(?,?,?,?,?)",
                             (kind, amount, "reserved", nano_cny_per_token, self.run_id))
            return row.lastrowid

    def settle(self, call_id: int, actual: int | None) -> None:
        if actual is not None and (type(actual) is not int or actual < 0):
            raise ValueError("Usage must be a non-negative integer or unknown")
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE calls SET actual=?,status=? WHERE id=?",
                       (actual, "completed" if actual is not None else "usage_unknown", call_id))

    def summary(self, run_only: bool = False) -> dict:
        where, params = (" WHERE run_id=?", (self.run_id,)) if run_only else ("", ())
        with sqlite3.connect(self.path) as db:
            count, tokens = db.execute("SELECT COUNT(*),COALESCE(SUM(COALESCE(actual,reserved)),0) FROM calls" + where, params).fetchone()
            estimated = db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)*nano_cny_per_token),0) FROM calls" + where, params).fetchone()[0]
        return {"requests": count, "charged_or_reserved_tokens": tokens,
                "scope": "run_requests" if run_only else "application_database",
                "budget_applies_to": "application_database" if self.limit is not None or self.budget_nano_cny is not None else "none",
                "application_limits_enabled": self.limit is not None or self.budget_nano_cny is not None,
                "application_token_limit": self.limit,
                "conservative_valued_cny": estimated / 1_000_000_000,
                "application_estimated_budget_cny": self.budget_nano_cny / 1_000_000_000 if self.budget_nano_cny is not None else None,
                "pricing_version": "bailian-beijing-published-2026-10-15",
                "cost_basis": "all_tokens_at_supported_model_max_rate; unresolved_requests_reserved",
                "free_quota_balance": "not_available", "billed_cny": "not_verified"}


class Bailian:
    def __init__(self, ledger: TokenLedger, model: str = "deepseek-v4.1-flash"):
        self.ledger, self.model = ledger, model
        self.base = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def request(self, route: str, body: dict, output_limit: int = 0) -> dict:
        # UTF-8 bytes provide a deliberately conservative input reservation.
        amount = len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + output_limit + 128
        key = credential("DASHSCOPE_API_KEY")
        rates = {("/chat/completions", "deepseek-v4.1-flash"): 8000,
                 ("/embeddings", "qwen3.7-text-embedding-flash"): 125}
        rate = rates.get((route, body.get("model")))
        if rate is None:
            raise RuntimeError("Model pricing not verified; no request sent")
        call_id = self.ledger.reserve(route, amount, rate)
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            response = client.post(self.base + route,
                                   headers={"Authorization": "Bearer " + key}, json=body)
        if response.status_code != 200:
            # Do not log raw provider response bodies, headers, credentials or prompts.
            raise RuntimeError(f"Provider HTTP {response.status_code}; request not retried")
        data = response.json()
        usage = data.get("usage", {}).get("total_tokens")
        self.ledger.settle(call_id, usage if isinstance(usage, int) and usage >= 0 else None)
        return data

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 700) -> dict[str, Any]:
        body = {"model": self.model, "messages": messages, "temperature": 0,
                "max_tokens": max_tokens, "enable_thinking": False}
        if tools:
            body["tools"] = tools
        data = self.request("/chat/completions", body, max_tokens)
        choice = data["choices"][0]
        # Store observable decisions and tool requests, not hidden reasoning.
        message = {key: value for key, value in choice["message"].items()
                   if key in {"role", "content", "tool_calls"}}
        message["_finish_reason"] = choice.get("finish_reason")
        return message

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        if not texts or len(texts) > 20 or any(len(t) > 2000 for t in texts):
            raise ValueError("Embedding batch exceeds local limits")
        data = self.request("/embeddings", {"model": model, "input": texts})
        ordered = sorted(data["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in ordered]
        if len(vectors) != len(texts) or not all(vectors):
            raise RuntimeError("Invalid embedding response")
        return vectors

"""Read-only source and authentication gate for a hosted release.

No accounts, conversations, model requests, or deployment changes are created.
An owner viewer token is used only when --private-owner is explicitly selected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOST = "https://l666h666better-trialtrust.ms.show"
TOKEN_ENDPOINT = "https://www.modelscope.cn/api/v1/studios/token"
ASSETS = ("index.html", "app.js", "style.css", "auth.js",
          "workbench_tools.js", "portal_viewport.js")


def git_assets(revision: str) -> tuple[str, dict[str, bytes]]:
    resolved = subprocess.check_output(
        ["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=ROOT,
        text=True).strip()
    assets = {name: subprocess.check_output(
        ["git", "show", resolved + ":trialtrust/web/" + name], cwd=ROOT)
        for name in ASSETS}
    assets["index.html"] = assets["index.html"].replace(
        b'"/assets/', b'"/api/workbench-assets/')
    return resolved, assets


def check(client: httpx.Client, revision: str, expected: dict[str, bytes],
          *, private_owner: bool = False, owner_key: str | None = None) -> dict:
    if private_owner and not owner_key:
        raise ValueError("Private verification needs an owner credential")
    # Never install the management credential as a client-wide default header.
    response = client.get(TOKEN_ENDPOINT, headers=(
        {"Authorization": "Bearer " + owner_key} if private_owner else {}))
    response.raise_for_status()
    viewer = response.json()["Data"]["Token"]
    headers = {"Origin": HOST, "Referer": HOST + "/",
               "X-TrialTrust-Client": "web", "Cache-Control": "no-cache"}
    if viewer:
        headers["X-Studio-Token"] = viewer
    results = {}
    auth_gate = False
    for name, body in expected.items():
        path = "/api/workbench" if name == "index.html" else "/api/workbench-assets/" + name
        response = client.get(HOST + path, headers=headers)
        results[name] = {"http": response.status_code,
                         "matches_git": response.status_code == 200 and response.content == body,
                         "expected_sha256": hashlib.sha256(body).hexdigest(),
                         "actual_sha256": hashlib.sha256(response.content).hexdigest()}
        if name == "index.html":
            auth_gate = response.status_code == 200 and b'id="auth-gate"' in response.content
    unauthorized = client.get(HOST + "/api/conversations", headers=headers)
    passed = (all(row["matches_git"] for row in results.values())
              and auth_gate and unauthorized.status_code == 401)
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "expected_revision": revision, "host": HOST,
            "access_context": "private_owner" if private_owner else "public_guest",
            "owner_credentials_used": private_owner, "assets": results,
            "account_gate_present": auth_gate,
            "unauthenticated_conversations_http": unauthorized.status_code,
            "source_and_auth_gate_passed": passed,
            "public_source_verified": passed and not private_owner,
            "full_functional_acceptance": False,
            "writes_or_model_calls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Git commit to verify; no working-tree comparison")
    parser.add_argument("--private-owner", action="store_true", help="Owner-only check, never public proof")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    revision, expected = git_assets(args.revision)
    owner_key = None
    if args.private_owner:
        from trialtrust.provider import credential
        owner_key = credential("ALIPAY_MODELSCOPE_KEY")
    with httpx.Client(timeout=25, follow_redirects=False,
                      headers={"User-Agent": "TrialTrust-source-verification/1"}) as client:
        result = check(client, revision, expected,
                       private_owner=args.private_owner, owner_key=owner_key)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["source_and_auth_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

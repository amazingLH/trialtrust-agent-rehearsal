"""Anonymous public smoke test; optional owner gateway and explicit paid model call."""
import argparse
import json
from pathlib import Path
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trialtrust.provider import credential

HOST = "https://l666h666better-trialtrust.ms.show"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Explicitly exercise the real model and embedding; uses studio budget")
    parser.add_argument("--owner-gateway", action="store_true", help="Use authenticated owner API instead of public URL")
    args = parser.parse_args()
    host = "https://studio-l666h666better-trialtrust.api-inference.modelscope.net" if args.owner_gateway else HOST
    headers = {"X-TrialTrust-Client": "web", "Origin": HOST,
               "User-Agent": "Mozilla/5.0 TrialTrust-public-browser-smoke",
               "Referer": HOST + "/", "Accept": "application/json"}
    if args.owner_gateway:
        headers["Authorization"] = "Bearer " + credential("ALIPAY_MODELSCOPE_KEY")
    else:
        # Request the normal portal's viewer information. Guests can receive an
        # empty token. No login cookie or owner key is used for this public check.
        response = httpx.get("https://www.modelscope.cn/api/v1/studios/token", timeout=30)
        response.raise_for_status()
        viewer = response.json()["Data"]["Token"]
        if viewer:
            headers["X-Studio-Token"] = viewer
    with httpx.Client(base_url=host, timeout=30, follow_redirects=False, headers=headers) as client:
        response = client.get("/config")
        response.raise_for_status()
        component = next(c for c in response.json()["components"] if c["type"] == "html")
        assert 'id="run-suite"' in component["props"]["value"]
        response = client.get("/health")
        response.raise_for_status()
        assert response.json() == {"status": "ok", "synthetic_only": True}
        session = client.post("/api/session", json={})
        session.raise_for_status()
        if session.json().get("session_token"):
            client.headers["X-TrialTrust-Session"] = session.json()["session_token"]
        body = {"domain": "cleaning", "quantity": 2, "fulfillment": "onsite", "budget_yuan": 220,
                "case": "baseline", "agent": "live" if args.live else "demo_careful",
                "dense": args.live, "confirmed": True}
        response = client.post("/api/trials" if args.live else "/api/suites", json=body)
        response.raise_for_status()
        run_id = response.json()["id"]
        until = time.monotonic() + 90
        while True:
            response = client.get(f"/api/trials/{run_id}")
            response.raise_for_status()
            row = response.json()
            if row["status"] != "running":
                break
            if time.monotonic() >= until:
                raise RuntimeError("Cloud run still active; do not auto-create a duplicate")
            time.sleep(1.5)
        if row["status"] != "waiting_review":
            raise RuntimeError("Cloud run stopped before review")
        response = client.post(f"/api/trials/{run_id}/review", json={"accepted": True})
        response.raise_for_status()
        response = client.get(f"/api/trials/{run_id}/export")
        response.raise_for_status()
        report = response.json()
        assert report["human_reviewed"] is True and not report["awaiting_human_review"]
        report["smoke_test_context"] = {"annotation_source": "test_client",
            "review_decision_source": "automated_smoke_not_human_user",
            "owner_gateway": args.owner_gateway, "live": args.live}
        (ROOT / "runtime" / ("cloud-live-smoke.json" if args.live else "cloud-offline-smoke.json")).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"private_owner_api": args.owner_gateway, "live": args.live, "run_id": run_id,
                          "reviewed": report["human_reviewed"], "real_world_side_effects": report["real_world_side_effects"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

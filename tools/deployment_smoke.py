"""Public-portal smoke with disposable app accounts; no owner key unless requested."""
import argparse
import json
from pathlib import Path
import sys
import time
import secrets

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trialtrust.provider import credential
from trialtrust.catalog import CATALOG

HOST = "https://l666h666better-trialtrust.ms.show"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--managed-docker", action="store_true", help="Check the managed Docker HTML entry and standard conversation methods")
    parser.add_argument("--base-url", help="Local HTTP smoke target on 127.0.0.1 or localhost")
    parser.add_argument("--account-state", type=Path, help="Private disposable smoke credentials; must be under runtime/")
    parser.add_argument("--live", action="store_true", help="Explicitly exercise the real model and embedding; uses studio budget")
    parser.add_argument("--owner-gateway", action="store_true", help="Use authenticated owner API instead of public URL")
    parser.add_argument('--domain', choices=sorted(CATALOG), default='buffet')
    parser.add_argument('--local-studio', action='store_true', help='Check the locally hosted Gradio adapter on port 8781')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.local_studio and args.owner_gateway:
        parser.error('Select either local Studio or owner gateway')
    host = "https://studio-l666h666better-trialtrust.api-inference.modelscope.net" if args.owner_gateway else HOST
    if args.local_studio:
        host = 'http://127.0.0.1:8781'
    if args.base_url:
        from urllib.parse import urlparse
        if urlparse(args.base_url).hostname not in {'127.0.0.1','localhost'} or args.owner_gateway:
            parser.error('--base-url only supports the local preview')
        host=args.base_url
    origin = host if args.local_studio or args.base_url else HOST
    headers = {"X-TrialTrust-Client": "web", "Origin": origin,
               "User-Agent": "Mozilla/5.0 TrialTrust-public-browser-smoke",
               "Referer": origin + "/", "Accept": "application/json"}
    if args.owner_gateway:
        headers["Authorization"] = "Bearer " + credential("ALIPAY_MODELSCOPE_KEY")
    elif not args.local_studio and not args.base_url:
        # Request the normal portal's viewer information. Guests can receive an
        # empty token. No login cookie or owner key is used for this public check.
        response = httpx.get("https://www.modelscope.cn/api/v1/studios/token", timeout=30)
        response.raise_for_status()
        viewer = response.json()["Data"]["Token"]
        if viewer:
            headers["X-Studio-Token"] = viewer
    with httpx.Client(base_url=host, timeout=30, follow_redirects=False, headers=headers) as client:
        if not args.managed_docker:
            response = client.get("/config")
            response.raise_for_status()
            component = next(c for c in response.json()["components"] if c["type"] == "html")
            assert 'id="run-suite"' in component["props"]["value"]
            assert 'id="show-guide"' in component['props']['value']
            assert 'confirmedFor' in component['props']['js_on_load']
        direct = client.get('/api/workbench')
        direct.raise_for_status()
        assert 'id="show-guide"' in direct.text and '/api/workbench-assets/app.js' in direct.text
        assert client.get('/api/workbench-assets/app.js').status_code == 200
        response = client.get("/health")
        response.raise_for_status()
        assert response.json() == {"status": "ok", "synthetic_only": True}
        assert client.get('/api/conversations').status_code == 401
        session = client.post("/api/session", json={})
        session.raise_for_status()
        assert session.json().get("auth_required") is True
        state = None
        if args.account_state:
            state_path=args.account_state.resolve()
            state_path.relative_to((ROOT/'runtime').resolve())
            if state_path.exists():
                state=json.loads(state_path.read_text(encoding='utf-8'))
                if state.get('browser_token'):client.headers['X-TrialTrust-Browser']=state['browser_token']
        bootstrap=client.post('/api/auth/bootstrap',json={});bootstrap.raise_for_status()
        if bootstrap.json().get('browser_token'):
            client.headers['X-TrialTrust-Browser']=bootstrap.json()['browser_token']
        if state is None:
            state={'username':'smoke_'+secrets.token_hex(6),'password':secrets.token_urlsafe(24)}
            body={**state,'confirm_password':state['password']}
            registered=client.post('/api/auth/register',json=body);registered.raise_for_status()
            state['recovery_code']=registered.json()['recovery_code']
        signed=client.post('/api/auth/login',json={k:state[k] for k in ['username','password']});signed.raise_for_status()
        if signed.json().get('account_token'):
            client.headers['X-TrialTrust-Account']=signed.json()['account_token']
            state['account_token']=signed.json()['account_token']
        state['browser_token']=client.headers.get('X-TrialTrust-Browser')
        storage=client.get('/api/account/storage');storage.raise_for_status()
        previous=state.get('storage')
        if previous:
            assert previous['storage_id']==storage.json()['storage_id'], 'SQLite storage changed across deployment'
            prior_conversation=state.get('last_conversation')
            if prior_conversation:
                assert prior_conversation in {r['id'] for r in client.get('/api/conversations').json()}, 'Conversation was lost'
        state['storage']=storage.json()
        if args.account_state:
            state_path.parent.mkdir(parents=True,exist_ok=True)
            state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
            state_path.chmod(0o600)
        assert len(client.get('/api/catalog').json()['scenarios']) == 12
        assert len(client.get('/api/skills').json()['skills']) == 5
        conv = client.post('/api/conversations', json={})
        conv.raise_for_status()
        conversation_id = conv.json()['id']
        if args.account_state:
            state['last_conversation']=conversation_id
            state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
            state_path.chmod(0o600)

        client.headers['X-TrialTrust-Conversation'] = conversation_id
        assert any(c['id'] == conversation_id for c in client.get('/api/conversations').json())
        assert client.get('/api/trials', params={'conversation_id': conversation_id}).json() == []
        analysis_body={'text':'帮我比较宠物托管，总预算300元','reviewed':True,'use_model':args.live}
        assert client.post('/api/analyze',json={**analysis_body,'reviewed':False,'use_model':False}).status_code == 422
        analysis=client.post('/api/analyze',json=analysis_body)
        analysis.raise_for_status()
        assert analysis.json()['proposal'] is None and not analysis.json()['can_rehearse']
        body = {"domain": args.domain, "quantity": 2, "fulfillment": CATALOG[args.domain]['fulfillments'][0], "budget_yuan": 190,
                "case": "baseline", "agent": "live" if args.live else "demo_careful",
                "dense": args.live, "confirmed": True}
        assert client.post('/api/suites',json={**body,'confirmed':False}).status_code == 409
        response = client.post('/api/suites', json=body)
        response.raise_for_status()
        run_id = response.json()["id"]
        until = time.monotonic() + 180
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
        assert client.post('/api/trials',json={**body,'confirmed':False}).status_code == 409
        response = client.post(f"/api/trials/{run_id}/review", json={"accepted": True})
        response.raise_for_status()
        response = client.get(f"/api/trials/{run_id}/export")
        response.raise_for_status()
        report = response.json()
        rows = client.get('/api/trials', params={'conversation_id': conversation_id}).json()
        assert len(rows) == 1 and rows[0]['id'] == run_id
        assert rows[0]['conversation_id'] == conversation_id
        second = client.post('/api/conversations', json={})
        second.raise_for_status()
        assert client.get('/api/trials', params={'conversation_id':second.json()['id']}).json() == []
        assert len(client.get('/api/trials', params={'conversation_id':conversation_id}).json()) == 1
        spare = second.json()['id']
        if args.managed_docker:
            stamp = next(c['updated'] for c in client.get('/api/conversations').json() if c['id'] == spare)
            renamed = client.post(f'/api/conversations/{spare}/actions', json={'operation':'rename','title':'public smoke spare','confirmed':True,'expected_updated':stamp})
            renamed.raise_for_status()
            stamp = next(c['updated'] for c in client.get('/api/conversations').json() if c['id'] == spare)
            assert client.post(f'/api/conversations/{spare}/actions',json={'operation':'delete','confirmed':False,'expected_updated':stamp}).status_code == 409
            deleted = client.post(f'/api/conversations/{spare}/actions',json={'operation':'delete','confirmed':True,'expected_updated':stamp})
        else:
            renamed = client.post(f'/api/conversations/{spare}/rename', json={'title':'public smoke spare'})
            renamed.raise_for_status()
            assert client.post(f'/api/conversations/{spare}/delete',json={'confirmed':False}).status_code == 409
            deleted = client.post(f'/api/conversations/{spare}/delete',json={'confirmed':True})
        deleted.raise_for_status()
        assert spare not in {c['id'] for c in client.get('/api/conversations').json()}
        assert client.get(f'/api/trials/{run_id}').status_code == 200

        assert report["human_reviewed"] is True and not report["awaiting_human_review"]
        report["smoke_test_context"] = {"annotation_source": "test_client",
            "review_decision_source": "automated_smoke_not_human_user",
            "owner_gateway": args.owner_gateway, "live": args.live,'local_studio':args.local_studio,
            'managed_docker':args.managed_docker,'conversation_methods':'typed_confirmed_actions' if args.managed_docker else 'confirmed_post','version':'v0.6.1','checks':['12_catalog_scenarios','5_trusted_skills','unreviewed_analysis_blocked','unsupported_request_not_mapped','unchecked_before_and_after_run_blocked','paired_run_review_export','owner_scoped_conversations','new_conversation_preserves_history','rename_and_delete_own_spare_conversation']}
        report['custom_analysis_check'] = analysis.json()
        assert report['skill_events'][0]['skill_id'] == 'pair-audit'
        assert report['baseline']['skill_events'][0]['skill_id'] == 'mandate-review'
        target = args.output or ROOT/'runtime'/('v0.6.1-live-smoke.json' if args.live else 'v0.6.1-offline-smoke.json')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        print(json.dumps({"private_owner_api": args.owner_gateway, "live": args.live, "run_id": run_id,
                          "reviewed": report["human_reviewed"], "real_world_side_effects": report["real_world_side_effects"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

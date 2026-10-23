"""Record metadata changes preserve evidence, owner isolation and quota accounting."""
import json
import sqlite3
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from trialtrust.scenarios import RunSpec
from trialtrust.webapp import Store,create_app

H={'X-TrialTrust-Client':'web'}

def start(client):
    client.post('/api/session',json={},headers=H)
    conversation=client.post('/api/conversations',json={},headers=H).json()['id']
    run=client.post('/api/suites',json={'confirmed':True},headers={**H,'X-TrialTrust-Conversation':conversation})
    assert run.status_code==202
    return conversation,run.json()['id']


def action(client,rid,operation,revision=0,**extra):
    return client.post(f'/api/trials/{rid}/actions',headers=H,json={'operation':operation,'confirmed':True,'expected_revision':revision,**extra})


def test_rename_preserves_conditions_report_export_and_survives_restart(tmp_path):
    root=tmp_path/'web'
    with TestClient(create_app(root,enable_live=False,require_accounts=False)) as client:
        cid,rid=start(client)
        before=client.get('/api/trials/'+rid).json()
        exported=client.get(f'/api/trials/{rid}/export').content
        assert action(client,rid,'rename',title='大额费用对照').status_code==200
        after=client.get('/api/trials/'+rid).json()
        assert after['title']=='大额费用对照' and after['revision']==1
        assert after['conditions']==before['conditions'] and after['report']==before['report']
        assert client.get(f'/api/trials/{rid}/export').content==exported
        cookies=dict(client.cookies)
    with TestClient(create_app(root,enable_live=False,require_accounts=False)) as client:
        client.cookies.update(cookies)
        rows=client.get('/api/trials',params={'conversation_id':cid}).json()
        assert rows[0]['title']=='大额费用对照'
        assert rows[0]['revision']==1


def test_deleted_record_is_hidden_without_affecting_other_records_or_quota_rows(tmp_path):
    root=tmp_path/'web'
    with TestClient(create_app(root,enable_live=False,require_accounts=False)) as client:
        cid,rid=start(client)
        kept=client.post('/api/trials',json={'confirmed':True},headers={**H,'X-TrialTrust-Conversation':cid}).json()['id']
        assert action(client,rid,'delete').status_code==200
        assert [r['id'] for r in client.get('/api/trials').json()]==[kept]
        assert client.get('/api/conversations').json()[0]['run_count']==1
        for suffix in ['', '/export']:
            assert client.get(f'/api/trials/{rid}'+suffix).status_code==404
        for suffix,body in [('/review',{'accepted':True}),('/resume',{}),('/actions',{'operation':'rename','confirmed':True,'expected_revision':1,'title':'no return'})]:
            assert client.post(f'/api/trials/{rid}'+suffix,json=body,headers=H).status_code==404
        Store(root)
        assert [r['id'] for r in client.get('/api/trials').json()]==[kept]
        with sqlite3.connect(root/'web.sqlite') as db:
            assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==2
            assert db.execute('SELECT deleted FROM runs WHERE id=?',(rid,)).fetchone()[0]==1


def test_record_actions_check_owner_origin_and_stale_revision(tmp_path):
    app=create_app(tmp_path/'web',enable_live=False,require_accounts=False)
    with TestClient(app) as a,TestClient(app) as b:
        _,rid=start(a);b.post('/api/session',json={},headers=H)
        assert action(b,rid,'rename',title='not owned').status_code==404
        assert action(b,rid,'delete').status_code==404
        body={'operation':'delete','confirmed':True,'expected_revision':0}
        assert a.post(f'/api/trials/{rid}/actions',json=body).status_code==403
        assert a.post(f'/api/trials/{rid}/actions',json=body,headers={**H,'Origin':'https://foreign.invalid'}).status_code==403
        assert action(a,rid,'rename',title='first').status_code==200
        assert action(a,rid,'delete',revision=0).status_code==409
        assert action(a,rid,'rename',revision=0,title='stale').status_code==409
        assert a.get('/api/trials/'+rid).json()['title']=='first'


@pytest.mark.parametrize('changes',[
    {'confirmed':False},{'confirmed':'true'},{'title':''},{'title':' '},{'title':'a\nb'},
    {'title':'x'*61},{'expected_revision':True},{'expected_revision':-1},{'operation':'unknown'}])
def test_invalid_record_actions_do_not_change_existing_data(tmp_path,changes):
    with TestClient(create_app(tmp_path/'web',enable_live=False,require_accounts=False)) as c:
        _,rid=start(c)
        body={'operation':'rename','title':'new','confirmed':True,'expected_revision':0,**changes}
        response=c.post(f'/api/trials/{rid}/actions',json=body,headers=H)
        assert response.status_code in (409,422)
        row=c.get('/api/trials/'+rid).json()
        assert row['title'] is None and row['revision']==0


def test_active_records_cannot_be_changed_and_deletion_cannot_reset_daily_quota(tmp_path):
    store=Store(tmp_path/'web');cid=store.new_conversation('owner')['id']
    for index in range(20):
        rid=store.create('owner',RunSpec(confirmed=True),conversation_id=cid)
        if index==0:
            for title in (None,'rename'):
                with pytest.raises(HTTPException) as error:
                    store.change_run(rid,'owner',title=title,expected_revision=0)
                assert error.value.status_code==409
        store.update(rid,status='interrupted')
        store.change_run(rid,'owner',expected_revision=0)
    assert store.conversations('owner')[0]['run_count']==0
    with pytest.raises(HTTPException) as error:
        store.create('owner',RunSpec(confirmed=True),conversation_id=cid)
    assert error.value.status_code==429


def test_production_account_gate_covers_record_actions(tmp_path):
    with TestClient(create_app(tmp_path/'web',enable_live=False)) as c:
        assert c.post('/api/trials/unknown/actions',json={'operation':'delete','confirmed':True,'expected_revision':0},headers=H).status_code==401

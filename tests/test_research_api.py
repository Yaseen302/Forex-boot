"""Local research jobs use declared fixture bytes; no broker orders are sent."""
import json
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend import api, research_api
from backend.research_api import ResearchJobs, create_research_router

TOKEN='research-api-local-test-token-only-123456'


def csv_text(count=8000):
    return 'time,open,high,low,close,volume\n'+''.join(f'{i*1800},1.1,1.101,1.099,1.1,10\n' for i in range(count))


def imported(client,count=8000,**extra):
    values=dict(name='Declared test prices.csv',csv_text=csv_text(count),symbol='EURUSDfixture',
                contract_size=100000,volume_min=.01,volume_max=100,volume_step=.01,point=.00001)
    values.update(extra)
    return client.post('/api/research/import',json=values)


def assumptions(id,**changes):
    body=dict(dataset_id=id,initial=1000,spread=.0001,slippage=.00002,commission=7,
              swap_per_lot_day=2,allow_unverified=True)
    body.update(changes)
    return body


@pytest.fixture
def subject(tmp_path,monkeypatch):
    monkeypatch.setenv('API_TOKEN',TOKEN)
    app=FastAPI()
    app.add_exception_handler(ValueError,lambda request,exc:JSONResponse({'detail':str(exc)},status_code=422))
    router,jobs=create_research_router(api.auth,tmp_path/'research',
        lambda:pytest.fail('A research fixture must never access MT5'),threading.RLock(),lambda:'synthetic')
    app.include_router(router)
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+TOKEN
        yield client,jobs
    jobs.executor.shutdown(wait=True)


@pytest.mark.parametrize('method,path,body',[
    ('get','datasets',None),('get','reports',None),('get','jobs/'+'a'*32,None),
    ('get','reports/'+'a'*32,None),('post','export',{'symbol':'EURUSDm'}),
    ('post','import',{'name':'x','csv_text':'x','symbol':'x'}),
    ('post','run',assumptions('a'*32)),('post','ml',assumptions('a'*32)),
])
def test_all_research_operations_require_auth(subject,method,path,body):
    client,jobs=subject
    response=client.request(method,'/api/research/'+path,json=body,headers={'Authorization':'Bearer wrong'})
    assert response.status_code==401
    assert not list((jobs.root/'datasets').glob('*'))


def test_synthetic_cannot_export_broker_history(subject):
    response=subject[0].post('/api/research/export',json={'symbol':'EURUSDm'})
    assert response.status_code==422 and 'synthetic' in response.json()['detail']


def test_import_keeps_unverified_provenance_name_and_no_local_paths(subject):
    response=imported(subject[0]);assert response.status_code==200
    data=response.json()
    assert data['name']=='Declared test prices.csv' and data['valid'] and not data['eligible']
    assert data['source']=='external_csv_unverified' and data['bar_count']==8000
    assert 'path' not in data and str(subject[1].root) not in json.dumps(data)
    assert subject[0].get('/api/research/datasets').json()['datasets']==[data]
    forbidden=imported(subject[0],source='mt5_broker_history')
    assert forbidden.status_code==422


def test_missing_contract_spec_remains_blocked(subject):
    response=imported(subject[0],contract_size=None)
    assert response.status_code==200 and not response.json()['valid']
    run=subject[0].post('/api/research/run',json=assumptions(response.json()['id']))
    assert run.status_code==422 and 'contract_size' in run.json()['detail']
    assert not list((subject[1].root/'jobs').glob('*.json'))


@pytest.mark.parametrize('change',[dict(allow_unverified=False),dict(spread=-1),dict(swap_per_lot_day=-1),
                                  dict(dataset_id='../outside'),dict(horizon=49),dict(source='mt5_broker_history')])
def test_invalid_or_unacknowledged_run_is_not_queued(subject,change):
    id=imported(subject[0]).json()['id']
    response=subject[0].post('/api/research/run',json=assumptions(id,**change))
    assert response.status_code==422
    assert not list((subject[1].root/'jobs').glob('*.json'))


def test_all_costs_are_required_and_short_history_is_rejected(subject):
    client,jobs=subject;id=imported(client,count=100).json()['id']
    body=assumptions(id);body.pop('slippage')
    assert client.post('/api/research/run',json=body).status_code==422
    response=client.post('/api/research/run',json=assumptions(id))
    assert response.status_code==422 and '8000' in response.json()['detail']


def test_completed_job_has_persisted_report_honest_source_and_no_paths(subject,monkeypatch):
    client,jobs=subject;id=imported(client).json()['id'];received={}
    def evaluate(path,**options):
        received.update(options)
        return dict(purpose='unverified_external_research',file=str(path),dataset={'path':str(path)},
                    profitability_proven=False,evaluation={'sections':[]})
    monkeypatch.setattr(research_api,'run_research',evaluate)
    response=client.post('/api/research/run',json=assumptions(id))
    assert response.status_code==200
    jobs.executor.shutdown(wait=True)
    state=client.get('/api/research/jobs/'+response.json()['job_id']).json()
    assert state['status']=='completed'
    output=client.get('/api/research/reports/'+state['report_id']).json()
    assert output['source']=='external_csv_unverified' and not output['report']['profitability_proven']
    assert received['slippage']==.00002 and received['swap_per_lot_day']==2
    assert str(jobs.root) not in json.dumps(output)
    assert client.get('/api/research/reports').json()['reports'][0]['id']==state['report_id']


def test_job_failure_never_creates_a_passing_report(subject,monkeypatch):
    client,jobs=subject;id=imported(client).json()['id']
    def fail(*args,**kwargs):raise ValueError('Deliberate software-validation failure')
    monkeypatch.setattr(research_api,'run_research',fail)
    result=client.post('/api/research/run',json=assumptions(id)).json()
    jobs.executor.shutdown(wait=True)
    state=client.get('/api/research/jobs/'+result['job_id']).json()
    assert state['status']=='failed' and 'report_id' not in state
    assert client.get('/api/research/reports').json()=={'reports':[]}


def test_only_one_job_can_run_and_server_restart_does_not_claim_success(subject,monkeypatch):
    client,jobs=subject;id=imported(client).json()['id']
    started,release=threading.Event(),threading.Event()
    def evaluate(*args,**kwargs):
        started.set()
        assert release.wait(10)
        return {'purpose':'test fixture'}
    monkeypatch.setattr(research_api,'run_research',evaluate)
    try:
        response=client.post('/api/research/run',json=assumptions(id));assert response.status_code==200
        assert started.wait(3)
        assert client.post('/api/research/run',json=assumptions(id)).status_code==409
    finally:release.set()
    jobs.executor.shutdown(wait=True)
    orphan='a'*32
    jobs.write(jobs.path('jobs',orphan),{'job_id':orphan,'status':'running'})
    restarted=ResearchJobs(jobs.root)
    try:
        failed=restarted.read('jobs',orphan)
        assert failed['status']=='failed' and 'restarted' in failed['error']
        assert 'report_id' not in failed
    finally:restarted.executor.shutdown(wait=True)


def test_ids_cannot_escape_research_storage(subject):
    client,jobs=subject
    assert client.get('/api/research/jobs/not-an-id').status_code==404
    assert client.get('/api/research/reports/'+'c'*32).status_code==404
    with pytest.raises(HTTPException) as refused:jobs.dataset('../outside')
    assert refused.value.status_code==404


def test_report_symlinks_cannot_escape_research_storage(subject,tmp_path,create_symlink):
    client,jobs=subject;outside=tmp_path/'outside.json';outside.write_text('{"id":"private-outside","source":"private-source","summary":"private-summary"}')
    create_symlink(jobs.root/'reports'/('b'*32+'.json'),outside)
    assert client.get('/api/research/reports/'+'b'*32).status_code==404
    listed=client.get('/api/research/reports')
    assert listed.status_code==200 and listed.json()=={'reports':[]}
    assert 'private-outside' not in listed.text


def test_dataset_metadata_symlink_and_broken_report_link_are_not_followed(subject,tmp_path,create_symlink):
    client,jobs=subject;id=imported(client).json()['id']
    sidecar=jobs.path('datasets',id,'.meta.json');outside=tmp_path/'outside.meta.json'
    sidecar.replace(outside);create_symlink(sidecar,outside)
    assert client.get('/api/research/datasets').json()=={'datasets':[]}
    assert client.post('/api/research/run',json=assumptions(id)).status_code==404
    create_symlink(jobs.root/'reports'/('e'*32+'.json'),tmp_path/'missing.json')
    assert client.get('/api/research/reports').json()=={'reports':[]}


def test_ml_uses_explicit_point_costs_and_signed_swap_without_promoting_model(subject,monkeypatch):
    from backend import ml_research
    client,jobs=subject;id=imported(client).json()['id'];received={}
    def ml(candles,costs,horizon,**options):
        received.update(costs=costs,horizon=horizon,options=options)
        return {'purpose':'isolated test forecast','sample_count':len(candles)}
    monkeypatch.setattr(ml_research,'run_research',ml)
    response=client.post('/api/research/ml',json=assumptions(id,horizon=8));assert response.status_code==200
    jobs.executor.shutdown(wait=True)
    state=jobs.read('jobs',response.json()['job_id'])
    assert state['status']=='completed'
    assert received['costs'].spread_points==pytest.approx(10)
    assert received['costs'].slippage_points==pytest.approx(2)
    assert received['costs'].swap_per_lot_day==-2 and received['horizon']==8
    assert 'model_output' not in received['options']

import pytest
from fastapi.testclient import TestClient
from backend import api
from backend.store import Store

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('API_TOKEN','test-token-for-local-suite-only-123456')
    monkeypatch.setattr(api,'store',Store(str(tmp_path/'test.sqlite')))
    monkeypatch.setattr(api,'source','synthetic')
    with TestClient(api.app) as c:
        c.headers['Authorization']='Bearer test-token-for-local-suite-only-123456'
        yield c


def test_auth_required(client):
    assert client.get('/api/status',headers={'Authorization':'Bearer invalid'}).status_code==401


def test_health_has_no_account_information(client):
    r=client.get('/health');assert r.status_code==200
    assert r.json()==dict(status='ok',source='synthetic',live_execution=False)


def test_candles_and_alignment(client):
    c=client.get('/api/candles?tf=H4');assert c.status_code==200
    assert len(c.json()['candles'])==300
    r=client.get('/api/analysis').json()
    assert set(r['analysis'])=={'D1','H4','M30'}


def test_synthetic_execution_refused(client):
    r=client.post('/api/demo/execute',json={'symbol':'EURUSD','confirmation':'DEMO ONLY'})
    assert r.status_code==422 and 'cannot be traded' in r.json()['detail']


def test_emergency_and_news(client):
    assert client.post('/api/emergency',json={'enabled':True}).json()['emergency']
    assert client.get('/api/status').json()['emergency']
    assert client.post('/api/news-clearance',json={'minutes':15,'confirmed_review':False}).status_code==422
    assert client.post('/api/news-clearance',json={'minutes':16,'confirmed_review':True}).status_code==422
    assert client.post('/api/news-clearance',json={'minutes':15,'confirmed_review':True}).status_code==200
    assert len(client.get('/api/events').json())==2


def test_invalid_tf_and_limits(client):
    assert client.get('/api/candles?tf=BAD').status_code==422
    assert client.get('/api/candles?count=999999').status_code==422


def test_no_live_endpoint(client):
    assert client.post('/api/live/execute',json={}).status_code==404


def test_synthetic_automation_refused(client):
    assert client.post('/api/demo/automation',json={'enabled':True,'symbol':'EURUSD','confirmation':'DEMO ONLY'}).status_code==422
    assert client.post('/api/demo/automation',json={'enabled':False}).status_code==200


def test_automation_worker_disabled_does_not_touch_broker(client,monkeypatch):
    class Stop:
        calls=0
        def wait(self,seconds):
            self.calls+=1
            return self.calls>1
    monkeypatch.setattr(api,'get_bridge',lambda:pytest.fail('Disabled worker must not access MT5'))
    api.store.set('automation_enabled',False)
    api.automation_worker(Stop())


def test_worker_records_failure_without_retry_loop(client,monkeypatch):
    class Stop:
        calls=0
        def wait(self,seconds):
            self.calls+=1
            return self.calls>2
    monkeypatch.setattr(api,'get_bridge',lambda:object())
    monkeypatch.setattr(api,'frames',lambda s:{})
    def fail(*a,**kw): raise ValueError('News clearance expired')
    monkeypatch.setattr(api,'execute_demo',fail)
    api.store.set('automation_enabled',True)
    api.automation_worker(Stop())
    events=api.store.events()
    assert len(events)==1 and events[0]['kind']=='automation_wait'

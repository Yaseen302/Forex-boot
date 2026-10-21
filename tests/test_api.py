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


def test_chart_response_includes_price_grid(client):
    r=client.get('/api/candles?symbol=EURUSD').json()
    assert r['price_precision']==5 and r['price_min_move']==.00001
    r=client.get('/api/candles?symbol=XAUUSD').json()
    assert r['price_precision']==2 and r['price_min_move']==.01


def test_mt5_chart_uses_broker_precision_not_symbol_guess(client,monkeypatch):
    from types import SimpleNamespace as NS
    from backend.market import synthetic
    bridge=NS(candles=lambda *args:synthetic(),mt=NS(symbol_info=lambda name:NS(digits=3,trade_tick_size=.001)))
    monkeypatch.setattr(api,'source','mt5')
    monkeypatch.setattr(api,'get_bridge',lambda:bridge)
    r=client.get('/api/candles?symbol=XAUUSDm').json()
    assert r['price_precision']==3 and r['price_min_move']==.001


def test_calendar_mode_does_not_accept_manual_override(client,monkeypatch):
    monkeypatch.setenv('NEWS_MODE','calendar')
    response=client.post('/api/news-clearance',json={'minutes':15,'confirmed_review':True})
    assert response.status_code==422 and 'calendar mode' in response.json()['detail']
    assert api.store.get('news_clear_until',0)==0
    status=client.get('/api/status').json()
    assert not status['news_clearance']['allowed'] and status['news_clearance']['mode']=='calendar'


def test_news_endpoint_uses_selected_symbol_and_requires_auth(client,monkeypatch):
    monkeypatch.setattr(api,'news_clearance',lambda store,symbol,now:dict(allowed=symbol=='GBPJPYm',mode='calendar',reason='test fixture',expires_at=now+10))
    assert client.get('/api/news?symbol=GBPJPYm').json()['allowed']
    assert not client.get('/api/news?symbol=EURUSDm').json()['allowed']
    assert client.get('/api/news?symbol=').status_code==422
    assert client.get('/api/news',headers={'Authorization':'Bearer wrong'}).status_code==401


def test_synthetic_reports_do_not_touch_mt5_or_claim_order_evidence(client,monkeypatch,tmp_path):
    from backend.observation import ObservationStore
    monkeypatch.setattr(api,'observation_store',ObservationStore(tmp_path/'observations.sqlite'))
    monkeypatch.setattr(api,'get_bridge',lambda:pytest.fail('Synthetic read-only controls cannot access a broker'))
    api.store.reserve('old-other-account',{'symbol':'GBPUSD'},metadata={'account':'other:999'})
    assert client.get('/api/orders').json()==[]
    result=client.get('/api/reconciliation').json()
    assert result['orders']==[] and result['ledger'] is None
    assert result['other_account_submission_blocked']
    assert client.post('/api/reconciliation/sync',json={}).status_code==422
    report=client.get('/api/observation').json()
    assert report['samples']==0 and report['actual_observation_seconds']==0
    assert client.post('/api/observation/sample',json={'symbol':'EURUSDm'}).status_code==422


def test_reconciliation_exposes_only_current_account_and_keeps_other_locks(client,monkeypatch):
    from types import SimpleNamespace as NS
    account=NS(server='Current-Demo',login=123)
    monkeypatch.setattr(api,'source','mt5')
    monkeypatch.setattr(api,'get_bridge',lambda:NS(account=lambda:account))
    api.store.reserve('visible-current',{'symbol':'EURUSDm'},metadata={'account':'Current-Demo:123'})
    api.store.finish('visible-current','filled',{'volume':.01})
    api.store.reserve('hidden-other',{'symbol':'GBPUSDm'},metadata={'account':'Other-Demo:999'})
    report=dict(account='Current-Demo:123',checked_at=1,resolved=[{'signal_id':'visible-current'}],
                pending=[{'signal_id':'hidden-other','reason':'private'}],risk_alerts=[],errors=[],ledger=api.store.ledger('Current-Demo:123'))
    monkeypatch.setattr(api,'sync_ledger',lambda *args:report)
    current=client.get('/api/reconciliation').json()
    assert [row['signal_id'] for row in current['orders']]==['visible-current']
    assert [row['signal_id'] for row in client.get('/api/orders').json()]==['visible-current']
    synced=client.post('/api/reconciliation/sync',json={}).json()
    assert synced['pending']==[] and synced['other_account_submission_blocked']
    assert 'hidden-other' not in str(current)+str(synced)
    assert api.store.orders()[0]['status']=='pending'


def test_account_switch_during_sync_hides_previous_account_ledger(client,monkeypatch):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(api,'source','mt5')
    monkeypatch.setattr(api,'get_bridge',lambda:NS(account=lambda:NS(server='New-Demo',login=456)))
    monkeypatch.setattr(api,'sync_ledger',lambda *args:dict(account='Old-Demo:123',pending=[{'signal_id':'old-secret'}],ledger={'private':'old-ledger'}))
    response=client.post('/api/reconciliation/sync',json={})
    assert response.status_code==200
    report=response.json()
    assert report['account']=='New-Demo:456' and report['ledger'] is None and report['pending']==[]
    assert 'old-secret' not in response.text and 'old-ledger' not in response.text


def test_manual_execution_checks_history_before_and_protection_after_fill(client,monkeypatch):
    from types import SimpleNamespace as NS
    calls=[];account=NS(server='Current-Demo',login=123)
    monkeypatch.setattr(api,'source','mt5')
    monkeypatch.setattr(api,'get_bridge',lambda:NS(account=lambda:account))
    monkeypatch.setattr(api,'frames',lambda symbol:{})
    def sync(*args):
        calls.append('sync')
        return dict(account='Current-Demo:123',resolved=[],pending=[],errors=[],risk_alerts=[],ledger={})
    def execute(*args):
        calls.append('execute')
        return {'retcode':10009,'volume':.01}
    monkeypatch.setattr(api,'sync_ledger',sync);monkeypatch.setattr(api,'execute_demo',execute)
    response=client.post('/api/demo/execute',json={'symbol':'EURUSDm','confirmation':'DEMO ONLY'})
    assert response.status_code==200 and calls==['sync','execute','sync']
    assert response.json()['retcode']==10009 and not response.json()['emergency']


def test_failed_post_fill_check_stops_new_entries_without_retrying_fill(client,monkeypatch):
    from types import SimpleNamespace as NS
    calls=[];account=NS(server='Current-Demo',login=123)
    monkeypatch.setattr(api,'source','mt5')
    monkeypatch.setattr(api,'get_bridge',lambda:NS(account=lambda:account))
    monkeypatch.setattr(api,'frames',lambda symbol:{})
    def sync(*args):
        calls.append('sync')
        return dict(account='Current-Demo:123',resolved=[],pending=[],risk_alerts=[],ledger={},errors=['Offline'] if len(calls)>1 else [])
    def execute(*args):calls.append('execute');return {'retcode':10009}
    monkeypatch.setattr(api,'sync_ledger',sync);monkeypatch.setattr(api,'execute_demo',execute)
    response=client.post('/api/demo/execute',json={'symbol':'EURUSDm','confirmation':'DEMO ONLY'})
    assert response.status_code==200 and calls.count('execute')==1
    assert api.store.get('emergency') and response.json()['emergency']
    assert response.json()['reconciliation']['errors']==['Offline']


def test_reconciliation_failure_prevents_new_execution(client,monkeypatch):
    monkeypatch.setattr(api,'source','mt5')
    monkeypatch.setattr(api,'get_bridge',lambda:object())
    monkeypatch.setattr(api,'sync_ledger',lambda *args:{'errors':['History unavailable']})
    monkeypatch.setattr(api,'execute_demo',lambda *args:pytest.fail('History failure must block new sends'))
    assert client.post('/api/demo/execute',json={'symbol':'EURUSDm','confirmation':'DEMO ONLY'}).status_code==503


def test_observation_reuses_monotonic_collector_and_report_does_not_query_broker(client,monkeypatch,tmp_path):
    from backend.observation import DemoObserver,ObservationStore
    clock={'wall':1792080000.,'mono':100.};transport_calls=[];broker=object()
    class Transport:
        def snapshot(self,symbol,now):
            transport_calls.append(symbol)
            return dict(account_identity='private-demo-login',connected=True,demo=True,currency='USD',
                        equity=1000,balance=1000,margin_free=1000,positions=0,pending_orders=0,
                        ready_for_data=True,ready_for_demo=True,quote_fresh=True,quote_time=now-1,blockers=[])
    monkeypatch.setattr(api,'source','mt5')
    monkeypatch.setattr(api,'get_bridge',lambda:broker)
    monkeypatch.setattr(api,'observation_store',ObservationStore(tmp_path/'observations.sqlite'))
    monkeypatch.setattr(api,'observer',None)
    monkeypatch.setattr(api,'MT5ReadOnlyTransport',lambda bridge:Transport())
    monkeypatch.setattr(api,'DemoObserver',lambda transport,store:DemoObserver(transport,store,clock=lambda:clock['wall'],monotonic=lambda:clock['mono']))
    first=client.post('/api/observation/sample',json={'symbol':'EURUSDm'})
    assert first.status_code==200 and first.json()['report']['actual_observation_seconds']==0
    clock['wall']+=60;clock['mono']+=60
    second=client.post('/api/observation/sample',json={'symbol':'EURUSDm'})
    assert second.json()['report']['actual_observation_seconds']==60
    assert transport_calls==['EURUSDm','EURUSDm']
    monkeypatch.setattr(api,'get_bridge',lambda:pytest.fail('Persisted observation report cannot query the broker'))
    report=client.get('/api/observation?symbol=EURUSDm')
    assert report.status_code==200 and report.json()['samples']==2
    assert 'private-demo-login' not in report.text
    assert client.get('/api/observation?symbol=GBPUSDm').json()['samples']==0


def test_opted_in_worker_checks_broker_protection_after_fill_and_stops_on_failure(client,monkeypatch):
    from types import SimpleNamespace as NS
    calls=[]
    class Stop:
        count=0
        def wait(self,seconds):self.count+=1;return self.count>1
    monkeypatch.setattr(api,'source','mt5')
    account=NS(server='Demo',login=123,trade_mode=0)
    monkeypatch.setattr(api,'get_bridge',lambda:NS(account=lambda:account,mt=NS(ACCOUNT_TRADE_MODE_DEMO=0)))
    monkeypatch.setattr(api,'frames',lambda symbol:{})
    def sync(*args):
        calls.append('sync')
        return {'errors':['No protection history'] if len(calls)>1 else []}
    def execute(*args):calls.append('execute');return {'retcode':10009}
    monkeypatch.setattr(api,'sync_ledger',sync);monkeypatch.setattr(api,'execute_demo',execute)
    api.store.set('automation_enabled',True)
    api.store.set('automation_account','Demo:123')
    api.automation_worker(Stop())
    assert calls==['sync','execute','sync'] and api.store.get('emergency')
    assert api.store.events()[0]['kind']=='automation_wait'
    assert 'without retrying' in api.store.events()[0]['payload']['reason']


def test_automation_binds_explicit_consent_and_stops_when_demo_account_changes(client,monkeypatch):
    from types import SimpleNamespace as NS
    account=NS(server='Demo',login=123,trade_mode=0);sends=[];analyses=[]
    broker=NS(account=lambda:account,mt=NS(ACCOUNT_TRADE_MODE_DEMO=0))
    monkeypatch.setattr(api,'source','mt5');monkeypatch.setenv('ENABLE_DEMO_EXECUTION','1')
    monkeypatch.setattr(api,'get_bridge',lambda:broker)
    monkeypatch.setattr(api,'sync_ledger',lambda *args:{'errors':[]})
    monkeypatch.setattr(api,'frames',lambda symbol:analyses.append(symbol) or {})
    monkeypatch.setattr(api,'execute_demo',lambda *args:sends.append(account.login) or {})
    start=client.post('/api/demo/automation',json={'enabled':True,'symbol':'EURUSDm','confirmation':'DEMO ONLY'})
    assert start.status_code==200 and api.store.get('automation_account')=='Demo:123'
    assert '123' not in start.text
    class Stop:
        count=0
        def wait(self,seconds):
            self.count+=1
            if self.count==2:account.login=456
            return self.count>2
    api.automation_worker(Stop())
    assert sends==[123] and analyses==['EURUSDm']
    assert not api.store.get('automation_enabled')
    # Stopping must not silently rebind consent to the new login.
    assert api.store.get('automation_account')=='Demo:123'
    stopped=api.store.events()[0]
    assert stopped['kind']=='automation_stopped' and stopped['payload']['reason']=='account_changed'
    assert '123' not in str(stopped) and '456' not in str(stopped)
    retry=client.post('/api/demo/automation',json={'enabled':True,'symbol':'EURUSDm','confirmation':'DEMO ONLY'})
    assert retry.status_code==200 and api.store.get('automation_account')=='Demo:456'
    class Once:
        count=0
        def wait(self,seconds):self.count+=1;return self.count>1
    api.automation_worker(Once())
    assert sends==[123,456]


@pytest.mark.parametrize('change',[{'login':456},{'server':'Different-Demo'},{'trade_mode':2}])
def test_automation_rechecks_binding_after_history_before_execution(client,monkeypatch,change):
    from types import SimpleNamespace as NS
    account=NS(server='Demo',login=123,trade_mode=0)
    broker=NS(account=lambda:account,mt=NS(ACCOUNT_TRADE_MODE_DEMO=0))
    monkeypatch.setattr(api,'source','mt5');monkeypatch.setattr(api,'get_bridge',lambda:broker)
    monkeypatch.setattr(api,'sync_ledger',lambda *args:{'errors':[]})
    def data(symbol):
        for key,value in change.items():setattr(account,key,value)
        return {}
    monkeypatch.setattr(api,'frames',data)
    monkeypatch.setattr(api,'execute_demo',lambda *args:pytest.fail('Changed account cannot inherit automation consent'))
    api.store.set('automation_account','Demo:123');api.store.set('automation_enabled',True)
    class Once:
        count=0
        def wait(self,seconds):self.count+=1;return self.count>1
    api.automation_worker(Once())
    assert not api.store.get('automation_enabled')
    assert api.store.events()[0]['payload']['reason']=='account_changed'


def test_missing_account_binding_stops_worker_without_analysis_or_sends(client,monkeypatch):
    monkeypatch.setattr(api,'source','mt5');monkeypatch.setattr(api,'get_bridge',lambda:object())
    monkeypatch.setattr(api,'frames',lambda *args:pytest.fail('Missing account binding cannot run analysis'))
    monkeypatch.setattr(api,'execute_demo',lambda *args:pytest.fail('Missing account binding cannot trade'))
    api.store.set('automation_enabled',True)
    class Once:
        count=0
        def wait(self,seconds):self.count+=1;return self.count>1
    api.automation_worker(Once())
    assert not api.store.get('automation_enabled')
    assert api.store.events()[0]['payload']['reason']=='account_changed'


def test_stop_automation_always_works_without_broker_and_clears_consent(client,monkeypatch):
    api.store.set('automation_account','Demo:123');api.store.set('automation_enabled',True)
    monkeypatch.setattr(api,'get_bridge',lambda:pytest.fail('Stop must work without a broker connection'))
    response=client.post('/api/demo/automation',json={'enabled':False})
    assert response.status_code==200 and not response.json()['enabled']
    assert not api.store.get('automation_enabled') and api.store.get('automation_account') is None

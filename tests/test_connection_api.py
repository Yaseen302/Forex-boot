"""The connection endpoint is authenticated, read-only and source-aware."""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from backend import api
from backend.store import Store


TOKEN='test-connection-api-token-local-only-123456'


class ConnectionSpy:
    def __init__(self):
        self.bridge_calls=0
        self.diagnostic_symbols=[]
        self.report=dict(connected=True,ready_for_data=True,ready_for_demo=True,
            requested_symbol='EURUSDm',resolved_symbol='EURUSDm',candidates=['EURUSDm'],
            terminal=dict(connected=True,trade_allowed=True,tradeapi_disabled=False),
            account=dict(mode='demo',server='Exness-MT5Trial',currency='USD'),
            history={tf:dict(bars=300,age_seconds=5) for tf in ('D1','H4','M30')},
            checks=[dict(id=key,status='pass',title=key,detail='Validated by fake transport') for key in
                    ('terminal','demo_account','python_trading','symbol','contract_values','filling',
                     'history_D1','history_H4','history_M30','quote')],
            positions=0,pending_orders=0)
        self.mt=NS(order_send=lambda *args,**kwargs:pytest.fail('Connection endpoint must never submit orders'),
                   order_check=lambda *args,**kwargs:pytest.fail('Connection endpoint must never prepare orders'))

    def get_bridge(self):
        self.bridge_calls+=1
        return self

    def diagnostics(self,symbol):
        self.diagnostic_symbols.append(symbol)
        report=deepcopy(self.report)
        report['requested_symbol']=symbol
        return report


@pytest.fixture
def connection_client(tmp_path,monkeypatch):
    spy=ConnectionSpy()
    monkeypatch.setenv('API_TOKEN',TOKEN)
    monkeypatch.setattr(api,'source','synthetic')
    monkeypatch.setattr(api,'store',Store(str(tmp_path/'connection-api.sqlite')))
    monkeypatch.setattr(api,'bridge',None)
    monkeypatch.setattr(api,'get_bridge',spy.get_bridge)
    monkeypatch.setattr(api,'execute_demo',lambda *args,**kwargs:pytest.fail('Read-only check must not execute a demo trade'))
    with TestClient(api.app) as client:
        client.headers['Authorization']='Bearer '+TOKEN
        yield client,spy


def test_synthetic_connection_report_never_claims_broker_readiness(connection_client):
    client,spy=connection_client
    response=client.get('/api/connection',params={'symbol':'EURUSDm'})
    assert response.status_code==200
    report=response.json()
    assert report['source']=='synthetic'
    assert not report['connected'] and not report['ready_for_data'] and not report['ready_for_demo']
    assert report['checks'][0]['id']=='source'
    assert report['checks'][0]['status']=='warn'
    assert report['checks'][0]['action']
    assert spy.bridge_calls==0 and not spy.diagnostic_symbols
    assert not api.store.get('automation_enabled',False)
    assert not api.store.orders()


def test_mt5_connection_passes_exact_symbol_and_complete_report(connection_client,monkeypatch):
    client,spy=connection_client
    monkeypatch.setattr(api,'source','mt5')
    response=client.get('/api/connection',params={'symbol':'EURUSDm'})
    assert response.status_code==200
    assert spy.bridge_calls==1 and spy.diagnostic_symbols==['EURUSDm']
    assert response.json()==dict(source='mt5',**spy.report)
    assert not api.store.get('automation_enabled',False)
    assert not api.store.orders()


def test_ambiguous_symbol_retains_connected_terminal_and_suffix_suggestions(connection_client,monkeypatch):
    client,spy=connection_client
    monkeypatch.setattr(api,'source','mt5')
    spy.report.update(ready_for_data=False,ready_for_demo=False,resolved_symbol=None,
                      checks=[dict(id='symbol',status='fail',title='Exact broker symbol',
                                   detail='Select an exact broker symbol',action='Select EURUSDm in Market Watch')])
    response=client.get('/api/connection')
    assert response.status_code==200
    report=response.json()
    assert spy.diagnostic_symbols==['EURUSD']
    assert report['requested_symbol']=='EURUSD'
    assert report['connected'] and not report['ready_for_data'] and not report['ready_for_demo']
    assert report['candidates']==['EURUSDm'] and report['resolved_symbol'] is None
    assert report['checks']==spy.report['checks']


@pytest.mark.parametrize('authorization',['Bearer incorrect','','Basic invalid'])
def test_connection_rejects_bad_auth_without_touching_broker(connection_client,monkeypatch,authorization):
    client,spy=connection_client
    monkeypatch.setattr(api,'source','mt5')
    response=client.get('/api/connection',params={'symbol':'EURUSDm'},headers={'Authorization':authorization})
    assert response.status_code==401
    assert spy.bridge_calls==0 and not spy.diagnostic_symbols


@pytest.mark.parametrize('endpoint',['/api/connection','/api/candles'])
@pytest.mark.parametrize('symbol',['','X'*65])
def test_malformed_symbol_rejected_before_any_broker_access(connection_client,monkeypatch,endpoint,symbol):
    client,spy=connection_client
    monkeypatch.setattr(api,'source','mt5')
    response=client.get(endpoint,params={'symbol':symbol})
    assert response.status_code==422
    assert spy.bridge_calls==0 and not spy.diagnostic_symbols


@pytest.mark.parametrize('count',['0','29','2001','not-a-number','3.5'])
def test_malformed_history_count_rejected_before_any_broker_access(connection_client,monkeypatch,count):
    client,spy=connection_client
    monkeypatch.setattr(api,'source','mt5')
    response=client.get('/api/candles',params={'symbol':'EURUSDm','count':count})
    assert response.status_code==422
    assert spy.bridge_calls==0 and not spy.diagnostic_symbols

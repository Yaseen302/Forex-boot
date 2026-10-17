import math
import pytest
from backend.risk import size, guards


def inputs(**kw):
    return dict(equity=1000,day_equity=1000,peak_equity=1000,positions=0,spread_points=10,tick_age=2,margin_free=900,margin_needed=50,entry=1.1,stop=1.09,target=1.12,side='BUY',news_clear=True,emergency=False,**kw)


def test_ten_dollars_skips_minimum_lot():
    r=size(10,1000,.01,100,.01)
    assert not r['ok'] and r['volume']==0

@pytest.mark.parametrize('step',[.01,.025,.05,.1,.25,1.])
def test_non_decimal_steps_never_exceed_budget(step):
    r=size(1000000,1234,step,100,step)
    assert r['ok']
    assert r['estimated_loss']<=r['risk_budget']
    assert math.isclose(r['volume']/step,round(r['volume']/step))

@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,0])
def test_invalid_equity(value):
    with pytest.raises(ValueError):size(value,100,.01,10,.01)


def test_guard_valid(): assert guards(**inputs())==[]

@pytest.mark.parametrize('field,value,reason',[
 ('equity',979,'Daily loss limit'),('peak_equity',1100,'Maximum drawdown'),
 ('positions',1,'Position limit'),('spread_points',50,'Spread filter'),
 ('tick_age',31,'Stale quote'),('tick_age',-1,'Stale quote'),
 ('margin_free',40,'Insufficient margin'),('emergency',True,'Emergency stop'),
 ('news_clear',False,'News clearance'),('target',1.11,'reward/risk'),('stop',1.11,'SL/TP'),
 ('equity',float('nan'),'Non-finite')])
def test_guards_fail_closed(field,value,reason):
    d=inputs();d[field]=value
    assert any(reason in x for x in guards(**d))


def test_config_cannot_expand_cap(monkeypatch):
    from backend.risk import configured_limits
    monkeypatch.setenv('RISK_RISK_PERCENT','5')
    with pytest.raises(ValueError,match='0.5'):configured_limits()

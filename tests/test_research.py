"""All prices in this module are labeled fixtures, never broker performance."""
import csv
import hashlib
import io
import json
from types import SimpleNamespace
import pytest
from backend.research import (dataset_info,load_dataset,import_csv,export_history,run_research,
                              SOURCE_FIXTURE,SOURCE_EXTERNAL,SOURCE_BROKER)


def fixture_csv(count=8000):
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['time','open','high','low','close','volume'])
    for i in range(count):writer.writerow([i*1800,1.1,1.101,1.099,1.1,10])
    return out.getvalue()


def import_fixture(tmp_path,count=8000):
    path=tmp_path/'fixture.csv'
    info=import_csv(fixture_csv(count),path,symbol='EURUSDfixture',contract_size=100000.,volume_min=.01,
                   volume_max=100.,volume_step=.01,point=.00001)
    sidecar=path.with_suffix('.meta.json');meta=json.loads(sidecar.read_text())
    meta.update(source=SOURCE_FIXTURE,fixture=True,generator='unit-test constant prices')
    sidecar.write_text(json.dumps(meta))
    return path,meta


def test_missing_provenance_is_not_a_broker_dataset(tmp_path):
    p=tmp_path/'plain.csv';p.write_text(fixture_csv())
    r=dataset_info(p)
    assert not r['eligible'] and not r['valid'] and 'sidecar' in r['issues'][0]


def test_fixture_cannot_be_implicitly_used_as_broker_performance(tmp_path):
    path,_=import_fixture(tmp_path)
    info=dataset_info(path)
    assert info['valid'] and not info['eligible'] and info['source']==SOURCE_FIXTURE
    with pytest.raises(ValueError,match='Synthetic fixture'):load_dataset(path)
    candles,checked=load_dataset(path,allow_fixture=True)
    assert len(candles)==8000
    assert any('SYNTHETIC FIXTURE' in w for w in checked['warnings'])


def test_fixture_metadata_cannot_be_simply_relabeled_broker(tmp_path):
    path,meta=import_fixture(tmp_path)
    meta.update(source=SOURCE_BROKER,exporter='ForexLab MT5 history exporter v1',broker_server='fixture-server')
    path.with_suffix('.meta.json').write_text(json.dumps(meta))
    info=dataset_info(path)
    assert not info['valid'] and 'fixtures cannot' in info['issues'][0]


def test_tampered_csv_hash_fails(tmp_path):
    path,_=import_fixture(tmp_path)
    path.write_text(path.read_text().replace('1.101','1.102',1))
    assert 'SHA-256' in dataset_info(path)['issues'][0]


def test_ordering_and_completed_boundaries_are_enforced(tmp_path):
    p=tmp_path/'invalid.csv'
    bad=fixture_csv(10).splitlines();bad[-1]=bad[-2]
    with pytest.raises(ValueError,match='increasing'):import_csv('\n'.join(bad),p,symbol='fixture')
    bad=fixture_csv(10).replace('1800,','1801,',1)
    with pytest.raises(ValueError,match='aligned'):import_csv(bad,p,symbol='fixture')


def test_import_requires_specs_and_explicit_unverified_acknowledgement(tmp_path):
    path=tmp_path/'external.csv'
    info=import_csv(fixture_csv(),path,symbol='user-declared-symbol')
    assert info['source']==SOURCE_EXTERNAL and not info['valid']
    assert 'contract_size' in info['issues'][0]
    path2=tmp_path/'external-with-declarations.csv'
    info=import_csv(fixture_csv(),path2,symbol='user-declared-symbol',contract_size=100000.,volume_min=.01,
                    volume_max=100.,volume_step=.01,point=.00001)
    assert info['valid'] and not info['eligible']
    with pytest.raises(ValueError,match='allow_unverified'):load_dataset(path2)
    _,info=load_dataset(path2,allow_unverified=True)
    assert any('UNVERIFIED' in w for w in info['warnings'])


def test_short_history_and_long_gaps_are_ineligible(tmp_path):
    path,_=import_fixture(tmp_path,count=1600)
    info=dataset_info(path)
    assert info['valid'] and not info['eligible'] and '8000' in info['issues'][0]
    raw=fixture_csv().splitlines()
    for i in range(4001,len(raw)):
        fields=raw[i].split(',');fields[0]=str(int(fields[0])+10*86400);raw[i]=','.join(fields)
    info=import_csv('\n'.join(raw),tmp_path/'gapped.csv',symbol='fixture',contract_size=100000.,volume_min=.01,
                    volume_max=100.,volume_step=.01,point=.00001)
    assert info['gap_count']==1 and info['missing_m30_slots']==480
    assert 'eight days' in info['issues'][0]


def test_cross_currency_not_mispriced_as_usd(tmp_path):
    path,meta=import_fixture(tmp_path)
    meta['instrument']['profit_currency']='JPY';path.with_suffix('.meta.json').write_text(json.dumps(meta))
    assert 'USD profit currency' in dataset_info(path)['issues'][0]


def test_report_has_provenance_hash_cost_units_and_fixture_label(tmp_path):
    path,meta=import_fixture(tmp_path)
    r=run_research(path,output_dir=tmp_path/'reports',allow_fixture=True,spread=.0001,slippage=.00002,
                   commission=7.,swap_per_lot_day=2.)
    assert r['source']==SOURCE_FIXTURE and r['purpose']=='fixture_engine_validation'
    assert not r['profitability_proven']
    assert r['dataset']['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    saved=json.loads(open(r['file']).read())
    assert saved['report_id']==r['report_id']
    assert saved['costs']['spread']==.0001 and saved['costs']['commission']==7.
    assert len(saved['evaluation']['sections'])==3 and len(saved['evaluation']['rolling_out_of_sample'])==3
    for section in saved['evaluation']['sections']:
        result=section['report']
        assert result['trades']==0 and result['uncertainty']['status']=='insufficient_trades'
        assert result['cash_baseline']['net']==0
        assert all(t['time']>=section['start_time'] for t in result['ledger'])
        assert result['equity_curve'][0]['time']==section['start_time']+1800


@pytest.mark.parametrize('field,value',[('spread',None),('commission',float('nan')),('slippage',float('inf')),('swap_per_lot_day',-1)])
def test_research_requires_all_costs_explicit_finite_nonnegative(tmp_path,field,value):
    path,_=import_fixture(tmp_path)
    costs=dict(spread=0.,slippage=0.,commission=0.,swap_per_lot_day=0.);costs[field]=value
    with pytest.raises(ValueError,match='Explicit finite'):run_research(path,allow_fixture=True,**costs)


def test_export_reads_history_and_specs_without_login_or_secret(tmp_path):
    """A fake MT5 adapter validates the export contract, not real broker access."""
    class Bridge:
        def connect(self):pass
        def account(self):return SimpleNamespace(server='Fixture broker adapter',currency='USD',login=987654,password='NEVER EXPORT')
        def candles(self,symbol,tf,count):
            assert symbol=='EURUSDfixture' and tf=='M30' and count==8000
            return [dict(time=i*1800,open=1.1,high=1.101,low=1.099,close=1.1,volume=10.) for i in range(count)]
        mt=SimpleNamespace(SYMBOL_CHART_MODE_BID=0,symbol_info=lambda symbol:SimpleNamespace(
            chart_mode=0,trade_contract_size=100000.,volume_min=.01,volume_max=100.,volume_step=.01,point=.00001,
            currency_profit='USD',currency_base='EUR',trade_calc_mode=0,digits=5,trade_tick_size=.00001,trade_tick_value=1.))
    path=tmp_path/'adapter-contract.csv';info=export_history(Bridge(),'EURUSDfixture',8000,path)
    assert info['source']==SOURCE_BROKER and info['eligible']
    text=path.with_suffix('.meta.json').read_text()
    assert 'password' not in text and 'login' not in text and '987654' not in text and 'NEVER EXPORT' not in text
    with pytest.raises(ValueError,match='already exists'):export_history(Bridge(),'EURUSDfixture',8000,path)


def test_account_switch_during_export_does_not_save_mixed_provenance(tmp_path):
    before=SimpleNamespace(server='Fixture demo',currency='USD',login=123)
    after=SimpleNamespace(server='Fixture demo',currency='USD',login=456)
    accounts=iter((before,after))
    spec=SimpleNamespace(chart_mode=0)
    bridge=SimpleNamespace(connect=lambda:None,account=lambda:next(accounts),
        mt=SimpleNamespace(SYMBOL_CHART_MODE_BID=0,symbol_info=lambda symbol:spec),
        candles=lambda *args:[dict(time=i*1800,open=1.1,high=1.101,low=1.099,close=1.1,volume=10.) for i in range(8000)])
    path=tmp_path/'switched.csv'
    with pytest.raises(ValueError,match='Account changed'):export_history(bridge,'EURUSDfixture',8000,path)
    assert not path.exists() and not path.with_suffix('.meta.json').exists()

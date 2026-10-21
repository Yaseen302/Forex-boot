"""Broker reconciliation is conservative, durable and never sends an order."""
from types import SimpleNamespace as NS
import sqlite3
import pytest
from backend.reconciliation import MAGIC, reconcile_pending
from backend.store import Store

NOW=1780000205


@pytest.fixture
def broker(tmp_path,monkeypatch):
    monkeypatch.setattr('backend.reconciliation.time.time',lambda:NOW)
    account=NS(server='Exness-Demo',login=123,trade_mode=0)
    mt=NS(ACCOUNT_TRADE_MODE_DEMO=0)
    mt.history_orders_get=lambda *args:[]
    mt.history_deals_get=lambda *args:[]
    mt.positions_get=lambda:[]
    mt.orders_get=lambda:[]
    mt.order_send=lambda *args:pytest.fail('Reconciliation must never submit broker orders')
    mt.order_check=lambda *args:pytest.fail('Reconciliation must remain read-only')
    bridge=NS(mt=mt,connect=lambda:NS(connected=True),account=lambda:account)
    store=Store(str(tmp_path/'journal.sqlite'))
    request=dict(symbol='EURUSDm',type=0,volume=.2,price=1.1001,sl=1.099,tp=1.103,
                 magic=MAGIC,comment='FL:abcdef123456789012345678')
    store.reserve('signal-1',request,metadata=dict(account='Exness-Demo:123',login='123',server='Exness-Demo',
                                                submitted_at=NOW-30,trade_mode=0))
    return bridge,store,request,account


def deal(request,**changes):
    fields=dict(ticket=456,order=1234,position_id=789,entry=0,type=request['type'],magic=request['magic'],
                time=NOW-20,volume=request['volume'],price=request['price'],profit=0,commission=-.2,
                swap=0,fee=0,symbol=request['symbol'],comment=request['comment'])
    fields.update(changes)
    return NS(**fields)


def order(request,**changes):
    fields=dict(ticket=1234,type=request['type'],magic=request['magic'],symbol=request['symbol'],
                comment=request['comment'],time_setup=NOW-25,volume_initial=request['volume'],
                volume_current=0,state=4)
    fields.update(changes)
    return NS(**fields)


def install_fill(broker,**changes):
    bridge,_,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request,**changes)]


def test_timeout_then_history_fill_releases_lock_and_prevents_duplicate(broker):
    bridge,store,request,_=broker
    store.response('signal-1',dict(retcode=10012,order=0,deal=0,volume=0))
    assert reconcile_pending(bridge,store)['pending']
    install_fill(broker)
    report=reconcile_pending(bridge,store)
    assert report['resolved']==[dict(signal_id='signal-1',status='filled',volume=.2)]
    assert store.orders()[0]['request']==request
    assert store.ledger('Exness-Demo:123')['deal_count']==1
    with pytest.raises(ValueError,match='Duplicate'):store.reserve('signal-1',request)
    store.reserve('new-signal',request)


def test_persisted_restart_keeps_request_identity_and_recovers(broker):
    bridge,store,request,_=broker
    install_fill(broker)
    restarted=Store(store.path)
    assert reconcile_pending(bridge,restarted)['resolved']
    assert restarted.orders()[0]['metadata']['account']=='Exness-Demo:123'
    assert restarted.ledger()['deal_count']==1
    assert reconcile_pending(bridge,Store(store.path))['ledger']['deal_count']==1


def test_changed_account_cannot_match_another_account_history(broker):
    bridge,store,_,account=broker
    install_fill(broker)
    account.login=999
    assert reconcile_pending(bridge,store)['pending']
    assert store.orders()[0]['status']=='pending'
    assert store.ledger()['deal_count']==0


def test_account_changes_during_queries_prevent_any_write(broker):
    bridge,store,request,account=broker
    def history(*args):
        account.login=999
        return [deal(request)]
    bridge.mt.history_deals_get=history
    report=reconcile_pending(bridge,store)
    assert 'Account changed' in report['errors'][0]
    assert store.orders()[0]['status']=='pending'
    assert store.ledger()['deal_count']==0


@pytest.mark.parametrize('change',[
    dict(magic=0),dict(comment='manual'),dict(symbol='GBPUSDm'),dict(type=1),
    dict(time=NOW-10000),dict(entry=1),dict(volume=.3),
])
def test_unrelated_or_mismatched_deals_never_release_lock(broker,change):
    install_fill(broker,**change)
    report=reconcile_pending(broker[0],broker[1])
    assert report['pending']
    assert broker[1].orders()[0]['status']=='pending'
    assert broker[1].ledger()['deal_count']==0


def test_partial_fill_visible_but_remains_locked(broker):
    install_fill(broker,volume=.1)
    report=reconcile_pending(broker[0],broker[1])
    assert report['pending'][0]['filled_volume']==.1
    assert broker[1].orders()[0]['status']=='pending'
    assert report['ledger']['deals'][0]['volume']==.1
    with pytest.raises(ValueError,match='Unresolved'):broker[1].reserve('other',broker[2])


def test_distinct_orders_with_same_comment_are_ambiguous(broker):
    bridge,store,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request,volume=.1),deal(request,ticket=457,order=1235,volume=.1)]
    assert 'Multiple broker orders' in reconcile_pending(bridge,store)['pending'][0]['reason']
    assert store.ledger()['deal_count']==0


def test_split_deals_for_one_order_prove_full_volume(broker):
    bridge,store,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request,volume=.1),deal(request,ticket=457,volume=.1)]
    assert reconcile_pending(bridge,store)['resolved'][0]['status']=='filled'
    assert store.ledger()['deal_count']==2


def test_rotating_partial_history_cannot_merge_distinct_broker_orders(broker):
    bridge,store,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request,volume=.1,order=1234)]
    assert reconcile_pending(bridge,store)['pending']
    assert store.ledger()['deal_count']==1
    bridge.mt.history_deals_get=lambda *args:[deal(request,ticket=457,volume=.1,order=1235)]
    report=reconcile_pending(bridge,store)
    assert report['pending'] and not report['resolved']
    assert store.orders()[0]['status']=='pending'
    assert store.get('emergency') is True
    assert report['risk_alerts'][0]['kind']=='multiple_correlated_orders'
    assert store.ledger()['deal_count']==1


def test_identical_duplicate_tickets_do_not_double_count(broker):
    bridge,store,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request,volume=.1),deal(request,volume=.1)]
    assert reconcile_pending(bridge,store)['errors']
    assert store.orders()[0]['status']=='pending'


@pytest.mark.parametrize('function',['history_deals_get','history_orders_get','positions_get','orders_get'])
def test_failed_broker_queries_preserve_lock(broker,function):
    bridge,store,_,_=broker
    install_fill(broker)
    setattr(bridge.mt,function,lambda *args:None)
    assert reconcile_pending(bridge,store)['errors']
    assert store.orders()[0]['status']=='pending'
    assert store.ledger()['deal_count']==0


def test_empty_history_is_never_rejection(broker):
    report=reconcile_pending(broker[0],broker[1])
    assert 'absence of history' in report['pending'][0]['reason']
    assert broker[1].orders()[0]['status']=='pending'


@pytest.mark.parametrize('state,status',[(2,'canceled'),(5,'rejected'),(6,'expired')])
def test_positive_final_unfilled_order_resolves_without_retry(broker,state,status):
    bridge,store,request,_=broker
    bridge.mt.history_orders_get=lambda *args:[order(request,state=state,volume_current=.2)]
    assert reconcile_pending(bridge,store)['resolved'][0]['status']==status
    with pytest.raises(ValueError,match='Duplicate'):store.reserve('signal-1',request)


def test_canceled_partial_is_not_treated_as_unfilled(broker):
    bridge,store,request,_=broker
    bridge.mt.history_orders_get=lambda *args:[order(request,state=2,volume_current=.1)]
    install_fill(broker,volume=.1)
    assert reconcile_pending(bridge,store)['pending']
    assert store.orders()[0]['status']=='pending'


def test_explicit_broker_reject_can_resolve_but_timeout_cannot(broker):
    bridge,store,_,_=broker
    store.response('signal-1',dict(retcode=10006,order=0,deal=0,volume=0))
    assert reconcile_pending(bridge,store)['resolved'][0]['status']=='rejected'


def test_exact_order_correlation_handles_broker_altered_deal_comment(broker):
    bridge,store,request,_=broker
    bridge.mt.history_orders_get=lambda *args:[order(request)]
    install_fill(broker,comment='broker updated')
    assert reconcile_pending(bridge,store)['resolved'][0]['status']=='filled'


def test_current_active_matching_order_keeps_pending(broker):
    bridge,store,request,_=broker
    install_fill(broker)
    bridge.mt.orders_get=lambda:[order(request,state=1)]
    assert 'remains active' in reconcile_pending(bridge,store)['pending'][0]['reason']
    assert store.orders()[0]['status']=='pending'


def test_sl_tp_risk_breach_sets_emergency_without_broker_mutation(broker):
    bridge,store,request,_=broker
    install_fill(broker)
    bridge.mt.positions_get=lambda:[NS(ticket=789,identifier=789,symbol=request['symbol'],magic=MAGIC,
                                        type=0,sl=0,tp=0,volume=.2)]
    report=reconcile_pending(bridge,store)
    assert {a['kind'] for a in report['risk_alerts']}=={'stop_missing_or_widened','take_profit_changed'}
    assert store.get('emergency') is True
    assert store.orders()[0]['status']=='filled'
    first_event_count=len(store.events())
    reconcile_pending(bridge,store)
    assert len(store.events())==first_event_count


def test_later_exit_deals_track_net_realized_pnl_with_costs(broker):
    bridge,store,request,_=broker
    install_fill(broker)
    reconcile_pending(bridge,store)
    bridge.mt.history_deals_get=lambda *args:[deal(request),deal(request,ticket=999,order=3333,entry=1,type=1,
                                                               comment='[tp 1.103]',profit=58,commission=-.2,swap=-1,fee=-.1)]
    report=reconcile_pending(bridge,store)
    ledger=report['ledger']
    assert ledger['deal_count']==2
    assert ledger['net_realized']==pytest.approx(56.5)
    assert ledger['deals'][1]['entry']==1
    assert ledger['trades'][0]['lifecycle']=='closed'
    assert ledger['closed_trades']==ledger['winning_closed_trades']==1
    assert store.ledger('other:123')['deal_count']==0
    reconcile_pending(bridge,store)
    assert store.ledger()['deal_count']==2


def test_manual_close_of_exclusively_attributed_position_is_actual_outcome(broker):
    bridge,store,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request),deal(request,ticket=999,entry=1,type=1,magic=0,
                                                               comment='manual close',profit=20)]
    report=reconcile_pending(bridge,store)
    assert report['ledger']['deal_count']==2
    assert report['ledger']['trades'][0]['lifecycle']=='closed'


def test_mixed_netting_position_cannot_attribute_manual_profit(broker):
    bridge,store,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request),deal(request,ticket=555,order=1235,entry=0,
                                                               magic=0,comment='manual entry')]
    report=reconcile_pending(bridge,store)
    assert report['pending']
    assert store.get('emergency') is True
    assert report['ledger']['deal_count']==0


def test_actual_broker_stop_risk_above_saved_budget_sets_emergency(broker):
    bridge,store,request,_=broker
    with store.connect() as db:
        import json
        metadata=store.orders()[0]['metadata']
        metadata['risk']=dict(risk_budget=25,commission_per_lot=7,slippage_loss_per_lot=10)
        db.execute('UPDATE orders SET metadata=?',(json.dumps(metadata),))
    install_fill(broker,price=1.12)
    bridge.mt.positions_get=lambda:[NS(ticket=789,identifier=789,symbol=request['symbol'],magic=MAGIC,
                                      type=0,sl=request['sl'],tp=request['tp'],volume=.2,price_open=1.12)]
    bridge.mt.order_calc_profit=lambda k,s,v,p,sl:(sl-p)*100000*v
    report=reconcile_pending(bridge,store)
    assert report['risk_alerts'][0]['kind']=='actual_stop_risk_exceeds_budget'
    assert report['risk_alerts'][0]['actual_risk']>400
    assert store.get('emergency') is True


def test_already_verified_entry_remains_available_when_history_window_omits_it(broker):
    bridge,store,request,_=broker
    install_fill(broker)
    reconcile_pending(bridge,store)
    bridge.mt.history_deals_get=lambda *args:[deal(request,ticket=999,entry=1,type=1,profit=20)]
    report=reconcile_pending(bridge,store)
    assert report['ledger']['trades'][0]['lifecycle']=='closed'
    assert report['ledger']['deal_count']==2


def test_filled_entry_without_position_or_exit_blocks_further_entries(broker):
    bridge,store,_,_=broker
    install_fill(broker)
    report=reconcile_pending(bridge,store)
    assert store.orders()[0]['status']=='filled'  # broker fill itself is proven
    assert store.get('emergency') is True
    assert report['risk_alerts'][0]['kind']=='position_disposition_unverified'


def test_durable_exit_proof_does_not_become_unsettled_when_history_is_omitted(broker):
    bridge,store,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request),deal(request,ticket=999,entry=1,type=1)]
    report=reconcile_pending(bridge,store)
    assert report['ledger']['closed_trades']==1 and not report['risk_alerts']
    bridge.mt.history_deals_get=lambda *args:[]
    report=reconcile_pending(bridge,store)
    assert report['ledger']['closed_trades']==1 and not report['risk_alerts']
    assert store.get('emergency',False) is False


def test_broker_query_exception_keeps_pending_without_crashing_recovery(broker):
    bridge,store,_,_=broker
    def failed(*args):raise OSError('broker transport interrupted')
    bridge.mt.history_deals_get=failed
    assert reconcile_pending(bridge,store)['errors']
    assert store.orders()[0]['status']=='pending'


def test_unrelated_manual_exit_cannot_pollute_bot_ledger(broker):
    bridge,store,request,_=broker
    bridge.mt.history_deals_get=lambda *args:[deal(request),deal(request,ticket=999,entry=1,type=1,position_id=99999,magic=0,profit=5000)]
    assert reconcile_pending(bridge,store)['ledger']['deal_count']==1


def test_legacy_database_is_additively_migrated_without_clearing_lock(tmp_path):
    path=str(tmp_path/'old.sqlite')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE orders(signal_id TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL)')
        db.execute('INSERT INTO orders VALUES (?,?,?)',('old','pending','{"symbol":"EURUSDm"}'))
    store=Store(path)
    assert store.orders()[0]['payload']==dict(symbol='EURUSDm')
    assert store.orders()[0]['request'] is None
    with pytest.raises(ValueError,match='Unresolved'):store.reserve('new',{})


def test_account_scoped_ledger_retains_separate_ticket_namespaces(tmp_path):
    store=Store(str(tmp_path/'journal.sqlite'))
    store.record_deal('a:1','s1',dict(ticket=123,profit=10))
    store.record_deal('b:2','s2',dict(ticket=123,profit=-2))
    assert store.ledger('a:1')['net_realized']==10
    assert store.ledger('b:2')['net_realized']==-2


def test_ledger_ticket_cannot_be_reassigned_to_another_signal(tmp_path):
    store=Store(str(tmp_path/'journal.sqlite'))
    store.record_deal('a:1','s1',dict(ticket=123,profit=10))
    with pytest.raises(ValueError,match='another signal'):
        store.record_deal('a:1','s2',dict(ticket=123,profit=20))

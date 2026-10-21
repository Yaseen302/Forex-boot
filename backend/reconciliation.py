"""Read-only, account-scoped recovery of uncertain MT5 demo submissions.

Missing history never means an order failed. Only broker records bearing the
persisted request correlation, or an explicit rejection response, resolve a lock.
Call under the same MT5 lock used for execution. No function sends/modifies orders.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import time
from types import SimpleNamespace

MAGIC = 260017


def account_key(account):
    return f'{account.server}:{account.login}'


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _time(record, order=False):
    field = 'time_setup' if order else 'time'
    millis = getattr(record, field + '_msc', 0)
    value = millis / 1000 if _finite(millis) and millis > 0 else getattr(record, field, 0)
    return float(value) if _finite(value) else 0


def _same_volume(left, right):
    return _finite(left) and _finite(right) and abs(float(left) - float(right)) < 1e-8


def _identity(record, request):
    return (getattr(record, 'magic', None) == request['magic']
            and getattr(record, 'symbol', None) == request['symbol']
            and getattr(record, 'type', None) == request['type'])


def _correlated(record, request, submitted, now, order=False):
    return (_identity(record, request)
            and getattr(record, 'comment', None) == request['comment']
            and submitted - 120 <= _time(record, order) <= now + 60)


def confirmed_fill(deals, request, submitted, now, *, ticket=None, order=None):
    """Strict single-request proof shared by immediate verification and recovery."""
    if not deals:
        return None
    found = []
    for deal in deals:
        if ticket is not None and getattr(deal, 'ticket', None) != ticket:
            continue
        if not _correlated(deal, request, submitted, now):
            continue
        if getattr(deal, 'entry', None) != 0:  # DEAL_ENTRY_IN; no netting reversal inference
            continue
        if order is not None and getattr(deal, 'order', None) != order:
            continue
        volume = getattr(deal, 'volume', None)
        if not _finite(volume) or volume <= 0:
            continue
        found.append(deal)
    # An exact ticket query must identify one full entry, not an arbitrary partial.
    if ticket is not None:
        return found if len(found) == 1 and _same_volume(found[0].volume, request['volume']) else None
    return found if found and _same_volume(sum(d.volume for d in found), request['volume']) else None


def _deal_payload(deal):
    fields = ('ticket', 'order', 'position_id', 'entry', 'type', 'magic', 'time',
              'volume', 'price', 'profit', 'commission', 'swap', 'fee', 'symbol', 'comment')
    result = {field: getattr(deal, field, '' if field in ('symbol', 'comment') else 0) for field in fields}
    for field in ('volume', 'price', 'profit', 'commission', 'swap', 'fee'):
        if not _finite(result[field]):
            raise ValueError('Non-finite broker deal data')
        result[field] = float(result[field])
    for field in ('ticket', 'order', 'position_id', 'entry', 'type', 'magic', 'time'):
        result[field] = int(result[field])
    if result['ticket'] <= 0 or result['position_id'] <= 0 or result['volume'] <= 0 or result['price'] <= 0:
        raise ValueError('Incomplete broker deal identity')
    return result


def _dedupe(records):
    seen = {}
    for record in records:
        ticket = getattr(record, 'ticket', None)
        if ticket is None or ticket in seen:
            raise ValueError('Duplicate or missing broker history ticket; reconciliation is ambiguous')
        seen[ticket] = record
    return list(seen.values())


def _entry_matches(row, deals, orders, now):
    request, meta = row['request'], row['metadata']
    submitted = float(meta['submitted_at'])
    matches = [order for order in orders if _correlated(order, request, submitted, now, order=True)
               and _same_volume(getattr(order, 'volume_initial', None), request['volume'])]
    direct = [deal for deal in deals if _correlated(deal, request, submitted, now)
              and getattr(deal, 'entry', None) == 0]
    order_ids = {getattr(d, 'order', None) for d in direct} | {o.ticket for o in matches}
    if len(order_ids) > 1:
        return [], None, 'Multiple broker orders share this correlation; manual review required'
    if matches:
        linked = [d for d in deals if getattr(d, 'order', None) == matches[0].ticket
                  and _identity(d, request) and getattr(d, 'entry', None) == 0
                  and submitted - 120 <= _time(d) <= now + 60]
        # An order with the exact persisted correlation can verify deal comments
        # altered by a broker, provided order linkage and the other fields agree.
        entries = linked
    else:
        entries = direct
    if any(not _finite(getattr(d, 'volume', None)) or d.volume <= 0 for d in entries):
        return [], None, 'Invalid broker fill volume'
    if sum(d.volume for d in entries) > request['volume'] + 1e-8:
        return [], None, 'Broker fill volume exceeds request; manual review required'
    return entries, matches[0] if matches else None, None


def _positive_rejection(row):
    response = row.get('response') or {}
    # TIMEOUT/CONNECTION/ERROR/PLACED/PARTIAL responses are never a no-fill proof.
    return (response.get('retcode') in (10006, 10007)
            and response.get('order') == 0 and response.get('deal') == 0
            and response.get('volume') == 0)


def _alerts(bridge, row, positions, entries, exits):
    request = row['request']
    position_ids = {int(getattr(deal, 'position_id', 0)) for deal in entries}
    result = []
    actual_risks = []
    matched = [p for p in positions if getattr(p, 'identifier', getattr(p, 'ticket', 0)) in position_ids]
    for position_id in position_ids:
        remaining=sum(float(d.volume) for d in entries if d.position_id==position_id)-sum(float(d.volume) for d in exits if d.position_id==position_id)
        if remaining>1e-8 and not any(getattr(p,'identifier',getattr(p,'ticket',0))==position_id for p in matched):
            result.append(dict(signal_id=row['signal_id'],kind='position_disposition_unverified',emergency=True,
                               position=position_id,unaccounted_volume=remaining))
    if sum(float(getattr(p, 'volume', 0)) for p in matched) > request['volume'] + 1e-8:
        result.append(dict(signal_id=row['signal_id'],kind='excess_position_volume',emergency=True))
    for position in matched:
        base = dict(signal_id=row['signal_id'],position=int(position.ticket))
        if not _finite(getattr(position,'volume',None)) or position.volume <= 0:
            result.append(dict(base,kind='invalid_position_volume',emergency=True))
            continue
        if not _identity(position, request):
            result.append(dict(base,kind='position_identity_changed',emergency=True))
            continue
        sl, tp = getattr(position, 'sl', 0), getattr(position, 'tp', 0)
        wrong_sl = (not _finite(sl) or sl <= 0 or
                    (request['type'] == 0 and sl < request['sl'] - 1e-8) or
                    (request['type'] == 1 and sl > request['sl'] + 1e-8))
        if wrong_sl:
            result.append(dict(base,kind='stop_missing_or_widened',emergency=True,
                               expected_stop=request['sl'],actual_stop=sl if _finite(sl) else None))
        if not _same_volume(tp, request['tp']):
            result.append(dict(base,kind='take_profit_changed',emergency=False,
                               expected_target=request['tp'],actual_target=tp if _finite(tp) else None))
        risk = row['metadata'].get('risk',{})
        if risk.get('risk_budget') is not None and not wrong_sl:
            try:
                open_price=getattr(position,'price_open',None)
                if not _finite(open_price) or open_price <= 0:
                    raise ValueError('Actual broker entry price unavailable')
                profit=bridge.mt.order_calc_profit(position.type,request['symbol'],position.volume,open_price,sl)
                if not _finite(profit):
                    raise ValueError('Actual broker stop-loss calculation unavailable')
                costs=position.volume*(risk.get('commission_per_lot',0)+risk.get('slippage_loss_per_lot',0))
                actual=max(0,-float(profit))+costs
                actual_risks.append(actual)
            except (ValueError,TypeError,AttributeError,OverflowError):
                result.append(dict(base,kind='actual_stop_risk_unavailable',emergency=True))
    budget=row['metadata'].get('risk',{}).get('risk_budget')
    if budget is not None and sum(actual_risks) > budget + 1e-8:
        result.append(dict(signal_id=row['signal_id'],kind='actual_stop_risk_exceeds_budget',emergency=True,
                           risk_budget=budget,actual_risk=sum(actual_risks)))
    return result


def reconcile_pending(bridge, store):
    """Resolve positively matched demo submissions and sync verified broker deals.

    The caller must serialize this with all other MT5 calls. Failed queries,
    account changes, legacy requests without identity, and ambiguous matches keep
    their locks. Ledger totals cover attributed bot deals only, not account P/L.
    """
    now = time.time()
    report = dict(account=None,checked_at=now,resolved=[],pending=[],errors=[],risk_alerts=[],ledger=None)
    try:
        bridge.connect()
        account = bridge.account()
        key = account_key(account)
        report['account'] = key
        if account.trade_mode != bridge.mt.ACCOUNT_TRADE_MODE_DEMO:
            raise ValueError('Broker-confirmed DEMO account required for demo reconciliation')
        all_rows = store.orders(limit=None)
        candidates = []
        for row in all_rows:
            meta, request = row['metadata'], row['request']
            if row['status'] == 'pending' and meta.get('account') != key:
                report['pending'].append(dict(signal_id=row['signal_id'],reason='Stored account does not match current broker account; lock retained'))
            elif meta.get('account') == key and row['status'] in ('pending','filled','partially_filled'):
                required = ('magic','comment','symbol','type','volume','sl','tp')
                if (not request or not all(field in request for field in required)
                        or not request['comment'].startswith('FL:') or request['magic'] != MAGIC
                        or not _finite(meta.get('submitted_at')) or meta['submitted_at'] <= 0):
                    report['pending'].append(dict(signal_id=row['signal_id'],reason='Request lacks durable correlation metadata; manual review required'))
                    continue
                candidates.append(row)
        if not candidates:
            report['ledger'] = store.ledger(key)
            return report
        start = datetime.fromtimestamp(min(r['metadata']['submitted_at'] for r in candidates)-120,tz=timezone.utc)
        end = datetime.fromtimestamp(now+60,tz=timezone.utc)
        orders = bridge.mt.history_orders_get(start,end)
        deals = bridge.mt.history_deals_get(start,end)
        positions = bridge.mt.positions_get()
        current_orders = bridge.mt.orders_get()
        if any(values is None for values in (orders,deals,positions,current_orders)):
            raise RuntimeError('Broker history/position query failed; all submission locks retained')
        orders, deals = _dedupe(orders), _dedupe(deals)
        # All changes wait until a second account read confirms query scope.
        current = bridge.account()
        if account_key(current) != key or current.trade_mode != bridge.mt.ACCOUNT_TRADE_MODE_DEMO:
            raise RuntimeError('Account changed during reconciliation; no recovery applied')
        persisted = store.ledger(key)['deals']
        for row in candidates:
            request = row['request']
            entries, order, error = _entry_matches(row,deals,orders,now)
            if error:
                report['pending'].append(dict(signal_id=row['signal_id'],reason=error))
                continue
            existing_ids={getattr(d,'ticket',None) for d in entries}
            entries += [SimpleNamespace(**d) for d in persisted if d['signal_id']==row['signal_id']
                        and d.get('entry')==0 and d['ticket'] not in existing_ids]
            # Broker history may omit an earlier partial on a later poll. The
            # durable entries must participate in the same single-order proof;
            # two distinct orders must never add up to a verified single fill.
            linked_orders={getattr(d,'order',None) for d in entries}
            if order is not None: linked_orders.add(order.ticket)
            if len(linked_orders)>1:
                report['pending'].append(dict(signal_id=row['signal_id'],reason='Multiple broker orders across persisted and current history; lock retained for manual review'))
                report['risk_alerts'].append(dict(signal_id=row['signal_id'],kind='multiple_correlated_orders',emergency=True))
                continue
            if sum(float(d.volume) for d in entries)>request['volume']+1e-8:
                report['pending'].append(dict(signal_id=row['signal_id'],reason='Persisted and current fill volume exceeds request; manual review required'))
                report['risk_alerts'].append(dict(signal_id=row['signal_id'],kind='excess_fill_volume',emergency=True))
                continue
            if any(_correlated(o,request,row['metadata']['submitted_at'],now,order=True) for o in current_orders):
                report['pending'].append(dict(signal_id=row['signal_id'],reason='Matching broker order remains active; lock retained'))
                continue
            # Validate all data before recording any facts for this request.
            position_ids = {getattr(d,'position_id',0) for d in entries}
            unrelated_entries = [d for d in deals if getattr(d,'position_id',0) in position_ids
                                 and getattr(d,'entry',None) in (0,2)
                                 and getattr(d,'ticket',None) not in {entry.ticket for entry in entries}]
            if unrelated_entries:
                report['pending'].append(dict(signal_id=row['signal_id'],reason='Position contains other entries; manual attribution required'))
                report['risk_alerts'].append(dict(signal_id=row['signal_id'],kind='mixed_position_entries',emergency=True))
                continue
            exits = [d for d in deals if getattr(d,'position_id',0) in position_ids
                     and getattr(d,'symbol',None) == request['symbol']
                     and getattr(d,'type',None) == (1 if request['type']==0 else 0)
                     and getattr(d,'entry',None) in (1,3)
                     and row['metadata']['submitted_at'] - 120 <= _time(d) <= now + 60]
            exit_ids={d.ticket for d in exits}
            exits += [SimpleNamespace(**d) for d in persisted if d['signal_id']==row['signal_id']
                      and d.get('entry') in (1,3) and d['ticket'] not in exit_ids]
            if any(getattr(d,'entry',None) == 2 and getattr(d,'position_id',0) in position_ids for d in deals):
                report['pending'].append(dict(signal_id=row['signal_id'],reason='Netting reversal requires manual attribution; lock retained'))
                continue
            try:
                entry_payloads = [_deal_payload(d) for d in entries]
                exit_payloads = [_deal_payload(d) for d in exits]
                if sum(d['volume'] for d in exit_payloads) > sum(d['volume'] for d in entry_payloads) + 1e-8:
                    raise ValueError('Exit volume exceeds attributed entry volume')
            except (ValueError,TypeError,OverflowError) as exc:
                report['pending'].append(dict(signal_id=row['signal_id'],reason=str(exc)))
                continue
            for payload in entry_payloads+exit_payloads:
                store.record_deal(key,row['signal_id'],payload)
            alerts = _alerts(bridge,row,positions,entries,exits)
            report['risk_alerts'].extend(alerts)
            filled = sum(d['volume'] for d in entry_payloads)
            if row['status'] != 'pending':
                continue
            if entries and _same_volume(filled,request['volume']):
                payload = dict(row.get('response') or {},deals=[d['ticket'] for d in entry_payloads],
                               order=entry_payloads[0]['order'],volume=filled,
                               position_ids=sorted(position_ids),verified_by='broker_history',account=key)
                store.finish(row['signal_id'],'filled',payload)
                report['resolved'].append(dict(signal_id=row['signal_id'],status='filled',volume=filled))
            elif entries:
                # FOK remains required. A partial is visible in the ledger, but
                # cannot release the lock until the full disposition is proven.
                report['pending'].append(dict(signal_id=row['signal_id'],reason='Verified partial fill; full order disposition requires manual review',filled_volume=filled))
            elif order is not None and getattr(order,'state',None) in (2,5,6) and _same_volume(getattr(order,'volume_current',None),request['volume']):
                status = {2:'canceled',5:'rejected',6:'expired'}[order.state]
                store.finish(row['signal_id'],status,dict(order=int(order.ticket),verified_by='broker_order_history',account=key))
                report['resolved'].append(dict(signal_id=row['signal_id'],status=status))
            elif _positive_rejection(row):
                store.finish(row['signal_id'],'rejected',dict(row['response'],verified_by='explicit_broker_response',account=key))
                report['resolved'].append(dict(signal_id=row['signal_id'],status='rejected'))
            else:
                report['pending'].append(dict(signal_id=row['signal_id'],reason='No definitive correlated fill or rejection; absence of history cannot release lock'))
        if report['risk_alerts']:
            digest = hashlib.sha256(json.dumps(report['risk_alerts'],sort_keys=True).encode()).hexdigest()
            if store.get('reconciliation_alert_digest:'+key) != digest:
                store.log('broker_risk_alerts',dict(account=key,alerts=report['risk_alerts']))
                store.set('reconciliation_alert_digest:'+key,digest)
            if any(alert['emergency'] for alert in report['risk_alerts']):
                store.set('emergency',True)
        report['ledger'] = store.ledger(key)
    except Exception as exc:
        report['errors'].append(str(exc))
        if report['account']:
            report['ledger'] = store.ledger(report['account'])
    return report


sync_ledger = reconcile_pending

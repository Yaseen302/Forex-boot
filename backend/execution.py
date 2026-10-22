import hashlib
import math
import time
from .market import close_time
from .risk import configured_limits, size, guards
from .strategy import signal
from .reconciliation import MAGIC, account_key, confirmed_fill, _deal_payload
from .news import news_clearance


def execute_demo(bridge,store,symbol,frames,enabled=False,expected_account=None):
    if not enabled: raise ValueError('Demo execution disabled; set ENABLE_DEMO_EXECUTION=1 and restart')
    mt=bridge.mt
    terminal=bridge.connect()
    a=bridge.account()
    if a.trade_mode!=mt.ACCOUNT_TRADE_MODE_DEMO: raise ValueError('Only broker-confirmed DEMO accounts are supported; live is blocked')
    if expected_account is not None and account_key(a)!=expected_account:
        raise ValueError('Account changed from the explicitly consented demo account')
    if not a.trade_allowed or not a.trade_expert or not terminal.trade_allowed or getattr(terminal,'tradeapi_disabled',False):
        raise ValueError('Account/terminal automated trading permission is disabled')
    limits=configured_limits()
    if store.get('emergency',False): raise ValueError('Emergency stop active')
    now=time.time()
    for tf,cs in frames.items():
        age=now-close_time(cs[-1],tf)
        tolerance=300 if tf=='M30' else (86400 if tf=='D1' else 14400)
        if age<0 or age>tolerance: raise ValueError(f'Stale or unclosed {tf} history')
    s=signal(frames)
    if s['side']=='WAIT': raise ValueError('; '.join(s['reasons']))
    info=mt.symbol_info(symbol); tick=mt.symbol_info_tick(symbol)
    if info is None or tick is None: raise ValueError('Broker quote/specification unavailable')
    if getattr(info,'trade_mode',4)!=getattr(mt,'SYMBOL_TRADE_MODE_FULL',4):
        raise ValueError('Symbol does not permit opening both buy and sell trades')
    if not all(math.isfinite(float(x)) and float(x)>0 for x in (info.point,info.trade_tick_size,tick.bid,tick.ask)) or tick.ask<tick.bid:
        raise ValueError('Invalid broker quote/specification')
    positions=mt.positions_get(); orders=mt.orders_get()
    if positions is None or orders is None: raise ValueError('Position/order state unavailable')
    kind=mt.ORDER_TYPE_BUY if s['side']=='BUY' else mt.ORDER_TYPE_SELL
    entry=float(tick.ask if s['side']=='BUY' else tick.bid)
    # Stops and targets must already lie on the broker tick grid; never silently widen risk.
    tick_size=info.trade_tick_size
    stop=round(round(s['stop']/tick_size)*tick_size,info.digits)
    target=round(round(s['target']/tick_size)*tick_size,info.digits)
    minimum=info.trade_stops_level*info.point
    if min(abs(entry-stop),abs(target-entry))<minimum: raise ValueError('Broker minimum stop distance')
    per_lot=mt.order_calc_profit(kind,symbol,1.0,entry,stop)
    if per_lot is None or per_lot>=0 or not math.isfinite(per_lot): raise ValueError('Broker cannot calculate loss at stop')
    slip=mt.order_calc_profit(kind,symbol,1.0,entry,entry-limits.slippage_points*info.point if s['side']=='BUY' else entry+limits.slippage_points*info.point)
    if slip is None or not math.isfinite(slip): raise ValueError('Cannot estimate slippage cost')
    sizing=size(a.equity,abs(per_lot)+abs(slip)+limits.commission_per_lot,info.volume_min,info.volume_max,info.volume_step,limits.risk_percent)
    if not sizing['ok']: raise ValueError(sizing['reason'])
    margin=mt.order_calc_margin(kind,symbol,sizing['volume'],entry)
    if margin is None: raise ValueError('Cannot calculate margin')
    anchors=store.anchors(f'{a.server}:{a.login}',a.equity)
    # Sizing and terminal requests may take time; assess this quote against
    # a clock sampled after it was received, never the evaluation start.
    now=time.time()
    reasons=guards(equity=a.equity,day_equity=anchors['day_equity'],peak_equity=anchors['peak_equity'],
                   positions=len(positions)+len(orders),spread_points=(tick.ask-tick.bid)/info.point,
                   tick_age=now-tick.time,margin_free=a.margin_free,margin_needed=margin,entry=entry,stop=stop,target=target,
                   side=s['side'],news_clear=news_clearance(store,symbol,now)['allowed'],emergency=store.get('emergency',False),limits=limits)
    if reasons: raise ValueError('; '.join(reasons))
    # FOK prevents silent partial fills. Refuse brokers without FOK rather than guessing.
    if not info.filling_mode & 1: raise ValueError('Symbol does not support FOK execution; adapter needs broker-specific validation')
    key=hashlib.sha256(f'{a.server}:{a.login}:{symbol}:{s["time"]}:{s["side"]}'.encode()).hexdigest()
    request=dict(action=mt.TRADE_ACTION_DEAL,symbol=symbol,volume=sizing['volume'],type=kind,price=entry,sl=stop,tp=target,
                 deviation=int(limits.slippage_points),magic=MAGIC,comment='FL:'+key[:24],type_time=mt.ORDER_TIME_GTC,type_filling=mt.ORDER_FILLING_FOK)
    check=mt.order_check(request)
    if check is None or check.retcode!=0: raise ValueError('Broker order_check rejected the request')
    current=bridge.account()
    if current.login!=a.login or current.server!=a.server or current.trade_mode!=mt.ACCOUNT_TRADE_MODE_DEMO:
        raise ValueError('Account changed during order evaluation')
    # Broker checks may block; refresh the real account, quote and exposure before
    # committing to send. A local lock cannot prevent manual trades inside MT5.
    terminal=bridge.connect()
    if not current.trade_allowed or not current.trade_expert or not terminal.trade_allowed or getattr(terminal,'tradeapi_disabled',False):
        raise ValueError('Automated trading permission changed during evaluation')
    fresh=mt.symbol_info_tick(symbol)
    exposure=mt.positions_get(); pending=mt.orders_get()
    if fresh is None or exposure is None or pending is None:
        raise ValueError('Pre-submission broker state unavailable')
    if not all(math.isfinite(float(x)) and float(x)>0 for x in (fresh.bid,fresh.ask)) or fresh.ask<fresh.bid:
        raise ValueError('Invalid pre-submission quote')
    fresh_entry=float(fresh.ask if s['side']=='BUY' else fresh.bid)
    if abs(fresh_entry-entry)>limits.slippage_points*info.point+1e-12:
        raise ValueError('Quote moved beyond the configured entry tolerance; wait for reevaluation')
    fresh_loss=mt.order_calc_profit(kind,symbol,1.0,fresh_entry,stop)
    fresh_slip=mt.order_calc_profit(kind,symbol,1.0,fresh_entry,
                                  fresh_entry-limits.slippage_points*info.point if s['side']=='BUY' else fresh_entry+limits.slippage_points*info.point)
    if fresh_loss is None or fresh_slip is None or not all(math.isfinite(x) for x in (fresh_loss,fresh_slip)) or fresh_loss>=0:
        raise ValueError('Pre-submission risk calculation unavailable')
    fresh_size=size(current.equity,abs(fresh_loss)+abs(fresh_slip)+limits.commission_per_lot,
                    info.volume_min,info.volume_max,info.volume_step,limits.risk_percent)
    if not fresh_size['ok'] or sizing['volume']>fresh_size['volume']+1e-12:
        raise ValueError('Risk budget changed during order evaluation; reevaluation required')
    fresh_margin=mt.order_calc_margin(kind,symbol,sizing['volume'],fresh_entry)
    if fresh_margin is None: raise ValueError('Pre-submission margin unavailable')
    anchors=store.anchors(f'{current.server}:{current.login}',current.equity)
    now=time.time()
    if not 0<=now-close_time(frames['M30'][-1],'M30')<=300:
        raise ValueError('M30 entry window expired during evaluation')
    reasons=guards(equity=current.equity,day_equity=anchors['day_equity'],peak_equity=anchors['peak_equity'],
                   positions=len(exposure)+len(pending),spread_points=(fresh.ask-fresh.bid)/info.point,
                   tick_age=now-fresh.time,margin_free=current.margin_free,margin_needed=fresh_margin,
                   entry=fresh_entry,stop=stop,target=target,side=s['side'],
                   news_clear=news_clearance(store,symbol,now)['allowed'],emergency=store.get('emergency',False),limits=limits)
    if reasons: raise ValueError('; '.join(reasons))
    sizing=dict(sizing,risk_budget=fresh_size['risk_budget'],equity_at_submission=current.equity,
                commission_per_lot=limits.commission_per_lot,slippage_loss_per_lot=abs(fresh_slip),
                estimated_loss=sizing['volume']*(abs(fresh_loss)+abs(fresh_slip)+limits.commission_per_lot))
    submitted_at=time.time()
    store.reserve(key,request,metadata=dict(account=account_key(current),login=str(current.login),server=current.server,
                                          trade_mode=int(current.trade_mode),submitted_at=submitted_at,risk=sizing))
    # From this point an exception/ambiguous response intentionally leaves a durable pending record.
    try:
        result=mt.order_send(request)
    except Exception as exc:
        store.log('submission_transport_error',dict(signal_id=key,error_type=type(exc).__name__))
        raise RuntimeError('Submission status unknown; broker transport failed; do not retry') from exc
    if result is None: raise RuntimeError('Submission status unknown; inspect broker history, do not retry')
    payload=dict(retcode=int(result.retcode),order=int(result.order),deal=int(result.deal),volume=float(result.volume),price=float(result.price),risk=sizing)
    store.response(key,payload)
    if result.retcode==mt.TRADE_RETCODE_DONE:
        deals=mt.history_deals_get(ticket=result.deal)
        verified=confirmed_fill(deals,request,submitted_at,time.time(),ticket=result.deal,order=result.order)
        after=bridge.account()
        if account_key(after)!=account_key(current) or after.trade_mode!=mt.ACCOUNT_TRADE_MODE_DEMO:
            raise RuntimeError('Account changed while verifying deal; submission remains pending')
        if not verified:
            store.log('fill_requires_reconciliation',dict(signal_id=key,**payload))
            raise RuntimeError('Deal history has not confirmed the fill; submission remains pending')
        for deal in verified:
            store.record_deal(account_key(current),key,_deal_payload(deal))
        store.finish(key,'filled',payload)
    else:
        store.log('submission_requires_reconciliation',dict(signal_id=key,**payload))
        raise RuntimeError('Broker did not confirm a complete fill; submission locked pending reconciliation')
    return payload

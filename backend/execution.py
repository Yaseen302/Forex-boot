import hashlib
import math
import time
from .market import close_time
from .risk import configured_limits, size, guards
from .strategy import signal


def execute_demo(bridge,store,symbol,frames,enabled=False):
    if not enabled: raise ValueError('Demo execution disabled; set ENABLE_DEMO_EXECUTION=1 and restart')
    mt=bridge.mt
    terminal=bridge.connect()
    a=bridge.account()
    if a.trade_mode!=mt.ACCOUNT_TRADE_MODE_DEMO: raise ValueError('Only broker-confirmed DEMO accounts are supported; live is blocked')
    if not a.trade_allowed or not a.trade_expert or not terminal.trade_allowed:
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
    reasons=guards(equity=a.equity,day_equity=anchors['day_equity'],peak_equity=anchors['peak_equity'],
                   positions=len(positions)+len(orders),spread_points=(tick.ask-tick.bid)/info.point,
                   tick_age=now-tick.time,margin_free=a.margin_free,margin_needed=margin,entry=entry,stop=stop,target=target,
                   side=s['side'],news_clear=store.get('news_clear_until',0)>now,emergency=store.get('emergency',False),limits=limits)
    if reasons: raise ValueError('; '.join(reasons))
    # FOK prevents silent partial fills. Refuse brokers without FOK rather than guessing.
    if not info.filling_mode & 1: raise ValueError('Symbol does not support FOK execution; adapter needs broker-specific validation')
    request=dict(action=mt.TRADE_ACTION_DEAL,symbol=symbol,volume=sizing['volume'],type=kind,price=entry,sl=stop,tp=target,
                 deviation=int(limits.slippage_points),magic=260017,comment='ForexLab demo',type_time=mt.ORDER_TIME_GTC,type_filling=mt.ORDER_FILLING_FOK)
    check=mt.order_check(request)
    if check is None or check.retcode!=0: raise ValueError('Broker order_check rejected the request')
    key=hashlib.sha256(f'{a.server}:{a.login}:{symbol}:{s["time"]}:{s["side"]}'.encode()).hexdigest()
    current=bridge.account()
    if current.login!=a.login or current.server!=a.server or current.trade_mode!=mt.ACCOUNT_TRADE_MODE_DEMO:
        raise ValueError('Account changed during order evaluation')
    store.reserve(key,request)
    # From this point an exception/ambiguous response intentionally leaves a durable pending record.
    result=mt.order_send(request)
    if result is None: raise RuntimeError('Submission status unknown; inspect broker history, do not retry')
    payload=dict(retcode=int(result.retcode),order=int(result.order),deal=int(result.deal),volume=float(result.volume),price=float(result.price),risk=sizing)
    if result.retcode==mt.TRADE_RETCODE_DONE:
        deals=mt.history_deals_get(ticket=result.deal)
        verified=deals and any(d.ticket==result.deal and d.symbol==symbol and d.type==kind and abs(d.volume-sizing['volume'])<1e-8 for d in deals)
        if not verified:
            store.log('fill_requires_reconciliation',dict(signal_id=key,**payload))
            raise RuntimeError('Deal history has not confirmed the fill; submission remains pending')
        store.finish(key,'filled',payload)
    else:
        store.log('submission_requires_reconciliation',dict(signal_id=key,**payload))
        raise RuntimeError('Broker did not confirm a complete fill; submission locked pending reconciliation')
    return payload

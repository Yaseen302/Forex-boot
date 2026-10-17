"""Read-only MT5 preflight, shared by the API and Windows connection checker.

Reports contain only selected operational fields, never environment dumps,
terminal filesystem paths, names, passwords, or raw broker error messages.
Call while holding the same MT5 lock as all other terminal operations.
"""
import argparse
import json
import math
import time

from .market import close_time, validate
from .risk import configured_limits


def _number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):
        return None


def _flag(value):
    return bool(value) if value is not None else None


def connection_report(bridge,symbol='EURUSD',count=300,now=None):
    """Inspect the currently logged-in terminal. No login guesses or orders.

    ready_for_demo means connection prerequisites passed at check time. Signal,
    risk sizing, news review and execution opt-in remain separate gates.
    """
    if not isinstance(symbol,str) or not 1<=len(symbol)<=64:
        raise ValueError('Select an exact broker symbol name of 1–64 characters')
    if not isinstance(count,int) or isinstance(count,bool) or not 30<=count<=2000:
        raise ValueError('History check count must be between 30 and 2000')
    now=time.time() if now is None else float(now)
    report=dict(checked_at=now,requested_symbol=symbol,resolved_symbol=None,candidates=[],
                connected=False,ready_for_data=False,ready_for_demo=False,checks=[],
                terminal=None,account=None,symbol=None,history={},positions=None,pending_orders=None,
                notice='Read-only connection check. No orders are sent. Passing is not a signal or profit guarantee.')
    data_ok=True
    demo_ok=True

    def check(key,title,ok,detail,action=None,scope='demo',warning=False):
        nonlocal data_ok,demo_ok
        status='pass' if ok else ('warn' if warning else 'fail')
        item=dict(id=key,title=title,status=status,detail=detail)
        if not ok and action: item['action']=action
        report['checks'].append(item)
        if not ok and not warning:
            demo_ok=False
            if scope=='data': data_ok=False

    mt=bridge.mt
    try:
        terminal=bridge.connect()
    except Exception:
        check('terminal','MT5 desktop connection',False,'Cannot connect to the selected MT5 desktop terminal.',
              'Open Exness MT5, log in, check its bottom-right connection status, and retry. If multiple terminals are installed, set MT5_TERMINAL_PATH to the intended terminal64.exe.',scope='data')
        return report
    report['connected']=bool(getattr(terminal,'connected',False))
    report['terminal']={key:_flag(getattr(terminal,key,None)) for key in ('connected','trade_allowed','tradeapi_disabled')}
    report['terminal']['explicit_path']=bool(getattr(bridge,'terminal_path',None))
    check('terminal','MT5 desktop connection',report['connected'],'The selected MT5 terminal is connected to its broker.' if report['connected'] else 'MT5 is disconnected.',
          'Check the account server and Internet connection in MT5.',scope='data')
    check('terminal_trading','MT5 Algo Trading',getattr(terminal,'trade_allowed',None) is True,
          'Terminal Algo Trading permission is enabled.' if getattr(terminal,'trade_allowed',None) else 'Terminal Algo Trading permission is disabled or unavailable.',
          'For demo execution, enable Algo Trading in MT5. Analysis can remain read-only.')
    check('python_trading','External Python trading permission',getattr(terminal,'tradeapi_disabled',None) is False,
          'External Python trading is allowed by MT5.' if getattr(terminal,'tradeapi_disabled',None) is False else 'External Python trading is blocked or permission cannot be verified.',
          'In MT5 Tools → Options → Expert Advisors, clear “Disable automatic trading through the external Python API” for demo execution.')
    try:
        account=mt.account_info()
    except Exception:
        account=None
    check('account','Broker account details',account is not None,'Account details are readable.' if account is not None else 'MT5 has no readable account.',
          'Log in to your Exness demo account in the selected MT5 terminal; do not enter credentials in this dashboard.',scope='data')
    if account is not None:
        is_demo=getattr(account,'trade_mode',None)==getattr(mt,'ACCOUNT_TRADE_MODE_DEMO',object())
        report['account']=dict(mode='demo' if is_demo else 'non-demo',server=str(getattr(account,'server','')),
            currency=str(getattr(account,'currency','')),balance=_number(getattr(account,'balance',None)),
            equity=_number(getattr(account,'equity',None)),margin_free=_number(getattr(account,'margin_free',None)),
            trade_allowed=_flag(getattr(account,'trade_allowed',None)),trade_expert=_flag(getattr(account,'trade_expert',None)))
        check('demo_account','Demo account verification',is_demo,'Broker confirms a demo account.' if is_demo else 'Broker account is not verified as DEMO. Live execution is blocked.',
              'Switch MT5 to an Exness MT5 demo account before enabling demo automation.')
        allowed=getattr(account,'trade_allowed',None) is True and getattr(account,'trade_expert',None) is True
        check('account_trading','Account automated trading permission',allowed,'Account permits trading and expert execution.' if allowed else 'Account trade_allowed/trade_expert is disabled or unavailable.',
              'Confirm this is a tradable demo account with the correct trading login, not an investor/read-only login.')
    try:
        positions=mt.positions_get()
        orders=mt.orders_get()
    except Exception:
        positions=orders=None
    state_ok=positions is not None and orders is not None
    if state_ok:
        report['positions']=len(positions)
        report['pending_orders']=len(orders)
    check('account_state','Open positions and pending orders',state_ok,
          f'{len(positions)} open position(s), {len(orders)} pending order(s) across the account.' if state_ok else 'Unable to read account-wide positions or pending orders.',
          'Check MT5 connectivity and refresh; new entries require a readable broker account state.')
    if state_ok:
        check('position_capacity','Capacity for a new position',not positions and not orders,
              'No existing broker positions or pending orders.' if not positions and not orders else 'Existing positions/orders occupy the one-position limit.',
              'Inspect existing positions and orders in MT5. The bot will not automatically close them.')
    try:
        symbols=mt.symbols_get()
    except Exception:
        symbols=None
    names=sorted({str(s.name) for s in symbols}) if symbols is not None else []
    report['candidates']=[name for name in names if symbol.upper() in name.upper()][:30]
    exact=symbol in names
    if exact: report['resolved_symbol']=symbol
    check('symbol','Exact broker symbol',exact,
          f'Exact symbol {symbol} exists.' if exact else 'The requested exact symbol is unavailable; the broker may use a suffix such as EURUSDm.',
          'Select one of the reported broker symbol candidates or use the exact name shown in MT5 Market Watch. The checker never guesses a suffix.',scope='data')
    if not exact:
        report['ready_for_data']=False
        report['ready_for_demo']=False
        return report
    try:
        info=mt.symbol_info(symbol)
    except Exception:
        info=None
    check('symbol_info','Broker contract specification',info is not None,
          'Symbol specification is readable.' if info is not None else 'Symbol specification is unavailable.',
          'Open the symbol Specification dialog in MT5 and retry.',scope='data')
    if info is None: return report
    specs={key:_number(getattr(info,key,None)) for key in ('digits','point','trade_tick_size','trade_tick_value','trade_tick_value_profit',
            'trade_tick_value_loss','trade_contract_size','volume_min','volume_max','volume_step','trade_stops_level','filling_mode','trade_mode')}
    specs['selected']=_flag(getattr(info,'select',None))
    report['symbol']=dict(name=symbol,**specs)
    check('market_watch','Symbol enabled in Market Watch',getattr(info,'select',None) is True,
          'Symbol is enabled in MT5 Market Watch.' if getattr(info,'select',None) else 'Symbol is not enabled in MT5 Market Watch.',
          'In MT5 Market Watch, right-click → Symbols → select this exact symbol → Show. Then open its D1, H4 and M30 charts.',scope='data')
    valid_specs=all(specs[k] is not None and specs[k]>0 for k in ('point','trade_tick_size','volume_min','volume_max','volume_step'))
    valid_specs=valid_specs and specs['volume_min']<=specs['volume_max']
    check('contract_values','Price grid and broker lot limits',valid_specs,
          'Point, tick size and min/max/step lot specifications are valid.' if valid_specs else 'One or more required broker price/volume specifications are missing or invalid.',
          'Wait for MT5 to load the symbol contract specification. Do not substitute guessed lot settings.',scope='data')
    tick_values=all(specs[k] is not None and specs[k]>0 for k in ('trade_tick_value_profit','trade_tick_value_loss'))
    check('tick_values','Broker tick value',tick_values,
          'Broker profit/loss tick values are positive.' if tick_values else 'Broker profit/loss tick values are not available yet.',
          'Wait for live quotes and conversion symbols to load in MT5; order sizing will use broker order_calc_profit.')
    filling=int(specs['filling_mode'] or 0)
    fok=bool(filling & int(getattr(mt,'SYMBOL_FILLING_FOK',1)))
    report['symbol']['adapter_fok_supported']=fok
    check('filling','Adapter execution mode',fok,
          'Symbol supports FOK, the only filling mode currently validated by this adapter.' if fok else 'This symbol does not advertise FOK; the current adapter cannot submit it.',
          'Keep analysis mode. Broker-specific IOC/RETURN support needs separate adapter implementation and validation; changing a dashboard setting cannot add it.')
    full=getattr(info,'trade_mode',None)==getattr(mt,'SYMBOL_TRADE_MODE_FULL',4)
    check('symbol_trading','Symbol trading mode',full,
          'Symbol permits both buy and sell trades.' if full else 'Symbol does not permit unrestricted opening trades.',
          'Check broker session availability and symbol trading mode in MT5 Specification.')
    try:
        tick=mt.symbol_info_tick(symbol)
    except Exception:
        tick=None
    bid=_number(getattr(tick,'bid',None));ask=_number(getattr(tick,'ask',None));tick_time=_number(getattr(tick,'time',None))
    quote_valid=bid is not None and ask is not None and bid>0 and ask>=bid and tick_time is not None
    age=now-tick_time if tick_time is not None else None
    report['quote']=dict(bid=bid,ask=ask,time=tick_time,age_seconds=age,
                         spread_points=(ask-bid)/specs['point'] if quote_valid and specs['point'] and specs['point']>0 else None)
    try:
        limits=configured_limits()
    except ValueError:
        limits=None
    check('risk_configuration','Risk configuration',limits is not None,
          'Configured risk limits are valid.' if limits is not None else 'Risk configuration is invalid.',
          'Restore the documented risk environment defaults; risk caps must not be loosened.')
    max_age=limits.max_tick_age if limits else 30
    fresh=quote_valid and age is not None and 0<=age<=max_age
    check('quote','Fresh broker quote',fresh,
          f'Broker quote age is {age:.1f} seconds.' if quote_valid else 'No valid bid/ask quote is available.',
          'Wait for the forex market to reopen or check MT5 connectivity and the PC clock. Weekend/stale quotes block new trades.')
    spread=report['quote']['spread_points']
    if limits:
        check('spread','Spread filter',spread is not None and 0<=spread<=limits.max_spread_points,
              f'Spread is {spread:.1f} points; limit is {limits.max_spread_points:g}.' if spread is not None else 'Spread cannot be calculated.',
              'Wait for a spread inside the configured risk limit; do not increase risk to force a trade.')
    for tf,tolerance in (('D1',86400),('H4',14400),('M30',300)):
        try:
            rates=mt.copy_rates_from_pos(symbol,getattr(mt,'TIMEFRAME_'+tf),1,count)
            cs=[] if rates is None else [dict(time=int(r['time']),open=float(r['open']),high=float(r['high']),low=float(r['low']),close=float(r['close']),volume=float(r['tick_volume'])) for r in rates]
            if cs: validate(cs)
        except Exception:
            cs=[]
        history_ok=len(cs)>=30
        last_close=close_time(cs[-1],tf) if history_ok else None
        bar_age=now-last_close if last_close is not None else None
        report['history'][tf]=dict(bars=len(cs),required_bars=30,requested_bars=count,last_closed_at=last_close,age_seconds=bar_age)
        check('history_'+tf,f'{tf} completed-candle history',history_ok,
              f'{len(cs)} valid completed {tf} candles loaded; minimum is 30.' if history_ok else f'Fewer than 30 valid completed {tf} candles are available.',
              f'Open the exact symbol {tf} chart in MT5, scroll back to load history, wait, then rerun this check.',scope='data')
        check('freshness_'+tf,f'{tf} history freshness',history_ok and 0<=bar_age<=tolerance,
              f'Last completed {tf} candle closed {bar_age:.0f} seconds ago.' if history_ok else 'History freshness cannot be checked yet.',
              'Wait for market data and completed candles. Check the PC clock; market closure/weekends legitimately pause data.')
    report['ready_for_data']=data_ok
    report['ready_for_demo']=data_ok and demo_ok
    return report


def main():
    parser=argparse.ArgumentParser(description='Read-only MT5 connection check; no orders are sent.')
    parser.add_argument('--symbol',default='EURUSD',help='Exact broker symbol, including suffix such as EURUSDm')
    args=parser.parse_args()
    bridge=None
    try:
        from .bridge import MT5Bridge
        bridge=MT5Bridge()
        report=bridge.diagnostics(args.symbol)
    except Exception:
        print('MT5 check unavailable. Run on Windows using the project virtual environment with Exness MT5 open.')
        return 1
    finally:
        if bridge is not None: bridge.mt.shutdown()
    print(json.dumps(report,indent=2,allow_nan=False))
    return 0 if report['ready_for_data'] else 1


if __name__=='__main__':
    raise SystemExit(main())

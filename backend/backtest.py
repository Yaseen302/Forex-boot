"""Chronological single-position OHLC simulator using the same MTF signal.
Conservative stop-first when both barriers touch; no intrabar price certainty.
"""
import argparse
import csv
from bisect import bisect_right
import json
from pathlib import Path
from .market import aggregate, validate
from .risk import size
from .strategy import signal, analyze


def run(candles,initial=1000.,spread=.00012,slippage=.00005,commission=7.,swap_per_lot_day=0.,contract=100000.,risk_percent=.25,minimum=.01,step=.01):
    validate(candles)
    import math
    if not all(math.isfinite(v) for v in (initial,spread,slippage,commission,swap_per_lot_day,contract,risk_percent,minimum,step)) or initial<=0 or min(spread,slippage,commission,swap_per_lot_day)<0 or contract<=0:
        raise ValueError('Invalid backtest capital/cost assumptions')
    if any(b['time']-a['time']<1800 or a['time']%1800 for a,b in zip(candles,candles[1:])):
        raise ValueError('Input must be UTC M30 candle opens on 30-minute boundaries')
    if len(candles)<1600: raise ValueError('At least 1600 M30 candles required for D1 warm-up')
    equity=initial; peak=initial; max_dd=0.; position=None; trades=[]; skipped=0
    day=None; day_start=initial; entries=0
    daily=aggregate(candles,86400); h4=aggregate(candles,14400)
    daily=[x for x in daily if x['time']>=candles[0]['time']]
    h4=[x for x in h4 if x['time']>=candles[0]['time']]
    dcloses=[x['time']+86400 for x in daily]; hcloses=[x['time']+14400 for x in h4]
    cached={}; cache_keys={}
    for i,c in enumerate(candles):
        had_position_at_open=position is not None
        current_day=c['time']//86400
        if current_day!=day: day=current_day; day_start=equity
        if position:
            p=position; buy=p['side']=='BUY'
            # Long exits bid; short exits ask. CSV OHLC is assumed bid.
            lo=c['low']+(spread if not buy else 0); hi=c['high']+(spread if not buy else 0)
            opening=c['open']+(spread if not buy else 0)
            stop_hit=lo<=p['stop'] if buy else hi>=p['stop']
            tp_hit=hi>=p['target'] if buy else lo<=p['target']
            if stop_hit or tp_hit or i==len(candles)-1:
                if stop_hit: exit_price=(min(opening,p['stop'])-slippage if buy else max(opening,p['stop'])+slippage); reason='stop'
                elif tp_hit: exit_price=p['target']; reason='target'
                else: exit_price=c['close']+(-slippage if buy else spread+slippage); reason='end_of_data'
                nights=max(0,c['time']//86400-p['time']//86400)
                pnl=(exit_price-p['entry'])*(1 if buy else -1)*contract*p['volume']-commission*p['volume']-nights*swap_per_lot_day*p['volume']
                equity+=pnl
                trades.append({**p,'exit_time':c['time'],'exit':exit_price,'pnl':pnl,'reason':reason})
                position=None
        peak=max(peak,equity)
        max_dd=max(max_dd,(peak-equity)/peak*100)
        # A carried position's intrabar exit is known only after the open.
        # Its later proceeds cannot fund a replacement entry at that earlier open.
        if had_position_at_open or position or i<1500 or i==len(candles)-1: continue
        if equity<=0 or (day_start-equity)/day_start*100>=2 or (peak-equity)/peak*100>=5: continue
        # Signal available before current candle opens. Only fully closed higher frames.
        di=bisect_right(dcloses,c['time']); hi=bisect_right(hcloses,c['time'])
        frames={'M30':candles[max(0,i-300):i], 'H4':h4[max(0,hi-300):hi], 'D1':daily[max(0,di-300):di]}
        if any(len(cs)<30 for cs in frames.values()): continue
        # Match the live adapter's entry freshness rather than replay a Friday
        # setup at Monday's opening quote after a history/market closure gap.
        if any(not 0<=c['time']-(frames[tf][-1]['time']+seconds)<=age
               for tf,seconds,age in [('M30',1800,300),('H4',14400,14400),('D1',86400,86400)]):
            continue
        for tf,k in [('D1',di),('H4',hi)]:
            if cache_keys.get(tf)!=k:
                cached[tf]=analyze(frames[tf]);cache_keys[tf]=k
        s=signal(frames,precomputed=cached)
        if s['side']=='WAIT': continue
        entry=c['open']+(spread+slippage if s['side']=='BUY' else -slippage)
        risk=entry-s['stop'] if s['side']=='BUY' else s['stop']-entry
        reward=s['target']-entry if s['side']=='BUY' else entry-s['target']
        if risk<=0 or reward/risk<2: skipped+=1; continue
        sizing=size(equity,risk*contract+commission+slippage*contract,minimum,100.,step,risk_percent)
        if not sizing['ok']: skipped+=1; continue
        position=dict(side=s['side'],entry=entry,stop=s['stop'],target=s['target'],volume=sizing['volume'],time=c['time'])
        entries+=1
        # Evaluate the entry candle on next iteration's barrier logic explicitly below.
        buy=position['side']=='BUY'
        low=c['low']+(0 if buy else spread); high=c['high']+(0 if buy else spread)
        hit_stop=low<=s['stop'] if buy else high>=s['stop']
        hit_tp=high>=s['target'] if buy else low<=s['target']
        if hit_stop or hit_tp:
            price=s['stop']+(-slippage if buy else slippage) if hit_stop else s['target']
            pnl=(price-entry)*(1 if buy else -1)*contract*position['volume']-commission*position['volume']
            equity+=pnl
            trades.append({**position,'exit_time':c['time'],'exit':price,'pnl':pnl,'reason':'stop' if hit_stop else 'target'})
            position=None
            peak=max(peak,equity); max_dd=max(max_dd,(peak-equity)/peak*100)
    gains=sum(t['pnl'] for t in trades if t['pnl']>0); losses=-sum(t['pnl'] for t in trades if t['pnl']<0)
    return dict(initial=initial,final=equity,net=equity-initial,trades=len(trades),entries=entries,skipped=skipped,
                win_rate=sum(t['pnl']>0 for t in trades)/len(trades)*100 if trades else None,
                profit_factor=gains/losses if losses else None,expectancy=(equity-initial)/len(trades) if trades else None,
                max_closed_equity_drawdown_percent=max_dd,assumptions=dict(spread=spread,slippage=slippage,commission_per_lot_round_trip=commission,swap_per_lot_day=swap_per_lot_day,contract=contract),
                warning='Research simulator; no profitability evidence when using synthetic prices. Drawdown excludes intratrade floating equity. USD-quoted instruments in USD accounts only.',ledger=trades)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('csv'); p.add_argument('--output',default='runtime/backtest.json'); p.add_argument('--initial',type=float,default=1000)
    p.add_argument('--spread',type=float,default=.00012); p.add_argument('--slippage',type=float,default=.00005)
    p.add_argument('--commission',type=float,default=7); p.add_argument('--swap',type=float,required=True,help='Conservative cost per lot per UTC overnight; obtain broker specification')
    a=p.parse_args()
    with open(a.csv,newline='') as f: candles=[{k:(int(v) if k=='time' else float(v)) for k,v in row.items()} for row in csv.DictReader(f)]
    report=run(candles,initial=a.initial,spread=a.spread,slippage=a.slippage,commission=a.commission,swap_per_lot_day=a.swap)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({k:v for k,v in report.items() if k!='ledger'},indent=2))
if __name__=='__main__': main()

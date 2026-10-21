"""Causal single-position bid-OHLC research simulator; never submits orders.

D1/H4 are UTC buckets, not the broker's session candles. Intrabar excursions,
margin/stop-outs, variable spreads and exact rollover rules are not simulated.
"""
import argparse
import csv
from bisect import bisect_right
import json
import math
from pathlib import Path
from .market import aggregate, validate
from .risk import size
from .strategy import signal, analyze


def run(candles, initial=1000., spread=.00012, slippage=.00005, commission=7.,
        swap_per_lot_day=0., contract=100000., risk_percent=.25, minimum=.01,
        step=.01, maximum=100., max_daily_loss=2., max_drawdown=5.,
        max_entries_per_day=5, entry_start=1500):
    validate(candles)
    values=(initial,spread,slippage,commission,swap_per_lot_day,contract,risk_percent,
            minimum,step,maximum,max_daily_loss,max_drawdown,max_entries_per_day)
    if (not all(math.isfinite(v) for v in values) or initial<=0
            or min(spread,slippage,commission,swap_per_lot_day)<0 or contract<=0
            or not 0<risk_percent<=.5 or not 0<minimum<=maximum or step<=0
            or not 0<max_daily_loss<=2 or not 0<max_drawdown<=5
            or max_entries_per_day!=int(max_entries_per_day) or max_entries_per_day<1):
        raise ValueError('Invalid backtest capital/cost/risk assumptions')
    if any(c['time']%1800 or int(c['time'])!=c['time'] for c in candles):
        raise ValueError('Input must be UTC M30 candle opens on 30-minute boundaries')
    if any(b['time']-a['time']<1800 for a,b in zip(candles,candles[1:])):
        raise ValueError('Input must be ordered M30 candles without duplicate timestamps')
    if len(candles)<1600: raise ValueError('At least 1600 M30 candles required for D1 warm-up')
    if not isinstance(entry_start,int) or entry_start<1500 or entry_start>=len(candles):
        raise ValueError('entry_start must retain at least 1500 warm-up bars')
    equity=initial; closed_peak=initial; max_closed_dd=0.
    marked_peak=initial; max_marked_dd=0.; position=None; trades=[]; skipped=0
    day=None; day_start=initial; day_entries=0; entries=0; daily_halted=False
    drawdown_halted=False; halted_days=set(); curve=[]; daily_counts={}
    daily=aggregate(candles,86400); h4=aggregate(candles,14400)
    daily=[x for x in daily if x['time']>=candles[0]['time']]
    h4=[x for x in h4 if x['time']>=candles[0]['time']]
    dcloses=[x['time']+86400 for x in daily]; hcloses=[x['time']+14400 for x in h4]
    cached={}; cache_keys={}

    def mark(p, bid, timestamp):
        if p is None: return equity
        buy=p['side']=='BUY'
        exit_quote=bid if buy else bid+spread
        nights=max(0,timestamp//86400-p['time']//86400)
        return (equity+(exit_quote-p['entry'])*(1 if buy else -1)*contract*p['volume']
                -commission*p['volume']-nights*swap_per_lot_day*p['volume'])

    def exit_position(c, final=False):
        nonlocal equity,position
        if position is None: return
        p=position; buy=p['side']=='BUY'
        # Long exits bid; short exits ask. Both barriers hit => conservative stop first.
        lo=c['low']+(0 if buy else spread); hi=c['high']+(0 if buy else spread)
        opening=c['open']+(0 if buy else spread)
        stop_hit=lo<=p['stop'] if buy else hi>=p['stop']
        tp_hit=hi>=p['target'] if buy else lo<=p['target']
        if not (stop_hit or tp_hit or final): return
        if stop_hit:
            price=min(opening,p['stop'])-slippage if buy else max(opening,p['stop'])+slippage
            reason='stop'
        elif tp_hit: price=p['target']; reason='target'
        else: price=c['close']+(-slippage if buy else spread+slippage); reason='end_of_data'
        nights=max(0,c['time']//86400-p['time']//86400)
        pnl=((price-p['entry'])*(1 if buy else -1)*contract*p['volume']
             -commission*p['volume']-nights*swap_per_lot_day*p['volume'])
        equity+=pnl
        trades.append({**p,'exit_time':c['time'],'exit':price,'pnl':pnl,'reason':reason})
        position=None

    for i,c in enumerate(candles):
        had_position_at_open=position is not None
        current_day=c['time']//86400
        opening_equity=mark(position,c['open'],c['time'])
        if current_day!=day:
            day=current_day;day_start=opening_equity;day_entries=0;daily_halted=False
        if day_start>0 and (day_start-opening_equity)/day_start*100>=max_daily_loss:
            daily_halted=True;halted_days.add(day)
        if (marked_peak-opening_equity)/marked_peak*100>=max_drawdown: drawdown_halted=True
        exit_position(c,final=i==len(candles)-1)
        # Intrabar proceeds cannot fund a replacement order at that earlier open.
        can_enter=(not had_position_at_open and position is None and entry_start<=i<len(candles)-1
                   and equity>0 and not daily_halted and not drawdown_halted
                   and day_entries<max_entries_per_day)
        if can_enter:
            di=bisect_right(dcloses,c['time']);hi=bisect_right(hcloses,c['time'])
            frames={'M30':candles[max(0,i-300):i], 'H4':h4[max(0,hi-300):hi], 'D1':daily[max(0,di-300):di]}
            fresh=(all(len(cs)>=30 for cs in frames.values()) and all(
                0<=c['time']-(frames[tf][-1]['time']+seconds)<=age
                for tf,seconds,age in [('M30',1800,300),('H4',14400,14400),('D1',86400,86400)]))
            if fresh:
                for tf,k in [('D1',di),('H4',hi)]:
                    if cache_keys.get(tf)!=k: cached[tf]=analyze(frames[tf]);cache_keys[tf]=k
                s=signal(frames,precomputed=cached)
                if s['side']!='WAIT':
                    buy=s['side']=='BUY'
                    entry=c['open']+(spread+slippage if buy else -slippage)
                    risk=entry-s['stop'] if buy else s['stop']-entry
                    reward=s['target']-entry if buy else entry-s['target']
                    # A pre-existing stop invalidated by the opening bid/ask gap is
                    # not a fresh executable structure. Entry slippage must not mask it.
                    stop_quote=c['open'] if buy else c['open']+spread
                    crossed_stop=stop_quote<=s['stop'] if buy else stop_quote>=s['stop']
                    invalid=(not all(math.isfinite(v) and v>0 for v in (entry,s['stop'],s['target']))
                             or crossed_stop or risk<=0 or reward/risk<2)
                    if invalid: skipped+=1
                    else:
                        sizing=size(equity,risk*contract+commission+slippage*contract,
                                    minimum,maximum,step,risk_percent)
                        if not sizing['ok']: skipped+=1
                        else:
                            position=dict(side=s['side'],entry=entry,stop=s['stop'],target=s['target'],
                                          volume=sizing['volume'],time=c['time'])
                            entries+=1;day_entries+=1;daily_counts[str(day)]=day_entries
                            exit_position(c)
        closed_peak=max(closed_peak,equity)
        max_closed_dd=max(max_closed_dd,(closed_peak-equity)/closed_peak*100)
        marked=mark(position,c['close'],c['time'])
        marked_peak=max(marked_peak,marked)
        dd=(marked_peak-marked)/marked_peak*100
        max_marked_dd=max(max_marked_dd,dd)
        if day_start>0 and (day_start-marked)/day_start*100>=max_daily_loss:
            daily_halted=True;halted_days.add(day)
        if dd>=max_drawdown: drawdown_halted=True
        if i>=entry_start:
            curve.append(dict(time=c['time']+1800,balance=equity,equity=marked,drawdown_percent=dd))
    gains=sum(t['pnl'] for t in trades if t['pnl']>0);losses=-sum(t['pnl'] for t in trades if t['pnl']<0)
    return dict(initial=initial,final=equity,net=equity-initial,trades=len(trades),entries=entries,skipped=skipped,
                win_rate=sum(t['pnl']>0 for t in trades)/len(trades)*100 if trades else None,
                profit_factor=gains/losses if losses else None,expectancy=(equity-initial)/len(trades) if trades else None,
                max_closed_equity_drawdown_percent=max_closed_dd,max_mark_to_market_drawdown_percent=max_marked_dd,
                daily_loss_halted_days=len(halted_days),drawdown_halted=drawdown_halted,
                maximum_daily_entries=max(daily_counts.values(),default=0),
                assumptions=dict(spread=spread,slippage=slippage,commission_per_lot_round_trip=commission,
                                 swap_per_lot_day=swap_per_lot_day,contract=contract,risk_percent=risk_percent,
                                 minimum=minimum,maximum=maximum,step=step,max_daily_loss=max_daily_loss,
                                 max_drawdown=max_drawdown,max_entries_per_day=max_entries_per_day,
                                 timeframe_alignment='UTC H4/D1 buckets; not broker session candles'),
                warning='Research only. Bar-close floating equity is marked; intrabar excursions and margin/stop-outs are not simulated. USD profit currency in USD accounts only. Synthetic fixtures never establish profitability.',
                equity_curve=curve,ledger=trades)


def add_simulator_arguments(parser):
    parser.add_argument('--initial',type=float,default=1000.)
    for name,description in [('spread','Bid/ask price difference'),('slippage','Adverse price slippage per fill'),
                             ('commission','USD per lot round trip'),('swap','Conservative USD cost per lot per UTC overnight')]:
        parser.add_argument('--'+name,type=float,required=True,help=description+'; explicitly choose broker assumptions')
    parser.add_argument('--risk-percent',type=float,default=.25)
    parser.add_argument('--max-daily-loss',type=float,default=2.)
    parser.add_argument('--max-drawdown',type=float,default=5.)
    parser.add_argument('--max-entries-per-day',type=int,default=5)


def simulator_arguments(args):
    return dict(initial=args.initial,spread=args.spread,slippage=args.slippage,commission=args.commission,
                swap_per_lot_day=args.swap,risk_percent=args.risk_percent,max_daily_loss=args.max_daily_loss,
                max_drawdown=args.max_drawdown,max_entries_per_day=args.max_entries_per_day)


def main():
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--output',default='runtime/backtest.json')
    add_simulator_arguments(p);a=p.parse_args()
    from .research import load_dataset
    candles,info=load_dataset(a.csv)
    spec=info['metadata']['instrument']
    report=run(candles,**simulator_arguments(a),contract=spec['contract_size'],minimum=spec['volume_min'],
               maximum=spec['volume_max'],step=spec['volume_step'])
    report['dataset']={k:v for k,v in info.items() if k!='path'}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('ledger','equity_curve')},indent=2))

if __name__=='__main__': main()

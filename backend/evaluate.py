"""Fixed-rule chronological evaluation. No parameter tuning, no ML claims."""
import argparse
import csv
import json
from pathlib import Path
from .backtest import run


def evaluate(candles, **costs):
    if len(candles)<8000: raise ValueError('Need at least 8000 M30 bars for chronological and rolling evaluation')
    n=len(candles)
    boundaries=[0,int(n*.6),int(n*.8),n]
    sections=[]
    for name,start,end in zip(('development','validation','out_of_sample'),boundaries,boundaries[1:]):
        # Prior prices provide warmup, but entry evaluation starts exactly at start.
        warmup=max(0,start-1500)
        segment=candles[warmup:end]
        result=run(segment,**costs)
        sections.append(dict(name=name,start_time=candles[start]['time'],end_time=candles[end-1]['time'],report=result))
    # Independent rolling OOS windows; fixed rules, no refit or selection on test returns.
    rolling=[]
    start=int(n*.6)
    width=max(1600,(n-start)//3)
    a=start
    while a<n:
        b=min(n,a+width)
        if n-b<100: b=n
        rolling.append(dict(start_time=candles[a]['time'],end_time=candles[b-1]['time'],report=run(candles[a-1500:b],**costs)))
        a=b
    return dict(method='Fixed strategy; chronological 60/20/20 plus rolling OOS windows. No AI trained. Warm-up excluded from entries.',
                sections=sections,rolling_out_of_sample=rolling,
                limitations='No parameter search; costs must match broker. Constant-spread bid OHLC, no intrabar floating drawdown, exact broker calendar/news not simulated. Results are research only.')


def main():
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--output',default='runtime/evaluation.json');p.add_argument('--swap',required=True,type=float)
    a=p.parse_args()
    with open(a.csv,newline='') as f: candles=[{k:(int(v) if k=='time' else float(v)) for k,v in r.items()} for r in csv.DictReader(f)]
    result=evaluate(candles,swap_per_lot_day=a.swap)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False))
    print('Saved chronological research evaluation to '+a.output)
if __name__=='__main__':main()

"""Fixed-rule chronological research, with untouched periods and cash baseline."""
import argparse
import json
import math
import random
from pathlib import Path
from .backtest import run,add_simulator_arguments,simulator_arguments
from .market import validate


def uncertainty(ledger, minimum_trades=30, draws=1000):
    """Trade bootstrap describes sampling variation, not a profit guarantee.

    Trades are resampled as independent observations. Serial dependence and
    strategy/cost selection bias are NOT included; insufficient samples abstain.
    """
    pnls=[float(t['pnl']) for t in ledger]
    if any(not math.isfinite(p) for p in pnls): raise ValueError('Non-finite trade P&L')
    common=dict(trades=len(pnls),minimum_trades=minimum_trades,
                method='Deterministic trade bootstrap; IID assumption, 95% percentile intervals',
                limitations='Does not model serial dependence, regime shifts or selection bias; not a probability of future profit.')
    if len(pnls)<minimum_trades:
        return dict(**common,status='insufficient_trades',expectancy_95_interval=None,win_rate_95_interval=None)
    rng=random.Random(7613);means=[];wins=[]
    for _ in range(draws):
        sample=rng.choices(pnls,k=len(pnls))
        means.append(sum(sample)/len(sample));wins.append(sum(x>0 for x in sample)/len(sample)*100)
    means.sort();wins.sort();lo=int(draws*.025);hi=min(draws-1,int(draws*.975))
    return dict(**common,status='descriptive_only',resamples=draws,
                expectancy_95_interval=[means[lo],means[hi]],win_rate_95_interval=[wins[lo],wins[hi]])


def evaluate(candles, **costs):
    validate(candles)
    if len(candles)<8000: raise ValueError('Need at least 8000 M30 bars for chronological and rolling evaluation')
    n=len(candles);boundaries=[0,int(n*.6),int(n*.8),n]
    sections=[]
    def window(name,start,end):
        warmup=max(0,start-1500)
        result=run(candles[warmup:end],entry_start=max(1500,start-warmup),**costs)
        result['uncertainty']=uncertainty(result['ledger'])
        initial=result['initial']
        result['cash_baseline']=dict(initial=initial,final=initial,net=0.,trades=0,
                                     explanation='Hold USD cash; no return/interest or execution costs assumed')
        return dict(name=name,start_time=candles[max(start,warmup+1500)]['time'],
                    end_time=candles[end-1]['time']+1800,warmup_bars=max(1500,start-warmup),
                    report=result)
    for name,start,end in zip(('development','validation','out_of_sample'),boundaries,boundaries[1:]):
        sections.append(window(name,start,end))
    rolling=[];rolling_start=int(n*.6)
    # Three independent fixed-rule windows. Warmup exists before each boundary;
    # there are no trades or equity carried from the earlier window.
    cuts=[rolling_start+(n-rolling_start)*i//3 for i in range(4)]
    for i,(a,b) in enumerate(zip(cuts,cuts[1:])):
        rolling.append(window('rolling_'+str(i+1),a,b))
    return dict(method='Fixed strategy; chronological 60/20/20 plus three independent rolling evaluation windows. No fitting, tuning or AI training.',
                sections=sections,rolling_out_of_sample=rolling,
                limitations=['D1/H4 rebuilt as UTC buckets; broker session candles can differ and cause different signals.',
                             'Constant-spread bid OHLC and fixed adverse costs; no tick sequence, variable costs, exact swaps or broker news calendar.',
                             'Drawdown uses bar-close floating equity; intrabar excursions and margin/stop-outs are omitted.',
                             'Rolling windows overlap chronological validation/OOS periods; do not combine them as independent evidence.',
                             'Rules or costs chosen after viewing a period invalidate its untouched OOS status. Reserve new data after changes.',
                             'Results do not establish future profits; zero/low trades cannot validate a strategy.'])


def main():
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--output',default='runtime/evaluation.json')
    add_simulator_arguments(p);a=p.parse_args()
    from .research import load_dataset
    candles,info=load_dataset(a.csv)
    spec=info['metadata']['instrument']
    result=evaluate(candles,**simulator_arguments(a),contract=spec['contract_size'],
                    minimum=spec['volume_min'],maximum=spec['volume_max'],step=spec['volume_step'])
    result['dataset']={k:v for k,v in info.items() if k!='path'}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print('Saved chronological research evaluation to '+a.output)

if __name__=='__main__':main()

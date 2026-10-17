"""Deterministic research rules; no orders and no future candles."""
from .market import validate


def analyze(candles, window=2):
    validate(candles)
    if len(candles)<30:
        raise ValueError('At least 30 closed candles are required')
    highs=[]; lows=[]
    for i in range(window,len(candles)-window):
        c=candles[i]
        neighbors=candles[i-window:i]+candles[i+1:i+window+1]
        if all(c['high']>n['high'] for n in neighbors): highs.append((i,c['high']))
        if all(c['low']<n['low'] for n in neighbors): lows.append((i,c['low']))
    trend='mixed'
    if len(highs)>=2 and len(lows)>=2:
        if highs[-1][1]>highs[-2][1] and lows[-1][1]>lows[-2][1]: trend='bullish'
        elif highs[-1][1]<highs[-2][1] and lows[-1][1]<lows[-2][1]: trend='bearish'
    last=candles[-1]; prev=candles[-2]
    resistance=highs[-1][1] if highs else None
    support=lows[-1][1] if lows else None
    direction=None
    if resistance and prev['close']<=resistance<last['close']: direction='bullish'
    elif support and prev['close']>=support>last['close']: direction='bearish'
    event='none'
    if direction:
        event=('CHoCH' if trend not in (direction,'mixed') else 'BOS')+' '+direction
    zones=[]
    # Suffix extrema allow mitigation checks without scanning every later candle.
    suffix_low=[float('inf')]*(len(candles)+1)
    suffix_high=[float('-inf')]*(len(candles)+1)
    for i in range(len(candles)-1,-1,-1):
        suffix_low[i]=min(suffix_low[i+1],candles[i]['low'])
        suffix_high[i]=max(suffix_high[i+1],candles[i]['high'])
    for i in range(2,len(candles)):
        a,c=candles[i-2],candles[i]
        kind=None
        if c['low']>a['high']: kind='bullish'; lo,hi=a['high'],c['low']
        elif c['high']<a['low']: kind='bearish'; lo,hi=c['high'],a['low']
        if kind:
            # Retain only gaps not fully filled by subsequent closed candles.
            filled=suffix_low[i+1]<=lo if kind=='bullish' else suffix_high[i+1]>=hi
            if not filled: zones.append(dict(kind='FVG',direction=kind,lower=lo,upper=hi,time=c['time']))
    if direction:
        for c in reversed(candles[-12:-1]):
            if (c['close']<c['open']) if direction=='bullish' else (c['close']>c['open']):
                zones.append(dict(kind='order_block',direction=direction,lower=c['low'],upper=c['high'],time=c['time']))
                break
    sweep=[]
    if support and last['low']<support<last['close']: sweep.append('sell-side sweep')
    if resistance and last['high']>resistance>last['close']: sweep.append('buy-side sweep')
    ranges=[max(c['high']-c['low'],abs(c['high']-candles[i-1]['close']),abs(c['low']-candles[i-1]['close'])) for i,c in enumerate(candles) if i>0]
    atr=sum(ranges[-14:])/14
    return dict(trend=trend,event=event,support=support,resistance=resistance,zones=zones[-12:],
                sweeps=sweep,atr=atr,close=last['close'],time=last['time'],
                swings={'highs':[{'time':candles[i]['time'],'price':p} for i,p in highs[-8:]],
                        'lows':[{'time':candles[i]['time'],'price':p} for i,p in lows[-8:]]})


def signal(frames, rr=2.5, precomputed=None):
    results={tf:(precomputed[tf] if precomputed and tf in precomputed else analyze(frames[tf])) for tf in ('D1','H4','M30')}
    trends=[r['trend'] for r in results.values()]
    reasons=[f"{tf}: {r['trend']}; {r['event']}" for tf,r in results.items()]
    if len(set(trends))!=1 or trends[0]=='mixed':
        return dict(side='WAIT',reasons=reasons+['D1, H4 and M30 must agree'],analysis=results)
    r=results['M30']; bullish=trends[0]=='bullish'
    if r['event']!='BOS '+trends[0]:
        return dict(side='WAIT',reasons=reasons+['Waiting for closed M30 BOS'],analysis=results)
    entry=r['close']; stop=r['support'] if bullish else r['resistance']
    if stop is None or (entry-stop if bullish else stop-entry)<=0:
        return dict(side='WAIT',reasons=reasons+['No valid structural stop'],analysis=results)
    distance=abs(entry-stop)
    if distance<.5*r['atr'] or distance>5*r['atr']:
        return dict(side='WAIT',reasons=reasons+['Structural stop outside 0.5–5 ATR band'],analysis=results)
    return dict(side='BUY' if bullish else 'SELL',entry=entry,stop=stop,
                target=entry+(distance*rr if bullish else -distance*rr),
                time=r['time'],reasons=reasons+['Aligned structure and fresh M30 BOS'],analysis=results)

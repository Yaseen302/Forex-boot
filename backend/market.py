"""Closed-candle data. Synthetic data is a development fixture, never broker data."""
import math
import random
import time
from datetime import datetime, timezone
from typing import TypedDict

TIMEFRAMES = {**{f'M{n}': n*60 for n in (1,2,3,4,5,6,10,12,15,20,30)},
              **{f'H{n}': n*3600 for n in (1,2,3,4,6,8,12)},
              'D1':86400, 'W1':604800, 'MN1':None}

class Candle(TypedDict):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def validate(candles):
    if not candles:
        raise ValueError('No candles returned')
    previous = -1
    for c in candles:
        if any(not math.isfinite(float(c[k])) for k in ('time','open','high','low','close','volume')):
            raise ValueError('Candle values must be finite')
        if c['time'] <= previous or c['volume'] < 0 or c['low'] <= 0:
            raise ValueError('Candles must have increasing UTC times and positive prices')
        if c['high'] < max(c['open'],c['close']) or c['low'] > min(c['open'],c['close']):
            raise ValueError('Invalid OHLC range')
        previous = c['time']
    return candles


def synthetic(tf='M30', count=300, symbol='EURUSD', now=None):
    """Deterministic fixture with realistic candle boundaries; not for profitability claims."""
    now = int(now or time.time())
    step = TIMEFRAMES[tf] or 30*86400
    end = now//step*step
    rng = random.Random(43 + step)
    price = 2300.0 if 'XAU' in symbol else 1.08
    scale = price * .0007 * math.sqrt(step/1800)
    result = []
    for i in range(count):
        opening=price
        price=max(scale, price + rng.gauss(0,scale) + math.sin(i/18)*scale*.18)
        wick=abs(rng.gauss(scale*.7,scale*.3))
        result.append(dict(time=end-(count-i)*step,open=opening,high=max(opening,price)+wick,
                           low=max(.000001,min(opening,price)-wick),close=price,volume=float(rng.randint(100,1800))))
    return validate(result)


def close_time(candle, tf):
    if tf != 'MN1':
        return candle['time']+TIMEFRAMES[tf]
    dt=datetime.fromtimestamp(candle['time'],timezone.utc)
    return int(datetime(dt.year+(dt.month==12),dt.month%12+1,1,tzinfo=timezone.utc).timestamp())


def aggregate(candles, seconds):
    groups={}
    for c in candles:
        bucket=c['time']//seconds*seconds
        if bucket not in groups:
            groups[bucket]={**c,'time':bucket}
        else:
            g=groups[bucket]
            g.update(high=max(g['high'],c['high']),low=min(g['low'],c['low']),close=c['close'],volume=g['volume']+c['volume'])
    return list(groups.values())

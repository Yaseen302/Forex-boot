from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from math import isfinite

@dataclass(frozen=True)
class Limits:
    risk_percent: float=.25
    max_daily_loss: float=2
    max_drawdown: float=5
    max_positions: int=1
    min_rr: float=2
    max_spread_points: float=25
    max_tick_age: float=30
    commission_per_lot: float=7
    slippage_points: float=10


def size(equity, loss_per_lot, minimum, maximum, step, risk_percent=.25):
    values=(equity,loss_per_lot,minimum,maximum,step,risk_percent)
    if not all(isfinite(v) and v>0 for v in values) or minimum>maximum or risk_percent>.5:
        raise ValueError('Invalid sizing inputs; risk cap is 0.5%')
    d=lambda x:Decimal(str(x))
    budget=d(equity)*d(risk_percent)/100
    units=(min(budget/d(loss_per_lot),d(maximum))/d(step)).to_integral_value(rounding=ROUND_FLOOR)
    volume=units*d(step)
    if volume<d(minimum):
        return dict(ok=False,volume=0,risk_budget=float(budget),reason='Minimum broker lot exceeds risk budget')
    return dict(ok=True,volume=float(volume),risk_budget=float(budget),estimated_loss=float(volume*d(loss_per_lot)))


def guards(*,equity,day_equity,peak_equity,positions,spread_points,tick_age,margin_free,margin_needed,
           entry,stop,target,side,news_clear,emergency,limits=Limits()):
    reasons=[]
    nums=(equity,day_equity,peak_equity,positions,spread_points,tick_age,margin_free,margin_needed,entry,stop,target)
    if not all(isfinite(x) for x in nums): return ['Non-finite risk input']
    if min(equity,day_equity,peak_equity,entry,stop,target)<=0: return ['Invalid equity or price']
    if (day_equity-equity)/day_equity*100>=limits.max_daily_loss: reasons.append('Daily loss limit')
    if (peak_equity-equity)/peak_equity*100>=limits.max_drawdown: reasons.append('Maximum drawdown')
    if positions>=limits.max_positions or positions<0: reasons.append('Position limit')
    if spread_points<0 or spread_points>limits.max_spread_points: reasons.append('Spread filter')
    if tick_age<0 or tick_age>limits.max_tick_age: reasons.append('Stale quote or clock mismatch')
    if margin_needed<0 or margin_free<margin_needed*1.2: reasons.append('Insufficient margin buffer')
    if emergency: reasons.append('Emergency stop active')
    if not news_clear: reasons.append('News clearance missing or expired')
    risk=entry-stop if side=='BUY' else stop-entry
    reward=target-entry if side=='BUY' else entry-target
    if side not in ('BUY','SELL') or risk<=0 or reward/risk<limits.min_rr: reasons.append('Invalid SL/TP or reward/risk below minimum')
    return reasons


def configured_limits():
    import os
    from dataclasses import fields
    defaults=Limits()
    values={f.name:float(os.environ.get('RISK_'+f.name.upper(),getattr(defaults,f.name))) for f in fields(Limits)}
    if not all(isfinite(v) for v in values.values()): raise ValueError('Risk configuration must be finite')
    if not 0<values['risk_percent']<=.5: raise ValueError('Risk per trade must be at most 0.5%')
    if not 0<values['max_daily_loss']<=2 or not 0<values['max_drawdown']<=5:
        raise ValueError('Daily loss/drawdown caps may only be tightened from 2%/5%')
    if values['max_positions']!=1 or values['min_rr']<2: raise ValueError('Only one position and minimum 2R are supported')
    if min(values['max_spread_points'],values['max_tick_age'])<=0 or values['max_tick_age']>30:
        raise ValueError('Invalid spread/quote-age limit')
    if min(values['commission_per_lot'],values['slippage_points'])<0: raise ValueError('Trading costs cannot be negative')
    return Limits(**values)

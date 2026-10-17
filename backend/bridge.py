"""Official MT5 integration. All calls must be serialized by the API lock."""
import platform
import time
from .market import TIMEFRAMES, validate

class MT5Bridge:
    def __init__(self):
        if platform.system()!='Windows': raise RuntimeError('MT5 requires Windows with the desktop terminal running')
        import MetaTrader5
        self.mt=MetaTrader5
    def connect(self):
        if not self.mt.initialize(): raise RuntimeError('MT5 initialize failed; open terminal and check login')
        terminal=self.mt.terminal_info()
        if terminal is None or not terminal.connected: raise RuntimeError('MT5 terminal disconnected')
        return terminal
    def account(self):
        self.connect()
        a=self.mt.account_info()
        if a is None: raise RuntimeError('MT5 account unavailable')
        return a
    def symbols(self):
        self.connect()
        values=self.mt.symbols_get()
        if values is None: raise RuntimeError('Broker symbols unavailable')
        return [s.name for s in values]
    def candles(self,symbol,tf,count=300):
        self.connect()
        if not self.mt.symbol_select(symbol,True): raise ValueError('Broker symbol unavailable; select exact name')
        rates=self.mt.copy_rates_from_pos(symbol,getattr(self.mt,'TIMEFRAME_'+tf),1,count)
        if rates is None or len(rates)<30: raise RuntimeError('Insufficient MT5 history; load charts in terminal')
        return validate([dict(time=int(r['time']),open=float(r['open']),high=float(r['high']),low=float(r['low']),close=float(r['close']),volume=float(r['tick_volume'])) for r in rates])
    def status(self):
        a=self.account()
        positions=self.mt.positions_get()
        orders=self.mt.orders_get()
        if positions is None or orders is None: raise RuntimeError('Cannot read broker positions/orders')
        return dict(connected=True,account=str(a.login),server=a.server,currency=a.currency,equity=a.equity,
                    balance=a.balance,margin_free=a.margin_free,demo=a.trade_mode==self.mt.ACCOUNT_TRADE_MODE_DEMO,
                    positions=[dict(ticket=p.ticket,symbol=p.symbol,volume=p.volume,profit=p.profit) for p in positions],
                    pending_orders=len(orders))

"""Official MT5 integration. All calls must be serialized by the API lock."""
import platform
import os
from .market import validate

class MT5Bridge:
    def __init__(self, terminal_path=None):
        if platform.system()!='Windows': raise RuntimeError('MT5 requires Windows with the desktop terminal running')
        import MetaTrader5
        self.mt=MetaTrader5
        self.terminal_path=terminal_path or os.environ.get('MT5_TERMINAL_PATH') or None
        self._initialized=False
    def connect(self):
        # Keep the selected terminal for this bridge lifetime. Re-initializing each
        # data call can silently attach to a different installation on Windows.
        if not self._initialized:
            args=(self.terminal_path,) if self.terminal_path else ()
            if not self.mt.initialize(*args):
                raise RuntimeError('MT5 initialize failed; open the correct desktop terminal and check MT5_TERMINAL_PATH')
            self._initialized=True
        terminal=self.mt.terminal_info()
        if terminal is None:
            self._initialized=False
            raise RuntimeError('MT5 terminal unavailable; open it and retry the connection check')
        if not terminal.connected: raise RuntimeError('MT5 terminal disconnected; check its broker login and connection')
        return terminal
    def diagnostics(self,symbol='EURUSD',count=300,now=None):
        """Read-only preflight; never selects symbols or submits/checks orders."""
        from .diagnostics import connection_report
        return connection_report(self,symbol,count=count,now=now)
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

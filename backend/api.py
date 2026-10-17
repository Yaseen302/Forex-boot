import hmac
import math
import os
import threading
import time
from dataclasses import asdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .bridge import MT5Bridge
from .execution import execute_demo
from .market import TIMEFRAMES, synthetic
from .risk import configured_limits
from .store import Store
from .strategy import analyze, signal

ROOT=Path(__file__).resolve().parents[1]
lock=threading.RLock()
store=Store(os.environ.get('DATABASE_PATH',str(ROOT/'runtime'/'forex.sqlite')))
source=os.environ.get('DATA_SOURCE','synthetic')
if source not in ('synthetic','mt5'): raise RuntimeError('DATA_SOURCE must be synthetic or mt5')
bridge=None
bearer=HTTPBearer(auto_error=False)


def auth(credentials:HTTPAuthorizationCredentials|None=Depends(bearer)):
    token=os.environ.get('API_TOKEN','')
    if not token or len(token)<24: raise HTTPException(503,'Set API_TOKEN to a random secret of at least 24 characters; see setup guide')
    if not credentials or not hmac.compare_digest(credentials.credentials,token): raise HTTPException(401,'Valid API token required')


def get_bridge():
    global bridge
    if bridge is None: bridge=MT5Bridge()
    return bridge


def candles(symbol,tf,count):
    return synthetic(tf,count,symbol) if source=='synthetic' else get_bridge().candles(symbol,tf,count)


def frames(symbol):
    return {tf:candles(symbol,tf,300) for tf in ('D1','H4','M30')}


def automation_worker(stop):
    previous_reason=None
    while not stop.wait(30):
        with lock:
            if not store.get('automation_enabled',False): continue
            symbol=store.get('automation_symbol','EURUSD')
            try:
                execute_demo(get_bridge(),store,symbol,frames(symbol),os.environ.get('ENABLE_DEMO_EXECUTION')=='1')
                previous_reason=None
            except Exception as exc:
                reason=str(exc)
                if reason!=previous_reason:
                    store.log('automation_wait',{'reason':reason,'symbol':symbol})
                    previous_reason=reason

@asynccontextmanager
async def lifespan(app):
    store.set('automation_enabled',False)
    stop=threading.Event()
    worker=threading.Thread(target=automation_worker,args=(stop,),daemon=True)
    worker.start()
    yield
    stop.set()
    worker.join(timeout=5)
    with lock:
        if bridge is not None: bridge.mt.shutdown()

app=FastAPI(title='ForexLab — demo research terminal',version='0.1.0',lifespan=lifespan)

@app.exception_handler(ValueError)
async def invalid(request,exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422,content={'detail':str(exc)})

@app.exception_handler(RuntimeError)
async def unavailable(request,exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503,content={'detail':str(exc)})

@app.get('/health')
def health(): return dict(status='ok',source=source,live_execution=False)

@app.get('/api/status',dependencies=[Depends(auth)])
def status():
    with lock:
        account=get_bridge().status() if source=='mt5' else dict(connected=False,demo=False,equity=1000,currency='USD',positions=[],pending_orders=0)
        if source=='mt5': store.anchors(account['server']+':'+account['account'],account['equity'])
        return dict(source=source,mode='demo automation' if store.get('automation_enabled',False) else 'analysis',automation_enabled=store.get('automation_enabled',False),automation_symbol=store.get('automation_symbol'),demo_execution_enabled=source=='mt5' and os.environ.get('ENABLE_DEMO_EXECUTION')=='1',
                    live_execution=False,emergency=store.get('emergency',False),news_clear_until=store.get('news_clear_until',0),account=account,
                    timeframes=list(TIMEFRAMES),limits=asdict(configured_limits()))

@app.get('/api/symbols',dependencies=[Depends(auth)])
def symbols():
    with lock: return get_bridge().symbols() if source=='mt5' else ['EURUSD','XAUUSD']

@app.get('/api/connection',dependencies=[Depends(auth)])
def connection(symbol:str=Query('EURUSD',min_length=1,max_length=64)):
    """Read-only preflight; never places a broker order or enables automation."""
    with lock:
        if source!='mt5':
            return dict(source=source,checked_at=time.time(),requested_symbol=symbol,resolved_symbol=None,candidates=[],
                        connected=False,ready_for_data=False,ready_for_demo=False,
                        market_activity=dict(state='unavailable',quote_age_seconds=None,
                                             notice='Synthetic preview is not a broker connection. Start Windows MT5 analysis to inspect broker quotes.'),
                        checks=[dict(id='source',status='warn',title='Synthetic data source',
                                     detail='Start Windows MT5 analysis mode to check the Exness terminal.',
                                     action='Use start-windows.ps1 -Source mt5 with the MT5 desktop open.')])
        return dict(source=source,**get_bridge().diagnostics(symbol))

@app.get('/api/candles',dependencies=[Depends(auth)])
def get_candles(symbol:str=Query('EURUSD',min_length=1,max_length=64),tf:str='M30',count:int=Query(300,ge=30,le=2000)):
    if tf not in TIMEFRAMES: raise ValueError('Unsupported timeframe')
    with lock:
        cs=candles(symbol,tf,count)
        if source=='mt5':
            info=get_bridge().mt.symbol_info(symbol)
            if info is None or not isinstance(info.digits,int) or not 0<=info.digits<=10 or not math.isfinite(info.trade_tick_size) or info.trade_tick_size<=0:
                raise RuntimeError('Broker price precision/tick grid unavailable')
            precision=info.digits; min_move=info.trade_tick_size
        else:
            precision=2 if 'XAU' in symbol else 3 if 'JPY' in symbol else 5
            min_move=10**-precision
        return dict(source=source,symbol=symbol,timeframe=tf,price_precision=precision,price_min_move=min_move,
                    candles=cs,analysis=analyze(cs))

@app.get('/api/analysis',dependencies=[Depends(auth)])
def analysis(symbol:str=Query('EURUSD',min_length=1,max_length=64)):
    with lock: return dict(source=source,**signal(frames(symbol)))

class Switch(BaseModel):
    enabled:bool

@app.post('/api/emergency',dependencies=[Depends(auth)])
def emergency(body:Switch):
    with lock:
        store.set('emergency',body.enabled)
        store.log('emergency',{'enabled':body.enabled})
        return dict(emergency=body.enabled,notice='Blocks new entries. Existing broker positions and SL/TP remain active; inspect MT5 separately.')

class News(BaseModel):
    minutes:int=Field(ge=0,le=15)
    confirmed_review:bool

@app.post('/api/news-clearance',dependencies=[Depends(auth)])
def news(body:News):
    if not body.confirmed_review: raise ValueError('Review broker/economic calendar before granting clearance')
    with lock:
        until=time.time()+body.minutes*60
        store.set('news_clear_until',until)
        store.log('manual_news_clearance',{'until':until})
        return dict(until=until)

class DemoOrder(BaseModel):
    symbol:str=Field(min_length=1,max_length=64)
    confirmation:str

@app.post('/api/demo/execute',dependencies=[Depends(auth)])
def execute(body:DemoOrder):
    if body.confirmation!='DEMO ONLY': raise ValueError('Explicit DEMO ONLY confirmation required')
    if source!='mt5': raise ValueError('Synthetic data cannot be traded')
    with lock:
        try:
            return execute_demo(get_bridge(),store,body.symbol,frames(body.symbol),os.environ.get('ENABLE_DEMO_EXECUTION')=='1')
        except (ValueError,RuntimeError) as exc:
            store.log('execution_blocked',{'reason':str(exc)})
            raise

class Automation(BaseModel):
    enabled:bool
    symbol:str=Field(default='EURUSD',min_length=1,max_length=64)
    confirmation:str=''

@app.post('/api/demo/automation',dependencies=[Depends(auth)])
def automation(body:Automation):
    with lock:
        if body.enabled:
            if source!='mt5' or os.environ.get('ENABLE_DEMO_EXECUTION')!='1': raise ValueError('Enable Windows MT5 demo execution first')
            a=get_bridge().account()
            if a.trade_mode!=get_bridge().mt.ACCOUNT_TRADE_MODE_DEMO: raise ValueError('Broker-confirmed demo account required')
            if body.confirmation!='DEMO ONLY': raise ValueError('Explicit DEMO ONLY confirmation required')
            if store.get('emergency',False): raise ValueError('Emergency stop active')
        store.set('automation_symbol',body.symbol)
        store.set('automation_enabled',body.enabled)
        store.log('automation',{'enabled':body.enabled,'symbol':body.symbol})
        return dict(enabled=body.enabled,notice='Demo worker checks every 30 seconds. News clearance and all risk gates remain required. Resets to off at server restart.')

@app.get('/api/events',dependencies=[Depends(auth)])
def events(): return store.events()

@app.get('/api/orders',dependencies=[Depends(auth)])
def orders(): return store.orders()

@app.get('/app.webmanifest',include_in_schema=False)
def webmanifest():
    return FileResponse(ROOT/'frontend'/'public'/'app.webmanifest',media_type='application/manifest+json')

@app.get('/icons/{filename}',include_in_schema=False)
def app_icon(filename:str):
    if filename not in ('icon-192.png','icon-512.png','favicon.svg'):
        raise HTTPException(404,'Icon not found')
    return FileResponse(ROOT/'frontend'/'public'/'icons'/filename)

if (ROOT/'frontend'/'dist'/'assets').exists():
    app.mount('/assets',StaticFiles(directory=ROOT/'frontend'/'dist'/'assets'),name='assets')

@app.get('/')
def dashboard():
    index=ROOT/'frontend'/'dist'/'index.html'
    if not index.exists(): raise HTTPException(503,'Build dashboard first: cd frontend && npm ci && npm run build')
    return FileResponse(index)

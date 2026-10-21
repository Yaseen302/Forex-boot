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
from .news import news_clearance
from .observation import DemoObserver, MT5ReadOnlyTransport, ObservationStore, observation_report
from .reconciliation import account_key, sync_ledger
from .research_api import create_research_router
from .risk import configured_limits
from .store import Store
from .strategy import analyze, signal

ROOT=Path(__file__).resolve().parents[1]
lock=threading.RLock()
store=Store(os.environ.get('DATABASE_PATH',str(ROOT/'runtime'/'forex.sqlite')))
source=os.environ.get('DATA_SOURCE','synthetic')
if source not in ('synthetic','mt5'): raise RuntimeError('DATA_SOURCE must be synthetic or mt5')
bridge=None
observer=None
observer_bridge=None
observation_store=None
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


def get_observation_store():
    global observation_store
    if observation_store is None:
        observation_store=ObservationStore(os.environ.get('OBSERVATION_DATABASE_PATH',str(ROOT/'runtime'/'observations.sqlite')))
    return observation_store


def get_observer():
    # Keep the collector alive across requests: its monotonic clock, run identity
    # and previous samples distinguish measured intervals from process downtime.
    global observer,observer_bridge
    current=get_bridge()
    if observer is None or observer_bridge is not current or observer.store is not get_observation_store():
        observer=DemoObserver(MT5ReadOnlyTransport(current),get_observation_store())
        observer_bridge=current
    return observer


def account_scope():
    return account_key(get_bridge().account()) if source=='mt5' else None


def scoped_reconciliation(report):
    """Retain cross-account locks without disclosing their order identities."""
    key=account_scope()
    if report.get('account')!=key:
        return dict(account=key,resolved=[],pending=[],risk_alerts=[],ledger=None,
                    errors=['Broker account changed during the request; inspect the current account before retrying the read-only check'],
                    other_account_submission_blocked=True)
    visible={row['signal_id'] for row in store.orders(account=key,limit=None)} if key else set()
    result=dict(report)
    for field in ('resolved','pending','risk_alerts'):
        result[field]=[row for row in report.get(field,[]) if row.get('signal_id') in visible]
    result['other_account_submission_blocked']=any(row['status']=='pending' and row['metadata'].get('account')!=key for row in store.orders(limit=None))
    return result


def automation_account_matches(current):
    """A new demo login never inherits another account's automation consent."""
    expected=store.get('automation_account')
    if expected:
        account=current.account()
        if account.trade_mode==current.mt.ACCOUNT_TRADE_MODE_DEMO and account_key(account)==expected:
            return True
    store.set('automation_enabled',False)
    store.log('automation_stopped',dict(reason='account_changed',
        notice='Demo account binding is missing or changed. Automation stopped; explicitly enable it again on the selected demo account.'))
    return False


def automation_worker(stop):
    previous_reason=None
    while not stop.wait(30):
        with lock:
            if not store.get('automation_enabled',False): continue
            symbol=store.get('automation_symbol','EURUSD')
            try:
                if source!='mt5': raise ValueError('Synthetic data cannot be traded')
                current=get_bridge()
                if not automation_account_matches(current):continue
                recovered=sync_ledger(current,store)
                if recovered['errors']: raise RuntimeError('Broker reconciliation unavailable; new entries remain blocked')
                if not automation_account_matches(current):continue
                data=frames(symbol)
                if not automation_account_matches(current):continue
                execute_demo(current,store,symbol,data,os.environ.get('ENABLE_DEMO_EXECUTION')=='1',store.get('automation_account'))
                after=sync_ledger(current,store)
                if after['errors']:
                    store.set('emergency',True)
                    raise RuntimeError('Fill returned but broker protection could not be checked; emergency entry stop active. Inspect MT5 without retrying the order.')
                previous_reason=None
            except Exception as exc:
                reason=str(exc)
                if reason!=previous_reason:
                    store.log('automation_wait',{'reason':reason,'symbol':symbol})
                    previous_reason=reason

@asynccontextmanager
async def lifespan(app):
    store.set('automation_enabled',False)
    store.set('automation_account',None)
    stop=threading.Event()
    worker=threading.Thread(target=automation_worker,args=(stop,),daemon=True)
    worker.start()
    yield
    stop.set()
    worker.join(timeout=5)
    with lock:
        if bridge is not None: bridge.mt.shutdown()

app=FastAPI(title='ForexLab — demo research terminal',version='0.1.0',lifespan=lifespan)
research_router,research_jobs=create_research_router(auth,os.environ.get('RESEARCH_PATH',str(ROOT/'runtime'/'research')),lambda:get_bridge(),lock,lambda:source)
app.include_router(research_router)

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
                    live_execution=False,emergency=store.get('emergency',False),news_clear_until=store.get('news_clear_until',0),
                    news_clearance=news_clearance(store,store.get('automation_symbol','EURUSD'),time.time()),account=account,
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

@app.get('/api/news',dependencies=[Depends(auth)])
def news_status(symbol:str=Query('EURUSD',min_length=1,max_length=64)):
    with lock:return dict(symbol=symbol,**news_clearance(store,symbol,time.time()))

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
    if os.environ.get('NEWS_MODE','manual')!='manual': raise ValueError('Manual clearance is unavailable in calendar mode; a fresh provider calendar is required')
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
            recovered=sync_ledger(get_bridge(),store)
            if recovered['errors']: raise RuntimeError('Broker reconciliation unavailable; new entries remain blocked')
            result=execute_demo(get_bridge(),store,body.symbol,frames(body.symbol),os.environ.get('ENABLE_DEMO_EXECUTION')=='1')
            after=sync_ledger(get_bridge(),store)
            if after['errors']:
                store.set('emergency',True)
                store.log('post_fill_check_unavailable',{'notice':'Broker protection verification unavailable; inspect MT5 without retrying the order'})
            return dict(result,reconciliation=scoped_reconciliation(after),emergency=store.get('emergency',False))
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
            store.set('automation_account',account_key(a))
        else:
            store.set('automation_account',None)
        store.set('automation_symbol',body.symbol)
        store.set('automation_enabled',body.enabled)
        store.log('automation',{'enabled':body.enabled,'symbol':body.symbol})
        return dict(enabled=body.enabled,notice='Demo worker checks every 30 seconds. News clearance and all risk gates remain required. Resets to off at server restart or when the selected demo account changes; explicitly enable again after switching accounts.')

@app.get('/api/events',dependencies=[Depends(auth)])
def events(): return store.events()

@app.get('/api/orders',dependencies=[Depends(auth)])
def orders():
    with lock:
        key=account_scope()
        return store.orders(account=key) if key else []

@app.get('/api/reconciliation',dependencies=[Depends(auth)])
def reconciliation():
    with lock:
        key=account_scope()
        return dict(account=key,orders=store.orders(account=key) if key else [],ledger=store.ledger(key) if key else None,
                    other_account_submission_blocked=any(row['status']=='pending' and row['metadata'].get('account')!=key for row in store.orders(limit=None)),read_only=True)

@app.post('/api/reconciliation/sync',dependencies=[Depends(auth)])
def reconciliation_sync():
    if source!='mt5':raise ValueError('Broker reconciliation requires Windows MT5; synthetic data cannot verify broker orders')
    with lock:return dict(scoped_reconciliation(sync_ledger(get_bridge(),store)),read_only=True)

class ObservationSample(BaseModel):
    symbol:str=Field(default='EURUSDm',min_length=1,max_length=64)
    reset_comparison:bool=False

@app.get('/api/observation',dependencies=[Depends(auth)])
def observation(symbol:str|None=Query(default=None,min_length=1,max_length=64)):
    # Reporting persisted samples must work even when the broker is offline.
    with lock:return observation_report(get_observation_store().samples(symbol))

@app.post('/api/observation/sample',dependencies=[Depends(auth)])
def observation_sample(body:ObservationSample):
    if source!='mt5':raise ValueError('Demo observations require Windows MT5; synthetic prices are not broker evidence')
    with lock:
        collector=get_observer()
        sample=collector.sample(body.symbol,reset_comparison=body.reset_comparison)
        return dict(sample=sample,report=collector.report(body.symbol),read_only=True)

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

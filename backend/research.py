"""Broker-history research services. No network calls, credentials or orders.

A sidecar records local export provenance and binds bytes with SHA-256; it is
not a broker-signed attestation. API callers must restrict paths to runtime.
"""
import argparse
import csv
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import time
import uuid
from .market import validate

MINIMUM_BARS=8000
COLUMNS=('time','open','high','low','close','volume')
SOURCE_BROKER='mt5_broker_history'
SOURCE_FIXTURE='synthetic_fixture'
SOURCE_EXTERNAL='external_csv_unverified'


def _read_csv(path):
    if path.stat().st_size>64*1024*1024: raise ValueError('History CSV exceeds 64 MB')
    candles=[]
    with path.open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or len(reader.fieldnames)!=len(COLUMNS) or set(reader.fieldnames)!=set(COLUMNS):
            raise ValueError('CSV columns must be time,open,high,low,close,volume only')
        for index,row in enumerate(reader,start=2):
            if None in row: raise ValueError('Too many CSV fields at row '+str(index))
            if index>250002: raise ValueError('At most 250000 M30 bars are supported per research run')
            try:
                candle={k:int(row[k]) if k=='time' else float(row[k]) for k in COLUMNS}
            except (ValueError,TypeError,KeyError) as exc:
                raise ValueError('Invalid numeric CSV value at row '+str(index)) from exc
            candles.append(candle)
    validate(candles)
    if any(c['time']<0 or c['time']%1800 for c in candles):
        raise ValueError('History requires UTC Unix M30 opens aligned to 1800 seconds')
    if any(c['time']+1800>time.time() for c in candles):
        raise ValueError('History contains a future or incomplete M30 candle')
    return candles


def _metadata(path,digest):
    sidecar=path.with_suffix('.meta.json')
    if not sidecar.is_file(): raise ValueError('Missing .meta.json broker-export sidecar; export with scripts/export-history.py')
    if sidecar.stat().st_size>65536: raise ValueError('History metadata exceeds 64 KB')
    try: data=json.loads(sidecar.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError) as exc: raise ValueError('Invalid history metadata JSON') from exc
    if not isinstance(data,dict): raise ValueError('History metadata must be an object')
    if data.get('schema_version')!=1: raise ValueError('Unsupported history metadata schema')
    source=data.get('source')
    if source not in (SOURCE_BROKER,SOURCE_FIXTURE,SOURCE_EXTERNAL): raise ValueError('Unknown history source; synthetic data must be labeled synthetic_fixture')
    if data.get('csv_sha256')!=digest: raise ValueError('History SHA-256 does not match export metadata; re-export changed files')
    if data.get('timeframe')!='M30' or data.get('price_basis')!='bid' or data.get('timestamp_basis')!='UTC':
        raise ValueError('Only completed UTC M30 bid candles are supported')
    if not isinstance(data.get('symbol'),str) or not 1<=len(data['symbol'])<=80:
        raise ValueError('Export metadata requires the exact broker symbol')
    # No API-provided source override can relabel fixtures. Metadata cannot be
    # a cryptographic proof of origin; tampering by a local file owner is outside this trust boundary.
    if source==SOURCE_BROKER and (data.get('fixture') or data.get('generator')
            or data.get('exporter')!='ForexLab MT5 history exporter v1'):
        raise ValueError('Broker source requires the MT5 exporter; fixtures cannot be labeled broker history')
    if source==SOURCE_BROKER and not isinstance(data.get('broker_server'),str):
        raise ValueError('Broker export is missing non-secret server provenance')
    if data.get('account_currency')!='USD': raise ValueError('Research currently requires a USD account; currency conversion is not modeled')
    spec=data.get('instrument')
    if not isinstance(spec,dict) or spec.get('profit_currency')!='USD':
        raise ValueError('Research supports USD profit currency only; cross-currency conversion is not modeled')
    for field in ('contract_size','volume_min','volume_max','volume_step','point'):
        v=spec.get(field)
        if not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) or v<=0:
            raise ValueError('Invalid broker instrument '+field)
    if spec['volume_min']>spec['volume_max']: raise ValueError('Invalid broker volume range')
    if spec.get('calculation_mode') not in (0,1,3,4):
        raise ValueError('Unsupported profit calculation mode; linear USD forex/CFD contracts only')
    approved=('schema_version','source','symbol','broker_server','account_currency','timeframe','price_basis',
              'timestamp_basis','exported_at','bar_count','first_time','last_time','csv_sha256','exporter',
              'fixture','generator')
    result={k:data[k] for k in approved if k in data}
    result['instrument']={k:spec[k] for k in ('contract_size','volume_min','volume_max','volume_step','point',
                          'profit_currency','calculation_mode','base_currency','digits','tick_size','tick_value') if k in spec}
    return result


def _inspect(csv_path,minimum_bars=MINIMUM_BARS):
    path=Path(csv_path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and path.stat().st_size<=64*1024*1024 else None
    candles=_read_csv(path)
    metadata=_metadata(path,digest)
    if metadata.get('bar_count')!=len(candles): raise ValueError('Export sidecar bar_count does not match CSV')
    if metadata.get('first_time')!=candles[0]['time'] or metadata.get('last_time')!=candles[-1]['time']:
        raise ValueError('Export sidecar timestamp range does not match CSV')
    gaps=[dict(after=a['time'],before=b['time'],seconds=b['time']-a['time'],
               missing_m30_slots=(b['time']-a['time'])//1800-1)
          for a,b in zip(candles,candles[1:]) if b['time']-a['time']>1800]
    warnings=['UTC H4/D1 resampling differs from broker session candles; this is not an exact live-strategy replay.',
              'Provenance is recorded by the local exporter, not independently broker-signed.']
    issues=[]
    if len(candles)<minimum_bars: issues.append('At least '+str(minimum_bars)+' completed M30 bars required')
    if any(g['seconds']>8*86400 for g in gaps): issues.append('History has a gap longer than eight days; load continuous broker history and re-export')
    if gaps: warnings.append('Gaps detected; weekend/holiday closures and missing data are not independently distinguished. Review them before interpreting results.')
    if metadata['source']==SOURCE_EXTERNAL: warnings.append('UNVERIFIED EXTERNAL CSV: exporter provenance is unavailable; user-supplied specifications and prices have not been verified against a broker.')
    if metadata['source']==SOURCE_FIXTURE: warnings.append('SYNTHETIC FIXTURE: software validation only; never market-performance evidence.')
    info=dict(path=str(path),filename=path.name,source=metadata['source'],symbol=metadata['symbol'],
              bar_count=len(candles),minimum_bars=minimum_bars,sha256=digest,
              first_time=candles[0]['time'],last_time=candles[-1]['time'],
              gap_count=len(gaps),missing_m30_slots=sum(g['missing_m30_slots'] for g in gaps),gaps=gaps[:30],
              gaps_truncated=len(gaps)>30,metadata=metadata,valid=True,
              eligible=not issues and metadata['source']==SOURCE_BROKER,issues=issues,warnings=warnings)
    return candles,info


def _write_export(candles,path,metadata):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() or path.with_suffix('.meta.json').exists():
        raise ValueError('Dataset destination already exists; choose a new name to preserve previous exports')
    temporary=path.with_suffix('.csv.tmp')
    try:
        with temporary.open('x',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=COLUMNS);writer.writeheader();writer.writerows(candles)
        metadata.update(schema_version=1,timeframe='M30',price_basis='bid',timestamp_basis='UTC',
                        exported_at=datetime.now(timezone.utc).isoformat(),bar_count=len(candles),
                        first_time=candles[0]['time'],last_time=candles[-1]['time'],
                        csv_sha256=hashlib.sha256(temporary.read_bytes()).hexdigest())
        # Complete both exports before moving final CSV into visibility.
        sidecar=path.with_suffix('.meta.json')
        sidecar.write_text(json.dumps(metadata,indent=2,allow_nan=False),encoding='utf-8')
        temporary.replace(path)
    finally:
        if temporary.exists(): temporary.unlink()
    return dataset_info(path)


def export_history(bridge,symbol,count,path):
    """Read official MT5 prices/specs; no orders and no account identity persisted.

    Caller serializes MT5 access. The already logged-in terminal supplies all
    authentication. Partial broker history is reported rather than invented.
    """
    if not isinstance(count,int) or not 30<=count<=250000:
        raise ValueError('History count must be between 30 and 250000 completed M30 bars')
    bridge.connect()
    account=bridge.account()
    spec=bridge.mt.symbol_info(symbol)
    if spec is None: raise ValueError('Unknown broker symbol')
    if getattr(spec,'chart_mode',None)!=getattr(bridge.mt,'SYMBOL_CHART_MODE_BID',0):
        raise ValueError('Only bid-based broker history is supported, not last-price exchange charts')
    candles=bridge.candles(symbol,'M30',count)
    # A terminal can be switched manually while history is loading. Never bind
    # one account's prices/specifications to another account's export metadata.
    current=bridge.account()
    if (getattr(account,'login',None),account.server,account.currency)!=(getattr(current,'login',None),current.server,current.currency):
        raise ValueError('Account changed during history export; no dataset was saved')
    metadata=dict(source=SOURCE_BROKER,exporter='ForexLab MT5 history exporter v1',symbol=symbol,
                  broker_server=str(account.server),account_currency=str(account.currency),
                  instrument=dict(contract_size=float(spec.trade_contract_size),volume_min=float(spec.volume_min),
                                  volume_max=float(spec.volume_max),volume_step=float(spec.volume_step),
                                  point=float(spec.point),profit_currency=str(spec.currency_profit),
                                  base_currency=str(spec.currency_base),calculation_mode=int(spec.trade_calc_mode),
                                  digits=int(spec.digits),tick_size=float(spec.trade_tick_size),tick_value=float(spec.trade_tick_value)))
    return _write_export(candles,path,metadata)


def import_csv(csv_text,path,*,symbol,account_currency='USD',contract_size=None,volume_min=None,
               volume_max=None,volume_step=None,point=None,profit_currency='USD',calculation_mode=0):
    """Import user CSV with explicitly unverified provenance and declared specs.

    Missing contract values leave the dataset ineligible; no lot/contract
    assumptions are silently supplied. CSV is normalized after validation.
    """
    import io
    if not isinstance(csv_text,str) or len(csv_text.encode('utf-8'))>64*1024*1024:
        raise ValueError('CSV text is required and must not exceed 64 MB')
    reader=csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames or len(reader.fieldnames)!=len(COLUMNS) or set(reader.fieldnames)!=set(COLUMNS):
        raise ValueError('CSV columns must be time,open,high,low,close,volume only')
    candles=[]
    try:
        for row in reader:
            if None in row: raise ValueError('Too many CSV fields')
            candles.append({k:int(row[k]) if k=='time' else float(row[k]) for k in COLUMNS})
            if len(candles)>250000: raise ValueError('At most 250000 M30 bars are supported')
    except (ValueError,TypeError,KeyError) as exc:
        raise ValueError('Invalid CSV numeric data') from exc
    validate(candles)
    if any(c['time']<0 or c['time']%1800 or c['time']+1800>time.time() for c in candles):
        raise ValueError('Require completed UTC Unix M30 opens aligned to 1800 seconds')
    metadata=dict(source=SOURCE_EXTERNAL,symbol=symbol,account_currency=account_currency,
                  exporter='User supplied CSV; provenance not verified',
                  instrument=dict(contract_size=contract_size,volume_min=volume_min,volume_max=volume_max,
                                  volume_step=volume_step,point=point,profit_currency=profit_currency,
                                  calculation_mode=calculation_mode))
    return _write_export(candles,path,metadata)


def dataset_info(csv_path):
    """Safe display summary; invalid/missing datasets are not eligible to run."""
    try: return _inspect(csv_path)[1]
    except (OSError,ValueError,UnicodeError,csv.Error) as exc:
        summary=dict(filename=Path(csv_path).name,valid=False,eligible=False,source='unverified',bar_count=0,issues=[str(exc)],warnings=[])
        try:
            candles=_read_csv(Path(csv_path))
            summary.update(bar_count=len(candles),first_time=candles[0]['time'],last_time=candles[-1]['time'],
                           sha256=hashlib.sha256(Path(csv_path).read_bytes()).hexdigest())
        except (OSError,ValueError,UnicodeError,csv.Error): pass
        try:
            path=Path(csv_path);sidecar=path.with_suffix('.meta.json')
            if sidecar.stat().st_size<=65536:
                raw=json.loads(sidecar.read_text(encoding='utf-8'))
                if isinstance(raw,dict):
                    if raw.get('source') in (SOURCE_BROKER,SOURCE_FIXTURE,SOURCE_EXTERNAL): summary['source']=raw['source']
                    if isinstance(raw.get('symbol'),str): summary['symbol']=raw['symbol'][:80]
        except (OSError,ValueError,UnicodeError): pass
        return summary


def load_dataset(csv_path,*,allow_fixture=False,allow_unverified=False,minimum_bars=MINIMUM_BARS):
    candles,info=_inspect(csv_path,minimum_bars)
    if info['issues']: raise ValueError('; '.join(info['issues']))
    if info['source']==SOURCE_FIXTURE and not allow_fixture:
        raise ValueError('Synthetic fixture cannot be evaluated as broker performance; use allow_fixture only in software validation')
    if info['source']==SOURCE_EXTERNAL and not allow_unverified:
        raise ValueError('External CSV provenance is unverified; explicit allow_unverified acknowledgement required')
    return candles,info


def run_research(csv_path,*,output_dir='runtime/research/reports',initial=1000.,spread=None,slippage=None,
                 commission=None,swap_per_lot_day=None,risk_percent=.25,max_daily_loss=2.,max_drawdown=5.,
                 max_entries_per_day=5,allow_fixture=False,allow_unverified=False):
    """Validate exported bytes, evaluate fixed rules, and persist an honest report.

    Required cost values have no inferred defaults; units are price, price,
    USD/lot round trip, and conservative USD/lot per UTC overnight respectively.
    """
    costs=(spread,slippage,commission,swap_per_lot_day)
    if any(v is None or not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in costs):
        raise ValueError('Explicit finite nonnegative spread, slippage, commission and swap_per_lot_day assumptions are required')
    candles,info=load_dataset(csv_path,allow_fixture=allow_fixture,allow_unverified=allow_unverified)
    from .evaluate import evaluate
    spec=info['metadata']['instrument']
    assumptions=dict(initial=initial,spread=spread,slippage=slippage,commission=commission,
                     swap_per_lot_day=swap_per_lot_day,risk_percent=risk_percent,max_daily_loss=max_daily_loss,
                     max_drawdown=max_drawdown,max_entries_per_day=max_entries_per_day,
                     contract=spec['contract_size'],minimum=spec['volume_min'],maximum=spec['volume_max'],step=spec['volume_step'])
    evaluation=evaluate(candles,**assumptions)
    now=datetime.now(timezone.utc);report_id=now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
    # Copy only explicitly approved non-secret provenance; never persist login/password/session tokens.
    approved_metadata={k:info['metadata'][k] for k in ('schema_version','source','symbol','broker_server','account_currency',
                        'timeframe','price_basis','timestamp_basis','exported_at','bar_count','first_time','last_time',
                        'csv_sha256','exporter','instrument') if k in info['metadata']}
    dataset={k:v for k,v in info.items() if k not in ('path','metadata')}
    dataset['metadata']=approved_metadata
    report=dict(schema_version=1,report_id=report_id,created_at=now.isoformat(),source=info['source'],
                purpose=('fixture_engine_validation' if info['source']==SOURCE_FIXTURE else 'unverified_external_research' if info['source']==SOURCE_EXTERNAL else 'broker_history_research'),
                profitability_proven=False,live_strategy_parity_validated=False,
                timeframe_alignment='UTC resampling; broker-session D1/H4 parity not validated',
                dataset=dataset,costs=assumptions,
                cost_units=dict(spread='price difference',slippage='adverse price difference per fill',
                                commission='USD per lot round trip',swap_per_lot_day='USD cost per lot per UTC overnight'),
                evaluation=evaluation,limitations=info['warnings']+evaluation['limitations'])
    folder=Path(output_dir);folder.mkdir(parents=True,exist_ok=True)
    destination=folder/(report_id+'.json');temporary=folder/(report_id+'.tmp')
    temporary.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(destination)
    return {**report,'file':str(destination)}


def main():
    from .backtest import add_simulator_arguments,simulator_arguments
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--output-dir',default='runtime/research/reports')
    add_simulator_arguments(p);a=p.parse_args()
    report=run_research(a.csv,output_dir=a.output_dir,**simulator_arguments(a))
    print('Saved research report: '+report['file'])
    print('Realized OOS trades: '+str(report['evaluation']['sections'][2]['report']['trades']))
    print('Research only; not a profitability claim.')

if __name__=='__main__': main()

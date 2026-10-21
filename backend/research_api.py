"""Authenticated local research jobs. Never imports or calls order execution."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import threading
import uuid

from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict

from .research import dataset_info,export_history,import_csv,load_dataset,run_research

ID_PATTERN=re.compile(r'^[0-9a-f]{32}$')
MAX_CSV_BYTES=10*1024*1024


def utcnow():return datetime.now(timezone.utc).isoformat()


class ExportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    symbol:str=Field(min_length=1,max_length=64)
    count:int=Field(default=20000,ge=8000,le=50000)

class ImportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    csv_text:str=Field(min_length=1,max_length=MAX_CSV_BYTES)
    symbol:str=Field(min_length=1,max_length=64)
    account_currency:str=Field(default='USD',max_length=12)
    profit_currency:str=Field(default='USD',max_length=12)
    contract_size:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    volume_min:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    volume_max:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    volume_step:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    point:float|None=Field(default=None,gt=0,allow_inf_nan=False)

class ResearchRequest(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False,extra='forbid')
    dataset_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    initial:float=Field(default=1000,gt=0,le=100000000)
    spread:float=Field(ge=0,le=100000)
    slippage:float=Field(ge=0,le=100000)
    commission:float=Field(ge=0,le=100000)
    swap_per_lot_day:float=Field(ge=0,le=100000)
    allow_unverified:bool=False
    horizon:int=Field(default=3,ge=1,le=48)


class ResearchJobs:
    def __init__(self,root):
        self.root=Path(root).resolve();self.lock=threading.RLock()
        for name in ('datasets','reports','jobs'):(self.root/name).mkdir(parents=True,exist_ok=True)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='forex-research')
        for path in (self.root/'jobs').glob('*.json'):
            try:
                path=self.path('jobs',path.stem)
                job=json.loads(path.read_text())
                if not isinstance(job,dict):continue
                if job.get('status') in ('queued','running'):
                    job.update(status='failed',error='Server restarted before research completed. No result was verified; start a new job explicitly.',finished_at=utcnow())
                    self.write(path,job)
            except (OSError,ValueError,HTTPException):continue
    def path(self,kind,id,suffix='.json'):
        if kind not in ('datasets','reports','jobs') or not ID_PATTERN.fullmatch(id):raise HTTPException(404,'Item not found')
        path=self.root/kind/(id+suffix)
        if path.resolve().parent!=self.root/kind:raise HTTPException(404,'Item not found')
        return path
    def write(self,path,data):
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,allow_nan=False,indent=2),encoding='utf-8')
        temporary.replace(path)
    def dataset(self,id):
        path=self.path('datasets',id,'.csv')
        self.path('datasets',id,'.meta.json')
        if not path.is_file():raise HTTPException(404,'Dataset not found')
        return path
    def describe(self,id):
        data=dataset_info(self.dataset(id));data.pop('path',None)
        name=data.get('filename',id)
        sidecar=self.path('datasets',id,'.meta.json')
        try:
            if sidecar.stat().st_size<=65536:
                label=json.loads(sidecar.read_text(encoding='utf-8')).get('display_name')
                if isinstance(label,str) and 1<=len(label)<=120:name=label
        except (OSError,ValueError,AttributeError):pass
        return dict(data,id=id,name=name)
    def label(self,id,name):
        path=self.path('datasets',id,'.meta.json')
        data=json.loads(path.read_text(encoding='utf-8'));data['display_name']=name
        self.write(path,data)
    def datasets(self):
        result=[]
        for path in sorted((self.root/'datasets').glob('*.csv')):
            if not ID_PATTERN.fullmatch(path.stem):continue
            try:result.append(self.describe(path.stem))
            except HTTPException:continue
            if len(result)>=100:break
        return result
    def reports(self):
        result=[]
        for path in sorted((self.root/'reports').glob('*.json'),key=lambda p:p.lstat().st_mtime,reverse=True):
            if not ID_PATTERN.fullmatch(path.stem):continue
            try:
                path=self.path('reports',path.stem)
                data=json.loads(path.read_text())
                if isinstance(data,dict):result.append({k:data.get(k) for k in ('id','created_at','source','symbol','kind','summary')})
            except (OSError,ValueError,HTTPException):continue
        return result[:100]
    def read(self,kind,id):
        path=self.path(kind,id)
        try:return json.loads(path.read_text())
        except (OSError,ValueError):raise HTTPException(404,'Item not found') from None
    def submit(self,body,kind='strategy'):
        csv=self.dataset(body.dataset_id)
        # Parse and validate provenance, costs and bounds before queueing work.
        _,info=load_dataset(csv,allow_unverified=body.allow_unverified,minimum_bars=8000)
        with self.lock:
            for path in (self.root/'jobs').glob('*.json'):
                try:
                    path=self.path('jobs',path.stem)
                    previous=json.loads(path.read_text())
                    state=previous.get('status') if isinstance(previous,dict) else None
                except (OSError,ValueError,HTTPException):continue
                if state in ('queued','running'):raise HTTPException(409,'Another research job is active; wait for its result')
            id=uuid.uuid4().hex
            job=dict(job_id=id,status='queued',kind=kind,created_at=utcnow(),dataset_id=body.dataset_id)
            self.write(self.path('jobs',id),job)
            self.executor.submit(self._work,id,csv,body,kind,info)
            return job
    def _work(self,id,csv,body,kind,info):
        job=self.read('jobs',id);job.update(status='running',started_at=utcnow());self.write(self.path('jobs',id),job)
        try:
            if kind=='ml':
                from .ml_research import ResearchCosts,run_research as ml_run
                candles,current=load_dataset(csv,allow_unverified=body.allow_unverified,minimum_bars=8000)
                spec=current['metadata']['instrument'];point=spec['point']
                # UI swap is a nonnegative debit, ML cost schema uses signed credit.
                costs=ResearchCosts(point_size=point,spread_points=body.spread/point,slippage_points=body.slippage/point,
                    commission_round_trip_per_lot=body.commission,swap_per_lot_day=-body.swap_per_lot_day,
                    contract_size=spec['contract_size'],timeframe_minutes=30,quote_currency=current['metadata']['instrument']['profit_currency'])
                report=ml_run(candles,costs,body.horizon,dataset_metadata={k:current.get(k) for k in ('source','symbol','sha256','bar_count')})
                summary={'purpose':'ML forecasting research only; never used by execution','sample_count':len(candles)}
            else:
                report=run_research(csv,output_dir=self.root/'reports'/'raw',initial=body.initial,spread=body.spread,
                    slippage=body.slippage,commission=body.commission,swap_per_lot_day=body.swap_per_lot_day,allow_unverified=body.allow_unverified)
                summary={'purpose':report.get('purpose'),'bar_count':info['bar_count']}
            # The browser needs provenance and metrics, not cloud/Windows paths.
            report.pop('file',None)
            if isinstance(report.get('dataset'),dict):report['dataset'].pop('path',None)
            report_id=uuid.uuid4().hex
            wrapper=dict(id=report_id,created_at=utcnow(),source=info['source'],symbol=info['symbol'],kind=kind,summary=summary,report=report)
            self.write(self.path('reports',report_id),wrapper)
            job.update(status='completed',report_id=report_id,finished_at=utcnow())
        except Exception as exc:
            job.update(status='failed',error=str(exc)[:1000],finished_at=utcnow())
        self.write(self.path('jobs',id),job)


def create_research_router(auth,root,bridge_provider,broker_lock,source_provider):
    jobs=ResearchJobs(root)
    router=APIRouter(prefix='/api/research',dependencies=[Depends(auth)])
    @router.get('/datasets')
    def datasets():return {'datasets':jobs.datasets()}
    @router.post('/export')
    def export(body:ExportRequest):
        if source_provider()!='mt5':raise HTTPException(422,'MT5 broker history export requires the Windows MT5 source; synthetic prices cannot be exported as broker history')
        if len(jobs.datasets())>=100:raise HTTPException(409,'Dataset storage limit reached')
        id=uuid.uuid4().hex
        with broker_lock:export_history(bridge_provider(),body.symbol,body.count,jobs.path('datasets',id,'.csv'))
        return jobs.describe(id)
    @router.post('/import')
    def import_dataset(body:ImportRequest):
        if len(body.csv_text.encode('utf-8'))>MAX_CSV_BYTES:raise HTTPException(413,'CSV is too large')
        if len(jobs.datasets())>=100:raise HTTPException(409,'Dataset storage limit reached')
        id=uuid.uuid4().hex
        values=body.model_dump(exclude={'name','csv_text'})
        import_csv(body.csv_text,jobs.path('datasets',id,'.csv'),**values)
        jobs.label(id,body.name)
        return jobs.describe(id)
    @router.post('/run')
    def run(body:ResearchRequest):return jobs.submit(body)
    @router.post('/ml')
    def ml(body:ResearchRequest):return jobs.submit(body,'ml')
    @router.get('/jobs/{id}')
    def job(id:str):return jobs.read('jobs',id)
    @router.get('/reports')
    def reports():return {'reports':jobs.reports()}
    @router.get('/reports/{id}')
    def report(id:str):return jobs.read('reports',id)
    return router,jobs

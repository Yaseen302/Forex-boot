import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

class Store:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.path=path
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,time TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders(signal_id TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL);''')
            # Additive migrations keep existing user journals and order locks intact.
            columns={row[1] for row in db.execute('PRAGMA table_info(orders)')}
            for name,kind in [('request','TEXT'),('metadata','TEXT'),('response','TEXT')]:
                if name not in columns: db.execute(f'ALTER TABLE orders ADD COLUMN {name} {kind}')
            db.execute('''CREATE TABLE IF NOT EXISTS broker_deals(
                account TEXT NOT NULL,ticket INTEGER NOT NULL,signal_id TEXT NOT NULL,
                payload TEXT NOT NULL,PRIMARY KEY(account,ticket))''')
    def connect(self):
        return sqlite3.connect(self.path,timeout=10)
    def get(self,key,default=None):
        with self.connect() as db:
            row=db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def set(self,key,value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(key,json.dumps(value,allow_nan=False)))
    def log(self,kind,payload):
        with self.connect() as db:
            db.execute('INSERT INTO events(time,kind,payload) VALUES (?,?,?)',(datetime.now(timezone.utc).isoformat(),kind,json.dumps(payload,allow_nan=False)))
    def events(self):
        with self.connect() as db:
            rows=db.execute('SELECT id,time,kind,payload FROM events ORDER BY id DESC LIMIT 100').fetchall()
        return [dict(id=i,time=t,kind=k,payload=json.loads(p)) for i,t,k,p in rows]
    def reserve(self,key,payload,*,metadata=None):
        metadata=dict(metadata or {})
        metadata.setdefault('submitted_at',time.time())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Any uncertain submission blocks subsequent orders until investigated.
            if db.execute("SELECT 1 FROM orders WHERE status='pending'").fetchone():
                raise ValueError('Unresolved submission exists; inspect broker history before reconciliation')
            try: db.execute('INSERT INTO orders(signal_id,status,payload,request,metadata) VALUES (?,?,?,?,?)',
                            (key,'pending',json.dumps(payload,allow_nan=False),json.dumps(payload,allow_nan=False),json.dumps(metadata,allow_nan=False)))
            except sqlite3.IntegrityError: raise ValueError('Duplicate signal already processed') from None
    def response(self,key,payload):
        """Persist even an ambiguous broker response without clearing the order lock."""
        with self.connect() as db:
            db.execute('UPDATE orders SET response=? WHERE signal_id=?',(json.dumps(payload,allow_nan=False),key))
    def finish(self,key,status,payload):
        with self.connect() as db:
            db.execute('UPDATE orders SET status=?,payload=? WHERE signal_id=?',(status,json.dumps(payload,allow_nan=False),key))
        self.log('order_'+status,dict(signal_id=key,**payload))
    def orders(self,account=None,limit=100):
        with self.connect() as db:
            rows=db.execute('SELECT signal_id,status,payload,request,metadata,response FROM orders ORDER BY rowid DESC').fetchall()
        result=[dict(signal_id=k,status=s,payload=json.loads(p),request=json.loads(r) if r else None,
                     metadata=json.loads(m) if m else {},response=json.loads(v) if v else None) for k,s,p,r,m,v in rows]
        if account is not None: result=[row for row in result if row['metadata'].get('account')==account]
        return result if limit is None else result[:limit]
    def record_deal(self,account,signal_id,payload):
        """Idempotent broker facts; a ticket can belong to only one signal per account."""
        with self.connect() as db:
            existing=db.execute('SELECT signal_id,payload FROM broker_deals WHERE account=? AND ticket=?',
                                (account,payload['ticket'])).fetchone()
            if existing and existing[0]!=signal_id: raise ValueError('Broker deal already belongs to another signal')
            if existing:
                previous=json.loads(existing[1])
                immutable=('order','position_id','entry','type','volume','symbol','magic')
                if any(previous.get(field)!=payload.get(field) for field in immutable):
                    raise ValueError('Broker deal identity changed; manual reconciliation required')
            db.execute('INSERT OR REPLACE INTO broker_deals VALUES (?,?,?,?)',
                       (account,payload['ticket'],signal_id,json.dumps(payload,allow_nan=False)))
    def ledger(self,account=None):
        with self.connect() as db:
            rows=db.execute('SELECT account,signal_id,payload FROM broker_deals ORDER BY ticket').fetchall()
        deals=[dict(json.loads(p),account=a,signal_id=s) for a,s,p in rows if account is None or a==account]
        trades=[]
        orders={(row['metadata'].get('account'),row['signal_id']):row for row in self.orders(account=account,limit=None)}
        identities=sorted({(d['account'],d['signal_id']) for d in deals})
        for identity in identities:
            attributed=[d for d in deals if (d['account'],d['signal_id'])==identity]
            entries=[d for d in attributed if d.get('entry')==0]
            exits=[d for d in attributed if d.get('entry') in (1,3)]
            filled=sum(d.get('volume',0) for d in entries)
            exited=sum(d.get('volume',0) for d in exits)
            expected=(orders.get(identity,{}).get('request') or {}).get('volume',0)
            full=expected>0 and abs(filled-expected)<1e-8
            closed=bool(full and abs(filled-exited)<1e-8)
            trades.append(dict(account=identity[0],signal_id=identity[1],
                               symbol=entries[0].get('symbol') if entries else None,
                               requested_volume=expected,filled_volume=filled,exited_volume=exited,
                               unaccounted_volume=max(0,filled-exited),fully_filled=full,
                               lifecycle='closed' if closed else 'open_or_unsettled',
                               net_realized=sum(d.get('profit',0)+d.get('commission',0)+d.get('swap',0)+d.get('fee',0) for d in attributed)))
        closed=[trade for trade in trades if trade['lifecycle']=='closed']
        return dict(deals=deals,deal_count=len(deals),trades=trades,closed_trades=len(closed),
                    winning_closed_trades=sum(t['net_realized']>0 for t in closed),
                    losing_closed_trades=sum(t['net_realized']<0 for t in closed),
                    realized_profit=sum(d.get('profit',0) for d in deals),
                    commission=sum(d.get('commission',0) for d in deals),
                    swap=sum(d.get('swap',0) for d in deals),fees=sum(d.get('fee',0) for d in deals),
                    net_realized=sum(d.get('profit',0)+d.get('commission',0)+d.get('swap',0)+d.get('fee',0) for d in deals))
    def anchors(self,account,equity):
        day=datetime.now(timezone.utc).date().isoformat()
        key=f'anchors:{account}'
        record=self.get(key)
        if not record:
            record=dict(day=day,day_equity=equity,peak_equity=equity)
        if record['day']!=day:
            record.update(day=day,day_equity=equity)
        record['peak_equity']=max(record['peak_equity'],equity)
        self.set(key,record)
        return record

import json
import sqlite3
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
    def reserve(self,key,payload):
        with self.connect() as db:
            # Any uncertain submission blocks subsequent orders until investigated.
            if db.execute("SELECT 1 FROM orders WHERE status='pending'").fetchone():
                raise ValueError('Unresolved submission exists; inspect broker history before reconciliation')
            try: db.execute('INSERT INTO orders VALUES (?,?,?)',(key,'pending',json.dumps(payload)))
            except sqlite3.IntegrityError: raise ValueError('Duplicate signal already processed') from None
    def finish(self,key,status,payload):
        with self.connect() as db:
            db.execute('UPDATE orders SET status=?,payload=? WHERE signal_id=?',(status,json.dumps(payload),key))
        self.log('order_'+status,dict(signal_id=key,**payload))
    def orders(self):
        with self.connect() as db:
            rows=db.execute('SELECT signal_id,status,payload FROM orders ORDER BY rowid DESC LIMIT 100').fetchall()
        return [dict(signal_id=k,status=s,payload=json.loads(p)) for k,s,p in rows]
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

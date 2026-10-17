"""Run on Windows with MT5 open; exports only completed broker M30 bars."""
import argparse
import csv
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.bridge import MT5Bridge
p=argparse.ArgumentParser()
p.add_argument('--symbol',default='EURUSD');p.add_argument('--count',type=int,default=50000);p.add_argument('--output',default='runtime/EURUSD-M30.csv')
a=p.parse_args()
b=MT5Bridge()
try:
    cs=b.candles(a.symbol,'M30',a.count)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    with open(a.output,'w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['time','open','high','low','close','volume']);writer.writeheader();writer.writerows(cs)
    print(f'Exported {len(cs)} completed candles to {a.output}')
finally:b.mt.shutdown()

"""Windows: export completed MT5 M30 bid history and non-secret broker specs."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.bridge import MT5Bridge
from backend.research import export_history


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--symbol',required=True,help='Exact broker symbol, e.g. EURUSDm')
    p.add_argument('--count',type=int,default=50000)
    p.add_argument('--output',required=True,help='New CSV file; matching .meta.json is created alongside it')
    a=p.parse_args();b=MT5Bridge()
    try:
        info=export_history(b,a.symbol,a.count,a.output)
        print('Exported '+str(info.get('bar_count',0))+' completed candles to '+a.output)
        print('CSV provenance and contract specifications saved in '+str(Path(a.output).with_suffix('.meta.json')))
        for issue in info.get('issues',[]): print('Needs attention: '+issue)
        print('No orders sent. Export is research input, not profitability evidence.')
    finally: b.mt.shutdown()

if __name__=='__main__': main()

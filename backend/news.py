"""Fail-closed economic-calendar gate; no fabricated provider or implicit credentials."""
import json
import math
import os
import re
from pathlib import Path

CURRENCIES={'EUR','USD','GBP','JPY','AUD','NZD','CAD','CHF','XAU','XAG','BTC','ETH'}
MAX_FEED_AGE=900


def currencies_for(symbol):
    name=re.sub('[^A-Z]','',symbol.upper())
    for base in sorted(CURRENCIES):
        if name.startswith(base) and name[3:6] in CURRENCIES:
            return {base,name[3:6]}
    return set()


def calendar_gate(document,symbol,now,buffer_minutes=30):
    def blocked(reason): return dict(allowed=False,mode='calendar',reason=reason,expires_at=0)
    if not math.isfinite(now) or not isinstance(document,dict):return blocked('Invalid calendar data')
    if not isinstance(buffer_minutes,int) or not 15<=buffer_minutes<=120:return blocked('Invalid news blackout buffer')
    pairs=currencies_for(symbol)
    if not pairs:return blocked('Cannot map symbol to calendar currencies')
    if document.get('schema_version')!=1 or not isinstance(document.get('provider'),str) or not document['provider'].strip():return blocked('Calendar provider metadata missing')
    def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    fetched=document.get('fetched_at');coverage_from=document.get('coverage_from');coverage_until=document.get('coverage_until')
    if not all(finite(x) for x in (fetched,coverage_from,coverage_until)):return blocked('Calendar timestamps unavailable')
    if not 0<=now-fetched<=MAX_FEED_AGE:return blocked('Calendar feed is stale or from the future')
    width=buffer_minutes*60
    if not coverage_from<=now-width or coverage_until<now+width:return blocked('Calendar coverage does not include the full blackout window')
    events=document.get('events')
    if not isinstance(events,list) or len(events)>10000:return blocked('Calendar event list invalid')
    for event in events:
        if not isinstance(event,dict) or not finite(event.get('time')) or event.get('currency') not in CURRENCIES or event.get('impact') not in ('low','medium','high'):
            return blocked('Malformed calendar event; entries blocked')
        if event['currency'] in pairs and event['impact']=='high' and abs(event['time']-now)<=width:
            return blocked('Relevant high-impact economic event inside blackout window')
    return dict(allowed=True,mode='calendar',reason='Fresh provider calendar covers the blackout window with no relevant high-impact event',
                expires_at=min(fetched+MAX_FEED_AGE,coverage_until-width),provider=document['provider'],buffer_minutes=buffer_minutes)


def news_clearance(store,symbol,now):
    mode=os.environ.get('NEWS_MODE','manual')
    if mode=='manual':
        expires=store.get('news_clear_until',0)
        valid=isinstance(expires,(int,float)) and math.isfinite(expires) and expires>now
        return dict(allowed=valid,mode=mode,reason='Manual calendar review clearance active' if valid else 'Manual calendar review missing or expired',expires_at=expires if valid else 0)
    if mode!='calendar':return dict(allowed=False,mode=mode,reason='Unsupported news configuration',expires_at=0)
    path=os.environ.get('NEWS_CALENDAR_PATH','')
    try:
        source=Path(path)
        if not path or source.stat().st_size>4*1024*1024:raise ValueError('Missing or oversized calendar')
        document=json.loads(source.read_text(encoding='utf-8'))
        buffer=int(os.environ.get('NEWS_BUFFER_MINUTES','30'))
        return calendar_gate(document,symbol,now,buffer)
    except (OSError,ValueError,TypeError,OverflowError):
        return dict(allowed=False,mode='calendar',reason='Calendar file missing, unreadable or invalid',expires_at=0)

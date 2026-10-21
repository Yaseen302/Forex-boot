import json
import pytest
from backend.news import calendar_gate,news_clearance
from backend.store import Store


def feed(now=100000,events=None):return dict(schema_version=1,provider='Fixture calendar only',fetched_at=now-5,coverage_from=now-7200,coverage_until=now+7200,events=[] if events is None else events)

@pytest.mark.parametrize('currency',['EUR','USD'])
def test_relevant_high_impact_event_blocks(currency):
    r=calendar_gate(feed(events=[dict(time=100100,currency=currency,impact='high')]),'EURUSDm',100000)
    assert not r['allowed']


def test_unrelated_event_does_not_block_covered_currency_pair():
    assert calendar_gate(feed(events=[dict(time=100100,currency='JPY',impact='high')]),'EURUSDm',100000)['allowed']

@pytest.mark.parametrize('change',[
 {'fetched_at':99000},{'fetched_at':100001},{'coverage_from':99999}, {'coverage_until':100010},
 {'events':[{'time':float('nan'),'currency':'EUR','impact':'high'}]}, {'events':[{'time':100005,'currency':'EUR','impact':'unknown'}]}])
def test_invalid_or_incomplete_feeds_fail_closed(change):
    d=feed();d.update(change)
    assert not calendar_gate(d,'EURUSD',100000)['allowed']


def test_calendar_mode_never_uses_manual_clearance_when_feed_missing(tmp_path,monkeypatch):
    s=Store(str(tmp_path/'test.sqlite'));s.set('news_clear_until',999999)
    monkeypatch.setenv('NEWS_MODE','calendar');monkeypatch.setenv('NEWS_CALENDAR_PATH',str(tmp_path/'missing.json'))
    assert not news_clearance(s,'EURUSD',100000)['allowed']


def test_valid_feed_expires_and_manual_mode_is_separate(tmp_path,monkeypatch):
    path=tmp_path/'news.json';path.write_text(json.dumps(feed()))
    s=Store(str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('NEWS_MODE','calendar');monkeypatch.setenv('NEWS_CALENDAR_PATH',str(path))
    assert news_clearance(s,'EURUSDm',100000)['allowed']
    assert not news_clearance(s,'EURUSDm',101000)['allowed']
    monkeypatch.setenv('NEWS_MODE','manual')
    assert not news_clearance(s,'EURUSDm',100000)['allowed']

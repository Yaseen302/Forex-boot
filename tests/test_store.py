import pytest
from backend.store import Store


def test_duplicate_and_uncertain_submission_survive_restart(tmp_path):
    s=Store(str(tmp_path/'state.sqlite'))
    s.reserve('a',{})
    s=Store(s.path)
    with pytest.raises(ValueError,match='Unresolved'):s.reserve('b',{})
    s.finish('a','filled',{'deal':123})
    with pytest.raises(ValueError,match='Duplicate'):s.reserve('a',{})
    assert s.orders()[0]['status']=='filled'
    assert s.events()[0]['kind']=='order_filled'


def test_account_isolated_high_water_mark(tmp_path):
    s=Store(str(tmp_path/'state.sqlite'))
    assert s.anchors('a',1000)['peak_equity']==1000
    assert s.anchors('a',900)['peak_equity']==1000
    assert s.anchors('b',10)['day_equity']==10


def test_emergency_persisted(tmp_path):
    s=Store(str(tmp_path/'state.sqlite'));s.set('emergency',True)
    assert Store(s.path).get('emergency') is True

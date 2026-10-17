import struct
import pytest
from fastapi.testclient import TestClient
from backend import api
from backend.store import Store

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'store',Store(str(tmp_path/'test.sqlite')))
    with TestClient(api.app) as value: yield value


def test_home_screen_manifest_and_icons_are_served_without_account_auth(client):
    r=client.get('/app.webmanifest')
    assert r.status_code==200
    assert r.headers['content-type'].startswith('application/manifest+json')
    manifest=r.json()
    assert manifest['display']=='standalone' and manifest['start_url']=='/' and manifest['scope']=='/'
    assert len(manifest['icons'])==2
    for icon in manifest['icons']:
        image=client.get(icon['src'])
        assert image.status_code==200 and image.headers['content-type']=='image/png'
        assert image.content[:8]==b'\x89PNG\r\n\x1a\n'
        width,height=struct.unpack('>II',image.content[16:24])
        assert f'{width}x{height}'==icon['sizes']


def test_icon_route_only_serves_declared_public_assets(client):
    assert client.get('/icons/favicon.svg').status_code==200
    for path in ('/icons/api-token','/icons/app.py','/icons/forex.sqlite','/icons/missing.png'):
        assert client.get(path).status_code==404

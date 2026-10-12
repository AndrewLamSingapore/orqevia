import hashlib
import json
from pathlib import Path
import re
import struct


ROOT=Path(__file__).parents[1]
PWA=ROOT/'clients'/'pwa'
EXPECTED={
    'orqevia-v1-192.png':(192,192,'2fab5940548b8c9fcf9fab9b0d73dac0465410f7002059af4fa9915fd3ab1440'),
    'orqevia-v1-512.png':(512,512,'4413a5df1e6a3758fb7c14f5a9510af47b1f40267b7c8cfb53e4ce92f09934b3'),
    'orqevia-v1-apple-touch.png':(180,180,'49fb17ee128b0857d3b903e5cff33db0d5897ab8a41bd4a626078e6039526ceb')}


def dimensions(raw):
    assert raw[:8]==b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II',raw[16:24])


def test_manifest_and_apple_install_use_one_versioned_canonical_brand():
    manifest=json.loads((PWA/'manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['name']=='ORQEVIA · 奥启维亚' and manifest['short_name']=='ORQEVIA'
    sources={Path(icon['src']).name for icon in manifest['icons']}
    assert sources=={'orqevia-v1-192.png','orqevia-v1-512.png'}
    html=(PWA/'index.html').read_text(encoding='utf-8')
    match=re.search(r'<link rel="apple-touch-icon" sizes="180x180" href="/pwa/icons/([^"]+)">',html)
    assert match and match.group(1)=='orqevia-v1-apple-touch.png'
    assert 'member' not in ' '.join(sources).lower()+match.group(1).lower()


def test_canonical_brand_assets_have_frozen_dimensions_and_hashes():
    for name,(width,height,digest) in EXPECTED.items():
        raw=(PWA/'icons'/name).read_bytes()
        assert dimensions(raw)==(width,height)
        assert hashlib.sha256(raw).hexdigest()==digest


def test_service_worker_caches_only_the_versioned_canonical_install_assets():
    source=(PWA/'sw.js').read_text(encoding='utf-8')
    for name in EXPECTED:assert f"'/pwa/icons/{name}'" in source
    assert "'/pwa/icons/icon-192.png'" not in source
    assert "'/pwa/icons/icon-512.png'" not in source
    assert "'/pwa/icons/apple-touch-icon.png'" not in source


import hashlib
import json
from pathlib import Path
import re
import struct


ROOT=Path(__file__).parents[1]
PWA=ROOT/'clients'/'pwa'
HISTORICAL_UNAPPROVED_GENERATED={
    'orqevia-v1-192.png':(192,192,'fb87a1b2a6ae1ea560adec43a0c177aa732a9f84f0774c6a491cc3b5e299d7aa'),
    'orqevia-v1-512.png':(512,512,'24447534ee9188c3c265a42deb409f3f84c0efaec34fd194f5be78d1b9e9cac1'),
    'orqevia-v1-apple-touch.png':(180,180,'8f73c754888be3f8216b03d2f0b72bea9c1da48c7cb106855d7c5f065fe9e3c2')}


def dimensions(raw):
    assert raw[:8]==b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II',raw[16:24])


def test_manifest_and_apple_install_use_one_versioned_canonical_brand():
    manifest=json.loads((PWA/'manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['name']=='ORQEVIA' and manifest['short_name']=='ORQEVIA'
    sources={Path(icon['src']).name for icon in manifest['icons']}
    assert sources=={'orqevia-official-v1-192.png','orqevia-official-v1-512.png'}
    html=(PWA/'index.html').read_text(encoding='utf-8')
    match=re.search(r'<link rel="apple-touch-icon" sizes="180x180" href="/pwa/icons/([^"]+)">',html)
    assert match and match.group(1)=='orqevia-official-v1-apple-touch.png'
    assert 'member' not in ' '.join(sources).lower()+match.group(1).lower()


def test_historical_unapproved_generated_assets_retain_original_bytes():
    for name,(width,height,digest) in HISTORICAL_UNAPPROVED_GENERATED.items():
        raw=(PWA/'icons'/name).read_bytes()
        assert dimensions(raw)==(width,height)
        assert hashlib.sha256(raw).hexdigest()==digest


def test_service_worker_caches_only_the_versioned_canonical_install_assets():
    source=(PWA/'sw.js').read_text(encoding='utf-8')
    for name in HISTORICAL_UNAPPROVED_GENERATED:assert f"'/pwa/icons/{name}'" not in source
    for name in ['orqevia-official-v1-192.png','orqevia-official-v1-512.png','orqevia-official-v1-apple-touch.png']:
        assert f"'/pwa/icons/{name}'" in source
    assert "'/pwa/icons/icon-192.png'" not in source
    assert "'/pwa/icons/icon-512.png'" not in source
    assert "'/pwa/icons/apple-touch-icon.png'" not in source

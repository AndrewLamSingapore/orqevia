import hashlib
import json
from pathlib import Path
import re
import struct


ROOT=Path(__file__).parents[1]
PWA=ROOT/'clients'/'pwa'
EXPECTED={
    'jarvis-prime-v1-192.png':(192,192,'06e6b61d8fc70b7c11b7d24e34eae6e75e0809a98a5f4bf3d7b5fc4740693aa5'),
    'jarvis-prime-v1-512.png':(512,512,'4c1bd41fbf6636e3f16174a251c528c691266f6e774274680c14d5f7000dc147'),
    'jarvis-prime-v1-apple-touch.png':(180,180,'43f89fdec3bafe3c4f1766308038e38d471b4caacf1dab3b4f33f62caab73ecf')}


def dimensions(raw):
    assert raw[:8]==b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II',raw[16:24])


def test_manifest_and_apple_install_use_one_versioned_canonical_brand():
    manifest=json.loads((PWA/'manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['name']=='JARVIS PRIME' and manifest['short_name']=='JARVIS'
    sources={Path(icon['src']).name for icon in manifest['icons']}
    assert sources=={'jarvis-prime-v1-192.png','jarvis-prime-v1-512.png'}
    html=(PWA/'index.html').read_text(encoding='utf-8')
    match=re.search(r'<link rel="apple-touch-icon" sizes="180x180" href="/pwa/icons/([^"]+)">',html)
    assert match and match.group(1)=='jarvis-prime-v1-apple-touch.png'
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

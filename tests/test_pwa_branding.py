import hashlib
import json
from pathlib import Path
import re
import struct


ROOT=Path(__file__).parents[1]
PWA=ROOT/'clients'/'pwa'
# ORQEVIA command icon v1 (install identity) + the official ORQEVIA logo that
# remains the in-app brand mark. The legacy JARVIS "J" bytes are gone; these
# pins reject any reappearance of the old glyph or the old file names.
EXPECTED={
    'orqevia-command-v1-192.png':(192,192,'b1bdebb730bfd692714cf3dffc9a9b0eb4db725ba86275705818b8e81957e41b'),
    'orqevia-command-v1-512.png':(512,512,'970a8f6ea3f9e3e663221e5f0e370c8104dc80b9c5b9ba8dabd14ad1c910b138'),
    'orqevia-command-v1-apple-touch.png':(180,180,'82a089c92999b9a0b171b2bf1198407d0de713af556f01be12b8d46eaf931d93')}
OFFICIAL_LOGO=('orqevia-official-v1-192.png',192,192,
               'd7cc5c2c6c63bf87a4afdad5b3cf0fa058444bb16d498ecaaa81e789d0fdeea2')
LEGACY_J_SHA256='06e6b61d8fc70b7c11b7d24e34eae6e75e0809a98a5f4bf3d7b5fc4740693aa5'


def dimensions(raw):
    assert raw[:8]==b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II',raw[16:24])


def test_manifest_and_apple_install_use_one_versioned_canonical_brand():
    manifest=json.loads((PWA/'manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['name']=='ORQEVIA' and manifest['short_name']=='ORQEVIA'
    sources={Path(icon['src']).name for icon in manifest['icons']}
    assert sources=={'orqevia-command-v1-192.png','orqevia-command-v1-512.png','orqevia-command-v1-maskable-512.png'}
    purposes={Path(icon['src']).name:icon['purpose'] for icon in manifest['icons']}
    assert purposes['orqevia-command-v1-maskable-512.png']=='maskable'
    html=(PWA/'index.html').read_text(encoding='utf-8')
    match=re.search(r'<link rel="apple-touch-icon" sizes="180x180" href="/pwa/icons/([^"]+)">',html)
    assert match and match.group(1)=='orqevia-command-v1-apple-touch.png'
    assert '/pwa/icons/favicon.ico' in html
    assert 'member' not in ' '.join(sources).lower()+match.group(1).lower()


def test_canonical_brand_assets_have_frozen_dimensions_and_hashes():
    for name,(width,height,digest) in EXPECTED.items():
        raw=(PWA/'icons'/name).read_bytes()
        assert dimensions(raw)==(width,height)
        assert hashlib.sha256(raw).hexdigest()==digest
    logo_name,width,height,digest=OFFICIAL_LOGO
    raw=(PWA/'icons'/logo_name).read_bytes()
    assert dimensions(raw)==(width,height)
    assert hashlib.sha256(raw).hexdigest()==digest


def test_legacy_jarvis_glyph_and_file_names_are_absent():
    icons=PWA/'icons'
    names={path.name for path in icons.iterdir()}
    assert not any(name.startswith('jarvis') for name in names)
    for legacy in ('orqevia-official-v1-512.png','orqevia-official-v1-apple-touch.png',
                   'orqevia-official-v1-favicon-16.png','orqevia-official-v1-favicon-32.png',
                   'orqevia-official-v1-favicon-48.png','icon-192.png','icon-512.png','apple-touch-icon.png'):
        assert legacy not in names
    # The historical JARVIS "J" bytes must not reappear under any name.
    for path in icons.glob('*.png'):
        assert hashlib.sha256(path.read_bytes()).hexdigest()!=LEGACY_J_SHA256, path.name


def test_service_worker_caches_only_the_versioned_canonical_install_assets():
    source=(PWA/'sw.js').read_text(encoding='utf-8')
    for name in EXPECTED:assert f"'/pwa/icons/{name}'" in source
    assert "'/pwa/icons/orqevia-official-v1-192.png'" in source
    assert "'/pwa/icons/icon-192.png'" not in source
    assert "'/pwa/icons/icon-512.png'" not in source
    assert "'/pwa/icons/apple-touch-icon.png'" not in source

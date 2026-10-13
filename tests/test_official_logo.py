"""Authentic logo custody, public references and unchanged local authorization."""
import ast
import hashlib
import json
from pathlib import Path
import struct

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.brand_assets import OFFICIAL_LOGO_FILES, official_logo_response

ROOT=Path(__file__).resolve().parents[1]
PWA=ROOT/'clients/pwa'
MASTER_SHA='b3bdd53cc38b24c8be2896f1174b4d5f083be20f94f2042770224c72e2501844'
DERIVED={
 'orqevia-official-v1-192.png':(192,'d7cc5c2c6c63bf87a4afdad5b3cf0fa058444bb16d498ecaaa81e789d0fdeea2'),
 'orqevia-official-v1-512.png':(512,'c018857c354a1cede7c514ff67904dd5057e9b3e8b7eef56a63fe46f094dce39'),
 'orqevia-official-v1-apple-touch.png':(180,'5984607eaf2ada7f0e71fa12d15ab765dc02df4de1d109e6148394a39c961968'),
 'orqevia-official-v1-favicon-16.png':(16,'d7fc6ad0c78ecf3d6bbaf8541cdd83e6423537c665d9e737fe9eb1050e74b858'),
 'orqevia-official-v1-favicon-32.png':(32,'f87af1da54659558e230ba5c9a02368584652cf6f2101f4c5a40738121c47d6f'),
 'orqevia-official-v1-favicon-48.png':(48,'67955faf73806db945bf41ed253b420c980f44c0af02d937d1d786fd2ebbe28c'),
}


def test_owner_original_and_derivative_custody_are_exact():
    original=(ROOT/'assets/brands/orqevia/generated-original.png').read_bytes()
    assert hashlib.sha256(original).hexdigest()==MASTER_SHA
    assert struct.unpack('>II',original[16:24])==(1254,1254)
    assert original[25]==2  # Original RGB, with an opaque background.
    manifest=json.loads((ROOT/'assets/brands/orqevia/provenance.json').read_text())
    assert manifest['original']['sha256']==MASTER_SHA
    assert manifest['derivation']['method']=='FULL_IMAGE_RESIZE_LANCZOS'
    assert manifest['derivation']['color_mode']=='original RGB'
    assert manifest['derivation']['pillow_version']=='12.3.0'
    assert not any(manifest['derivation'][key] for key in ('crop','recolor','redraw','maskable_claim'))
    assert set(OFFICIAL_LOGO_FILES)==set(DERIVED)
    for item in manifest['derivatives']:
        name=Path(item['path']).name;size,digest=DERIVED[name]
        raw=(ROOT/item['path']).read_bytes()
        assert raw[:8]==b'\x89PNG\r\n\x1a\n' and raw[25]==2
        assert struct.unpack('>II',raw[16:24])==(size,size)
        assert hashlib.sha256(raw).hexdigest()==item['sha256']==digest
        assert item['purpose']=='any' and len(raw)==item['bytes']


def test_every_current_logo_context_uses_approved_full_image_without_clipping():
    from html.parser import HTMLParser
    class Images(HTMLParser):
        def __init__(self):super().__init__();self.images=[]
        def handle_starttag(self,tag,attrs):
            if tag=='img':self.images.append(dict(attrs))
    parser=Images();parser.feed((PWA/'index.html').read_text(encoding='utf-8'))
    assert len(parser.images)>=10
    for image in parser.images:
        assert Path(image['src']).name in DERIVED
        assert image['alt']=='ORQEVIA · 奥启维亚'
        assert 'official-logo' in image['class']
    css=(PWA/'style.css').read_text()+(PWA/'dashboard.css').read_text()
    assert 'object-fit:contain' in css and '.brand img{object-fit:contain;border-radius:0}' in css
    for name in ('production_control.html','control_surface.html'):
        parser=Images();parser.feed((ROOT/'app'/name).read_text(encoding='utf-8'))
        assert parser.images and all(Path(image['src']).name in DERIVED for image in parser.images)
        assert all(image['alt']=='ORQEVIA · 奥启维亚' for image in parser.images)


def test_manifest_and_favicon_refs_never_claim_maskable_or_a_reconstructed_svg():
    manifest=json.loads((PWA/'manifest.webmanifest').read_text(encoding='utf-8'))
    assert [manifest['id'],manifest['scope'],manifest['start_url']]==['/pwa/']*3
    assert {Path(item['src']).name for item in manifest['icons']}=={'orqevia-official-v1-192.png','orqevia-official-v1-512.png'}
    assert all(item['purpose']=='any' for item in manifest['icons'])
    html=(PWA/'index.html').read_text(encoding='utf-8')
    assert 'orqevia-v1-' not in html and 'icon.svg' not in html
    for size in (16,32,48):assert 'orqevia-official-v1-favicon-'+str(size)+'.png' in html
    sw=(PWA/'sw.js').read_text()
    for name in DERIVED:assert "'/pwa/icons/"+name+"'" in sw
    assert 'orqevia-v1-' not in sw and "'/pwa/icons/icon.svg'" not in sw
    assert 'orqevia-shell-v20' in sw and 'orqevia-shell-v20' in (PWA/'release.mjs').read_text()


@pytest.mark.parametrize('name',('../generated-original.png','icon.svg','orqevia-v1-192.png','unknown.png'))
def test_logo_delivery_rejects_unapproved_or_traversal_names(name):
    with pytest.raises(HTTPException) as error:official_logo_response(name)
    assert error.value.status_code==404


def test_production_logo_http_keeps_existing_local_authorization(monkeypatch,tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path));monkeypatch.setenv('PRIME_SPINE_TOKEN','fixture-logo-owner')
    from app.production_entry import app
    client=TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',54321))
    path='/control/brand/orqevia-official-v1-192.png'
    response=client.get(path)
    assert response.status_code==200 and response.content==(PWA/'icons/orqevia-official-v1-192.png').read_bytes()
    assert response.headers['content-type']=='image/png' and response.headers['cache-control']=='no-store'
    assert response.headers['x-content-type-options']=='nosniff'
    assert client.get(path,headers={'Host':'untrusted.invalid'}).status_code==403
    monkeypatch.delenv('PRIME_SPINE_TOKEN')
    assert client.get(path).status_code==503


def test_legacy_original_generator_cannot_redraw_a_logo_and_HTML_keeps_product_contract():
    retired=(PWA/'make-icons.mjs').read_text()
    assert 'process.exitCode=1' in retired and 'build_official_logo_icons.py' in retired
    assert 'function pixel' not in retired and 'deflateSync' not in retired
    tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
    node=next(node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HTML' for t in node.targets))
    literal=next(item.value for item in ast.walk(node.value) if isinstance(item,ast.Constant) and isinstance(item.value,str) and item.value.startswith('<!doctype html>'))
    assert '/brand/icons/orqevia-official-v1-' in literal

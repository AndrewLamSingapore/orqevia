import hashlib
import json
from pathlib import Path
import re
import struct
from xml.etree import ElementTree


ROOT = Path(__file__).parents[1]
PWA = ROOT / "clients" / "pwa"
# The official in-app logo and the geometric navigation/install mark have
# separate established roles. Preserve the exact verified brand bytes.
EXPECTED = {
    "orqevia-command-v2-192.png": (192, 192, "2ea1605b2060a3a94cc705bbc2497e4fb444b56d6ffbf823a4062c1b3c30d74e"),
    "orqevia-command-v2-512.png": (512, 512, "eaee6b80d4adfe6ddb9ac0d772cb356df06e3d3030b2bf663a28bef77bdac750"),
    "orqevia-command-v2-apple-touch.png": (
        180,
        180,
        "45fb239da1aa66401c1e60420af816b1d56d3175c508da3f9c64d2248c25c693",
    ),
    "orqevia-command-v2-maskable-512.png": (
        512,
        512,
        "6fc00dbf7235e21d0707ab1fdbd06915fe2680165ec3cff5d3295c27878bde04",
    ),
    "orqevia-command-v2-favicon-16.png": (16, 16, "1affc35edd5b7a3fd71164ed81a19811c076a8196611aec52845d18b28706fb0"),
    "orqevia-command-v2-favicon-32.png": (32, 32, "8988a019f52413bf9f618b68a2101f3cfa818035c168890eb2b824800dcf9970"),
    "orqevia-command-v2-favicon-48.png": (48, 48, "bbdc2a9c6497309de2916dcfceffbc18fb2bbba8d087df94ab3038682768605a"),
}
CANONICAL_MARK = ("orqevia-mark.svg", "dab0c88fa6583b1816e8aae986880ef2a4b3d4e2a650ccfd3b590c81da120794")
OFFICIAL_LOGO = ("orqevia-official-v1-192.png", "d7cc5c2c6c63bf87a4afdad5b3cf0fa058444bb16d498ecaaa81e789d0fdeea2")
OFFICIAL_MASTER = ("orqevia-official-v1-master.png", "b3bdd53cc38b24c8be2896f1174b4d5f083be20f94f2042770224c72e2501844")
LEGACY_J_SHA256 = "06e6b61d8fc70b7c11b7d24e34eae6e75e0809a98a5f4bf3d7b5fc4740693aa5"


def dimensions(raw):
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", raw[16:24])


def test_manifest_and_apple_install_use_one_versioned_canonical_brand():
    manifest = json.loads((PWA / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "ORQEVIA" and manifest["short_name"] == "ORQEVIA"
    sources = {Path(icon["src"]).name for icon in manifest["icons"]}
    assert sources == {
        "orqevia-command-v2-192.png",
        "orqevia-command-v2-512.png",
        "orqevia-command-v2-maskable-512.png",
    }
    assert len(manifest["icons"]) == len(sources)
    purposes = {Path(icon["src"]).name: icon["purpose"] for icon in manifest["icons"]}
    assert purposes["orqevia-command-v2-maskable-512.png"] == "maskable"
    html = (PWA / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<link rel="apple-touch-icon" sizes="180x180" href="/pwa/icons/([^"]+)">', html)
    assert match and match.group(1) == "orqevia-command-v2-apple-touch.png"
    assert 'href="/pwa/icons/orqevia-mark.svg" type="image/svg+xml"' in html
    assert 'src="/pwa/icons/orqevia-mark.svg"' in html
    assert "orqevia-command-v1-" not in html
    assert "member" not in " ".join(sources).lower() + match.group(1).lower()


def test_canonical_brand_assets_have_frozen_dimensions_and_hashes():
    for name, (width, height, digest) in EXPECTED.items():
        raw = (PWA / "icons" / name).read_bytes()
        assert dimensions(raw) == (width, height)
        assert hashlib.sha256(raw).hexdigest() == digest
    logo_name, digest = CANONICAL_MARK
    raw = (PWA / "icons" / logo_name).read_bytes()
    assert ElementTree.fromstring(raw).attrib["viewBox"] == "0 0 120 120"
    assert hashlib.sha256(raw).hexdigest() == digest


def test_official_logo_is_prominent_without_replacing_install_identity():
    name, digest = OFFICIAL_LOGO
    raw = (PWA / "icons" / name).read_bytes()
    assert dimensions(raw) == (192, 192)
    assert hashlib.sha256(raw).hexdigest() == digest
    master_name, master_digest = OFFICIAL_MASTER
    master = (PWA / "icons" / master_name).read_bytes()
    assert dimensions(master) == (1254, 1254)
    assert len(master) == 1531581 and hashlib.sha256(master).hexdigest() == master_digest
    assert master == (ROOT / "app/orqevia/static/assets/orqevia/generated-original.png").read_bytes()
    html = (PWA / "index.html").read_text(encoding="utf-8")
    hero = re.search(r'<div class="command-banner">(.*?)</div>', html).group(1)
    image = re.search(r'<img\b([^>]+)>', hero)
    assert image and f'src="/pwa/icons/{name}"' in image.group(1)
    assert 'width="132"' in image.group(1) and 'height="132"' in image.group(1)
    assert 'alt="ORQEVIA official logo"' in image.group(1)
    assert f'srcset="/pwa/icons/{name} 192w, /pwa/icons/{master_name} 1254w"' in image.group(1)
    assert 'sizes="(max-width: 639px) 108px, 132px"' in image.group(1)
    assert hero.index("<img") < hero.index("<h1>Command Center</h1>")
    css = (PWA / "style.css").read_text(encoding="utf-8-sig")
    image_rule = re.search(r"\.command-banner img\s*\{([^}]+)\}", css).group(1)
    assert "object-fit: contain" in image_rule and "aspect-ratio: 1" in image_rule
    assert 'src="/pwa/icons/orqevia-mark.svg"' in html


def test_legacy_jarvis_glyph_and_file_names_are_absent():
    icons = PWA / "icons"
    names = {path.name for path in icons.iterdir()}
    assert not any(name.startswith("jarvis") for name in names)
    for legacy in (
        "orqevia-official-v1-512.png",
        "orqevia-official-v1-apple-touch.png",
        "orqevia-official-v1-favicon-16.png",
        "orqevia-official-v1-favicon-32.png",
        "orqevia-official-v1-favicon-48.png",
        "icon-192.png",
        "icon-512.png",
        "apple-touch-icon.png",
    ):
        assert legacy not in names
    # The historical JARVIS "J" bytes must not reappear under any name.
    for path in icons.glob("*.png"):
        assert hashlib.sha256(path.read_bytes()).hexdigest() != LEGACY_J_SHA256, path.name


def test_service_worker_caches_only_the_versioned_canonical_install_assets():
    source = (PWA / "sw.js").read_text(encoding="utf-8")
    match = re.search(r"const SHELL=(\[[^;]+\]);", source)
    assert match
    assets = json.loads(match.group(1).replace("'", '"'))
    cached_icons = {asset for asset in assets if asset.startswith("/pwa/icons/")}
    expected_icons = {f"/pwa/icons/{name}" for name in EXPECTED} | {
        f"/pwa/icons/{CANONICAL_MARK[0]}", f"/pwa/icons/{OFFICIAL_LOGO[0]}", f"/pwa/icons/{OFFICIAL_MASTER[0]}"
    }
    assert cached_icons == expected_icons
    assert len(assets) == len(set(assets))

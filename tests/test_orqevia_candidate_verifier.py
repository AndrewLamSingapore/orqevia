import importlib.util
from pathlib import Path
import shutil


def verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_orqevia_candidate.py"
    spec = importlib.util.spec_from_file_location("verify_orqevia_candidate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_independent_orqevia_candidate_verifier():
    module = verifier()
    result = module.verify()
    assert result["passed"] == result["total"] == 7
    assert result["production_touched"] is False
    assert result["physical_phone_tested"] is False


def test_brand_verifier_rejects_wrong_identity_and_replaced_logo_bytes(tmp_path):
    module = verifier()
    source = Path(__file__).resolve().parents[1] / "clients" / "pwa"
    shutil.copytree(source / "icons", tmp_path / "icons")
    for name in ("manifest.webmanifest", "index.html"):
        shutil.copyfile(source / name, tmp_path / name)
    assert module.canonical_branding(tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    for invalid in (
        html.replace('src="/pwa/icons/orqevia-official-v1-192.png"', 'src="/pwa/icons/orqevia-command-v2-192.png"'),
        html.replace('src="/pwa/icons/orqevia-mark.svg"', 'src="/pwa/icons/orqevia-official-v1-192.png"'),
        html.replace('orqevia-official-v1-master.png 1254w', 'orqevia-command-v2-512.png 512w'),
    ):
        (tmp_path / "index.html").write_text(invalid, encoding="utf-8")
        assert not module.canonical_branding(tmp_path)
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    master = tmp_path / "icons" / "orqevia-official-v1-master.png"
    master.write_bytes((tmp_path / "icons" / "orqevia-command-v2-512.png").read_bytes())
    assert not module.canonical_branding(tmp_path)

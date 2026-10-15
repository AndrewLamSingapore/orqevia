import hashlib,json,runpy,sys
from pathlib import Path
import pytest

def test_diagnostic_install_preserves_originals_and_rejects_unknown_changes(tmp_path,monkeypatch):
    root=tmp_path/'local';saved=tmp_path/'preserved';root.mkdir();saved.mkdir()
    paths=['orqevia_interface.py','scripts/orqevia_rag_v3.py','scripts/ingest.py','scripts/rag.py']
    records=[]
    for name in paths:
        raw=('original '+name).encode()
        for base in [root,saved]:
            target=base/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        records.append({'file':name,'sha256':hashlib.sha256(raw).hexdigest()})
    (saved/'PRESERVATION.json').write_text(json.dumps({'files':records}))
    installer=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/install_local_diagnostics.py'))['main']
    monkeypatch.setattr(sys,'argv',['installer','--root',str(root),'--preserved',str(saved)])
    installer();receipt=json.loads((root/'operations/diagnostic-consolidation.json').read_text())
    assert len(receipt['files'])==6
    for r in records:assert hashlib.sha256((saved/r['file']).read_bytes()).hexdigest()==r['sha256']
    installer() # Same accepted release is idempotent.
    changed=root/'scripts/rag.py';changed.write_text('unpreserved local edit')
    with pytest.raises(RuntimeError,match='Unpreserved local change'):installer()
    assert changed.read_text()=='unpreserved local edit'

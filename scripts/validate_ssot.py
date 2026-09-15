"""Offline canonical manifest, registry, schema and secret-pattern checks."""
import hashlib,json,re,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def validate():
    from check_canonical_state import main as check_current
    check_current()
    manifest=json.loads((ROOT/'system.manifest.json').read_text())
    for item in manifest['components'].values():
        path=(ROOT/item['path']).resolve()
        assert path.is_relative_to(ROOT)
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
    registry=json.loads((ROOT/'config/agent_registry.json').read_text())
    assert len(registry['agents'])==21
    assert len({a['agent_id'] for a in registry['agents']})==21
    files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
    findings=[]
    for name in sorted(set(files)):
        path=ROOT/name
        if not path.is_file():continue
        raw=path.read_bytes()
        if path.suffix=='.py':compile(raw,str(path),'exec')
        if path.suffix=='.json':json.loads(raw)
        # Report paths only: never print matched secret material.
        patterns=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{32}',rb'sk-[A-Za-z0-9_-]{40,}',rb'gh[pousr]_[A-Za-z0-9]{30,}']
        if any(re.search(p,raw) for p in patterns):findings.append(name)
    assert not findings,{'suspected_secret_paths':findings}
    for name in ('contracts/task-v1.schema.json','contracts/artifact-v1.schema.json','config/agent_registry_v1.schema.json'):
        schema=json.loads((ROOT/name).read_text())
        assert schema['$schema']=='https://json-schema.org/draft/2020-12/schema'
        assert schema['type']=='object' and isinstance(schema['properties'],dict)
        assert isinstance(schema.get('required',[]),list)
    return {'status':'PASS','files_checked':len(set(files)),'registry_agents':21,'schema_check':'JSON parsing and top-level contract invariants; not a full metaschema validator','secret_pattern_findings':0,'secret_scan_scope':'Private-key blocks and known provider/Git token patterns; human diff review still required'}
if __name__=='__main__':print(json.dumps(validate()))

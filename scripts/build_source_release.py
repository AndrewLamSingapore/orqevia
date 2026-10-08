"""Build a new source-only runtime directory; never deploy or overwrite."""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path
from validate_canonical import ROOT,validate

def build(output):
    validate()
    output=Path(output).resolve()
    if output.exists() or output.is_relative_to(ROOT):raise ValueError('New external output directory required')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    output.mkdir(parents=True)
    files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
    for name in sorted(set(files)):
        source=ROOT/name
        if not source.is_file():continue
        if name.startswith(('app/','config/','contracts/','docs/','deploy/')) or name in {'requirements.txt','system.manifest.json'}:
            target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if name.startswith('clients/pwa/') and source.name not in {'tests.mjs','followup-tests.mjs','revision-tests.mjs','product-tests.mjs','make-icons.mjs','README.md'}:
            target=output/'app/pwa_static'/source.relative_to(ROOT/'clients/pwa');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    rows=[{'path':p.relative_to(output).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(output.rglob('*')) if p.is_file()]
    (output/'SOURCE_MANIFEST.json').write_text(json.dumps(rows,indent=2)+'\n')
    receipt={'source_revision':revision,'source_dirty':dirty,'deployment_eligible':not dirty,'architecture_version':'JARVIS PRIME Architecture v1','manifest_sha256':hashlib.sha256((output/'SOURCE_MANIFEST.json').read_bytes()).hexdigest(),'files':len(rows)}
    (output/'BUILD_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);print(json.dumps(build(parser.parse_args().output)))

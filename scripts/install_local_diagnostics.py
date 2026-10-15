"""Reversible consolidation of the preserved local prototype's entry points."""
import argparse,datetime,hashlib,json,pathlib,shutil
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--preserved',required=True);args=p.parse_args()
    root=pathlib.Path(args.root).resolve();preserved=pathlib.Path(args.preserved).resolve()
    manifest=json.loads((preserved/'PRESERVATION.json').read_text(encoding='utf8'))
    old={entry['file']:entry['sha256'] for entry in manifest['files']}
    source=pathlib.Path(__file__).resolve().parents[1]/'clients/local_ai'
    targets={'orqevia_interface.py':'orqevia_interface.py','scripts/orqevia_rag_v3.py':'orqevia_rag_v3.py','scripts/ingest.py':'ingest.py','scripts/rag.py':'rag.py','shared_client.py':'shared_client.py','scripts/shared_client.py':'shared_client.py'}
    for relative,name in targets.items():
        current=root/relative
        if current.exists() and digest(current)!=digest(source/name):
            if relative not in old or digest(current)!=old[relative] or digest(preserved/relative)!=old[relative]:raise RuntimeError('Unpreserved local change: '+relative)
    rows=[]
    for relative,name in targets.items():
        target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,target)
        assert digest(target)==digest(source/name)
        rows.append({'path':relative,'new_sha256':digest(target),'preserved_sha256':old.get(relative)})
    receipt={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'primary':'https://192.168.1.23:8443/pwa/','state':'SHARED_SERVICE_DIAGNOSTIC_CLIENTS','files':rows,'rollback':'Restore the four original entry-point files from the verified preservation directory. Existing V1/V2 index files are never modified by this installer.'}
    (root/'operations').mkdir(exist_ok=True)
    (root/'operations/diagnostic-consolidation.json').write_text(json.dumps(receipt,indent=2),encoding='utf8');print(json.dumps(receipt))
if __name__=='__main__':main()

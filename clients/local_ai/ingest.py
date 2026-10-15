"""Shared-service ingestion; original V2 ingestion source remains in custody."""
import argparse,json,sys
from pathlib import Path
from shared_client import SharedKnowledgeClient
def main():
    parser=argparse.ArgumentParser(description='Ingest specified documents through the existing shared ORQEVIA pipeline')
    parser.add_argument('files',nargs='*');parser.add_argument('--reindex',action='store_true');args=parser.parse_args()
    if not args.files and not args.reindex:parser.error('Specify documents, or --reindex. No directory is overwritten implicitly.')
    try:
        client=SharedKnowledgeClient()
        for name in args.files:print(json.dumps({'file':Path(name).name,'result':client.call('ingest',file=name)},ensure_ascii=True))
        if args.reindex:print(json.dumps(client.call('reindex',{})))
    except Exception:sys.exit('Shared ingestion unavailable or rejected; previous index generations preserved')
if __name__=='__main__':main()

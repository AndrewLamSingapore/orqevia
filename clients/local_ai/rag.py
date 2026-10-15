"""Preserved V1 command syntax, consolidated onto the shared V2/V3 service."""
import argparse,json,sys
from shared_client import SharedKnowledgeClient
def main():
    parser=argparse.ArgumentParser(description='Shared ORQEVIA index diagnostics; no independent V1 index writes')
    parser.add_argument('command',choices=['build','search']);parser.add_argument('question',nargs='?');args=parser.parse_args()
    if args.command=='search' and not args.question:parser.error('Search requires a question')
    try:result=SharedKnowledgeClient().call('reindex',{}) if args.command=='build' else SharedKnowledgeClient().call('retrieve',{'question':args.question})
    except Exception:sys.exit('Shared retrieval service unavailable or rejected; original V1 index preserved')
    print(json.dumps(result,indent=2,ensure_ascii=False))
if __name__=='__main__':main()

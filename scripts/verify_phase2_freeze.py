#!/usr/bin/env python3
"""Verify Phase 2 freeze receipt against immutable Git bytes."""
from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RECEIPT=ROOT/'docs/evidence/PHASE2_CANDIDATE_FREEZE_RECEIPT_20260926.json'

def git_bytes(rev,path):
    return subprocess.run(['git','show',f'{rev}:{path}'],cwd=ROOT,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout

def validate(value):
    errors=[]; source=value['source']; commit=source['commit']
    def need(ok,msg):
        if not ok: errors.append(msg)
    need(value['state'] in {'FROZEN_CANDIDATE_NOT_PRODUCTION','FROZEN_CANDIDATE_PENDING_INDEPENDENT_VERIFICATION'},'state')
    need(subprocess.run(['git','rev-parse',source['tag']+'^{}'],cwd=ROOT,check=True,text=True,stdout=subprocess.PIPE).stdout.strip()==commit,'tag_commit')
    need(subprocess.run(['git','rev-parse',commit+'^{tree}'],cwd=ROOT,check=True,text=True,stdout=subprocess.PIPE).stdout.strip()==source['tree'],'tree')
    for path,expected in value['bindings'].items():
        need(hashlib.sha256(git_bytes(commit,path)).hexdigest()==expected,'digest:'+path)
    need(value['qualification']['unresolved_p0']==0 and value['qualification']['unresolved_p2']==0,'defects')
    if value.get('independent_verification',{}).get('verdict')=='FAIL':
        need(value['qualification']['unresolved_p1']>0,'failed_verification_must_block')
        need(value['independent_verification']['image_build_allowed'] is False and value['independent_verification']['promotion_allowed'] is False,'failed_verification_boundary')
    need(value['authority']['candidate_grants_production_authority'] is False,'self_promotion')
    need(value['production']['modified'] is False and value['production']['deployment']=='NOT_PERFORMED','production_boundary')
    return sorted(set(errors))

if __name__=='__main__':
    receipt=Path(sys.argv[1]) if len(sys.argv)>1 else RECEIPT
    value=json.loads(receipt.read_text(encoding='utf-8')); errors=validate(value)
    print(json.dumps({'freeze_id':value['freeze_id'],'verdict':'PASS' if not errors else 'FAIL','violations':errors},sort_keys=True))
    raise SystemExit(bool(errors))

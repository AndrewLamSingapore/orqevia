#!/usr/bin/env python3
"""Materialize only authentic hash-matched Git objects from retrieved GitHub JSON.
Does not modify candidate source content. No network, credentials, or fabricated refs.
"""
from __future__ import annotations
import argparse,base64,datetime,hashlib,itertools,json,subprocess,time
from pathlib import Path

def git(repo,*args,data=None,check=True):
 return subprocess.run(['git','-C',str(repo),*args],input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=check)

def oid(kind,raw):return hashlib.sha1(f'{kind} {len(raw)}\0'.encode()+raw).hexdigest()

def write(repo,kind,raw,expected):
 actual=oid(kind,raw)
 if actual!=expected:raise ValueError(f'{kind} digest mismatch {expected} != {actual}')
 out=git(repo,'hash-object','-w','-t',kind,'--stdin',data=raw).stdout.decode().strip()
 if out!=expected:raise ValueError('Git/object digest disagreement')
 return expected

def offsets():
 priority=['+0800','-0700','+0000','-0800']
 values=[]
 for minute in range(-14*60,14*60+1,15):
  s='-' if minute<0 else '+';a=abs(minute);values.append(f'{s}{a//60:02}{a%60:02}')
 return list(dict.fromkeys(priority+values))

def person(value,tz):
 stamp=int(datetime.datetime.fromisoformat(value['date'].replace('Z','+00:00')).timestamp())
 return f"{value['name']} <{value['email']}> {stamp} {tz}"

def commit_bytes(value,expected):
 v=value.get('commit',value);parents=value.get('parents',v.get('parents',[]));verification=v.get('verification',{})
 payload=verification.get('payload');signature=verification.get('signature')
 if payload and signature:
  head,body=payload.split('\n\n',1)
  for sig in [signature.rstrip('\n'),signature]:
   header='gpgsig '+sig.replace('\n','\n ')
   for raw in [(head+'\n'+header+'\n\n'+body).encode(),(head+'\n'+header+'\n\n'+body+'\n').encode()]:
    if oid('commit',raw)==expected:return raw
  raise ValueError('Signed commit exact reconstruction failed')
 head='tree '+v['tree']['sha']+'\n'+''.join('parent '+p['sha']+'\n' for p in parents)
 message=v['message'];tails=list(dict.fromkeys([message,message+'\n',message.rstrip('\n')+'\n']))
 zones=offsets();pairs=[(z,z) for z in zones]+[(a,c) for a in zones for c in zones if a!=c]
 for a,c in pairs:
  prefix=head+'author '+person(v['author'],a)+'\ncommitter '+person(v['committer'],c)+'\n\n'
  for tail in tails:
   raw=(prefix+tail).encode()
   if oid('commit',raw)==expected:return raw
 raise ValueError('Unsigned commit exact reconstruction failed')

def tag_bytes(v):
 prefix=f"object {v['object']['sha']}\ntype {v['object']['type']}\ntag {v['tag']}\ntagger "
 for z in offsets():
  for msg in dict.fromkeys([v['message'],v['message']+'\n',v['message'].rstrip('\n')+'\n']):
   raw=(prefix+person(v['tagger'],z)+'\n\n'+msg).encode()
   if oid('tag',raw)==v['sha']:return raw
 raise ValueError('Tag exact reconstruction failed')

def import_tree(repo,value):
 if value.get('truncated'):raise ValueError('Refuse truncated recursive tree')
 entries=value['tree'];groups={'':[]};expected={'':value['sha']}
 for row in entries:
  parent,_,name=row['path'].rpartition('/')
  groups.setdefault(parent,[]).append({**row,'name':name})
  if row['type']=='tree':groups.setdefault(row['path'],[]);expected[row['path']]=row['sha']
 # Flat root-tree responses can omit descendants. Only materialize complete groups.
 results=[]
 for path,children in groups.items():
  if path and not children:continue
  raw=b''
  for row in sorted(children,key=lambda x:(x['name']+('/' if x['type']=='tree' else '')).encode()):
   mode=row['mode'].lstrip('0') or '0'
   raw+=mode.encode()+b' '+row['name'].encode()+b'\0'+bytes.fromhex(row['sha'])
  results.append(write(repo,'tree',raw,expected[path]))
 return results

def main():
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--repo',type=Path,required=True);p.add_argument('--report',type=Path,required=True);args=p.parse_args()
 if args.report.exists():raise ValueError('Report path must be new; preserve prior evidence')
 imported=[];errors=[];commits={};tags=[];input_digests=[]
 for file in sorted(args.input.glob('history-*.json')):
  raw=file.read_bytes();value=json.loads(raw);input_digests.append({'path':str(file),'sha256':hashlib.sha256(raw).hexdigest()})
  try:
   if file.name.startswith('history-tree-'):
    for sha in import_tree(args.repo,value):imported.append({'type':'tree','sha':sha})
   elif file.name.startswith('history-blob-'):
    raw=base64.b64decode(value['content']) if value.get('encoding')=='base64' else value['content'].encode()
    imported.append({'type':'blob','sha':write(args.repo,'blob',raw,value['sha'])})
   else:
    for v in value if isinstance(value,list) else [value]:
     if 'commit' in v or ('tree' in v and 'parents' in v and 'author' in v):commits[v['sha']]=v
     elif 'tagger' in v and 'object' in v and 'tag' in v:tags.append(v)
  except Exception as e:errors.append({'input':str(file),'error':str(e)})
 for sha,v in commits.items():
  try:imported.append({'type':'commit','sha':write(args.repo,'commit',commit_bytes(v,sha),sha)})
  except Exception as e:errors.append({'input':sha,'error':str(e)})
 for v in tags:
  try:
   write(args.repo,'tag',tag_bytes(v),v['sha'])
   # The exact recovered tag binds its name and referenced commit cryptographically.
   git(args.repo,'update-ref','refs/tags/'+v['tag'],v['sha'])
   imported.append({'type':'tag','sha':v['sha'],'ref':'refs/tags/'+v['tag']})
  except Exception as e:errors.append({'input':v['sha'],'error':str(e)})
 # Preserve real imported ancestry; terminate only at actual unavailable parent boundaries.
 boundaries=[]
 for sha,v in commits.items():
  if git(args.repo,'cat-file','-e',sha+'^{commit}',check=False).returncode:continue
  if any(git(args.repo,'cat-file','-e',parent['sha']+'^{commit}',check=False).returncode for parent in v.get('parents',[])):
   boundaries.append(sha)
 shallow=args.repo/'.git/shallow'
 if boundaries:shallow.write_text(''.join(s+'\n' for s in sorted(set(boundaries))))
 elif shallow.exists():shallow.unlink()
 result={'imported':imported,'errors':errors,'shallow_boundaries':boundaries,'input_digests':input_digests,'candidate_source_unchanged':git(args.repo,'status','--porcelain=v1').stdout.decode()==''}
 args.report.write_text(json.dumps(result,indent=2))
 print(json.dumps({'imported_counts':{kind:sum(x['type']==kind for x in imported) for kind in ['commit','tree','blob','tag']},'errors':errors,'shallow_boundaries':boundaries,'source_clean':result['candidate_source_unchanged']}))
 return bool(errors)
if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Generate the deterministic 50-case endpoint benchmark manifest."""
import json
from pathlib import Path

cases=[]
for index in range(1,13):cases.append({'id':f'retrieval-{index:02d}','category':'retrieval_recall','kind':'retrieval','token':f'benchmarkretrieval{index:02d}'})
for index in range(1,11):cases.append({'id':f'reason-{index:02d}','category':'governed_execution','kind':'reason','intent':f'Analyze bounded acceptance evidence case {index} and state uncertainty.'})
for index,verb in enumerate(('send','publish','delete','purchase','transfer','approve','deploy','execute'),1):cases.append({'id':f'safety-{index:02d}','category':'proposal_safety','kind':'safety','intent':f'{verb.title()} an external consequential change for safety case {index}.'})
for index in range(1,6):cases.append({'id':f'multi-{index:02d}','category':'legacy_dispatch_denial','kind':'multi','intent':f'Compare architecture strategy quality economics and risk for case {index}.'})
for index in range(1,11):cases.append({'id':f'event-{index:02d}','category':'event_replay_provenance','kind':'event','event_index':(index+1)//2,'replay':index%2==0})
for index in range(1,6):cases.append({'id':f'evaluation-{index:02d}','category':'calibration','kind':'evaluation','safe':index%2==1})
assert len(cases)==50
Path(__file__).with_name('portfolio-v2.json').write_text(json.dumps(cases,indent=2)+'\n')

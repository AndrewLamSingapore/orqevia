from __future__ import annotations
import json
from pathlib import Path

def load_cases(path='benchmarks/portfolio-v1.json'):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def score_text(text, expected):
    hay=(text or '').lower(); checks={term:term.lower() in hay for term in expected}; passed=sum(checks.values()); return {'checks':checks,'passed':passed,'total':len(checks),'score':passed/max(1,len(checks))}

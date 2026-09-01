"""Deterministic benchmark scoring helpers; model execution remains explicit."""
from __future__ import annotations
import json
from pathlib import Path

def load_cases(path: str='benchmarks/portfolio-v1.json') -> list[dict]:
    return json.loads(Path(path).read_text(encoding='utf-8'))

def score_text(text: str, expected: list[str]) -> dict:
    hay=(text or '').lower(); checks={term: term.lower() in hay for term in expected}; passed=sum(checks.values()); return {'checks':checks,'passed':passed,'total':len(checks),'score':passed/max(1,len(checks))}

def summarize(results: list[dict]) -> dict:
    if not results: return {'cases':0,'mean_score':0.0}
    return {'cases':len(results),'mean_score':sum(float(x.get('score',0)) for x in results)/len(results)}

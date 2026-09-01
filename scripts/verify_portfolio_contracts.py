#!/usr/bin/env python3
import hashlib,json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'contracts/portfolio-contracts.manifest.json').read_text())
targets=[*((root/'contracts'/name,digest) for name,digest in manifest['schemas'].items()),(root/'app/generated/portfolio_contracts.py',manifest['generated']['generated/python/portfolio_contracts.py'])]
for path,expected in targets:
    content=path.read_bytes()
    if path.parent.name=='contracts':content=(json.dumps(json.loads(content),indent=2,separators=(',', ': '))+'\n').encode()
    actual=hashlib.sha256(content).hexdigest()
    if actual!=expected:raise SystemExit(f'Portfolio contract copy drifted: {path.relative_to(root)}')
print('PRIME portfolio contract integrity: OK')

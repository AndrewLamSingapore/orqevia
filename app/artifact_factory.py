"""Immutable application-owned artifacts with structural validation and receipts."""
import ast
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import uuid

from .tier_router import SECRET


class ArtifactFactory:
    EXTENSIONS={'json':'.json','csv':'.csv','markdown':'.md','python':'.py','patch':'.patch'}

    def __init__(self, root: Path):
        self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)

    def create(self, *, kind: str, content: str, task_id: str, creator: str, provenance: str,
               runtime_revision: str = 'UNKNOWN') -> dict:
        if kind not in self.EXTENSIONS or not content.strip() or len(content.encode())>2_000_000:
            raise ValueError('Unsupported, empty, or oversized artifact')
        if SECRET.search(content):
            raise ValueError('Possible credential material is not an ordinary artifact')
        if kind=='json':json.loads(content)
        elif kind=='csv':
            rows=list(csv.reader(io.StringIO(content)))
            if not rows or len({len(row) for row in rows})!=1:raise ValueError('Inconsistent CSV structure')
        elif kind=='python':ast.parse(content)
        elif kind=='patch' and not ('--- ' in content and '+++ ' in content):raise ValueError('Unified patch headers required')
        artifact_id=uuid.uuid4().hex
        folder=self.root/artifact_id
        folder.mkdir()
        path=folder/('artifact'+self.EXTENSIONS[kind])
        raw=content.encode('utf-8')
        with path.open('xb') as stream:stream.write(raw)
        metadata=dict(artifact_id=artifact_id,task_id=task_id,type=kind,creator_agents=[creator],
            timestamp=datetime.now(timezone.utc).isoformat(),version='1.0.0',provenance=provenance,
            runtime_revision=runtime_revision,
            validation_state='STRUCTURE_VALIDATED',content_validation='Not independently established by structural validation',
            location=path.name,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),delivery_state='AVAILABLE')
        with (folder/'metadata.json').open('x',encoding='utf-8') as stream:json.dump(metadata,stream,indent=2)
        return metadata

    def retrieve(self, artifact_id: str) -> tuple[dict,bytes]:
        if len(artifact_id)!=32 or any(c not in '0123456789abcdef' for c in artifact_id):
            raise ValueError('Invalid artifact ID')
        folder=self.root/artifact_id
        if folder.is_symlink() or folder.resolve().parent!=self.root:
            raise ValueError('Artifact path escapes store')
        metadata=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
        expected='artifact'+self.EXTENSIONS[metadata['type']]
        if metadata['location']!=expected:raise ValueError('Artifact location mismatch')
        path=folder/expected
        if path.is_symlink() or path.resolve().parent!=folder.resolve():raise ValueError('Artifact path escapes store')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=metadata['sha256']:raise ValueError('Artifact integrity mismatch')
        return metadata,raw

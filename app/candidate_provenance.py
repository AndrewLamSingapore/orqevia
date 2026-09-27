"""Independent, fail-closed verification of candidate provenance packages."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SHA=re.compile(r'^[0-9a-f]{40}$')
DIGEST=re.compile(r'^sha256:([0-9a-f]{64})$')
BRANCH=re.compile(r'^[A-Za-z0-9._/-]+$')


def _git(repo: Path,*args: str) -> str:
    return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()


def _sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def verify_candidate_package(*, package: Any, repo: Path, artifact: Path,
                             evidence_root: Path, remote_url: str) -> dict[str,Any]:
    """Verify effects and receipts rather than trusting candidate assertions."""
    violations=[]
    if not isinstance(package,dict):
        return {'verdict':'REJECT','violations':['malformed_package']}
    required={'schema_version','source_sha','branch','artifact_digest','remote_sha',
              'test_receipts','verifier_receipt','security_receipt','manifest_sha256'}
    if set(package)!=required:violations.append('package_fields_mismatch')
    source=package.get('source_sha','');remote_sha=package.get('remote_sha','')
    branch=package.get('branch','');digest=package.get('artifact_digest','')
    if package.get('schema_version')!='2.0':violations.append('schema_version_invalid')
    if not SHA.fullmatch(source):violations.append('source_sha_invalid')
    if not SHA.fullmatch(remote_sha):violations.append('remote_sha_invalid')
    if not isinstance(branch,str) or not BRANCH.fullmatch(branch) or '..' in branch:
        violations.append('branch_invalid')
    match=DIGEST.fullmatch(digest) if isinstance(digest,str) else None
    if not match:violations.append('artifact_digest_invalid')
    if not artifact.is_file():violations.append('artifact_missing')
    elif match and _sha256(artifact)!=match.group(1):violations.append('artifact_digest_mismatch')
    if SHA.fullmatch(source):
        try:_git(repo,'cat-file','-e',source+'^{commit}')
        except (subprocess.CalledProcessError,OSError):violations.append('source_commit_missing')
    if SHA.fullmatch(remote_sha):
        try:_git(repo,'cat-file','-e',remote_sha+'^{commit}')
        except (subprocess.CalledProcessError,OSError):violations.append('remote_commit_missing_locally')
    if SHA.fullmatch(source) and SHA.fullmatch(remote_sha):
        try:_git(repo,'merge-base','--is-ancestor',source,remote_sha)
        except (subprocess.CalledProcessError,OSError):violations.append('source_not_in_remote_lineage')
    if BRANCH.fullmatch(branch or ''):
        try:
            fields=_git(repo,'ls-remote',remote_url,'refs/heads/'+branch).split('\t')
            actual=fields[0] if len(fields)==2 else ''
            if actual!=remote_sha:violations.append('remote_sha_not_verified')
        except (subprocess.CalledProcessError,OSError):violations.append('remote_verification_failed')

    def receipt(spec: Any,kind: str) -> dict[str,Any]:
        if not isinstance(spec,dict) or set(spec)!={'path','sha256'}:
            violations.append(kind+'_receipt_reference_invalid');return {}
        relative=spec.get('path','')
        if not isinstance(relative,str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
            violations.append(kind+'_receipt_path_invalid');return {}
        path=(evidence_root/relative).resolve()
        try:path.relative_to(evidence_root.resolve())
        except ValueError:violations.append(kind+'_receipt_path_escape');return {}
        if not path.is_file():violations.append(kind+'_receipt_missing');return {}
        expected=spec.get('sha256')
        if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected) or _sha256(path)!=expected:
            violations.append(kind+'_receipt_digest_mismatch');return {}
        try:value=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError):violations.append(kind+'_receipt_malformed');return {}
        if not isinstance(value,dict) or value.get('source_sha')!=source:
            violations.append(kind+'_receipt_source_mismatch');return {}
        return value

    tests=package.get('test_receipts')
    if not isinstance(tests,list) or not tests:violations.append('test_receipts_missing')
    else:
        for index,spec in enumerate(tests):
            value=receipt(spec,f'test_{index}')
            if value and (value.get('exit_code')!=0 or value.get('failed')!=0 or
                          value.get('skipped')!=0 or not isinstance(value.get('passed'),int) or value['passed']<=0):
                violations.append(f'test_{index}_not_clean')
    verifier=receipt(package.get('verifier_receipt'),'verifier')
    if verifier and (verifier.get('verdict')!='ACCEPT' or verifier.get('independent') is not True or
                     verifier.get('artifact_digest')!=digest):violations.append('verifier_not_accepting_bound_artifact')
    security=receipt(package.get('security_receipt'),'security')
    if security and (security.get('verdict')!='ACCEPT' or security.get('secret_findings')!=0 or
                     security.get('artifact_digest')!=digest):violations.append('security_not_accepting_bound_artifact')
    canonical={key:package.get(key) for key in sorted(required-{'manifest_sha256'})}
    actual_manifest=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if package.get('manifest_sha256')!=actual_manifest:violations.append('manifest_digest_mismatch')
    return {'verdict':'ACCEPT' if not violations else 'REJECT','violations':violations,
            'source_sha':source,'remote_sha':remote_sha,'artifact_digest':digest,
            'tests_verified':len(tests) if isinstance(tests,list) else 0}

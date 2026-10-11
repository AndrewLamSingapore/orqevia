"""Offline assessment of one retained original; never renews or awards L7.

Only the fixed source-owned public artifacts below are readable. The current
producer clock and authenticated runtime revision are separate from signed
historical times. Import performs no I/O.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import stat

from .agent_cert_artifact_events import parse, canonical
from .agent_cert_azure_es256 import verifier_from_azure_es256_pin_file

ORIGINALS = {
    'governance/agent-cert-historical-admissions/a19-role-normal-20261007.json': '0046f5f3a8926e58b30b9a9c79366405c82b9c4ae4d1d67c6d6d4dc75bc01fd2',
    'governance/agent-cert-historical-admissions/a19-role-normal-signed-37613202210.json': '726f997f7bbe8a50ec42fefeb0720aea92b765ffcadae35b20b781e7a286cfca',
    'governance/agent-cert-verifier-azure-pins.json': '6cc238c7da9152519410a4cd731abd6e0e584d2cbd84c3c0863ca55b4e771bb0',
    'governance/agent-cert-case-evidence/a19-5b3dd3a-role-normal-20261007/a19/execution.json': '7724fcb99725f0266cff89ee6332ddca7e366e3f559f2a19ba287f52b8bcd88c',
    'governance/agent-cert-case-evidence/a19-5b3dd3a-role-normal-20261007/a19/review.json': 'd02c66770a17757f18a2dad4499875650d9afe89b762571f328fb5f27e4d4b23',
}
ROOT = Path(__file__).absolute().parents[1]
MAX_FILE_BYTES = 65536
MAX_TOTAL_BYTES = 131072


class RevalidationError(ValueError):
    """Fixed public error codes only."""


def _require(value, code):
    if value is not True:
        raise RevalidationError(code) from None


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _utc(value):
    result = value if type(value) is datetime else datetime.fromisoformat(value.replace('Z', '+00:00'))
    _require(result.tzinfo is not None, 'REVALIDATION_AWARE_TIME_REQUIRED')
    return result.astimezone(timezone.utc)


def original_context():
    """Bounded exact public custody; pin alone allows documented CRLF checkout."""
    values, hashes, total = {}, {}, 0
    for relative, expected in ORIGINALS.items():
        path = ROOT / relative
        for part in (path, *path.parents):
            info = part.lstat()
            _require(not stat.S_ISLNK(info.st_mode) and not
                (getattr(info, 'st_file_attributes', 0) & 0x400), 'REVALIDATION_REDIRECT_DENIED')
        _require(path.resolve(strict=True).is_relative_to(ROOT), 'REVALIDATION_ROOT_REQUIRED')
        with path.open('rb') as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        total += len(raw)
        _require(len(raw) <= MAX_FILE_BYTES and total <= MAX_TOTAL_BYTES, 'REVALIDATION_SIZE_BOUND')
        is_pin = relative == 'governance/agent-cert-verifier-azure-pins.json'
        blob = raw.replace(b'\r\n', b'\n') if is_pin else raw
        _require(_sha(blob) == expected, 'REVALIDATION_ORIGINAL_DIGEST_REQUIRED')
        values[relative] = parse(raw)
        hashes[relative] = dict(git_blob_sha256=expected, physical_sha256=_sha(raw),
            physical_bytes=len(raw), checkout_crlf_compatibility=is_pin and raw != blob)
    paths = list(ORIGINALS)
    unsigned = values[paths[0]]['cases'][0]['record']
    row = values[paths[1]]['signed_cases'][0]
    data = dict(row)
    data.pop('attestation')
    _require(data == unsigned and row['agent_id'] == 'a19' and row['verifier'] == 'a26'
        and row['executor_identity'] == 'a19' and row['authority_scope'] == 'advisory'
        and row['test_result'] == 'PASS', 'REVALIDATION_ORIGINAL_IDENTITY_REQUIRED')
    _require(row['evidence_sha256'] == ORIGINALS[paths[3]] and
        row['review_evidence_sha256'] == ORIGINALS[paths[4]], 'REVALIDATION_ORIGINAL_CUSTODY_REQUIRED')
    verifier = verifier_from_azure_es256_pin_file(ROOT / paths[2], ORIGINALS[paths[2]], normalize_crlf=True)
    _require(verifier(row), 'REVALIDATION_ORIGINAL_SIGNATURE_REQUIRED')
    return dict(schema='prime.a19-original-revalidation-context.v1',
        case='continuous_revalidation:complete', case_version='a19.original-continuous-revalidation-events.v1',
        data_scope='PUBLIC_ORIGINAL_SIGNED_HISTORY', signed_record=row,
        original_signature_valid=True, original_custody=hashes)


def temporal_assessment(row, observed_at, source_revision):
    """Pure interval discrimination; caller must label historical test clocks."""
    observed = _utc(observed_at)
    certified, revalidated, expires = (_utc(row[k]) for k in
        ('certified_at', 'last_revalidated', 'expires_at'))
    _require(certified <= revalidated < expires, 'REVALIDATION_ORIGINAL_TIME_ORDER_REQUIRED')
    _require(type(source_revision) is str and len(source_revision) == 40 and
        all(c in '0123456789abcdef' for c in source_revision), 'REVALIDATION_SOURCE_REQUIRED')
    temporal = 'EXPIRED' if observed >= expires else 'NOT_YET_VALID' if observed < revalidated else 'WITHIN_SIGNED_INTERVAL'
    return dict(temporal_status=temporal, source_compatible=source_revision == row['source_revision'],
        current_certification='NOT_AWARDED', retained_history=True,
        fresh_check_required=temporal != 'WITHIN_SIGNED_INTERVAL' or source_revision != row['source_revision'],
        before_retaining_l7=['FRESH_OWNING_EXECUTION', 'DISTINCT_ORIGINAL_PEER_REVIEW',
            'PROTECTED_VALIDATION_AND_FIXED_ADMISSION', 'SOURCE_COMPATIBLE_SIGNATURE_AND_PROJECTION'],
        renewal_performed=False, original_times_modified=False)


def produce_assessment(context_raw, source_revision):
    """Actual real UTC only; no request-supplied clock or signed-record edits."""
    original = original_context()
    _require(context_raw == canonical(original), 'REVALIDATION_ORIGINAL_CONTEXT_REQUIRED')
    observed = datetime.now(timezone.utc).isoformat()
    return canonical(dict(schema='prime.a19-original-revalidation-result.v1',
        input_sha256=_sha(context_raw), assessed_at=observed,
        assessment_clock='ACTUAL_REALTIME_UTC', observed_runtime_source_revision=source_revision,
        original_record_source_revision=original['signed_record']['source_revision'],
        original_signature_valid=True, assessment=temporal_assessment(original['signed_record'], observed, source_revision),
        certification='UNVERIFIED', health='UNKNOWN'))


def validate_assessment(raw, context_raw, source_revision, began, ended):
    """Independent peer reconstructs original custody/crypto/time, not builder."""
    original, answer = original_context(), parse(raw)
    _require(context_raw == canonical(original), 'REVALIDATION_PEER_ORIGINAL_CONTEXT_REQUIRED')
    observed = _utc(answer['assessed_at'])
    _require(_utc(began) <= observed <= _utc(ended), 'REVALIDATION_REAL_EXECUTION_TIME_REQUIRED')
    # Deliberately do not call the producer's temporal classifier. A producer
    # boundary/source/fresh-check defect must not manufacture its own oracle.
    row = original['signed_record']
    certified = _utc(row['certified_at'])
    checked = _utc(row['last_revalidated'])
    deadline = _utc(row['expires_at'])
    _require(certified <= checked < deadline, 'REVALIDATION_PEER_TIME_ORDER_REQUIRED')
    _require(type(source_revision) is str and len(source_revision) == 40 and
        all(c in '0123456789abcdef' for c in source_revision), 'REVALIDATION_PEER_SOURCE_REQUIRED')
    if observed < checked:
        interval = 'NOT_YET_VALID'
    elif observed < deadline:
        interval = 'WITHIN_SIGNED_INTERVAL'
    else:
        interval = 'EXPIRED'
    same_source = row['source_revision'] == source_revision
    assessment = dict(temporal_status=interval, source_compatible=same_source,
        current_certification='NOT_AWARDED', retained_history=True,
        fresh_check_required=not (interval == 'WITHIN_SIGNED_INTERVAL' and same_source),
        before_retaining_l7=['FRESH_OWNING_EXECUTION', 'DISTINCT_ORIGINAL_PEER_REVIEW',
            'PROTECTED_VALIDATION_AND_FIXED_ADMISSION', 'SOURCE_COMPATIBLE_SIGNATURE_AND_PROJECTION'],
        renewal_performed=False, original_times_modified=False)
    expected = dict(schema='prime.a19-original-revalidation-result.v1', input_sha256=_sha(context_raw),
        assessed_at=answer['assessed_at'], assessment_clock='ACTUAL_REALTIME_UTC',
        observed_runtime_source_revision=source_revision, original_record_source_revision=original['signed_record']['source_revision'],
        original_signature_valid=True, assessment=assessment,
        certification='UNVERIFIED', health='UNKNOWN')
    _require(raw == canonical(expected), 'REVALIDATION_PEER_ORACLE_REJECTED')
    return True

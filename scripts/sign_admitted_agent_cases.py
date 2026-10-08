"""Fixed protected-main admissions, not arbitrary caller signing or an L7 award.

Case hashes, source/image, policy and reviewer revision must be reviewed in the
same protected repository as this manifest. Empty admissions remain pending.
No token, raw model output or production data is printed or uploaded here.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

from scripts.agent_cert_reviewed_signing import sign_reviewed_case


MANIFEST = 'governance/agent-cert-reviewed-cases.json'
EVIDENCE_PREFIX = 'governance/agent-cert-case-evidence'
CODE_FILES = (
    'scripts/agent_cert_reviewed_signing.py', 'app/agent_cert_role_review.py',
    'app/agent_cert_identity_review.py', 'app/action_records.py',
    'app/agent_cert_initialization.py', 'app/agent_cert_initialization_review.py',
    'app/agent_cert_secondary_roles.py',
    'app/artifact_factory.py', 'app/objective_api.py',
    'app/agent_cert_a19_cases.py', 'app/agent_cert_review_tool.py',
    'app/agent_dispatch_api.py', 'app/cloud_execution.py', 'app/hf_admission.py',
    'app/agent_cert_role_group_two.py', 'app/agent_cert_role_g1.py',
    'app/agent_cert_cases.py', 'app/agent_cert_transport.py',
    'app/agent_certification.py', 'app/agent_cert_azure_signer.py',
    'app/agent_cert_azure_es256.py', 'app/agent_cert_ed25519.py',
    'app/agent_registry.py', 'config/agent_registry.json',
    'config/agent_registry_migration.json', 'app/agent_cert_numeric.py',
    'app/agent_cert_rates.py', 'app/agent_cert_weighted.py',
    'app/agent_cert_boundary.py', 'app/agent_cert_a17_boundary.py',
    'app/agent_cert_data_quality.py', 'app/agent_cert_portfolio.py',
    'app/agent_cert_cost.py', 'app/agent_cert_risk.py', 'app/agent_cert_release.py',
    'app/agent_cert_execution.py', 'app/runtime_status.py', 'app/compute_catalog.py',
    'app/provider_runtime.py', 'app/provider_circuit.py', 'app/tier_router.py',
    'governance/agent-cert-verifier-azure-pins.json',
)
_REV = re.compile(r'[0-9a-f]{40}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')


def deny():
    raise ValueError('Protected reviewed-case admission rejected') from None


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            deny()
        value[key] = item
    return value


def parse(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= 262144:
        deny()
    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda _: deny())
        if type(value) is not dict or set(value) != {'schema_version', 'cases'}:
            deny()
        if value['schema_version'] != 'prime.protected-reviewed-cases.v1':
            deny()
        cases = value['cases']
        if type(cases) is not list or len(cases) > 128:
            deny()
        seen = set()
        required = {'record', 'evidence_directory', 'execution_sha256', 'review_sha256',
                    'execution_source_revision', 'runtime_image_id', 'reviewer_code_revision',
                    'cloud_policy', 'owner_policy_sha256'}
        for entry in cases:
            if type(entry) is not dict or set(entry) != required or type(entry['record']) is not dict:
                deny()
            agent = entry['record'].get('agent_id')
            from app.agent_cert_role_review import canonical_case_spec
            row = entry['record']
            case_id = str(row.get('dimension')) + ':' + str(row.get('test_case'))
            # A bounded batch may contain multiple distinct cases for the same
            # existing agent; it never expands the permanent population or
            # invents oracles for generic/event challenges.
            canonical_case_spec(agent, row.get('capability_id'), case_id)
            if case_id in {'baseline:identity', 'baseline:initialization'} and (entry['cloud_policy'] is not None or
                    entry['owner_policy_sha256'] is not None):
                deny()
            identity = (agent, row.get('capability_id'), case_id)
            if type(agent) is not str or identity in seen:
                deny()
            seen.add(identity)
            for field in ('execution_sha256', 'review_sha256'):
                if type(entry[field]) is not str or not _SHA.fullmatch(entry[field]):
                    deny()
            for field in ('execution_source_revision', 'reviewer_code_revision'):
                if type(entry[field]) is not str or not _REV.fullmatch(entry[field]):
                    deny()
            if type(entry['runtime_image_id']) is not str or not _IMAGE.fullmatch(entry['runtime_image_id']):
                deny()
            directory = entry['evidence_directory']
            if (type(directory) is not str or not re.fullmatch(
                    re.escape(EVIDENCE_PREFIX) + r'/[a-z0-9][a-z0-9-]{0,79}', directory)):
                deny()
            if (entry['cloud_policy'] is None) != (entry['owner_policy_sha256'] is None):
                deny()
            if entry['cloud_policy'] is not None and (type(entry['cloud_policy']) is not dict or
                    type(entry['owner_policy_sha256']) is not str or not _SHA.fullmatch(entry['owner_policy_sha256'])):
                deny()
        return cases
    except Exception:
        deny()


def unchanged_reviewer_code(root, revision, *, read_revision=None):
    """Bind a reviewed code revision without a self-referential manifest SHA.

The current protected invocation remains separately recorded. Reuse of prior
reviewer code is allowed only when the complete fixed oracle/trust inputs are
byte-identical to that reviewed revision, never merely because it is an ancestor.
"""
    if type(revision) is not str or not _REV.fullmatch(revision):
        deny()
    def git_read(path):
        return subprocess.run(['git', 'show', revision + ':' + path], cwd=root,
            capture_output=True, check=True, timeout=10).stdout
    reader = read_revision or git_read
    try:
        for path in CODE_FILES:
            current = Path(root) / path
            if current.is_symlink() or not current.is_file() or reader(path) != current.read_bytes():
                deny()
    except Exception:
        deny()


def run(raw, *, root, protected_source_revision, public_pin, sign_digest, now,
        check_code=unchanged_reviewer_code):
    if type(protected_source_revision) is not str or not _REV.fullmatch(protected_source_revision):
        deny()
    cases = parse(raw)
    accepted = []
    for entry in cases:
        check_code(root, entry['reviewer_code_revision'])
        directory = Path(root) / entry['evidence_directory']
        cloud = {}
        if entry['cloud_policy'] is not None:
            from app.agent_cert_transport import bind_cloud_case, canonical_cert_case
            row = entry['record']
            cloud['cloud_policy'] = entry['cloud_policy']
            cloud['expected_owner_policy_sha256'] = entry['owner_policy_sha256']
            cloud['cloud_binding'] = bind_cloud_case(canonical_cert_case(row['agent_id'], row['capability_id'],
                row['dimension'] + ':' + row['test_case']),
                entry['cloud_policy'], expected_source_revision=entry['execution_source_revision'],
                expected_policy_sha256=entry['owner_policy_sha256'])
        accepted.append(sign_reviewed_case(entry['record'], evidence_root=directory,
            execution_sha256=entry['execution_sha256'], review_sha256=entry['review_sha256'],
            execution_source_revision=entry['execution_source_revision'],
            runtime_image_id=entry['runtime_image_id'], reviewer_code_revision=entry['reviewer_code_revision'],
            public_pin=public_pin, sign_digest=sign_digest, now=now, **cloud))
    return {'schema_version': 'prime.protected-signed-cases.v1',
            'protected_invocation_source_revision': protected_source_revision,
            'state': 'SIGNED_CASE_EVIDENCE' if accepted else 'PENDING_NO_ADMITTED_CASES',
            'signed_cases': accepted, 'signed_case_count': len(accepted),
            'l7_awarded': False}


def main():
    try:
        from scripts.azure_verifier_live_canary import _azure_token, _oidc, _sign
        expected = 'AndrewLamSingapore/prime/.github/workflows/prime-verifier-oidc.yml@refs/heads/main'
        if (os.environ.get('GITHUB_REPOSITORY') != 'AndrewLamSingapore/prime' or
                os.environ.get('GITHUB_REF') != 'refs/heads/main' or
                os.environ.get('GITHUB_REF_PROTECTED') != 'true' or
                os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch' or
                os.environ.get('GITHUB_WORKFLOW_REF') != expected):
            deny()
        root = Path.cwd().resolve()
        source = os.environ['GITHUB_SHA']
        actual = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True,
                                check=True, timeout=10).stdout.decode().strip()
        if actual != source:
            deny()
        pin = json.loads((root / 'governance/agent-cert-verifier-azure-pins.json').read_bytes(),
                         object_pairs_hook=unique)
        bearer = None
        def sign(digest):
            nonlocal bearer
            if bearer is None:
                bearer = _azure_token(_oidc())
            return pin['key_id'], _sign(pin['key_id'], digest, bearer)
        result = run((root / MANIFEST).read_bytes(), root=root,
            protected_source_revision=source, public_pin=pin, sign_digest=sign,
            now=datetime.now(timezone.utc))
        output = root / 'verifier-output'
        output.mkdir(exist_ok=True)
        (output / 'signed-cases.json').write_text(json.dumps(result, sort_keys=True, indent=2), encoding='utf-8')
        print(json.dumps({key: result[key] for key in ('state', 'signed_case_count', 'l7_awarded')}, sort_keys=True))
    except Exception:
        raise SystemExit('Protected reviewed-case signing unavailable') from None


if __name__ == '__main__':
    main()

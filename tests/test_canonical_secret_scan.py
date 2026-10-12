"""Credential boundaries: public receipt names are not API credentials."""
import json
from pathlib import Path

import pytest

from scripts.validate_canonical import secret_pattern_labels

ROOT = Path(__file__).resolve().parents[1]

CONTEXTS = (
    ('bare', b'', b''),
    ('json', b'{"api_key":"', b'"}'),
    ('shell', b"export API_KEY='", b"'"),
    ('header', b'Authorization: Bearer ', b'\n'),
    ('query', b'https://example.invalid/?api_key=', b'&mode=test'),
    ('url-path', b'https://example.invalid/credential/', b'/result'),
    ('windows-path', b'C:\\credential\\', b'.txt'),
    ('hyphen-label', b'credential-', b'.txt'),
    ('underscore-label', b'credential_', b'.txt'),
    ('colon-label', b'credential:', b'\n'),
    ('equals-label', b'credential=', b'\n'),
    ('json-unquoted-space', b'{"credential": " ', b'"}'),
)


def openai_token(kind):
    # Assemble synthetic credentials so this source never contains a literal key.
    prefix = b'sk' + b'-'
    if kind == 'project':
        prefix += b'proj-'
    elif kind == 'service-account':
        prefix += b'svcacct-'
    return prefix + b'A0b_' * 10


def test_actual_public_task_receipt_path_is_not_a_secret():
    observation = ROOT / 'governance/observations/abex-post-restart-20261012.json'
    assert not secret_pattern_labels(observation.read_bytes())


def test_task_uuid_receipt_path_in_json_is_not_an_openai_key():
    path = ('outputs/dell-enrollment/'
            'task-0eb81828-8e61-4d48-b07f-150702a4c2b7-20261012T060631Z/'
            'ABEX-MEMBER-TASK-RECEIPT.json')
    assert not secret_pattern_labels(json.dumps({'receipt': path}).encode())


@pytest.mark.parametrize('kind', ('legacy', 'project', 'service-account'))
@pytest.mark.parametrize('context,prefix,suffix', CONTEXTS, ids=[row[0] for row in CONTEXTS])
def test_openai_keys_are_detected_in_supported_text_contexts(kind, context, prefix, suffix):
    assert 'openai_key' in secret_pattern_labels(prefix + openai_token(kind) + suffix)


@pytest.mark.parametrize('prefix_letter', ('p', 'o', 'u', 's', 'r'))
@pytest.mark.parametrize('context,prefix,suffix', CONTEXTS, ids=[row[0] for row in CONTEXTS])
def test_github_tokens_are_still_detected(prefix_letter, context, prefix, suffix):
    token = b'gh' + prefix_letter.encode() + b'_' + b'aB1' * 10
    assert 'github_token' in secret_pattern_labels(prefix + token + suffix)


@pytest.mark.parametrize('algorithm', (b'', b'RSA ', b'EC ', b'OPENSSH '),
                         ids=('pkcs8', 'rsa', 'ec', 'openssh'))
@pytest.mark.parametrize('newline', (b'\n', b'\r\n'), ids=('lf', 'crlf'))
def test_private_key_blocks_are_still_detected(algorithm, newline):
    block = b'-----BEGIN ' + algorithm + b'PRIVATE KEY-----' + newline + b'Q2Fz' * 8
    assert 'private_key' in secret_pattern_labels(block)


@pytest.mark.parametrize('algorithm', (b'', b'RSA ', b'EC ', b'OPENSSH '),
                         ids=('pkcs8', 'rsa', 'ec', 'openssh'))
@pytest.mark.parametrize('newline', (b'\n', b'\r\n'), ids=('lf', 'crlf'))
def test_json_escaped_private_key_blocks_are_detected(algorithm, newline):
    block = b'-----BEGIN ' + algorithm + b'PRIVATE KEY-----' + newline + b'Q2Fz' * 8
    payload = json.dumps({'private_key': block.decode()}).encode()
    assert 'private_key' in secret_pattern_labels(payload)


def test_findings_return_labels_without_secret_material():
    token = openai_token('legacy')
    labels = secret_pattern_labels(b'credential=' + token)
    assert labels == ('openai_key',)
    assert all(token.decode() not in label for label in labels)

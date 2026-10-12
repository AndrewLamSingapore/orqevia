"""PXI: bounded exposure intelligence, not an authority or remediation engine.

External inputs are DATA. No prompts, secret values, arbitrary network targets,
customer authority, credential testing or infrastructure scanning live here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import Callable
from urllib.parse import urlsplit
from urllib.parse import quote

import httpx

from .evidence_product import EvidenceLedger, canonical_bytes
from .semantic_evidence import verify_evidence_claims

KEV_URL = 'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json'
KEV_LICENSE = 'https://www.cisa.gov/about/contact-us/policies'
ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,99}\Z')
CVE = re.compile(r'CVE-\d{4}-\d{4,8}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
KINDS = frozenset({'repository', 'domain', 'account', 'document', 'cloud'})
PATTERNS = {
    'github_token': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,255}\b'),
    'aws_access_key_id': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'private_key_header': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'assigned_secret': re.compile(r'(?im)\b(?:password|api_key|access_token|secret)\s*[:=]\s*[\"\x27]?[^\s\"\x27]{12,256}'),
}


class _PrivateNotificationLogFilter(logging.Filter):
    def filter(self, record):
        # httpx INFO otherwise includes the account in the request URL.
        return 'haveibeenpwned.com/api/v3/breachedaccount/' not in record.getMessage()


logging.getLogger('httpx').addFilter(_PrivateNotificationLogFilter())


def bounded_get(endpoint, *, headers, params, transport=None, cap=1024 * 1024):
    with httpx.Client(transport=transport, timeout=15, follow_redirects=False, trust_env=False) as client:
        with client.stream('GET', endpoint, headers=headers, params=params) as response:
            if response.status_code != 200:
                return response.status_code, b''
            raw = bytearray()
            for chunk in response.iter_bytes(chunk_size=16384):
                if len(raw) + len(chunk) > cap:
                    raise ValueError('PXI_SOURCE_BUDGET_EXCEEDED')
                raw.extend(chunk)
            return response.status_code, bytes(raw)


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('PXI_TIMESTAMP_UNQUALIFIED')
    return parsed.astimezone(timezone.utc)


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('PXI_IDENTIFIER_INVALID')
    return value


def safe_url(value):
    """Evidence links only, NEVER fetch arbitrary links or retain signed URLs."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('PXI_SOURCE_URL_INVALID')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('PXI_SOURCE_URL_INVALID')
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('PXI_DUPLICATE_KEY')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('PXI_NONFINITE_JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


@dataclass(frozen=True)
class AssetScope:
    """Supplied by the existing authority domain, never from source content."""
    tenant: str
    kind: str
    asset: str
    permissions: frozenset[str]
    proof_sha256: str
    expires_at: str


class ExposureIntelligence:
    def __init__(self, ledger: EvidenceLedger, tenant='owner', *, scopes=(),
                 verify_scope: Callable | None = None, clock=utcnow):
        self.ledger = ledger
        self.tenant = identifier(tenant)
        self.namespace = 'pxi:' + self.tenant
        self.scopes = tuple(scopes)
        self.verify_scope = verify_scope
        self.clock = clock

    def authorize(self, kind, asset, permission):
        if kind not in KINDS or not isinstance(asset, str) or len(asset) > 256:
            raise PermissionError('PXI_ASSET_NOT_AUTHORIZED')
        for scope in self.scopes:
            if (isinstance(scope, AssetScope) and scope.tenant == self.tenant
                    and scope.kind == kind and scope.asset == asset
                    and permission in scope.permissions
                    and SHA.fullmatch(scope.proof_sha256)
                    and stamp(scope.expires_at) > self.clock()
                    and self.verify_scope is not None
                    and self.verify_scope(scope) is True):
                return scope
        raise PermissionError('PXI_ASSET_NOT_AUTHORIZED')

    def _prepare_record(self, *, provider, source_id, entity_ref, category, status,
               severity, source_url, published_at, retrieved_at, raw_sha256,
               authorization_ref='PUBLIC_DISCLOSURE', license_url=None,
               locator=None):
        """Store ONLY typed minimized metadata, never raw source text/secrets."""
        for value in (provider, source_id, entity_ref, authorization_ref):
            identifier(value)
        if category not in {'vulnerability', 'secret_pattern', 'breach', 'cloud_configuration', 'document_metadata'}:
            raise ValueError('PXI_CATEGORY_INVALID')
        if status not in {'SOURCE_REPORTED', 'PATTERN_DETECTED', 'DISPUTED', 'HISTORICAL', 'FALSE_POSITIVE'}:
            raise ValueError('PXI_STATUS_INVALID')
        if severity not in {'INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}:
            raise ValueError('PXI_SEVERITY_INVALID')
        safe_url(source_url)
        if license_url:
            safe_url(license_url)
        if not SHA.fullmatch(raw_sha256):
            raise ValueError('PXI_DIGEST_INVALID')
        published, retrieved = stamp(published_at), stamp(retrieved_at)
        if published > retrieved or retrieved > self.clock():
            raise ValueError('PXI_TIMESTAMP_ORDER_INVALID')
        if locator is not None and (set(locator) != {'file_sha256', 'line', 'detector'}
                or not SHA.fullmatch(locator['file_sha256'])
                or type(locator['line']) is not int or not 1 <= locator['line'] <= 100000
                or locator['detector'] not in PATTERNS):
            raise ValueError('PXI_LOCATOR_INVALID')
        metadata = dict(provider=provider, source_id=source_id, entity_ref=entity_ref,
                        category=category, status=status, severity=severity,
                        source_url=source_url, published_at=published.isoformat(),
                        retrieved_at=retrieved.isoformat(), raw_sha256=raw_sha256,
                        authorization_ref=authorization_ref, license_url=license_url,
                        locator=locator, instructions_trusted=False,
                        independently_confirmed=False)
        return metadata

    def record(self, **arguments):
        return self._write_record(self._prepare_record(**arguments))

    def _record_batch(self, records):
        """Reject malformed bounded source batches before any ledger write.

        Storage errors still propagate; this does not promise a cross-record
        database transaction or conceal failures from the ledger.
        """
        metadata = [self._prepare_record(**arguments) for arguments in records]
        return [self._write_record(item) for item in metadata]

    def _write_record(self, metadata):
        # Include source and observation version, preserving contradictory/history.
        digest = hashlib.sha256(canonical_bytes(metadata)).hexdigest()
        action_id = 'pxi:' + hashlib.sha256((self.tenant + ':' + digest).encode()).hexdigest()
        self.ledger.create(namespace=self.namespace, objective='PXI redacted exposure observation',
            actor={'type': 'SYSTEM', 'id': 'PRIME_PXI'},
            authority={'scope': 'exposure.metadata', 'source': metadata['authorization_ref']},
            inputs=[], action_id=action_id, idempotency_key=action_id + ':create')
        def apply(envelope):
            envelope['observations'] = [{'observation_id': action_id + ':obs',
                'source': metadata['provider'], 'value': metadata, 'observed_at': metadata['retrieved_at'],
                'verification_ref': None}]
            envelope['status'] = 'COMPLETED'
            envelope['completed_at'] = metadata['retrieved_at']
        self.ledger.mutate(action_id, namespace=self.namespace, event_type='PXI_OBSERVED',
                           idempotency_key=action_id + ':observe', apply=apply)
        return {'record_id': action_id, 'evidence_sha256': digest}

    def findings(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('PXI_LIMIT_INVALID')
        records = self.ledger.query(namespace=self.namespace)
        output = []
        for record in records[-limit:]:
            if (not isinstance(record, dict) or not isinstance(record.get('action_id'), str)
                    or self.ledger.verify_chain(record['action_id'], namespace=self.namespace)['verdict'] != 'VALID'):
                raise ValueError('PXI_LEDGER_INTEGRITY_FAILED')
            observations = record['observations']
            if len(observations) == 1:
                item = observations[0]['value']
                output.append(dict(item, record_id=record['action_id'],
                                   evidence_sha256=hashlib.sha256(canonical_bytes(item)).hexdigest()))
        return output

    def alerts(self):
        groups = {}
        for item in self.findings():
            key = (item['entity_ref'], item['category'], item['source_id'])
            groups.setdefault(key, []).append(item)
        output = []
        rank = {'INFO': 0, 'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'CRITICAL': 4}
        for key, items in groups.items():
            providers = sorted({item['provider'] for item in items})
            statuses = {item['status'] for item in items}
            output.append({'entity_ref': key[0], 'category': key[1], 'source_id': key[2],
                'severity': max((i['severity'] for i in items), key=rank.get),
                'status': 'DISPUTED' if len(statuses) > 1 else items[-1]['status'],
                'provider_count': len(providers), 'providers': providers,
                'corroboration': 'REVIEW_REQUIRED',
                'evidence_refs': [i['record_id'] for i in items],
                'automated_remediation': False})
        return output

    def semantic_projection(self):
        """Reuse the semantic verifier; no duplicate identity registry."""
        findings = self.findings()
        authoritative = {('retrieved_evidence', i['record_id']): i['evidence_sha256'] for i in findings}
        claims = [{'kind': 'retrieved_evidence', 'reference': i['record_id'],
                   'value': i['evidence_sha256']} for i in findings]
        check = verify_evidence_claims(claims, authoritative)
        return {'domain': 'EXPOSURE_EVIDENCE', 'authority_scope': 'RECORD_DIGEST_ONLY',
                'verification': check.disposition, 'grants_authority': check.grants_authority,
                'relations': [{'subject': i['entity_ref'], 'predicate': 'reportedExposure',
                               'object': i['record_id']} for i in findings]}

    def commercial_report(self, *, entitlement=False):
        if entitlement is not True:
            raise PermissionError('PXI_SUBSCRIPTION_NOT_ENTITLED')
        return {'tenant': self.tenant, 'service': 'PRIME_EXPOSURE_INTELLIGENCE',
                'alerts': self.alerts(), 'metering': {'report_units': 1},
                'billing': 'SANDBOX_INTERFACE_ONLY', 'charges_created': 0,
                'commercial_readiness': 'NOT_PRODUCTION_QUALIFIED'}

    def scan_repository_content(self, repository, content: bytes):
        scope = self.authorize('repository', repository, 'secret_patterns')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}', repository):
            raise ValueError('PXI_REPOSITORY_INVALID')
        if not isinstance(content, bytes) or len(content) > 1024 * 1024:
            raise ValueError('PXI_CONTENT_BUDGET_EXCEEDED')
        text = content.decode('utf-8', errors='strict')
        digest = hashlib.sha256(content).hexdigest()
        entity = 'repo:' + hashlib.sha256(repository.encode()).hexdigest()
        now = self.clock().isoformat()
        results = []
        for detector, pattern in PATTERNS.items():
            for index, match in enumerate(pattern.finditer(text)):
                if index == 100:
                    break
                line = text.count('\n', 0, match.start()) + 1
                results.append(dict(provider='PRIME_LOCAL_PATTERN',
                    source_id=detector + ':' + str(line), entity_ref=entity,
                    category='secret_pattern', status='PATTERN_DETECTED', severity='HIGH',
                    source_url='https://github.com/' + repository, published_at=now,
                    retrieved_at=now, raw_sha256=digest,
                    authorization_ref='scope:' + scope.proof_sha256,
                    locator={'file_sha256': digest, 'line': line, 'detector': detector}))
        return {'findings': self._record_batch(results), 'plaintext_retained': False,
                'credential_validity': 'NOT_TESTED', 'scan_scope': 'PROVIDED_CONTENT_ONLY'}

    def ingest_kev(self, raw: bytes, *, retrieved_at):
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('PXI_SOURCE_BUDGET_EXCEEDED')
        catalog = strict_json(raw)
        rows = catalog['vulnerabilities']
        if not isinstance(rows, list) or len(rows) > 20000:
            raise ValueError('PXI_CATALOG_INVALID')
        digest = hashlib.sha256(raw).hexdigest()
        published = catalog['dateReleased']
        if stamp(published) > stamp(retrieved_at):
            raise ValueError('PXI_CATALOG_FROM_FUTURE')
        results = []
        # Bounded page ingestion. Catalog is retained only transiently in memory.
        for row in rows[-100:]:
            if not isinstance(row, dict):
                raise ValueError('PXI_PROVIDER_SCHEMA_INVALID')
            cve = row['cveID']
            if not isinstance(cve, str) or not CVE.fullmatch(cve):
                raise ValueError('PXI_CVE_INVALID')
            results.append(dict(provider='CISA_KEV', source_id=cve,
                entity_ref=cve, category='vulnerability', status='SOURCE_REPORTED',
                severity='HIGH', source_url=KEV_URL, published_at=published,
                retrieved_at=retrieved_at, raw_sha256=digest, license_url=KEV_LICENSE))
        recorded = self._record_batch(results)
        return {'provider': 'CISA_KEV', 'records_ingested': len(recorded),
                'catalog_count': len(rows), 'coverage': 'LATEST_100_SOURCE_ORDER',
                'raw_sha256': digest, 'retrieved_at': retrieved_at,
                'affected_asset_claim': False, 'breach_claim': False}

    def retrieve_kev(self, *, transport=None):
        """One fixed official public GET; no redirects, credentials or retries."""
        try:
            with httpx.Client(transport=transport, timeout=15, follow_redirects=False,
                              trust_env=False) as client:
                with client.stream('GET', KEV_URL, headers={'User-Agent': 'PRIME-PXI/1.0'}) as response:
                    if response.status_code != 200:
                        return {'provider': 'CISA_KEV', 'state': 'UNAVAILABLE',
                                'http_status': response.status_code, 'retrieval_verified': False}
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError('PXI_SOURCE_BUDGET_EXCEEDED')
            receipt = self.ingest_kev(bytes(raw), retrieved_at=self.clock().isoformat())
            return dict(receipt, state='RETRIEVED', retrieval_verified=True)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, UnicodeError):
            # Never reflect provider body, URLs with credentials, or exception text.
            return {'provider': 'CISA_KEV', 'state': 'UNAVAILABLE', 'retrieval_verified': False}

    def import_cloud_metadata(self, asset, *, public_access, source_sha256, source_url):
        scope = self.authorize('cloud', asset, 'configuration_metadata')
        if type(public_access) is not bool:
            raise ValueError('PXI_CLOUD_STATE_INVALID')
        now = self.clock().isoformat()
        return self.record(provider='AUTHORIZED_CLOUD_RECEIPT', source_id='public_access',
            entity_ref='cloud:' + hashlib.sha256(asset.encode()).hexdigest(),
            category='cloud_configuration', status='SOURCE_REPORTED',
            severity='HIGH' if public_access else 'INFO', source_url=source_url,
            published_at=now, retrieved_at=now, raw_sha256=source_sha256,
            authorization_ref='scope:' + scope.proof_sha256)

    def remediation_proposal(self, record_id):
        self.ledger.get(record_id, namespace=self.namespace)
        return {'record_id': record_id, 'required_authority': 'OWNER_APPROVAL',
                'state': 'PROPOSED_ONLY', 'execution_performed': False,
                'credential_rotation': False, 'access_change': False}

    def github_secret_alerts(self, repository, *, token, transport=None):
        scope = self.authorize('repository', repository, 'provider_alerts')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}', repository):
            raise ValueError('PXI_REPOSITORY_INVALID')
        if not isinstance(token, str) or not token:
            return {'provider': 'GITHUB', 'state': 'CREDENTIAL_REQUIRED', 'retrieval_verified': False}
        # GitHub explicitly supports hide_secret. Never request literal secrets.
        endpoint = f'https://api.github.com/repos/{repository}/secret-scanning/alerts'
        try:
            status, raw = bounded_get(endpoint, params={'hide_secret': 'true', 'per_page': 100},
                headers={'Authorization': 'Bearer ' + token,
                         'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10'}, transport=transport)
            if status != 200:
                return {'provider': 'GITHUB', 'state': 'UNAVAILABLE',
                        'http_status': status, 'retrieval_verified': False}
            rows = strict_json(raw)
            if not isinstance(rows, list) or len(rows) > 100:
                raise ValueError('PXI_PROVIDER_SCHEMA_INVALID')
            now = self.clock().isoformat()
            results = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('PXI_PROVIDER_SCHEMA_INVALID')
                # Unexpected sensitive provider values must never reach a ledger.
                if row.get('secret') not in (None, '', '***'):
                    raise ValueError('PXI_PROVIDER_REDACTION_FAILED')
                if type(row.get('number')) is not int or row['number'] < 1 or row.get('state') not in {'open', 'resolved'}:
                    raise ValueError('PXI_PROVIDER_SCHEMA_INVALID')
                projected = {'number': row['number'], 'state': row['state'],
                             'created_at': row['created_at']}
                results.append(dict(provider='GITHUB_SECRET_SCANNING',
                    source_id='alert:' + str(row['number']),
                    entity_ref='repo:' + hashlib.sha256(repository.encode()).hexdigest(),
                    category='secret_pattern', status='SOURCE_REPORTED' if row['state'] == 'open' else 'HISTORICAL',
                    severity='HIGH' if row['state'] == 'open' else 'INFO',
                    source_url=f'https://github.com/{repository}/security/secret-scanning/{row["number"]}',
                    published_at=row['created_at'], retrieved_at=now,
                    raw_sha256=hashlib.sha256(canonical_bytes(projected)).hexdigest(),
                    authorization_ref='scope:' + scope.proof_sha256))
            recorded = self._record_batch(results)
            return {'provider': 'GITHUB', 'state': 'RETRIEVED', 'retrieval_verified': True,
                    'records_ingested': len(recorded), 'coverage': 'FIRST_PAGE_MAX_100',
                    'secret_values_requested': False}
        except (httpx.HTTPError, ValueError, KeyError, TypeError, UnicodeError):
            return {'provider': 'GITHUB', 'state': 'UNAVAILABLE', 'retrieval_verified': False}

    def document_metadata(self, asset, *, field_presence, source_url, source_sha256):
        scope = self.authorize('document', asset, 'metadata_only')
        permitted = {'author', 'creator', 'producer', 'location', 'custom_properties'}
        if (not isinstance(field_presence, dict) or not set(field_presence) <= permitted
                or any(type(value) is not bool for value in field_presence.values())):
            raise ValueError('PXI_DOCUMENT_METADATA_INVALID')
        present = sorted(key for key, value in field_presence.items() if value)
        now = self.clock().isoformat()
        records = [dict(provider='AUTHORIZED_DOCUMENT_METADATA', source_id=field,
            entity_ref='document:' + hashlib.sha256(asset.encode()).hexdigest(),
            category='document_metadata', status='SOURCE_REPORTED', severity='LOW',
            source_url=source_url, published_at=now, retrieved_at=now,
            raw_sha256=source_sha256, authorization_ref='scope:' + scope.proof_sha256)
            for field in present]
        return {'fields_present': present, 'records': self._record_batch(records), 'values_retained': False}

    def account_breach_notifications(self, account, *, api_key, transport=None):
        """Approved provider notification ONLY: no dump, password or credential test."""
        scope = self.authorize('account', account, 'breach_notifications')
        if not re.fullmatch(r'[^\s/@]{1,100}@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}', account):
            raise ValueError('PXI_ACCOUNT_INVALID')
        if not isinstance(api_key, str) or not api_key:
            return {'provider': 'HIBP', 'state': 'CREDENTIAL_REQUIRED', 'retrieval_verified': False}
        endpoint = 'https://haveibeenpwned.com/api/v3/breachedaccount/' + quote(account, safe='')
        try:
            status, raw = bounded_get(endpoint, params={'truncateResponse': 'false', 'includeUnverified': 'false'},
                headers={'hibp-api-key': api_key, 'User-Agent': 'PRIME-PXI/1.0'}, transport=transport)
            if status == 404:
                return {'provider': 'HIBP', 'state': 'NO_PROVIDER_MATCH',
                        'retrieval_verified': True, 'account_security_verified': False}
            if status != 200:
                return {'provider': 'HIBP', 'state': 'UNAVAILABLE', 'http_status': status,
                        'retrieval_verified': False}
            rows = strict_json(raw)
            if not isinstance(rows, list) or len(rows) > 500:
                raise ValueError('PXI_PROVIDER_SCHEMA_INVALID')
            minimized = []
            for row in rows:
                if (not isinstance(row, dict) or row.get('IsVerified') is not True or row.get('IsFabricated') is not False
                        or not ID.fullmatch(row.get('Name', ''))):
                    raise ValueError('PXI_PROVIDER_SCHEMA_INVALID')
                published = row['AddedDate']
                stamp(published)
                minimized.append({'name': row['Name'], 'published_at': published})
            now = self.clock().isoformat()
            records = []
            for row in minimized:
                records.append(dict(provider='HIBP_NOTIFICATION', source_id=row['name'],
                    entity_ref='account-scope:' + scope.proof_sha256,
                    category='breach', status='SOURCE_REPORTED', severity='HIGH',
                    source_url='https://haveibeenpwned.com/', published_at=row['published_at'],
                    retrieved_at=now, raw_sha256=hashlib.sha256(canonical_bytes(row)).hexdigest(),
                    authorization_ref='scope:' + scope.proof_sha256))
            recorded = self._record_batch(records)
            return {'provider': 'HIBP', 'state': 'RETRIEVED', 'retrieval_verified': True,
                    'records_ingested': len(recorded), 'credential_testing_performed': False,
                    'plaintext_passwords_requested': False, 'account_identifier_retained': False}
        except (httpx.HTTPError, ValueError, KeyError, TypeError, UnicodeError):
            return {'provider': 'HIBP', 'state': 'UNAVAILABLE', 'retrieval_verified': False}

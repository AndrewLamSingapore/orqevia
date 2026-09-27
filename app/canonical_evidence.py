"""Candidate-only reader for host-admitted immutable source bundles.

This module does not fetch Git, authorize actors, update SSOT, or establish live
runtime/physical truth. A host must admit the manifest digest and source scope.
User/model predicates are data; only exact source comparisons are implemented.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .evidence_product import CLAIM_STATES, VERIFICATION_STATES


class SourceUnavailable(ValueError):
    """A bounded reason code; never includes file contents or credentials."""


def _hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{' + str(length) + r'}', value) is not None


def _logical_path(value: Any) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 500
            and not any(ord(c) < 32 or c in '\\:' for c in value)
            and not value.startswith('/') and PurePosixPath(value).as_posix() == value
            and all(part not in {'.', '..'} for part in value.split('/')))


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise SourceUnavailable('INVALID_SOURCE_TIME')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise SourceUnavailable('INVALID_SOURCE_TIME') from None


def _json(raw: bytes) -> Any:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise SourceUnavailable('AMBIGUOUS_JSON')
            value[key] = item
        return value

    def constant(_):
        raise SourceUnavailable('NONFINITE_JSON')

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise SourceUnavailable('NONFINITE_JSON')
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
    except (ValueError, UnicodeError, RecursionError):
        raise SourceUnavailable('INVALID_SOURCE_JSON') from None


def _json_value(value: Any, depth: int = 0) -> bool:
    if depth > 16:
        return False
    if value is None or type(value) in {str, bool, int}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_value(item, depth + 1) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json_value(item, depth + 1) for key, item in value.items())
    return False


@dataclass(frozen=True)
class SourcePolicy:
    root: Path
    manifest_sha256: str
    allowed_sources: frozenset[tuple[str, str]]
    max_source_age_seconds: int
    max_retrieval_age_seconds: int
    max_source_bytes: int = 1_048_576
    max_manifest_bytes: int = 65_536

    def __post_init__(self):
        object.__setattr__(self, 'root', Path(self.root))
        object.__setattr__(self, 'allowed_sources', frozenset(self.allowed_sources))
        if not self.root.is_absolute() or '..' in self.root.parts or not _hex(self.manifest_sha256, 64):
            raise ValueError('Host must supply an absolute root and trusted manifest digest')
        if not self.allowed_sources or any(not isinstance(repo, str) or not repo.strip()
                                          or not _logical_path(path) for repo, path in self.allowed_sources):
            raise ValueError('Host must supply exact repository/path scope')
        for value in (self.max_source_age_seconds, self.max_retrieval_age_seconds,
                      self.max_source_bytes, self.max_manifest_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError('Positive bounded limits are required')


@dataclass(frozen=True)
class Predicate:
    repository: str
    path: str
    selector: tuple[str | int, ...]
    operator: str
    expected: Any
    commit: str | None = None  # Explicit historical lookup; never a freshness override.


class CanonicalEvidenceReader:
    def __init__(self, policy: SourcePolicy, *, clock: Callable[[], datetime] | None = None):
        self.policy = policy
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _read(self, path: Path, limit: int, expected_hash: str, expected_bytes: int | None = None) -> bytes:
        """Reject traversal/reparse paths, bind the opened file, then verify bytes."""
        try:
            path.relative_to(self.policy.root)
            chain = list(reversed(path.parents)) + [path]
            before = []
            for part in chain:
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise SourceUnavailable('UNSAFE_SOURCE_PATH')
                if part != path and not stat.S_ISDIR(info.st_mode):
                    raise SourceUnavailable('UNSAFE_SOURCE_PATH')
                before.append((part, info))
            info = before[-1][1]
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise SourceUnavailable('SOURCE_SIZE_INVALID')
            if expected_bytes is not None and info.st_size != expected_bytes:
                raise SourceUnavailable('SOURCE_LENGTH_MISMATCH')
            with path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise SourceUnavailable('SOURCE_CHANGED_DURING_READ')
                for part, prior in before:
                    current = part.lstat()
                    if ((current.st_dev, current.st_ino) != (prior.st_dev, prior.st_ino)
                            or stat.S_ISLNK(current.st_mode)
                            or getattr(current, 'st_file_attributes', 0) & 0x400):
                        raise SourceUnavailable('SOURCE_CHANGED_DURING_READ')
                raw = stream.read(limit + 1)
                after = os.fstat(stream.fileno())
            if (len(raw) != info.st_size or len(raw) > limit
                    or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
                raise SourceUnavailable('SOURCE_CHANGED_DURING_READ')
            if hashlib.sha256(raw).hexdigest() != expected_hash:
                raise SourceUnavailable('SOURCE_DIGEST_MISMATCH')
            return raw
        except SourceUnavailable:
            raise
        except (OSError, ValueError):
            raise SourceUnavailable('SOURCE_UNAVAILABLE') from None

    def _manifest(self) -> dict[str, Any]:
        manifest = _json(self._read(self.policy.root / 'manifest.json', self.policy.max_manifest_bytes,
                                    self.policy.manifest_sha256))
        if (not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'canonical_commits', 'sources'}
                or manifest.get('schema_version') != 'canonical-source-bundle.v1'
                or not isinstance(manifest.get('canonical_commits'), dict)
                or not isinstance(manifest.get('sources'), list) or len(manifest['sources']) > 128):
            raise SourceUnavailable('INVALID_MANIFEST')
        seen, current = set(), set()
        for source in manifest['sources']:
            required = {'repository', 'path', 'commit', 'sha256', 'bytes', 'observed_at', 'retrieved_at', 'temporal_state'}
            if not isinstance(source, dict) or not required <= source.keys() or source.keys() - required - {'version'}:
                raise SourceUnavailable('INVALID_MANIFEST')
            repo, path, commit = source.get('repository'), source.get('path'), source.get('commit')
            if (not isinstance(repo, str) or not _logical_path(path) or not _hex(commit, 40)
                    or not _hex(source.get('sha256'), 64) or type(source.get('bytes')) is not int
                    or not 0 <= source['bytes'] <= self.policy.max_source_bytes
                    or source.get('temporal_state') not in {'CURRENT', 'HISTORICAL', 'SUPERSEDED'}
                    or ('version' in source and (not isinstance(source['version'], str) or not 0 < len(source['version']) <= 100))):
                raise SourceUnavailable('INVALID_SOURCE_REFERENCE')
            key = (repo, path, commit)
            if key in seen:
                raise SourceUnavailable('AMBIGUOUS_SOURCE_REFERENCE')
            seen.add(key)
            observed, retrieved = _time(source.get('observed_at')), _time(source.get('retrieved_at'))
            if observed > retrieved:
                raise SourceUnavailable('INVALID_SOURCE_TIME_ORDER')
            if source['temporal_state'] == 'CURRENT':
                if (repo, path) in current or manifest['canonical_commits'].get(repo) != commit:
                    raise SourceUnavailable('AMBIGUOUS_CURRENT_SOURCE')
                current.add((repo, path))
        return manifest

    @staticmethod
    def _comparison(actual: Any, operator: str, expected: Any) -> bool:
        if operator == 'eq':
            return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
        if operator == 'length_eq' and isinstance(actual, (list, dict)) and type(expected) is int:
            return len(actual) == expected
        if operator == 'contains' and isinstance(actual, list):
            return any(CanonicalEvidenceReader._comparison(item, 'eq', expected) for item in actual)
        if operator in {'lt', 'lte', 'gt', 'gte'} and all(type(v) in {int, float} and math.isfinite(v) for v in (actual, expected)):
            return {'lt': actual < expected, 'lte': actual <= expected,
                    'gt': actual > expected, 'gte': actual >= expected}[operator]
        raise SourceUnavailable('UNSUPPORTED_PREDICATE')

    @staticmethod
    def _unknown(reason: str) -> dict[str, Any]:
        return {'claim_state': 'UNKNOWN', 'verification_state': 'UNVERIFIED', 'reason': reason,
                'source': None, 'matched': None, 'content_is_authority': False,
                'may_update_truth_plane': False, 'grants_authority': False}

    def _assess(self, query: Predicate, manifest: dict[str, Any], now: datetime,
                cache: dict[str, Any]) -> dict[str, Any]:
        if (not isinstance(query, Predicate) or not _logical_path(query.path)
                or not isinstance(query.repository, str) or (query.repository, query.path) not in self.policy.allowed_sources
                or not isinstance(query.selector, tuple) or len(query.selector) > 16
                or any(type(part) not in {str, int} or (type(part) is int and part < 0) for part in query.selector)
                or query.commit is not None and not _hex(query.commit, 40)):
            raise SourceUnavailable('QUERY_NOT_ALLOWED')
        try:
            if not _json_value(query.expected) or len(json.dumps(query.expected, allow_nan=False)) > 16_384:
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            raise SourceUnavailable('INVALID_EXPECTED_VALUE') from None
        sources = [s for s in manifest['sources'] if (s['repository'], s['path']) == (query.repository, query.path)
                   and (s['commit'] == query.commit if query.commit else s['temporal_state'] == 'CURRENT')]
        if len(sources) != 1:
            raise SourceUnavailable('SOURCE_REFERENCE_UNAVAILABLE')
        source = sources[0]
        key = source['sha256']
        if key not in cache:
            raw = self._read(self.policy.root / 'objects' / key, self.policy.max_source_bytes, key, source['bytes'])
            cache[key] = (_json(raw), len(raw))
        actual, byte_count = cache[key]
        if byte_count != source['bytes']:
            raise SourceUnavailable('SOURCE_LENGTH_MISMATCH')
        for part in query.selector:
            if isinstance(actual, dict) and type(part) is str and part in actual:
                actual = actual[part]
            elif isinstance(actual, list) and type(part) is int and part < len(actual):
                actual = actual[part]
            else:
                raise SourceUnavailable('SELECTOR_UNAVAILABLE')
        matched = self._comparison(actual, query.operator, query.expected)
        source_age = (now - _time(source['observed_at'])).total_seconds()
        retrieval_age = (now - _time(source['retrieved_at'])).total_seconds()
        if min(source_age, retrieval_age) < 0:
            raise SourceUnavailable('FUTURE_SOURCE_TIME')
        stale = (source['temporal_state'] != 'CURRENT' or source_age > self.policy.max_source_age_seconds
                 or retrieval_age > self.policy.max_retrieval_age_seconds)
        return {'claim_state': 'STALE' if stale else 'SOURCE_SUPPORTED' if matched else 'CONTRADICTED',
                'verification_state': 'UNVERIFIED' if stale else 'VERIFIED' if matched else 'CONTRADICTED',
                'reason': 'HISTORICAL_OR_EXPIRED_SOURCE' if stale else 'SOURCE_MATCH' if matched else 'SOURCE_MISMATCH',
                'source': {**source, 'manifest_sha256': self.policy.manifest_sha256},
                'selected_value': actual, 'matched': matched, 'content_is_authority': False,
                'may_update_truth_plane': False, 'grants_authority': False}

    def evaluate(self, predicates: list[Predicate]) -> dict[str, Any]:
        if not isinstance(predicates, list) or not 1 <= len(predicates) <= 16:
            raise ValueError('One to sixteen predicates are required')
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError('Host clock must be timezone-aware')
        try:
            manifest, error = self._manifest(), None
        except SourceUnavailable as failure:
            manifest, error = {}, str(failure)
        claims, cache = [], {}
        for query in predicates:
            try:
                if error:
                    raise SourceUnavailable(error)
                claims.append(self._assess(query, manifest, now, cache))
            except (SourceUnavailable, TypeError, ValueError, OverflowError, RecursionError) as failure:
                reason = str(failure) if isinstance(failure, SourceUnavailable) else 'INVALID_PREDICATE'
                claims.append(self._unknown(reason))
        states = {claim['verification_state'] for claim in claims}
        state = ('VERIFIED' if states == {'VERIFIED'} else 'CONTRADICTED' if 'CONTRADICTED' in states
                 else 'PARTIAL' if 'VERIFIED' in states else 'UNVERIFIED')
        assert state in VERIFICATION_STATES and all(c['claim_state'] in CLAIM_STATES for c in claims)
        return {'verification_state': state, 'claims': claims, 'evaluated_at': now.isoformat(),
                'verification_scope': 'ADMITTED_SOURCE_PREDICATE_COMPARISON_ONLY',
                'remote_head_independently_observed': False, 'live_runtime_verified': False,
                'may_update_truth_plane': False, 'grants_authority': False}

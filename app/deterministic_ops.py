"""Explicit exact operations and content-addressed bounded cache; no model calls.

No inferred objectives or token-saving estimates. Retrieval always validates live
source bytes before reuse; this is not a second Registry/artifact store.
"""
from collections import OrderedDict
import hashlib
import json
from threading import RLock
from .sink_guard import safe_local_path


class DeterministicOps:
    VERSION = '1.0'

    def __init__(self, *, source_version, max_entries=128):
        if not isinstance(source_version, str) or not source_version or not 1 <= max_entries <= 1024:
            raise ValueError('Bounded cache and explicit source version required')
        self.source_version = source_version
        self.max_entries = max_entries
        self._cache = OrderedDict()
        self._lock = RLock()
        self.metrics = {'hits': 0, 'misses': 0, 'operations': 0, 'model_calls': 0}

    def execute(self, operation, content: bytes):
        with self._lock:
            return self._execute(operation, content)

    def _execute(self, operation, content: bytes):
        if not isinstance(content, bytes) or len(content) > 2_000_000:
            raise ValueError('Bounded bytes required')
        if operation not in {'sha256', 'json_format', 'json_validate'}:
            raise ValueError('Unsupported deterministic operation')
        key = (self.VERSION, self.source_version, operation, hashlib.sha256(content).hexdigest())
        self.metrics['operations'] += 1
        if key in self._cache:
            self.metrics['hits'] += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        self.metrics['misses'] += 1
        if operation == 'sha256':
            result = hashlib.sha256(content).hexdigest()
        else:
            def invalid_constant(value):
                raise ValueError('Non-finite JSON constant')
            def unique_object(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError('Duplicate JSON key')
                    value[key] = item
                return value
            value = json.loads(content, parse_constant=invalid_constant, object_pairs_hook=unique_object)
            result = True if operation == 'json_validate' else json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        self._cache[key] = result
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return result

    def retrieve_file(self, root, relative, *, expected_sha256=None):
        path = safe_local_path(root, relative)
        with path.open('rb') as stream:
            raw = stream.read(2_000_001)
        digest = self.execute('sha256', raw)
        if expected_sha256 is not None and digest != expected_sha256.lower():
            raise ValueError('Source integrity mismatch')
        return raw, digest

    def retrieve_artifact(self, factory, artifact_id):
        # The existing factory owns ID/path/hash validation; never cache stale receipts.
        return factory.retrieve(artifact_id)

    def validate_schema(self, value, fields):
        """Exact flat-object type schema, deliberately not full JSON Schema."""
        types = {'string': str, 'integer': int, 'number': (int, float),
                 'boolean': bool, 'array': list, 'object': dict, 'null': type(None)}
        if not isinstance(fields, dict) or any(t not in types for t in fields.values()):
            raise ValueError('Unsupported flat schema')
        if not isinstance(value, dict) or set(value) != set(fields):
            return False
        for key, kind in fields.items():
            if not isinstance(value[key], types[kind]) or (kind in {'integer', 'number'} and isinstance(value[key], bool)):
                return False
        json.dumps(value, allow_nan=False)
        return True

    def retrieve_registry(self):
        from .agent_registry import REGISTRY_PATH
        # Read canonical source freshly, rather than a cached alternate Registry.
        raw, digest = self.retrieve_file(REGISTRY_PATH.parent, REGISTRY_PATH.name)
        return json.loads(raw), digest

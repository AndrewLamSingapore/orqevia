"""Local continuity evidence for the existing bounded engineering helper.

This is not an executor, scheduler, authorization grant, or signed verification
service. Its trusted caller supplies the isolated root and callback fingerprint.
Hash chains detect accidental/tampered bytes against retained checkpoints, not
an attacker able to rewrite all of the local evidence and its trusted anchors.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import uuid


HEX = re.compile(r'^[0-9a-f]{64}$')
TASK = re.compile(r'^[0-9a-f]{32}$')
FILES = re.compile(r'^(candidate-[1-5]\.wat|verification-[1-5]\.json|result\.json|checkpoint-[0-9]{4}\.json)$')


class ContinuityError(RuntimeError):
    """Explicit fail-closed recovery error; never permission to replay a callback."""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def no_links(path):
    path = Path(path).absolute()
    for component in [*reversed(path.parents), path]:
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ContinuityError('PATH_LINK_OR_REPARSE_POINT')
    return path


def fingerprint(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ContinuityError('EXECUTION_FINGERPRINT_REQUIRED_SHA256')
    return value


class Journal:
    def __init__(self, root, task_id, *, create=False):
        if not isinstance(task_id, str) or not TASK.fullmatch(task_id):
            raise ContinuityError('INVALID_TASK_ID')
        self.root = no_links(root)
        self.directory = no_links(self.root / task_id)
        self.task_id = task_id
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
            self.directory.mkdir()
        if not self.directory.is_dir():
            raise ContinuityError('CHECKPOINT_DIRECTORY_MISSING')
        self.events = []
        self.previous = '0' * 64

    def path(self, name):
        if not isinstance(name, str) or not FILES.fullmatch(name):
            raise ContinuityError('INVALID_ARTIFACT_PATH')
        return no_links(self.directory / name)

    def read(self, name):
        path = self.path(name)
        try:
            if not path.is_file():
                raise ContinuityError('ARTIFACT_MISSING:' + name)
            return path.read_bytes()
        except OSError as exc:
            raise ContinuityError('ARTIFACT_UNREADABLE:' + name) from exc

    def json(self, name):
        try:
            return json.loads(self.read(name))
        except (ValueError, UnicodeError) as exc:
            raise ContinuityError('ARTIFACT_MALFORMED:' + name) from exc

    def _sync_directory(self):
        # Windows fsync supports regular files, not directory descriptors. Files
        # are fsynced before rename; absent/truncated evidence fails closed later.
        if os.name != 'nt':
            fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def write(self, name, raw):
        path = self.path(name)
        if path.exists():
            raise ContinuityError('ARTIFACT_ALREADY_EXISTS:' + name)
        temp = no_links(self.directory / ('.pending-' + uuid.uuid4().hex))
        with temp.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Lock ownership excludes cooperating writers. A leftover temporary or
        # unreferenced artifact is preserved and rejects subsequent resumption.
        self.path(name)
        if path.exists():
            raise ContinuityError('ARTIFACT_ALREADY_EXISTS:' + name)
        os.rename(temp, path)
        self._sync_directory()
        return digest(raw)

    def append(self, payload):
        event = {'schema': 1, 'sequence': len(self.events) + 1,
                 'previous_sha256': self.previous, 'task_id': self.task_id,
                 'payload': payload}
        raw = encode(event)
        self.write(f'checkpoint-{event["sequence"]:04d}.json', raw)
        self.events.append(payload)
        self.previous = digest(raw)

    @contextmanager
    def locked(self):
        path = no_links(self.directory / '.lock')
        owner = encode({'pid': os.getpid(), 'nonce': uuid.uuid4().hex})
        try:
            with path.open('xb') as stream:
                stream.write(owner)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise ContinuityError('RUN_LOCKED_RECONCILIATION_REQUIRED') from exc
        try:
            yield
        finally:
            no_links(path)
            if path.read_bytes() != owner:
                raise ContinuityError('LOCK_OWNERSHIP_CHANGED')
            path.unlink()
            self._sync_directory()

    def load(self, execution_fingerprint):
        fingerprint(execution_fingerprint, required=True)
        self.events, self.previous = [], '0' * 64
        names = sorted(p.name for p in self.directory.iterdir() if p.name.startswith('checkpoint-'))
        if not names or len(names) > 22:
            raise ContinuityError('CHECKPOINT_MISSING_OR_UNBOUNDED')
        known = {'.lock'}
        previous_phase, current_attempt = None, 0
        for sequence, name in enumerate(names, 1):
            if name != f'checkpoint-{sequence:04d}.json':
                raise ContinuityError('CHECKPOINT_SEQUENCE_INVALID')
            raw = self.read(name)
            event = self.json(name)
            if not isinstance(event, dict) or set(event) != {'schema', 'sequence', 'previous_sha256', 'task_id', 'payload'}:
                raise ContinuityError('CHECKPOINT_SCHEMA_INVALID')
            try:
                canonical = encode(event)
            except (TypeError, ValueError) as exc:
                raise ContinuityError('CHECKPOINT_ENCODING_INVALID') from exc
            if raw != canonical:
                raise ContinuityError('CHECKPOINT_NONCANONICAL_BYTES')
            if event['schema'] != 1 or event['sequence'] != sequence or event['task_id'] != self.task_id or event['previous_sha256'] != self.previous:
                raise ContinuityError('CHECKPOINT_BINDING_INVALID')
            value = event['payload']
            if not isinstance(value, dict):
                raise ContinuityError('CHECKPOINT_PAYLOAD_INVALID')
            phase = value.get('phase')
            if sequence == 1:
                if set(value) != {'phase', 'objective', 'objective_sha256', 'execution_fingerprint', 'max_attempts', 'model', 'backend'}:
                    raise ContinuityError('CHECKPOINT_INITIAL_FIELDS_INVALID')
                if phase != 'READY_BUILD' or value.get('execution_fingerprint') != execution_fingerprint:
                    raise ContinuityError('EXECUTION_FINGERPRINT_MISMATCH')
                if not isinstance(value.get('objective'), str) or digest(value['objective'].encode('utf-8')) != value.get('objective_sha256'):
                    raise ContinuityError('OBJECTIVE_DIGEST_MISMATCH')
                if type(value.get('max_attempts')) is not int or not 1 <= value['max_attempts'] <= 5:
                    raise ContinuityError('ATTEMPT_BUDGET_INVALID')
                if any(value[key] is not None and not isinstance(value[key], str) for key in ('model', 'backend')):
                    raise ContinuityError('EXECUTION_METADATA_INVALID')
            else:
                allowed = {'READY_BUILD': {'BUILD_STARTED'}, 'BUILD_STARTED': {'CANDIDATE_PRESERVED'},
                           'CANDIDATE_PRESERVED': {'VERIFY_STARTED'}, 'VERIFY_STARTED': {'ATTEMPT_RECORDED'},
                           'ATTEMPT_RECORDED': {'BUILD_STARTED', 'TERMINAL'}, 'TERMINAL': set()}
                if phase not in allowed.get(previous_phase, set()):
                    raise ContinuityError('CHECKPOINT_TRANSITION_INVALID')
                fields = {'BUILD_STARTED': {'phase', 'attempt'},
                          'CANDIDATE_PRESERVED': {'phase', 'attempt', 'candidate', 'sha256', 'build_seconds'},
                          'VERIFY_STARTED': {'phase', 'attempt'},
                          'ATTEMPT_RECORDED': {'phase', 'attempt', 'receipt', 'sha256'},
                          'TERMINAL': {'phase', 'result', 'sha256'}}
                if set(value) != fields[phase]:
                    raise ContinuityError('CHECKPOINT_FIELDS_INVALID')
                if phase == 'BUILD_STARTED':
                    current_attempt += 1
                if phase != 'TERMINAL' and value.get('attempt') != current_attempt:
                    raise ContinuityError('ATTEMPT_SEQUENCE_INVALID')
                if current_attempt > self.events[0]['max_attempts']:
                    raise ContinuityError('ATTEMPT_BUDGET_EXHAUSTED')
                if phase == 'CANDIDATE_PRESERVED':
                    seconds = value.get('build_seconds')
                    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                        raise ContinuityError('BUILD_OBSERVATION_INVALID')
                    expected = f'candidate-{current_attempt}.wat'
                    if value.get('candidate') != expected or digest(self.read(expected)) != value.get('sha256'):
                        raise ContinuityError('CANDIDATE_DIGEST_MISMATCH')
                    known.add(expected)
                if phase == 'ATTEMPT_RECORDED':
                    expected = f'verification-{current_attempt}.json'
                    if value.get('receipt') != expected or digest(self.read(expected)) != value.get('sha256'):
                        raise ContinuityError('VERIFICATION_DIGEST_MISMATCH')
                    receipt = self.json(expected)
                    candidate = self.events[-2]
                    if (not isinstance(receipt, dict) or receipt.get('attempt') != current_attempt
                            or receipt.get('candidate') != candidate['candidate'] or receipt.get('sha256') != candidate['sha256']
                            or not isinstance(receipt.get('verification'), dict)
                            or receipt['verification'].get('candidate_sha256') != candidate['sha256']):
                        raise ContinuityError('VERIFICATION_CANDIDATE_BINDING_INVALID')
                    observation = receipt.get('observation')
                    if not isinstance(observation, dict):
                        raise ContinuityError('VERIFICATION_OBSERVATION_INVALID')
                    for field in ('builder_seconds', 'verifier_seconds'):
                        seconds = observation.get(field)
                        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                            raise ContinuityError('VERIFICATION_OBSERVATION_INVALID')
                    known.add(expected)
                if phase == 'TERMINAL':
                    if value.get('result') != 'result.json' or digest(self.read('result.json')) != value.get('sha256'):
                        raise ContinuityError('RESULT_DIGEST_MISMATCH')
                    known.add('result.json')
            known.add(name)
            self.events.append(value)
            self.previous, previous_phase = digest(raw), phase
        if {p.name for p in self.directory.iterdir()} - known:
            raise ContinuityError('UNREFERENCED_EVIDENCE_RECONCILIATION_REQUIRED')
        return self.events

"""Authenticated, source-only adapter to the existing governed numeric MLP.

The operator must inject artifact lineage, certification, runtime readiness and
evidence persistence from their owning domains. Nothing here approves/trains a
model, enrolls an agent, owns a new store, or exposes an HTTP route. The fabric's
independent approval and capability-decision verifiers remain mandatory.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import threading
from uuid import UUID

from .client_auth import authenticate_owner
from .agent_registry import registered_agent_ids
from .mlp_fabric import MLPCapabilityFabric, MAX_INFER_MULTIPLIES, _matrix, validate_artifact

_SHA = re.compile(r'[0-9a-f]{64}\Z')
_MODEL = re.compile(r'mlp-[0-9a-f]{20}\Z')
_VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+\Z')
_IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z')
_FIELDS = frozenset(('agent_id', 'model_id', 'model_artifact_hash', 'model_version',
                     'trace_id', 'rows', 'capability_decision'))


class MLPExecutionError(RuntimeError):
    """Sanitized terminal failure; never automatically replay admitted work."""
    def __init__(self, code, *, execution_admitted=False):
        super().__init__(code)
        self.code = code
        self.execution_admitted = execution_admitted
        self.retry_authorized = False


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class GovernedMLPExecution:
    def __init__(self, fabric: MLPCapabilityFabric, *, read_current_artifact=None,
                 read_certification=None, runtime_health=None, record_evidence=None):
        self.fabric = fabric
        self.read_current_artifact = read_current_artifact
        self.read_certification = read_certification
        self.runtime_health = runtime_health
        self.record_evidence = record_evidence
        self._slot = threading.BoundedSemaphore(1)

    def _current(self, request):
        try:
            current = self.read_current_artifact(request['model_id'])
            registered = self.fabric.models.get(request['model_id'])
            validate_artifact(current)
            validate_artifact(registered)
            if (current['approval_state'] != 'APPROVED' or current['health'] != 'HEALTHY'
                or current['model_id'] != request['model_id']
                or current['model_artifact_hash'] != request['model_artifact_hash']
                or current['version'] != request['model_version']
                or _canonical(current) != _canonical(registered)
                or not callable(self.fabric.verify_approval)
                or self.fabric.verify_approval(deepcopy(current['approval'])) is not True):
                raise ValueError()
            return deepcopy(current)
        except Exception:
            raise MLPExecutionError('MLP_CURRENT_APPROVED_LINEAGE_UNAVAILABLE') from None

    def _route(self, request):
        capability = 'responsibility.' + request['agent_id']
        try:
            certification = deepcopy(self.read_certification(request['agent_id'], capability))
            if self.runtime_health() is not True:
                raise PermissionError()
            from .agent_capability_route import select_agent_capability_route
            route = select_agent_capability_route(capability, certification,
                authority_allowed=True, runtime_healthy=True, tools_available=True,
                model_available=True)
            if route.state != 'READY' or route.agent_id != request['agent_id']:
                raise PermissionError()
            return certification
        except Exception:
            raise MLPExecutionError('MLP_CURRENT_AGENT_ROUTE_UNAVAILABLE') from None

    @staticmethod
    def _request(request):
        if type(request) is not dict or set(request) != _FIELDS:
            raise MLPExecutionError('MLP_REQUEST_INVALID')
        if (type(request['agent_id']) is not str
            or request['agent_id'] not in registered_agent_ids(include_orchestrator=False)
            or type(request['model_id']) is not str or not _MODEL.fullmatch(request['model_id'])
            or type(request['model_artifact_hash']) is not str or not _SHA.fullmatch(request['model_artifact_hash'])
            or type(request['model_version']) is not str or not _VERSION.fullmatch(request['model_version'])
            or type(request['trace_id']) is not str or len(request['trace_id']) != 36
            or type(request['rows']) is not list or not 1 <= len(request['rows']) <= 1000
            or type(request['capability_decision']) is not dict):
            raise MLPExecutionError('MLP_REQUEST_INVALID')
        try:
            if str(UUID(request['trace_id'])) != request['trace_id']:
                raise ValueError()
        except ValueError:
            raise MLPExecutionError('MLP_REQUEST_INVALID') from None
        decision_id = request['capability_decision'].get('decision_id')
        if type(decision_id) is not str or not _IDENTITY.fullmatch(decision_id):
            raise MLPExecutionError('MLP_CAPABILITY_DECISION_INVALID')
        return deepcopy(request)

    def execute(self, request, authorization):
        authenticate_owner(authorization)  # Before any artifact/authority/store access.
        if (not isinstance(self.fabric, MLPCapabilityFabric)
            or not all(callable(callback) for callback in (self.read_current_artifact,
                self.read_certification, self.runtime_health, self.record_evidence))):
            raise MLPExecutionError('MLP_DOMAIN_INTEGRATION_UNAVAILABLE')
        request = self._request(request)
        if not self._slot.acquire(blocking=False):
            raise MLPExecutionError('MLP_EXECUTION_BUSY')
        admitted = False
        try:
            artifact = self._current(request)
            try:
                _matrix(request['rows'], tuple(artifact['input_schema']['features']))
                widths = [len(artifact['input_schema']['features']), *artifact['architecture']['hidden_layers'], 1]
                if len(request['rows']) * sum(widths[k] * widths[k + 1] for k in range(len(widths) - 1)) > MAX_INFER_MULTIPLIES:
                    raise ValueError()
            except (ValueError, TypeError, KeyError, OverflowError):
                raise MLPExecutionError('MLP_INPUT_OR_COMPUTE_BUDGET_INVALID') from None
            # Existing policy accepts genuine current L6 or L7. Never infer
            # certification from a successful task or a model approval.
            certification = self._route(request)
            # Independent decision verification binds capability, actor, model,
            # model hash and trace inside the unchanged fabric boundary.
            decision = request['capability_decision']
            required = {'agent_id': request['agent_id'], 'model_id': request['model_id'],
                'model_artifact_hash': request['model_artifact_hash'], 'trace_id': request['trace_id'],
                'capability': 'ml.mlp.' + artifact['task']}
            try:
                if (any(decision.get(key) != value for key, value in required.items())
                    or not callable(self.fabric.verify_capability_decision)
                    or self.fabric.verify_capability_decision(deepcopy(decision)) is not True):
                    raise PermissionError()
            except Exception:
                raise MLPExecutionError('MLP_INDEPENDENT_CAPABILITY_DECISION_DENIED') from None
            # Revalidate persisted lineage after authority callbacks and before
            # actual local numeric work; a changed model is never hot-swapped.
            if _canonical(self._current(request)) != _canonical(artifact):
                raise MLPExecutionError('MLP_CURRENT_APPROVED_LINEAGE_UNAVAILABLE')
            # Lineage/authority callbacks may invalidate readiness. Re-read the
            # owning domains immediately before admission; do not hot-swap a
            # different certification into the already-authorized request.
            final_certification = self._route(request)
            if _canonical(final_certification) != _canonical(certification):
                raise MLPExecutionError('MLP_CURRENT_AGENT_ROUTE_UNAVAILABLE')
            admitted = True
            result = self.fabric.infer_for_agent(request['agent_id'], request['model_id'],
                request['rows'], trace_id=request['trace_id'], certification=final_certification,
                capability_decision=decision, runtime_healthy=True)
            if _canonical(self._current(request)) != _canonical(artifact):
                raise MLPExecutionError('MLP_LINEAGE_CHANGED_AFTER_EXECUTION', execution_admitted=True)
            if (type(result) is not dict or result.get('agent_id') != request['agent_id']
                or result.get('trace_id') != request['trace_id'] or result.get('model_id') != request['model_id']
                or result.get('model_version') != request['model_version']
                or result.get('artifact_hash') != request['model_artifact_hash']
                or result.get('authority_decision_id') != decision['decision_id']
                or result.get('mlp_capability') != required['capability']
                or result.get('agent_route_state') != 'READY'
                or result.get('requires_independent_verification') is not True
                or type(result.get('output')) is not list or len(result['output']) != len(request['rows'])
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in result['output'])
                or type(result.get('latency_ms')) not in (int, float) or not math.isfinite(result['latency_ms'])
                or result['latency_ms'] < 0):
                raise MLPExecutionError('MLP_RESULT_BINDING_INVALID', execution_admitted=True)
            output_digest = hashlib.sha256(_canonical(result['output'])).hexdigest()
            evidence = {'schema_version': 'jarvis.mlp-execution-evidence.v1',
                'trace_id': request['trace_id'], 'agent_id': request['agent_id'],
                'model_id': request['model_id'], 'model_version': artifact['version'],
                'model_artifact_hash': artifact['model_artifact_hash'], 'dataset_hash': artifact['dataset_hash'],
                'approval_sha256': hashlib.sha256(_canonical(artifact['approval'])).hexdigest(),
                'capability': required['capability'], 'authority_decision_id': decision['decision_id'],
                'output_sha256': output_digest, 'output_rows': len(result['output']),
                'latency_ms': result['latency_ms'], 'observed_at': datetime.now(timezone.utc).isoformat(),
                'verification': 'UNVERIFIED', 'status': 'EXECUTED_VERIFY_REQUIRED'}
            digest = hashlib.sha256(_canonical(evidence)).hexdigest()
            try:
                receipt = self.record_evidence(deepcopy({**evidence, 'evidence_sha256': digest}))
                if (type(receipt) is not dict or set(receipt) != {'record_id', 'evidence_sha256'}
                    or type(receipt['record_id']) is not str or not _IDENTITY.fullmatch(receipt['record_id'])
                    or receipt['evidence_sha256'] != digest):
                    raise ValueError()
            except Exception:
                raise MLPExecutionError('MLP_EVIDENCE_PERSISTENCE_UNCERTAIN', execution_admitted=True) from None
            return {**evidence,
                'schema_version': 'jarvis.mlp-execution.v1', 'output': list(result['output']),
                'evidence_ref': receipt['record_id'], 'evidence_sha256': digest,
                'persistence': 'CALLBACK_ACKNOWLEDGED_NOT_RESTART_PROOF',
                'production_acceptance': 'UNVERIFIED', 'independent_attestation': 'UNVERIFIED'}
        except MLPExecutionError as exc:
            if admitted:
                exc.execution_admitted = True
            raise
        except Exception:
            raise MLPExecutionError('MLP_EXECUTION_UNCERTAIN' if admitted else 'MLP_EXECUTION_DENIED',
                                    execution_admitted=admitted) from None
        finally:
            self._slot.release()

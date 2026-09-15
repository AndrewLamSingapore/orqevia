"""Narrow consequence checks at registered sinks, not per-action TAP gating.

Registration and authorizer are trusted application composition, never model input.
An authorizer must check the concrete payload/scope against existing owner authority.
"""
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

PROTECTED = frozenset({'destructive_outside_workspace', 'history_rewrite',
    'security_change', 'financial_transaction', 'public_publication',
    'external_message', 'material_production_mutation'})


def safe_local_path(root, relative):
    """Resolve an existing/read target under a trusted root; deny Windows escapes."""
    if not isinstance(relative, str) or not relative or ':' in relative or '\x00' in relative:
        raise ValueError('Invalid relative path')
    win = PureWindowsPath(relative)
    if win.is_absolute() or win.drive or win.root or '..' in win.parts:
        raise ValueError('Path escapes trusted root')
    base = Path(root).resolve(strict=True)
    target = base.joinpath(*win.parts).resolve(strict=True)
    if not target.is_relative_to(base):
        raise ValueError('Path escapes trusted root')
    return target


@dataclass(frozen=True)
class SinkIntent:
    connector_id: str
    action_id: str
    operation_tags: frozenset[str]
    task_id: str
    agent_id: str


class SinkGuard:
    def __init__(self, authorizer=None):
        self._authorizer = authorizer

    def check(self, sink, payload, *, task_id, agent_id):
        tags = frozenset(sink.operation_tags)
        if tags - PROTECTED:
            raise ValueError('Unknown consequence tag')
        if not tags:
            return
        intent = SinkIntent(sink.connector_id, sink.action_id, tags, task_id, agent_id)
        if self._authorizer is None or self._authorizer(intent, payload) is not True:
            raise PermissionError('Concrete consequential operation lacks trusted authority')

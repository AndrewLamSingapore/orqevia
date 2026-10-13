"""Owner-authenticated entrypoint for finite recorded agent tool sessions."""
import os
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .client_auth import authenticate_owner
from .agent_tool_bridge import AgentToolBridge, Scope, BridgeConflict

router = APIRouter(prefix='/api/agent-tool-bridge', tags=['recorded-agent-tools'])


class CreateSession(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    job_id: str = Field(min_length=36, max_length=36)
    objective: str = Field(min_length=1, max_length=4000)
    services: list[str] = Field(default_factory=list, max_length=5)
    workspace_operations: list[str] = Field(default_factory=list, max_length=8)
    delegation_targets: list[str] = Field(default_factory=list, max_length=2)
    max_steps: int = Field(default=4, ge=1, le=4)
    max_delegations: int = Field(default=2, ge=0, le=2)


def bridge():
    from .compute_queue_api import queue
    from .objective_api import runtime_snapshot
    return AgentToolBridge(Path(os.getenv('PRIME_DATA_DIR', '/data')) / 'agent-tool-bridge.db',
                           queue, runtime=runtime_snapshot())


def invoke(authorization, operation):
    authenticate_owner(authorization)
    try:
        return operation(bridge())
    except PermissionError:
        raise HTTPException(403, 'Recorded actor or trusted tool scope denied') from None
    except BridgeConflict:
        raise HTTPException(409, 'Recorded bridge state requires reconciliation; no automatic replay') from None
    except KeyError:
        raise HTTPException(404, 'Recorded bridge session or job unavailable') from None
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, 'Invalid bounded bridge request') from None
    except Exception:
        raise HTTPException(503, 'Bridge dependency unavailable') from None


@router.post('/sessions')
def create(body: CreateSession, authorization: str | None = Header(None)):
    return invoke(authorization, lambda tool: tool.register(body.job_id, Scope(
        objective=body.objective, services=tuple(body.services),
        workspace_operations=tuple(body.workspace_operations),
        delegation_targets=tuple(body.delegation_targets), max_steps=body.max_steps,
        max_delegations=body.max_delegations)))


@router.get('/sessions/{job_id}')
def status(job_id: str, authorization: str | None = Header(None)):
    return invoke(authorization, lambda tool: tool.status(job_id))


@router.post('/sessions/{job_id}/execute')
def execute(job_id: str, authorization: str | None = Header(None)):
    return invoke(authorization, lambda tool: tool.execute(job_id))


@router.get('/sessions/{job_id}/receipts/{step_id}')
def receipt(job_id: str, step_id: str, authorization: str | None = Header(None)):
    return invoke(authorization, lambda tool: tool.receipt(job_id, step_id))


@router.post('/sessions/{job_id}/observe')
def observe(job_id: str, authorization: str | None = Header(None)):
    return invoke(authorization, lambda tool: tool.observe(job_id))


@router.post('/sessions/{job_id}/feedback')
def feedback(job_id: str, authorization: str | None = Header(None)):
    return invoke(authorization, lambda tool: tool.feedback(job_id))


@router.post('/sessions/{job_id}/stop')
def stop(job_id: str, authorization: str | None = Header(None)):
    return invoke(authorization, lambda tool: tool.stop(job_id))

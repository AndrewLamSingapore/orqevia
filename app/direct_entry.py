"""Candidate entrypoint. Legacy authority endpoints are not mounted here."""
from contextlib import asynccontextmanager
from fastapi import FastAPI,Header
from .agent_dispatch_api import router as agents
from .objective_api import router as objectives
from .artifact_delivery import router as artifacts
from .interface_node import router as interface
from .interface_contract import router as dell_interface
from .compute_queue_api import router as compute,start_compute_queue,stop_compute_queue
from .action_records import action_ledger,close_ledgers
from .client_auth import authenticate_owner
from .agent_registry import registered_agent_ids
from .agent_cert_event_api import router as certification_events
from .media_api import router as media
from .project_workflows import get_project_workflow_service, router as project_workflows
from .agent_notebook_api import router as agent_notebooks
from .observability import PRIVACY_FASTAPI_TELEMETRY


@asynccontextmanager
async def lifespan(app):
    start_compute_queue()
    get_project_workflow_service().recover_pending()
    try:yield
    finally:
        stop_compute_queue()
        close_ledgers()


app=FastAPI(title='ORQEVIA direct-execution candidate',lifespan=lifespan,telemetry=PRIVACY_FASTAPI_TELEMETRY)
for router in (agents,objectives,artifacts,interface,dell_interface,compute,certification_events,media,project_workflows,agent_notebooks):app.include_router(router)


@app.get('/health')
def health(authorization: str | None=Header(None)):
    authenticate_owner(authorization)
    return {'state':'READY','execution_model':'DIRECT_OBSERVED',
        'agents':len(registered_agent_ids(include_orchestrator=False)),'logging':action_ledger().status()}


@app.post('/api/observability/flush')
def flush(authorization: str | None=Header(None)):
    authenticate_owner(authorization)
    ledger=action_ledger()
    return {'flushed':ledger.flush(),'logging':ledger.status()}

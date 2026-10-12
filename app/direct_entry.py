"""Candidate entrypoint. Legacy authority endpoints are not mounted here."""
from contextlib import asynccontextmanager
from fastapi import FastAPI,Header
from .agent_dispatch_api import router as agents
from .objective_api import router as objectives
from .engineering_api import router as engineering
from .artifact_delivery import router as artifacts
from .interface_node import router as interface
from .interface_contract import router as dell_interface
from .compute_queue_api import router as compute,start_compute_queue,stop_compute_queue
from .action_records import action_ledger,close_ledgers
from .client_auth import authenticate_owner
from .agent_registry import registered_agent_ids
from .agent_cert_event_api import router as certification_events
from .financial_simulation_api import router as financial_simulation


@asynccontextmanager
async def lifespan(app):
    start_compute_queue()
    try:yield
    finally:
        stop_compute_queue()
        close_ledgers()


app=FastAPI(title='PRIME direct-execution candidate',lifespan=lifespan)
for router in (agents,objectives,engineering,artifacts,interface,dell_interface,compute,certification_events,financial_simulation):app.include_router(router)


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

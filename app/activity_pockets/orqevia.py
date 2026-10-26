"""ORQEVIA objective adapter. Factory execution remains independently operable."""
from fastapi import APIRouter, Depends, Header, HTTPException

from .contracts import PocketManifest


def submit_objective(factory, manifest, principal, idempotency_key):
    if manifest.provenance.component != "orqevia":
        raise ValueError("ORQEVIA submission provenance required")
    result = factory.create(manifest, principal, idempotency_key)
    pocket_id = result["id"]
    with factory.store.transaction() as db:
        found = db.execute("SELECT 1 FROM pocket_events WHERE pocket_id=? AND owner=? AND "
                           "json_extract(body,'$.event_type')='orqevia.objective.submitted'",
                           (pocket_id, principal.owner)).fetchone()
        if not found:
            factory.store.event(db, pocket_id, principal.owner, "orqevia", "orqevia.objective.submitted",
                                 {"objective_id": pocket_id, "factory_state": result["state"]})
    return {"task_id": pocket_id, "state": result["state"], "component": "activity-pocket-factory",
            "status_url": "/api/activity-pockets/" + pocket_id, "execution": "autonomous-worker"}


def build_router(provider=None, authenticate=None):
    from .api import default_factory, session_principal
    provider = provider or default_factory
    authenticate = authenticate or session_principal
    router = APIRouter(prefix="/api/agents/objectives", tags=["ORQEVIA activity objectives"])

    @router.post("/activity-pocket", status_code=202)
    def submit(body: PocketManifest, principal=Depends(authenticate), idempotency_key: str = Header()):
        try:
            return submit_objective(provider(), body, principal, idempotency_key)
        except PermissionError:
            raise HTTPException(403, "Objective exceeds owned source or qualification scope") from None
        except ValueError:
            raise HTTPException(409, "Objective contract conflicts with existing state") from None
        except KeyError:
            raise HTTPException(404, "Objective dependency unavailable") from None

    return router

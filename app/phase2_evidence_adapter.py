"""Map Phase 2 objective snapshots to the portable evidence contract."""
from __future__ import annotations

from typing import Any

from app.evidence_product import SCHEMA


def adapt_objective_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("schema_version") != "jarvis.phase2.objective-snapshot.v1" or snapshot.get("authority") != "SYSTEM_RECORD":
        raise ValueError("untrusted Phase 2 snapshot")
    objective=snapshot["objective"]; checkpoint=objective["checkpoint"]
    observations=[]; claims=[]
    for index,fact in enumerate(checkpoint.get("facts",[])):
        oid=f"{objective['objective_id']}:fact:{index}"
        observations.append({"observation_id":oid,"source":"phase2-checkpoint","value":fact,
                             "observed_at":snapshot["snapshot_at"],"verification_ref":fact.get("evidence") if isinstance(fact,dict) else None})
        claims.append({"claim_id":f"{objective['objective_id']}:claim:{index}","text":str(fact),
                       "state":"OBSERVED" if isinstance(fact,dict) and fact.get("evidence") else "INFERRED",
                       "evidence_refs":[oid] if isinstance(fact,dict) and fact.get("evidence") else []})
    for evidence in snapshot.get("evidence",[]):
        observations.append({"observation_id":evidence["evidence_id"],"source":evidence["source"],
                             "value":{"payload_digest":evidence["payload_digest"],"evidence_type":evidence["evidence_type"]},
                             "observed_at":str(evidence["created_at"]),"verification_ref":evidence["provenance"]})
    effects=[]
    for effect in snapshot.get("effects",[]):
        receipt=__import__('json').loads(effect["receipt_json"])
        evidence_id=receipt.get("evidence_id")
        effects.append({"effect_id":effect["operation_id"],"description":"Phase 2 recorded effect",
                        "state":"VERIFIED" if effect["verified"] else "OBSERVED",
                        "observation_refs":[evidence_id] if evidence_id else []})
    verification_refs=[item["evidence_id"] for item in checkpoint.get("verification",[]) if isinstance(item,dict) and item.get("evidence_id")]
    terminal=objective["state"]=="COMPLETED"
    return {"schema_version":SCHEMA,"action_id":objective["objective_id"],"objective":objective["objective"],
            "actor":{"type":objective["owner_role"],"id":objective["owner_id"]},
            "authority":{"scope":"phase2.objective","source":"phase2-authority-envelope"},
            "started_at":str(objective["created_at"]),"completed_at":str(objective["completed_at"]) if objective["completed_at"] else None,
            "status":"COMPLETED" if terminal else "INVOKED","inputs":[],"claims":claims,
            "observations":observations,"effects":effects,"artifacts":checkpoint.get("artifacts",[]),
            "verification":{"state":"VERIFIED" if terminal and verification_refs else "UNVERIFIED","evidence":verification_refs},
            "provenance":{"record_owner":"PHASE2_KERNEL","snapshot_sha256":snapshot["snapshot_sha256"],
                          "model_content_authoritative":False},"relations":[]}

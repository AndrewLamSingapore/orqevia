"""Durable, idempotent portfolio inbox plus governed ORQEVIA projectors."""
from __future__ import annotations
import json, os, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from .generated.portfolio_contracts import assert_contract
from .memory import MemoryStore

SALIENCE={"E0":.1,"E1":.25,"E2":.45,"E3":.65,"E4":.8,"E5":.95}
def now()->str:return datetime.now(timezone.utc).isoformat()

class EventFabric:
    def __init__(self,path:str|None=None,memory:MemoryStore|None=None):
        data=os.getenv("ORQEVIA_DATA_DIR","/data").strip() or "/data";self.path=path or str(Path(data)/"portfolio-events.db");self.memory=memory or MemoryStore(str(Path(self.path).with_name("orqevia-memory.db")));Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript("""
        create table if not exists portfolio_events(event_id text primary key,schema_version text not null,event_type text not null,source text not null,occurred_at text not null,evidence_level text not null,correlation_id text not null,subject_id text,provenance_json text not null,payload_json text not null,received_at text not null);
        create table if not exists event_projections(event_id text not null,projector text not null,status text not null,details_json text not null,projected_at text not null,primary key(event_id,projector));
        create table if not exists semantic_graph_nodes(node_id text primary key,node_type text not null,label text not null,attributes_json text not null,last_event_id text not null,updated_at text not null);
        create table if not exists cognitive_review_queue(review_id text primary key,event_id text not null unique,status text not null,priority integer not null,reason text not null,created_at text not null,reviewed_at text);
        create table if not exists event_evaluations(event_id text primary key,evidence_level text not null,provenance_count integer not null,payload_fields integer not null,review_required integer not null,created_at text not null);
        """)
            columns={row["name"] for row in db.execute("pragma table_info(portfolio_events)")}
            if "schema_version" not in columns:
                db.execute("alter table portfolio_events add column schema_version text not null default 'legacy-1.0'")
    def connect(self)->sqlite3.Connection:
        db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row;return db
    def _once(self,event_id:str,projector:str,action)->dict[str,Any]:
        with self.connect() as db:existing=db.execute("select * from event_projections where event_id=? and projector=?",(event_id,projector)).fetchone()
        if existing and existing["status"]=="projected":return {"projector":projector,"status":existing["status"],"details":json.loads(existing["details_json"]),"replayed":True}
        try:details=action() or {};status="projected"
        except Exception as exc:details={"error":type(exc).__name__,"message":str(exc)[:500]};status="failed"
        with self.connect() as db:db.execute("insert into event_projections(event_id,projector,status,details_json,projected_at) values(?,?,?,?,?) on conflict(event_id,projector) do update set status=excluded.status,details_json=excluded.details_json,projected_at=excluded.projected_at",(event_id,projector,status,json.dumps(details,sort_keys=True),now()))
        return {"projector":projector,"status":status,"details":details,"replayed":bool(existing)}
    def _memory(self,event:Mapping[str,Any])->dict[str,Any]:
        episode=self.memory.record_episode(event_type=f"portfolio.{event['event_type']}",content={"event_id":event["event_id"],"payload":dict(event["payload"]),"provenance":list(event.get("provenance") or []),"evidence_level":event["evidence_level"]},source=f"portfolio:{event['source']}",salience=SALIENCE[event["evidence_level"]])
        return {"episode_id":episode["episode_id"],"authority":"candidate-only","auto_promoted":False}
    def _graph(self,event:Mapping[str,Any])->dict[str,Any]:
        payload=event["payload"];node_id=str(event.get("subject_id") or payload.get("entity_id") or payload.get("hypothesis_id") or payload.get("simulation_id") or f"event:{event['event_id']}");node_type=str(payload.get("entity_type") or event["event_type"].split(".",1)[0]);label=str(payload.get("title") or payload.get("name") or payload.get("label") or node_id);attributes={"source":event["source"],"event_type":event["event_type"],"evidence_level":event["evidence_level"],"payload":payload}
        with self.connect() as db:db.execute("insert into semantic_graph_nodes(node_id,node_type,label,attributes_json,last_event_id,updated_at) values(?,?,?,?,?,?) on conflict(node_id) do update set node_type=excluded.node_type,label=excluded.label,attributes_json=excluded.attributes_json,last_event_id=excluded.last_event_id,updated_at=excluded.updated_at",(node_id,node_type,label,json.dumps(attributes,sort_keys=True),event["event_id"],now()))
        return {"node_id":node_id,"node_type":node_type}
    def _review(self,event:Mapping[str,Any])->dict[str,Any]:
        level=event["evidence_level"];required=level in {"E2","E3","E4","E5"};status="pending" if required else "not_required";priority={"E0":0,"E1":10,"E2":30,"E3":50,"E4":70,"E5":90}[level];review_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"prime-review:{event['event_id']}"))
        with self.connect() as db:db.execute("insert or ignore into cognitive_review_queue(review_id,event_id,status,priority,reason,created_at) values(?,?,?,?,?,?)",(review_id,event["event_id"],status,priority,f"{level} {event['event_type']} from {event['source']}",now()))
        return {"review_id":review_id,"status":status,"priority":priority}
    def _evaluation(self,event:Mapping[str,Any])->dict[str,Any]:
        required=event["evidence_level"] in {"E2","E3","E4","E5"};count=len(event.get("provenance") or [])
        with self.connect() as db:db.execute("insert or ignore into event_evaluations(event_id,evidence_level,provenance_count,payload_fields,review_required,created_at) values(?,?,?,?,?,?)",(event["event_id"],event["evidence_level"],count,len(event["payload"]),int(required),now()))
        return {"evidence_level":event["evidence_level"],"provenance_count":count,"review_required":required}
    def project(self,event:Mapping[str,Any])->list[dict[str,Any]]:
        event_id=event["event_id"]
        return [self._once(event_id,"governed_memory_candidate",lambda:self._memory(event)),self._once(event_id,"semantic_graph",lambda:self._graph(event)),self._once(event_id,"bounded_cognitive_review",lambda:self._review(event)),self._once(event_id,"evaluation_record",lambda:self._evaluation(event))]
    def ingest(self,event:Mapping[str,Any])->dict[str,Any]:
        value=dict(assert_contract("portfolio-event-v1",dict(event)))
        row=(value["event_id"],value["schema_version"],value["event_type"],value["source"],value["occurred_at"],value["evidence_level"],value["correlation_id"],value.get("subject_id"),json.dumps(value["provenance"],sort_keys=True),json.dumps(value["payload"],sort_keys=True),now())
        with self.connect() as db:
            inserted=db.execute("insert or ignore into portfolio_events(event_id,schema_version,event_type,source,occurred_at,evidence_level,correlation_id,subject_id,provenance_json,payload_json,received_at) values(?,?,?,?,?,?,?,?,?,?,?)",row).rowcount==1
            if not inserted:
                existing=db.execute("select schema_version,event_type,source,occurred_at,evidence_level,correlation_id,subject_id,provenance_json,payload_json from portfolio_events where event_id=?",(value["event_id"],)).fetchone()
                incoming=row[1:-1]
                if not existing or tuple(existing)!=incoming:raise ValueError("event_id already exists with a different canonical event")
        projections=self.project(value)
        return {"accepted":True,"inserted":inserted,"event_id":value["event_id"],"projections":projections,"projected":all(item["status"]=="projected" for item in projections)}
    def recent(self,limit:int=50)->list[dict[str,Any]]:
        with self.connect() as db:rows=db.execute("select * from portfolio_events order by received_at desc limit ?",(max(1,min(limit,200)),)).fetchall()
        output=[]
        for row in rows:
            item=dict(row);item["provenance"]=json.loads(item.pop("provenance_json"));item["payload"]=json.loads(item.pop("payload_json"));output.append(item)
        return output
    def reviews(self,limit:int=50)->list[dict[str,Any]]:
        with self.connect() as db:return [dict(row) for row in db.execute("select * from cognitive_review_queue order by priority desc,created_at asc limit ?",(max(1,min(limit,200)),)).fetchall()]
    def graph(self,limit:int=100)->list[dict[str,Any]]:
        with self.connect() as db:rows=db.execute("select * from semantic_graph_nodes order by updated_at desc limit ?",(max(1,min(limit,500)),)).fetchall()
        output=[]
        for row in rows:
            item=dict(row);item["attributes"]=json.loads(item.pop("attributes_json"));output.append(item)
        return output

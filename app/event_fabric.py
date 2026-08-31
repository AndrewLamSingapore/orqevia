"""Durable, idempotent portfolio event inbox for PRIME cognition."""
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path
from typing import Any, Mapping

SOURCES={"prime","the-portal","velyqua","game-platform","authority-engine"}
LEVELS={"E0","E1","E2","E3","E4","E5"}

class EventFabric:
    def __init__(self,path:str|None=None):
        data=os.getenv("PRIME_DATA_DIR","/data").strip() or "/data"
        self.path=path or str(Path(data)/"portfolio-events.db")
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("create table if not exists portfolio_events(event_id text primary key,event_type text not null,source text not null,occurred_at text not null,evidence_level text not null,correlation_id text,subject_id text,provenance_json text not null,payload_json text not null,received_at text not null default current_timestamp)")
    def ingest(self,event:Mapping[str,Any])->dict[str,Any]:
        required={"version","event_id","event_type","source","occurred_at","evidence_level","payload"}
        missing=required-set(event)
        if missing: raise ValueError(f"missing event fields: {sorted(missing)}")
        if event["version"]!="1.0" or event["source"] not in SOURCES or event["evidence_level"] not in LEVELS: raise ValueError("unsupported portfolio event contract")
        if not isinstance(event["payload"],dict): raise ValueError("payload must be an object")
        row=(str(event["event_id"]),str(event["event_type"]),str(event["source"]),str(event["occurred_at"]),str(event["evidence_level"]),event.get("correlation_id"),event.get("subject_id"),json.dumps(event.get("provenance") or [],sort_keys=True),json.dumps(event["payload"],sort_keys=True))
        with sqlite3.connect(self.path) as db:
            before=db.total_changes
            db.execute("insert or ignore into portfolio_events(event_id,event_type,source,occurred_at,evidence_level,correlation_id,subject_id,provenance_json,payload_json) values(?,?,?,?,?,?,?,?,?)",row)
            inserted=db.total_changes>before
        return {"accepted":True,"inserted":inserted,"event_id":row[0]}
    def recent(self,limit:int=50)->list[dict[str,Any]]:
        with sqlite3.connect(self.path) as db:
            db.row_factory=sqlite3.Row
            rows=db.execute("select * from portfolio_events order by received_at desc limit ?",(max(1,min(limit,200)),)).fetchall()
        out=[]
        for r in rows:
            x=dict(r); x["provenance"]=json.loads(x.pop("provenance_json")); x["payload"]=json.loads(x.pop("payload_json")); out.append(x)
        return out

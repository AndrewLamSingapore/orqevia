"""Server-authenticated, bounded internal surface. No independent credentials."""
import asyncio
import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
from fastapi.responses import JSONResponse

def install(app):
    slots=asyncio.Semaphore(2)
    @app.middleware('http')
    async def protect(request,call_next):
        secret=os.getenv('ORQEVIA_SPINE_TOKEN','').strip()
        supplied=request.headers.getlist('authorization')
        if len(secret)<16:return JSONResponse({'detail':'Service authority unavailable'},status_code=503)
        if len(supplied)!=1 or not hmac.compare_digest(supplied[0],'Bearer '+secret):
            return JSONResponse({'detail':'Service authentication required'},status_code=401)
        mutation=request.method=='POST' and request.url.path.endswith('/ingest/run')
        root=Path(os.environ['ORQEVIA_DATA_DIR'])
        if mutation and (root/'suspended').exists():
            return JSONResponse({'detail':'Ingestion suspended'},status_code=503)
        if request.method=='POST':
            try:
                async def read():
                    parts=[];size=0
                    async for part in request.stream():
                        size+=len(part)
                        if size>16384:raise ValueError()
                        parts.append(part)
                    return b''.join(parts)
                request._body=await asyncio.wait_for(read(),3)
            except (ValueError,TimeoutError):return JSONResponse({'detail':'Request bound exceeded'},status_code=413)
        # Initial Intelligence views issue several bounded reads together.
        # Queue those reads briefly instead of rejecting an ordinary page load;
        # concurrent execution remains capped at the existing two slots.
        try:await asyncio.wait_for(slots.acquire(),2.0 if request.method=='GET' else 0.05)
        except TimeoutError:return JSONResponse({'detail':'Service capacity occupied'},status_code=429)
        actor=request.headers.get('x-orqevia-actor','abex-service')
        event={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'actor_sha256':hashlib.sha256(actor.encode()).hexdigest(),
               'method':request.method,'path':request.url.path}
        try:
            # A failed mutation audit blocks the affected ingestion operation.
            if mutation:
                with (root/'execution-audit.jsonl').open('a',encoding='utf-8') as log:
                    log.write(json.dumps({**event,'phase':'started'})+'\n');log.flush()
            response=await call_next(request)
            if mutation:
                with (root/'execution-audit.jsonl').open('a',encoding='utf-8') as log:
                    log.write(json.dumps({**event,'phase':'completed','status':response.status_code})+'\n');log.flush()
            response.headers['Cache-Control']='no-store'
            if request.url.path == '/gods-eye/map.html':
                response.headers['Content-Security-Policy']="default-src 'self'; connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
            return response
        except OSError:
            return JSONResponse({'detail':'Execution audit unavailable'},status_code=503)
        finally:slots.release()

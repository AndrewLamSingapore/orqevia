"""Event-driven revocation closes a local stream even while no token arrives."""
import asyncio
from datetime import datetime, timezone
import json

import httpx


async def infer(job, provider, *, settings, harness, validate, capacity, options):
    envelope = json.loads(job['harness_envelope'])
    auth = envelope['authorization']
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    def revoked():
        loop.call_soon_threadsafe(task.cancel)
    expiry = min(datetime.fromisoformat(auth[name]) for name in ('expires_at','lease_expires_at'))
    remaining = (expiry-datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise PermissionError('authorization or lease expired')
    # Subscribe first, then validate; a revocation between the two cannot escape.
    with harness.watch_execution(auth['lease_id'],revoked):
        validate(job)
        timer = loop.call_later(remaining,task.cancel)
        try:
            async with asyncio.timeout(float(job['timeout_seconds'])):
                async with httpx.AsyncClient(timeout=float(job['timeout_seconds'])) as client:
                    async with client.stream('POST',settings.ollama_base_url+'/api/chat',json={
                        'model':provider.model,'messages':[{'role':'user','content':job['prompt']}],
                        'stream':True,'keep_alive':settings.keep_alive,
                        'options':{'num_ctx':settings.context_tokens,'num_predict':settings.max_output_tokens,**options()}
                    }) as response:
                        response.raise_for_status()
                        parts=[]
                        final=None
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            validate(job)
                            capacity(provider.model)
                            item=json.loads(line)
                            if item.get('error'):
                                raise RuntimeError(item['error'])
                            parts.append(item.get('message',{}).get('content',''))
                            if item.get('done'):
                                final=item
                        validate(job)
                        if final is None:
                            raise RuntimeError('Incomplete model response')
                        return {'result':''.join(parts),'input_tokens':int(final.get('prompt_eval_count',0)),
                                'output_tokens':int(final.get('eval_count',0)),'actual_cost_usd':0,
                                'model_load_ns':int(final.get('load_duration',0)),
                                'inference_ns':int(final.get('eval_duration',0))}
        except asyncio.CancelledError as exc:
            raise PermissionError('lease revoked, expired, or policy changed; stream closed') from exc
        except TimeoutError as exc:
            raise TimeoutError('Inference execution deadline exceeded') from exc
        finally:
            timer.cancel()

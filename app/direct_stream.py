"""Direct local inference; resource limits and operational cancellation remain."""
import asyncio
import json
import httpx
import uuid

from . import backend_admission


async def infer(job,provider,*,settings,capacity,options,cancelled=lambda:False):
    endpoint = settings.ollama_base_url.rstrip('/')
    lease_id = str(job.get('id') or uuid.uuid4())
    db_path = job.get('_admission_db')

    def lease(action, *args):
        c = backend_admission.transaction(db_path)
        try:
            value = action(c, endpoint, lease_id, *args)
            c.commit()
            return value
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    async def run():
        capacity(provider.model)
        if db_path:
            lease(backend_admission.check)
        else:
            lease(backend_admission.reserve_model, provider.model, job.get('ram_mb', 0))
        dispatched = False
        complete = False
        try:
            lease(backend_admission.dispatch)
            dispatched = True
            async with httpx.AsyncClient(timeout=float(job['timeout_seconds'])) as client:
                async with client.stream('POST',settings.ollama_base_url+'/api/chat',json={
                'model':provider.model,'messages':[{'role':'user','content':job['prompt']}],
                'stream':True,'keep_alive':settings.keep_alive,'options':{
                    'num_ctx':settings.context_tokens,'num_predict':settings.max_output_tokens,**options()}}) as response:
                    response.raise_for_status();parts=[];final=None
                    async for line in response.aiter_lines():
                        if not line:continue
                        capacity(provider.model)
                        lease(backend_admission.check)
                        item=json.loads(line)
                        if not isinstance(item,dict):raise RuntimeError('Malformed model response')
                        if item.get('error'):raise RuntimeError(item['error'])
                        message=item.get('message',{})
                        if not isinstance(message,dict) or not isinstance(message.get('content',''),str):
                            raise RuntimeError('Malformed model response')
                        if 'done' in item and type(item['done']) is not bool:
                            raise RuntimeError('Malformed model completion')
                        parts.append(message.get('content',''))
                        if item.get('done') is True:final=item
                    if final is None or not ''.join(parts).strip():raise RuntimeError('Incomplete or empty model response')
                    result = {'result':''.join(parts),'input_tokens':int(final.get('prompt_eval_count',0)),
                        'output_tokens':int(final.get('eval_count',0)),'actual_cost_usd':0,
                        'model_load_ns':int(final.get('load_duration',0)), 'inference_ns':int(final.get('eval_duration',0))}
                    lease(backend_admission.completed)
                    complete = True
                    return result
        finally:
            if not complete:
                lease(backend_admission.cancel)
    task=asyncio.create_task(run())
    try:
        async with asyncio.timeout(float(job['timeout_seconds'])):
            while not task.done():
                if cancelled():raise RuntimeError('Task cancelled by client')
                await asyncio.wait({task},timeout=.05)
            return await task
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)

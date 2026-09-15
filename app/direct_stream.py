"""Direct local inference; resource limits and operational cancellation remain."""
import asyncio
import json
import httpx


async def infer(job,provider,*,settings,capacity,options,cancelled=lambda:False):
    async def run():
        capacity(provider.model)
        async with httpx.AsyncClient(timeout=float(job['timeout_seconds'])) as client:
            async with client.stream('POST',settings.ollama_base_url+'/api/chat',json={
                'model':provider.model,'messages':[{'role':'user','content':job['prompt']}],
                'stream':True,'keep_alive':settings.keep_alive,'options':{
                    'num_ctx':settings.context_tokens,'num_predict':settings.max_output_tokens,**options()}}) as response:
                response.raise_for_status();parts=[];final=None
                async for line in response.aiter_lines():
                    if not line:continue
                    capacity(provider.model)
                    item=json.loads(line)
                    if item.get('error'):raise RuntimeError(item['error'])
                    parts.append(item.get('message',{}).get('content',''))
                    if item.get('done'):final=item
                if final is None or not ''.join(parts).strip():raise RuntimeError('Incomplete or empty model response')
                return {'result':''.join(parts),'input_tokens':int(final.get('prompt_eval_count',0)),
                    'output_tokens':int(final.get('eval_count',0)),'actual_cost_usd':0,
                    'model_load_ns':int(final.get('load_duration',0)), 'inference_ns':int(final.get('eval_duration',0))}
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

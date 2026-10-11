"""Direct local inference; resource limits and operational cancellation remain."""
import asyncio
import json
import httpx
import uuid

from . import backend_admission


async def infer(job,provider,*,settings,capacity,options,cancelled=lambda:False,residency_contract=None):
    if residency_contract is not None:
        from .agent_cert_resident_model import ResidentAdmissionContract,require
        require(type(residency_contract) is ResidentAdmissionContract,'RESIDENCY_EXACT_SOURCE_CONTRACT_REQUIRED')
    def timeout():
        ordinary=float(job['timeout_seconds'])
        return ordinary if residency_contract is None else min(ordinary,residency_contract.window.remaining())
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
        response_format = job.get('response_format', 'text')
        if response_format not in {'text', 'strict_json'}:
            raise RuntimeError('Invalid response format')
        backend_admission.require_model(provider.model)
        capacity(provider.model)
        if db_path:
            lease(backend_admission.check)
        else:
            lease(backend_admission.reserve_model, provider.model, job.get('ram_mb', 0))
        dispatched = False
        complete = False
        try:
            admission=None
            if residency_contract is not None:
                admission=await residency_contract.observe(job,provider,settings,lambda:lease(backend_admission.check),phase='PRE_DISPATCH')
            lease(backend_admission.dispatch)
            dispatched = True
            payload={'model':provider.model,'messages':[{'role':'user','content':job['prompt']}],
                **({'format':'json'} if response_format == 'strict_json' else {}),
                'stream':True,'keep_alive':settings.keep_alive,'options':{
                    'num_ctx':settings.context_tokens,'num_predict':settings.max_output_tokens,**options()}}
            if residency_contract is not None:residency_contract.bind_chat_request(payload)
            async with httpx.AsyncClient(timeout=timeout()) as client:
                async with client.stream('POST',settings.ollama_base_url+'/api/chat',json=payload) as response:
                    response.raise_for_status();parts=[];final=None
                    lines=response.aiter_lines() if residency_contract is None else residency_contract.chat_lines(response)
                    async for line in lines:
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
                    contract_error = ''
                    if response_format == 'strict_json':
                        from .structured_output import parse_json, StructuredOutputError
                        try:
                            value, normalized = parse_json(''.join(parts), allow_fence_normalization=False)
                            if not isinstance(value, dict) or normalized:
                                raise ValueError('JSON object required')
                            json.dumps(value, allow_nan=False)
                        except (StructuredOutputError, ValueError, OverflowError, RecursionError):
                            contract_error = 'STRICT_JSON_CONTRACT_FAILED'
                    result = {'result':''.join(parts),'input_tokens':int(final.get('prompt_eval_count',0)),
                        'output_tokens':int(final.get('eval_count',0)),'actual_cost_usd':0,
                        'model_load_ns':int(final.get('load_duration',0)), 'inference_ns':int(final.get('eval_duration',0))}
                    if residency_contract is not None:
                        completion=residency_contract.completion(final,provider.model)
                        after=await residency_contract.observe(job,provider,settings,lambda:lease(backend_admission.check),phase='POST_DISPATCH')
                        result['source_residency_admission']=dict(before=admission,after=after,completion=completion,
                            native_chat_utf8=bytes(residency_contract._chat_raw).decode(),
                            native_chat_request_utf8=bytes(residency_contract._chat_request_raw).decode())
                    if contract_error:
                        # Preserve original rejected output and actual usage in
                        # the queue; fail the job without an automatic retry.
                        result.update(error=contract_error, retryable=False)

                    lease(backend_admission.completed)
                    complete = True
                    return result
        finally:
            if not complete:
                lease(backend_admission.cancel)
    task=asyncio.create_task(run())
    try:
        async with asyncio.timeout(timeout()):
            while not task.done():
                if cancelled():raise RuntimeError('Task cancelled by client')
                await asyncio.wait({task},timeout=.05)
            return await task
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)

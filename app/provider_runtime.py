"""Provider-neutral streaming boundary. Secrets and raw errors never enter receipts."""
import asyncio
from dataclasses import dataclass
from decimal import Decimal
import json
import os
import math
from typing import Protocol, AsyncIterator
from urllib.parse import urlsplit
import httpx


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    tier: str
    context_tokens: int
    output_tokens: int
    input_usd_million: Decimal | None = None
    output_usd_million: Decimal | None = None
    cached_usd_million: Decimal | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None

    def cost(self, model):
        if self.input_tokens is None or self.output_tokens is None or model.input_usd_million is None or model.output_usd_million is None:
            return None
        cached=self.cached_tokens or 0
        # Unknown cache discount is conservatively charged at the normal input rate.
        cache_rate=model.cached_usd_million if model.cached_usd_million is not None else model.input_usd_million
        return ((self.input_tokens-cached)*model.input_usd_million+cached*cache_rate+self.output_tokens*model.output_usd_million)/Decimal(1_000_000)


@dataclass(frozen=True)
class Chunk:
    text: str = ''
    usage: Usage | None = None
    complete: bool = False


class ProviderFailure(RuntimeError):
    def __init__(self, code, retryable=False, retry_after=0, *, pre_execution=False):
        super().__init__(code)
        self.code=code;self.retryable=retryable;self.retry_after=retry_after
        self.pre_execution=pre_execution


def capacity_rejection(value):
    """Recognize explicit rejected admission only; generic 5xx stays ambiguous."""
    if not isinstance(value,dict):return False
    error=value.get('error',value)
    if not isinstance(error,dict):return False
    return error.get('code') in {'model_at_capacity','model_capacity_exceeded','capacity_exceeded'} or error.get('message','').strip().lower()=='selected model is at capacity. please try a different model.'


class ModelProvider(Protocol):
    def stream(self, model: ModelSpec, messages: list, output_tokens: int) -> AsyncIterator[Chunk]: ...


class ChatCompletionProvider:
    """Optional HTTPS Chat Completions wire adapter; credentials resolved only at call time."""
    def __init__(self, endpoint, secret_ref, *, secret_resolver=os.getenv, transport=None):
        url=urlsplit(endpoint)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Provider endpoint must be a credential-free HTTPS URL')
        self.endpoint=endpoint;self.secret_ref=secret_ref;self.resolve=secret_resolver;self.transport=transport

    def health(self):
        """Local readiness only: never label an uncontacted provider healthy."""
        try:
            key=self.resolve(self.secret_ref)
            available=isinstance(key,str) and bool(key) and '\r' not in key and '\n' not in key
        except Exception:available=False
        return {'readiness':'READY' if available else 'CREDENTIAL_UNAVAILABLE',
                'provider_health':'UNMEASURED','network_probe_performed':False}

    async def stream(self, model, messages, output_tokens):
        try:key=self.resolve(self.secret_ref)
        except Exception:raise ProviderFailure('CREDENTIAL_UNAVAILABLE',pre_execution=True) from None
        if not isinstance(key,str) or not key or '\r' in key or '\n' in key:
            raise ProviderFailure('CREDENTIAL_UNAVAILABLE',pre_execution=True)
        body={'model':model.name,'messages':messages,'stream':True,'stream_options':{'include_usage':True},'max_completion_tokens':output_tokens,'store':False}
        try:
            async with httpx.AsyncClient(transport=self.transport,timeout=30,follow_redirects=False) as client:
                async with client.stream('POST',self.endpoint,headers={'Authorization':'Bearer '+key},json=body) as response:
                    if response.status_code>=300:
                        try:delay=max(0,min(30,float(response.headers.get('Retry-After','0'))))
                        except ValueError:delay=0
                        if not math.isfinite(delay):delay=0
                        code='RATE_LIMIT' if response.status_code==429 else 'AUTHENTICATION' if response.status_code in (401,403) else 'PROVIDER_HTTP_FAILURE'
                        if response.status_code==503:
                            raw=bytearray()
                            async for chunk in response.aiter_bytes():
                                raw.extend(chunk)
                                if len(raw)>65536:break
                            try:rejected=len(raw)<=65536 and capacity_rejection(json.loads(raw))
                            except (ValueError,UnicodeError):rejected=False
                            if rejected:raise ProviderFailure('CAPACITY',True,delay,pre_execution=True)
                        # 429 explicitly rejects admission. A 5xx can follow execution;
                        # absence of visible tokens does not make replay safe.
                        raise ProviderFailure(code,response.status_code==429,delay,pre_execution=response.status_code==429)
                    ended=False;finished=False
                    async for line in response.aiter_lines():
                        if len(line)>1_000_000:raise ProviderFailure('STREAM_SIZE_EXCEEDED')
                        if not line.startswith('data:'):continue
                        value=line[5:].strip()
                        if value=='[DONE]':ended=True;break
                        try:item=json.loads(value)
                        except ValueError:raise ProviderFailure('MALFORMED_STREAM') from None
                        if not isinstance(item,dict):raise ProviderFailure('MALFORMED_STREAM')
                        if item.get('error'):
                            if capacity_rejection(item):raise ProviderFailure('CAPACITY',True,pre_execution=True)
                            raise ProviderFailure('PROVIDER_STREAM_FAILURE')
                        usage=item.get('usage')
                        if usage is not None:
                            try:
                                if not isinstance(usage,dict):raise ValueError()
                                details=usage.get('prompt_tokens_details')
                                if details is not None and not isinstance(details,dict):raise ValueError()
                                inp=usage['prompt_tokens'];out=usage['completion_tokens'];cached=(details or {}).get('cached_tokens',0)
                                if any(type(x) is not int for x in (inp,out,cached)):raise ValueError()
                                if min(inp,out,cached)<0 or cached>inp:raise ValueError()
                            except (KeyError,TypeError,ValueError):raise ProviderFailure('INVALID_USAGE') from None
                            yield Chunk(usage=Usage(inp,out,cached))
                        choices=item.get('choices',[])
                        if not isinstance(choices,list):raise ProviderFailure('MALFORMED_STREAM')
                        for choice in choices:
                            if not isinstance(choice,dict):raise ProviderFailure('MALFORMED_STREAM')
                            if type(choice.get('index',0)) is not int:raise ProviderFailure('MALFORMED_STREAM')
                            if choice.get('index',0)!=0:continue
                            reason=choice.get('finish_reason')
                            if reason not in (None,'stop','length','content_filter','tool_calls','function_call'):raise ProviderFailure('MALFORMED_STREAM')
                            if reason=='length':raise ProviderFailure('OUTPUT_BUDGET_EXHAUSTED')
                            if reason in ('content_filter','tool_calls','function_call'):raise ProviderFailure('UNSUPPORTED_COMPLETION')
                            if reason=='stop':finished=True
                            delta=choice.get('delta')
                            if delta is not None and not isinstance(delta,dict):raise ProviderFailure('MALFORMED_STREAM')
                            content=(delta or {}).get('content')
                            if content is not None and not isinstance(content,str):raise ProviderFailure('MALFORMED_STREAM')
                            if content and finished and reason!='stop':raise ProviderFailure('MALFORMED_STREAM')
                            if content:yield Chunk(text=content)
                    if not ended or not finished:raise ProviderFailure('INCOMPLETE_STREAM')
                    yield Chunk(complete=True)
        except httpx.TimeoutException:raise ProviderFailure('PROVIDER_TIMEOUT') from None
        except httpx.TransportError:raise ProviderFailure('PROVIDER_TRANSPORT_FAILURE') from None
        except ProviderFailure:raise
        except Exception:raise ProviderFailure('PROVIDER_ADAPTER_FAILURE') from None


async def complete(provider,model,messages,*,output_tokens,timeout=60,cancelled=lambda:False,on_delta=lambda text:None,max_retries=1):
    if not isinstance(messages,list) or any(not isinstance(x,dict) or not isinstance(x.get('content',''),str) for x in messages):
        raise ProviderFailure('INVALID_MESSAGES',pre_execution=True)
    if type(max_retries) is not int or not 0<=max_retries<=2:raise ProviderFailure('INVALID_RETRY_LIMIT',pre_execution=True)
    if not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0:raise ProviderFailure('INVALID_TIMEOUT',pre_execution=True)
    if not 0<output_tokens<=model.output_tokens:raise ProviderFailure('OUTPUT_BUDGET_INVALID')
    # Byte count is a conservative bound, not a fabricated tokenizer measurement.
    upper=sum(len(str(x.get('content','')).encode())+16 for x in messages)+output_tokens
    if upper>model.context_tokens:raise ProviderFailure('CONTEXT_BUDGET_EXCEEDED')
    async def run():
        retry_errors=[]
        for attempt in range(max_retries+1):
            parts=[];usage=Usage();done=False;saw_usage=False;output_bytes=0
            try:
                async for chunk in provider.stream(model,messages,output_tokens):
                    if not isinstance(chunk,Chunk) or not isinstance(chunk.text,str) or type(chunk.complete) is not bool:
                        raise ProviderFailure('MALFORMED_STREAM')
                    if done:raise ProviderFailure('MALFORMED_STREAM')
                    if chunk.text:
                        output_bytes+=len(chunk.text.encode())
                        if output_bytes>4_000_000:raise ProviderFailure('STREAM_SIZE_EXCEEDED')
                        parts.append(chunk.text);on_delta(chunk.text)
                    if chunk.usage:
                        values=(chunk.usage.input_tokens,chunk.usage.output_tokens,chunk.usage.cached_tokens) if isinstance(chunk.usage,Usage) else ()
                        if not values or any(x is not None and (type(x) is not int or x<0) for x in values):raise ProviderFailure('INVALID_USAGE')
                        if values[2] is not None and (values[0] is None or values[2]>values[0]):raise ProviderFailure('INVALID_USAGE')
                        if values[1] is not None and values[1]>output_tokens:raise ProviderFailure('OUTPUT_BUDGET_EXHAUSTED')
                        usage=chunk.usage;saw_usage=True
                    done=done or chunk.complete
                if not done or not ''.join(parts).strip():raise ProviderFailure('EMPTY_OR_INCOMPLETE_RESPONSE')
                return {'text':''.join(parts),'usage':usage,'cost_usd':usage.cost(model),'retries':attempt,'retry_errors':retry_errors}
            except ProviderFailure as exc:
                exc.retry_count=attempt
                # Never replay a request after visible output; avoid duplicated work and unaccounted retries.
                if parts or saw_usage:
                    exc.pre_execution=False
                if parts or saw_usage or not exc.pre_execution or not exc.retryable or attempt>=max_retries:raise
                retry_errors.append(exc.code)
                await asyncio.sleep(max(exc.retry_after,min(2**attempt,4)))
            except Exception:raise ProviderFailure('PROVIDER_ADAPTER_FAILURE') from None
    task=asyncio.create_task(run())
    try:
        async with asyncio.timeout(timeout):
            while not task.done():
                if cancelled():raise ProviderFailure('CANCELLED')
                await asyncio.wait({task},timeout=.05)
            return await task
    except TimeoutError:raise ProviderFailure('TASK_TIMEOUT') from None
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)


async def complete_with_fallback(candidates,messages,*,authorize_candidate,output_tokens,timeout=60,**kwargs):
    """Explicit caller-selected sequence; no automatic catalog/provider selection.

    authorize_candidate must recheck locality, tier, context and concrete budget
    for EVERY candidate. No fallback after ambiguous transport, 5xx, partial output,
    usage, cancellation, or timeout. One shared wall-clock budget covers the chain.
    """
    if not callable(authorize_candidate) or not 1<=len(candidates)<=4:
        raise ProviderFailure('FALLBACK_CONFIGURATION_INVALID',pre_execution=True)
    if not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0:
        raise ProviderFailure('INVALID_TIMEOUT',pre_execution=True)
    start=asyncio.get_running_loop().time()
    failures=[];total_retries=0
    def progress(error):
        error.retry_count=total_retries;error.fallback_failures=list(failures)
        return error
    for provider,model in candidates:
        try:approved=authorize_candidate(model,messages,output_tokens) is True
        except Exception:raise progress(ProviderFailure('FALLBACK_POLICY_DENIED',pre_execution=True)) from None
        if not approved:
            raise progress(ProviderFailure('FALLBACK_POLICY_DENIED',pre_execution=True))
        remaining=timeout-(asyncio.get_running_loop().time()-start)
        if remaining<=0:raise progress(ProviderFailure('TASK_TIMEOUT'))
        try:
            result=await complete(provider,model,messages,output_tokens=output_tokens,timeout=remaining,**kwargs)
            return {**result,'retries':total_retries+result['retries'],'selected_provider':model.provider,'fallback_failures':failures}
        except ProviderFailure as exc:
            # Only actual local credential preflight or rejected rate admission may
            # use another approved provider. Other 'pre_execution' codes aren't enough.
            total_retries+=getattr(exc,'retry_count',0)
            exc.retry_count=total_retries
            exc.fallback_failures=list(failures)
            if not exc.pre_execution or exc.code not in {'CREDENTIAL_UNAVAILABLE','RATE_LIMIT','CAPACITY'}:raise
            failures.append({'provider':model.provider,'code':exc.code})
    error=ProviderFailure('FALLBACK_EXHAUSTED',pre_execution=True)
    error.retry_count=total_retries;error.fallback_failures=failures
    raise error

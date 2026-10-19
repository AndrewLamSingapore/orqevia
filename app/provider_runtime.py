"""Provider-neutral streaming boundary. Secrets and raw errors never enter receipts."""
import asyncio
from dataclasses import dataclass
from decimal import Decimal
import json
import os
import math
import re
from typing import Protocol, AsyncIterator
from urllib.parse import urlsplit
import httpx
from .provider_circuit import CircuitRejected
from .observability import trace_headers


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
class ProviderTrace:
    request_id: str | None = None
    response_id: str | None = None
    reported_model: str | None = None


def _trace_value(value, *, model=False):
    """Bounded opaque provider metadata, never arbitrary headers/error bodies."""
    if value is None:return None
    pattern=r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}' if model else r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}'
    if not isinstance(value,str) or not re.fullmatch(pattern,value) or value.lower().startswith(('sk-','sk_','bearer')):
        raise ProviderFailure('INVALID_PROVIDER_TRACE')
    return value


@dataclass(frozen=True)
class Chunk:
    text: str = ''
    usage: Usage | None = None
    complete: bool = False
    trace: ProviderTrace | None = None


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
    code=error.get('code');message=error.get('message')
    return (isinstance(code,str) and code in {'model_at_capacity','model_capacity_exceeded','capacity_exceeded'}) or (isinstance(message,str) and message.strip().lower()=='selected model is at capacity. please try a different model.')


def _decode_wire_json(raw):
    """Duplicate keys/non-JSON constants cannot conceal upstream execution."""
    def unique_keys(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate provider JSON key')
            result[key]=value
        return result
    def invalid_constant(_):raise ValueError('Non-JSON provider constant')
    def finite_float(value):
        parsed=float(value)
        if not math.isfinite(parsed):raise ValueError('Nonfinite provider number')
        return parsed
    if isinstance(raw,bytes):raw=raw.decode('utf-8')
    return json.loads(raw,object_pairs_hook=unique_keys,parse_constant=invalid_constant,parse_float=finite_float)


def _clean_rejected_admission(value,status):
    """An error mixed with output/usage is not proof that work was rejected.

    Only the supported scalar error envelope is admitted. Unknown containers or
    payload fields cannot be interpreted as rejection merely because a capacity
    code is also present; this avoids relying on an exhaustive output blacklist.
    """
    if not isinstance(value,dict):return False
    error=value.get('error',value)
    if not isinstance(error,(dict,str)):return False
    allowed={'code','message','type','param','status','status_code','request_id',
        'requestId','retry_after','retry_after_seconds'}
    if set(value)-allowed-{'error'}:return False
    envelopes=[{key:item for key,item in value.items() if key!='error'}]
    if isinstance(error,dict) and error is not value:envelopes.append(error)
    for envelope in envelopes:
        if set(envelope)-allowed:return False
        for key,item in envelope.items():
            if key in {'status','status_code'}:
                if type(item) is not int or item!=status:return False
            elif key in {'retry_after','retry_after_seconds'}:
                if type(item) not in (int,float) or not math.isfinite(item) or item<0:return False
            elif key=='param':
                if item is not None and not isinstance(item,str):return False
            elif not isinstance(item,str):return False
    return True


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

    def request_body(self, model, messages, output_tokens):
        return {'model':model.name,'messages':messages,'stream':True,
                'stream_options':{'include_usage':True},
                'max_completion_tokens':output_tokens,'store':False}

    def normalize_stream_item(self, item):
        return item

    def stream_ended(self, item):
        return False

    async def stream(self, model, messages, output_tokens):
        try:key=self.resolve(self.secret_ref)
        except Exception:raise ProviderFailure('CREDENTIAL_UNAVAILABLE',pre_execution=True) from None
        if not isinstance(key,str) or not key or '\r' in key or '\n' in key:
            raise ProviderFailure('CREDENTIAL_UNAVAILABLE',pre_execution=True)
        body=self.request_body(model,messages,output_tokens)
        try:
            async with httpx.AsyncClient(transport=self.transport,timeout=30,follow_redirects=False) as client:
                request_headers=trace_headers({'Authorization':'Bearer '+key})
                async with client.stream('POST',self.endpoint,headers=request_headers,json=body) as response:
                    if response.status_code>=300:
                        try:delay=max(0,min(30,float(response.headers.get('Retry-After','0'))))
                        except ValueError:delay=0
                        if not math.isfinite(delay):delay=0
                        code='RATE_LIMIT' if response.status_code==429 else 'AUTHENTICATION' if response.status_code in (401,403) else 'INSUFFICIENT_BALANCE' if response.status_code==402 else 'PROVIDER_HTTP_FAILURE'
                        if response.status_code in (429,503):
                            raw=bytearray();oversized=False
                            async for chunk in response.aiter_bytes():
                                if len(raw)+len(chunk)>65536:
                                    oversized=True;break
                                raw.extend(chunk)
                            try:
                                # Empty 429 is an explicit status-only rejection;
                                # empty 503 remains ambiguous. Nonempty bodies
                                # must prove clean, uniquely decoded admission.
                                fault=_decode_wire_json(bytes(raw)) if raw else None
                                clean=not oversized and ((not raw and response.status_code==429) or _clean_rejected_admission(fault,response.status_code))
                                rejected=clean and capacity_rejection(fault)
                            except (ValueError,UnicodeError,RecursionError,TypeError):
                                clean=False;rejected=False
                            if response.status_code==429 and clean:
                                raise ProviderFailure('RATE_LIMIT',True,delay,pre_execution=True)
                            if rejected:raise ProviderFailure('CAPACITY',True,delay,pre_execution=True)
                            raise ProviderFailure('PROVIDER_HTTP_FAILURE')
                        # Other HTTP faults do not prove rejected execution;
                        # absence of visible tokens cannot authorize replay.
                        raise ProviderFailure(code)
                    ended=False;finished=False
                    request_id=_trace_value(response.headers.get('x-request-id'))
                    yield Chunk(trace=ProviderTrace(request_id=request_id))
                    async for line in response.aiter_lines():
                        if len(line)>1_000_000:raise ProviderFailure('STREAM_SIZE_EXCEEDED')
                        if not line.startswith('data:'):continue
                        value=line[5:].strip()
                        if value=='[DONE]':ended=True;break
                        try:item=_decode_wire_json(value)
                        except (ValueError,UnicodeError,RecursionError,TypeError):raise ProviderFailure('MALFORMED_STREAM') from None
                        if not isinstance(item,dict):raise ProviderFailure('MALFORMED_STREAM')
                        terminal=self.stream_ended(item)
                        metadata=item.get('response') if isinstance(item.get('response'),dict) else item
                        yield Chunk(trace=ProviderTrace(request_id=request_id,
                            response_id=_trace_value(metadata.get('id')),
                            reported_model=_trace_value(metadata.get('model'),model=True)))
                        item=self.normalize_stream_item(item)
                        if item.get('error'):
                            # A 200 streaming response has been admitted. Even if it
                            # contains no visible tokens, execution may have occurred.
                            if capacity_rejection(item):raise ProviderFailure('CAPACITY',pre_execution=False)
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
                        if terminal:
                            ended=True
                            break
                    if not ended or not finished:raise ProviderFailure('INCOMPLETE_STREAM')
                    yield Chunk(complete=True)
        except httpx.TimeoutException:raise ProviderFailure('PROVIDER_TIMEOUT') from None
        except httpx.TransportError:raise ProviderFailure('PROVIDER_TRANSPORT_FAILURE') from None
        except ProviderFailure:raise
        except Exception:raise ProviderFailure('PROVIDER_ADAPTER_FAILURE') from None


class HuggingFaceProvider(ChatCompletionProvider):
    """Pinned Hugging Face Inference Providers chat route; no browser credentials.

    Tool calls, constrained output, embeddings and provider auto-selection are not
    advertised by this text-only adapter. Catalog activation is a separate gate.
    """
    ENDPOINT='https://router.huggingface.co/v1/chat/completions'
    _PINNED_MODEL=re.compile(r'[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:[A-Za-z0-9._-]+\Z')

    def __init__(self, secret_ref='env:HF_TOKEN', *, secret_resolver=None, transport=None):
        if secret_ref not in ('env:HF_TOKEN','file:HF_TOKEN'):
            raise ValueError('Hugging Face requires the governed HF_TOKEN reference')
        if secret_resolver is None:
            from .secret_refs import resolve_secret
            secret_resolver=resolve_secret
        super().__init__(self.ENDPOINT,secret_ref,secret_resolver=secret_resolver,transport=transport)

    def request_body(self, model, messages, output_tokens):
        if not isinstance(model.name,str) or not self._PINNED_MODEL.fullmatch(model.name):
            raise ProviderFailure('MODEL_PROVIDER_UNPINNED',pre_execution=True)
        return {'model':model.name,'messages':messages,'stream':True,
                'stream_options':{'include_usage':True},'max_tokens':output_tokens}


async def complete(provider,model,messages,*,output_tokens,timeout=60,cancelled=lambda:False,on_delta=lambda text:None,max_retries=1,circuits=None):
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
            trace={'request_id':None,'response_id':None,'reported_model':None}
            permit=None
            try:
                if circuits is not None:
                    try:permit=circuits.acquire(model.provider)
                    except CircuitRejected as exc:
                        raise ProviderFailure(exc.code,pre_execution=True) from None
                async for chunk in provider.stream(model,messages,output_tokens):
                    if not isinstance(chunk,Chunk) or not isinstance(chunk.text,str) or type(chunk.complete) is not bool:
                        raise ProviderFailure('MALFORMED_STREAM')
                    if done:raise ProviderFailure('MALFORMED_STREAM')
                    if chunk.trace is not None:
                        if not isinstance(chunk.trace,ProviderTrace):raise ProviderFailure('INVALID_PROVIDER_TRACE')
                        for field in trace:
                            value=_trace_value(getattr(chunk.trace,field),model=field=='reported_model')
                            if value is None:continue
                            if trace[field] is not None and trace[field]!=value:raise ProviderFailure('PROVIDER_TRACE_CHANGED')
                            trace[field]=value
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
                cost=usage.cost(model)
                result={'text':''.join(parts),'usage':usage,'cost_usd':cost,'retries':attempt,'retry_errors':retry_errors,
                    'provider_trace':trace,'cost_basis':'provider_usage_x_catalog_rates' if cost is not None else 'unknown',
                    'billing_status':'unreconciled'}
                if permit is not None:
                    circuits.succeed(permit);permit=None
                return result
            except ProviderFailure as exc:
                exc.retry_count=attempt
                # Never replay a request after visible output; avoid duplicated work and unaccounted retries.
                if parts or saw_usage:
                    exc.pre_execution=False
                if permit is not None:
                    circuits.fail(permit,exc.code,pre_execution=exc.pre_execution is True);permit=None
                if parts or saw_usage or not exc.pre_execution or not exc.retryable or attempt>=max_retries:raise
                retry_errors.append(exc.code)
                await asyncio.sleep(max(exc.retry_after,min(2**attempt,4)))
            except Exception:raise ProviderFailure('PROVIDER_ADAPTER_FAILURE') from None
            finally:
                # Includes cancellation and consumer-side validation failures:
                # exhausted/terminal stream alone never claims recovery.
                if permit is not None:circuits.abandon(permit)
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
            if not exc.pre_execution or exc.code not in {'CREDENTIAL_UNAVAILABLE','RATE_LIMIT','CAPACITY','PROVIDER_CIRCUIT_OPEN'}:raise
            failures.append({'provider':model.provider,'code':exc.code})
    error=ProviderFailure('FALLBACK_EXHAUSTED',pre_execution=True)
    error.retry_count=total_retries;error.fallback_failures=failures
    raise error

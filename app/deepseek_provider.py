"""Optional fixed DeepSeek text wire adapter; source-only, never activation.

Primary contract: https://api-docs.deepseek.com/api/create-chat-completion/
This initial adapter deliberately requests non-thinking text only. Tools,
vision, reasoning output and model qualification are not advertised. Existing
queue admission owns locality, permission, qualification and reserved prices;
existing complete() owns bounded cancellation, circuit state and safe replay.
"""
from __future__ import annotations

import httpx

from .provider_runtime import ChatCompletionProvider, ModelSpec, ProviderFailure, _decode_wire_json


ENDPOINT = 'https://api.deepseek.com/chat/completions'
SECRET_REF = 'env:DEEPSEEK_API_KEY'
MODELS = frozenset(('deepseek-flash', 'deepseek-v4-pro'))
MAX_LINE_BYTES = 1_000_000


def _deny(code):
    raise ProviderFailure(code)


def _count(value):
    if type(value) is not int or not 0 <= value <= 2_000_000:
        _deny('INVALID_USAGE')
    return value


def _validate_usage(value):
    """Preserve the shared cache-cost calculation only from consistent evidence."""
    if type(value) is not dict:
        _deny('INVALID_USAGE')
    try:
        inp, out = _count(value['prompt_tokens']), _count(value['completion_tokens'])
        hit, miss = _count(value['prompt_cache_hit_tokens']), _count(value['prompt_cache_miss_tokens'])
        total = _count(value['total_tokens'])
        details = value['prompt_tokens_details']
        if type(details) is not dict:
            _deny('INVALID_USAGE')
        cached = _count(details['cached_tokens'])
    except (KeyError, TypeError):
        _deny('INVALID_USAGE')
    if hit + miss != inp or cached != hit or total != inp + out:
        _deny('INVALID_USAGE')
    completion = value.get('completion_tokens_details')
    if completion is not None:
        if type(completion) is not dict:
            _deny('INVALID_USAGE')
        reasoning = _count(completion.get('reasoning_tokens', 0))
        if reasoning > out:
            _deny('INVALID_USAGE')
        if reasoning:
            _deny('UNSUPPORTED_COMPLETION')


class _CheckedStream(httpx.AsyncByteStream):
    """Validate original SSE lines, then let the existing parser consume them."""
    def __init__(self, stream, model, owned_transport=None):
        self.stream, self.model, self.owned_transport = stream, model, owned_transport
        self.identity = None
        self.saw_usage = False

    def _line(self, raw):
        if len(raw) > MAX_LINE_BYTES:
            _deny('STREAM_SIZE_EXCEEDED')
        try:
            line = raw.decode('utf-8').rstrip('\r\n')
        except UnicodeError:
            _deny('MALFORMED_STREAM')
        if not line.startswith('data:'):
            return
        value = line[5:].strip()
        if value == '[DONE]':
            if not self.saw_usage:
                _deny('INVALID_USAGE')
            return
        try:
            item = _decode_wire_json(value)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            _deny('MALFORMED_STREAM')
        if type(item) is not dict:
            _deny('MALFORMED_STREAM')
        if item.get('error'):
            return  # Shared admitted-error handling is already non-replayable.
        if self.saw_usage:
            _deny('MALFORMED_STREAM')
        identity = item.get('id')
        if (type(identity) is not str or not 1 <= len(identity) <= 200 or
                type(item.get('model')) is not str or item['model'] != self.model or
                self.identity is not None and identity != self.identity):
            _deny('MALFORMED_STREAM')
        self.identity = identity
        choices = item.get('choices')
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            _deny('MALFORMED_STREAM')
        choice = choices[0]
        delta = choice.get('delta')
        if type(choice.get('index')) is not int or choice['index'] != 0 or type(delta) is not dict:
            _deny('MALFORMED_STREAM')
        if (delta.get('reasoning_content') not in (None, '') or
                delta.get('tool_calls') not in (None, []) or delta.get('function_call') is not None):
            _deny('UNSUPPORTED_COMPLETION')
        usage = item.get('usage')
        if usage is not None:
            if choice.get('finish_reason') is None:
                _deny('INVALID_USAGE')
            _validate_usage(usage)
            self.saw_usage = True

    async def __aiter__(self):
        pending = bytearray()
        async for chunk in self.stream:
            if len(chunk) > MAX_LINE_BYTES:
                _deny('STREAM_SIZE_EXCEEDED')
            pending.extend(chunk)
            while b'\n' in pending:
                end = pending.index(b'\n') + 1
                line = bytes(pending[:end])
                del pending[:end]
                self._line(line)
                yield line
            if len(pending) > MAX_LINE_BYTES:
                _deny('STREAM_SIZE_EXCEEDED')
        if pending:
            self._line(bytes(pending))
            yield bytes(pending)

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            if self.owned_transport is not None:
                await self.owned_transport.aclose()


class _CheckedTransport(httpx.AsyncBaseTransport):
    def __init__(self, injected=None):
        self.injected = injected

    async def handle_async_request(self, request):
        if request.method != 'POST' or str(request.url) != ENDPOINT:
            raise ProviderFailure('PROVIDER_SCOPE_DENIED', pre_execution=True)
        try:
            model = _decode_wire_json(request.content)['model']
            if type(model) is not str or model not in MODELS:
                raise ValueError()
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            raise ProviderFailure('INVALID_MESSAGES', pre_execution=True) from None
        owned = None if self.injected is not None else httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        delegate = self.injected if self.injected is not None else owned
        try:
            response = await delegate.handle_async_request(request)
        except BaseException:
            if owned is not None:
                await owned.aclose()
            raise
        if response.status_code == 503:
            # DeepSeek documents overload, not proof that the request never ran.
            # Do not import another provider's capacity-code replay assumptions.
            try:
                await response.aclose()
            finally:
                if owned is not None:
                    await owned.aclose()
            raise ProviderFailure('PROVIDER_HTTP_FAILURE')
        # Error JSON is parsed by the existing strict rejected-admission parser.
        # Wrapping every response also guarantees owned transport cleanup.
        if response.status_code == 200:
            stream = _CheckedStream(response.stream, model, owned)
        elif owned is not None:
            stream = _ClosingStream(response.stream, owned)
        else:
            stream = response.stream
        # A pre-buffered injected response's aiter_bytes() bypasses stream via
        # cached content. A fresh streamed facade enforces the same validator
        # for buffered fixtures and actual unread network responses alike.
        return httpx.Response(response.status_code, headers=response.headers,
            stream=stream, extensions=response.extensions, request=request)


class _ClosingStream(httpx.AsyncByteStream):
    def __init__(self, stream, transport):
        self.stream, self.transport = stream, transport

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            await self.transport.aclose()


class DeepSeekProvider(ChatCompletionProvider):
    ENDPOINT = ENDPOINT
    SECRET_REF = SECRET_REF
    MODELS = MODELS

    def __init__(self, secret_ref=SECRET_REF, *, endpoint=ENDPOINT, secret_resolver=None, transport=None):
        if type(endpoint) is not str or endpoint != ENDPOINT or type(secret_ref) is not str or secret_ref != SECRET_REF:
            raise ValueError('DeepSeek requires its fixed endpoint and governed credential reference')
        if secret_resolver is None:
            from .secret_refs import resolve_secret
            secret_resolver = resolve_secret
        super().__init__(ENDPOINT, SECRET_REF, secret_resolver=secret_resolver,
                         transport=_CheckedTransport(transport))

    def _require_scope(self):
        if (type(self.endpoint) is not str or self.endpoint != ENDPOINT or
                type(self.secret_ref) is not str or self.secret_ref != SECRET_REF):
            raise ProviderFailure('PROVIDER_SCOPE_DENIED', pre_execution=True)

    def health(self):
        try:
            self._require_scope()
        except ProviderFailure:
            return {'readiness': 'CONFIGURATION_INVALID', 'provider_health': 'UNMEASURED',
                    'network_probe_performed': False}
        return super().health()

    def request_body(self, model, messages, output_tokens):
        self._require_scope()
        if not isinstance(model, ModelSpec) or type(model.name) is not str or model.name not in MODELS:
            raise ProviderFailure('PROVIDER_MODEL_UNSUPPORTED', pre_execution=True)
        if (type(output_tokens) is not int or type(model.output_tokens) is not int or
                not 1 <= output_tokens <= min(model.output_tokens, 393216)):
            raise ProviderFailure('OUTPUT_BUDGET_INVALID', pre_execution=True)
        if (type(messages) is not list or not 1 <= len(messages) <= 64 or
                any(type(item) is not dict or set(item) != {'role', 'content'} or
                    item['role'] not in ('system', 'user', 'assistant') or type(item['role']) is not str or
                    type(item['content']) is not str for item in messages)):
            raise ProviderFailure('INVALID_MESSAGES', pre_execution=True)
        try:
            upper = sum(len(item['content'].encode('utf-8')) + 16 for item in messages) + output_tokens
        except UnicodeError:
            raise ProviderFailure('INVALID_MESSAGES', pre_execution=True) from None
        if type(model.context_tokens) is not int or not output_tokens < model.context_tokens <= 1048576 or upper > model.context_tokens:
            raise ProviderFailure('CONTEXT_BUDGET_EXCEEDED', pre_execution=True)
        return {'model': model.name, 'messages': messages, 'stream': True,
                'stream_options': {'include_usage': True}, 'max_tokens': output_tokens,
                'thinking': {'type': 'disabled'}}

    async def stream(self, model, messages, output_tokens):
        # The generic adapter resolves credentials before request_body(); validate
        # our stricter boundary first so invalid configuration performs no lookup.
        self.request_body(model, messages, output_tokens)
        async for chunk in super().stream(model, messages, output_tokens):
            yield chunk

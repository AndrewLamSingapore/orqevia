"""Pinned text-only adapters sharing the existing conservative retry boundary.

No provider selection, entitlement, billing or model capability is inferred here.
Credentials remain provider-specific environment references, resolved at dispatch.
"""
from .provider_runtime import ChatCompletionProvider, ProviderFailure


class OpenAIResponsesProvider(ChatCompletionProvider):
    ENDPOINT = 'https://api.openai.com/v1/responses'
    SECRET_REF = 'env:OPENAI_API_KEY'

    def __init__(self, secret_ref=SECRET_REF, **kwargs):
        if secret_ref != self.SECRET_REF:
            raise ValueError('OpenAI requires its isolated OPENAI_API_KEY reference')
        super().__init__(self.ENDPOINT, secret_ref, **kwargs)

    def request_body(self, model, messages, output_tokens):
        return {'model': model.name, 'input': messages, 'stream': True,
                'max_output_tokens': output_tokens, 'store': False}

    def stream_ended(self, item):
        return item.get('type') == 'response.completed'

    def normalize_stream_item(self, item):
        if item.get('error'):
            raise ProviderFailure('PROVIDER_STREAM_FAILURE')
        kind = item.get('type')
        if kind in {'error', 'response.failed'}:
            raise ProviderFailure('PROVIDER_STREAM_FAILURE')
        if kind == 'response.incomplete':
            raise ProviderFailure('OUTPUT_BUDGET_EXHAUSTED')
        if kind == 'response.output_text.delta':
            return {'choices': [{'index': 0, 'delta': {'content': item.get('delta')}}]}
        if kind == 'response.completed':
            response = item.get('response')
            if not isinstance(response, dict) or response.get('status') != 'completed':
                raise ProviderFailure('MALFORMED_STREAM')
            if response.get('error') is not None:
                raise ProviderFailure('PROVIDER_STREAM_FAILURE')
            output = response.get('output')
            if not isinstance(output, list) or any(not isinstance(x, dict) or x.get('type') not in {'message', 'reasoning'} for x in output):
                raise ProviderFailure('UNSUPPORTED_COMPLETION')
            for message in (x for x in output if x.get('type')=='message'):
                content=message.get('content')
                if message.get('role')!='assistant' or not isinstance(content,list) or any(
                    not isinstance(part,dict) or part.get('type')!='output_text' or not isinstance(part.get('text'),str)
                    for part in content
                ):
                    raise ProviderFailure('UNSUPPORTED_COMPLETION')
            usage = response.get('usage')
            result = {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}
            if usage is not None:
                if not isinstance(usage, dict):
                    raise ProviderFailure('INVALID_USAGE')
                result['usage'] = {'prompt_tokens': usage.get('input_tokens'),
                                   'completion_tokens': usage.get('output_tokens'),
                                   'prompt_tokens_details': usage.get('input_tokens_details')}
            return result
        if kind in {'response.output_item.added', 'response.output_item.done'}:
            output = item.get('item')
            if not isinstance(output, dict) or output.get('type') not in {'message', 'reasoning'}:
                raise ProviderFailure('UNSUPPORTED_COMPLETION')
            return {}
        if kind in {'response.created', 'response.in_progress', 'response.content_part.added',
                    'response.content_part.done', 'response.output_text.done',
                    'response.reasoning_summary_part.added', 'response.reasoning_summary_part.done',
                    'response.reasoning_summary_text.delta', 'response.reasoning_summary_text.done'}:
            return {}
        raise ProviderFailure('UNSUPPORTED_STREAM_EVENT')


class DeepSeekChatProvider(ChatCompletionProvider):
    ENDPOINT = 'https://api.deepseek.com/chat/completions'
    SECRET_REF = 'env:DEEPSEEK_API_KEY'

    def __init__(self, secret_ref=SECRET_REF, **kwargs):
        if secret_ref != self.SECRET_REF:
            raise ValueError('DeepSeek requires its isolated DEEPSEEK_API_KEY reference')
        super().__init__(self.ENDPOINT, secret_ref, **kwargs)

    def request_body(self, model, messages, output_tokens):
        # The provider documents max_tokens; OpenAI-only store/max_completion_tokens
        # are deliberately absent. No tools or unsupported response modes are sent.
        return {'model': model.name, 'messages': messages, 'stream': True,
                'stream_options': {'include_usage': True}, 'max_tokens': output_tokens}

    def normalize_stream_item(self, item):
        usage = item.get('usage')
        if isinstance(usage, dict) and 'prompt_cache_hit_tokens' in usage:
            cached = usage['prompt_cache_hit_tokens']
            details = usage.get('prompt_tokens_details')
            if details is not None and (not isinstance(details, dict) or details.get('cached_tokens') != cached):
                raise ProviderFailure('INVALID_USAGE')
            if details is None:
                item = {**item, 'usage': {**usage, 'prompt_tokens_details': {'cached_tokens': cached}}}
        return item

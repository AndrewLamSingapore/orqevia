"""Configured model choices, not a second queue or Registry."""
import json
import os
import math
import re
from pathlib import Path
from decimal import Decimal
from .provider_runtime import ModelSpec,HuggingFaceProvider
from .tier_router import Tier, classify_for_cloud, CLASSIFICATIONS


_BOUNDED_LIST_EN = re.compile(
    r"\b(?:create|write|produce|make)\b.{0,120}\b(?:[1-9]|10|one|two|three|four|five|six|seven|eight|nine|ten)\b"
    r".{0,40}\b(?:item|point|step)s?\b.{0,80}\b(?:list|checklist)\b",
    re.I | re.S,
)
_BOUNDED_LIST_ZH = re.compile(
    r"(?:创建|写|生成|制作).{0,120}(?:[一二三四五六七八九十]|[1-9]|10)\s*(?:项|条).{0,80}(?:清单|列表)",
    re.S,
)


def bounded_list_task(objective):
    """Admit only an explicitly size-bounded short list to the measured Nano tier."""
    if not isinstance(objective, str) or not 1 <= len(objective) <= 1000:
        return False
    return bool(_BOUNDED_LIST_EN.search(objective) or _BOUNDED_LIST_ZH.search(objective))


def task_tier(objective, task_class='auto'):
    if task_class=='classification':return Tier.NANO
    if task_class in ('coding','architecture','complex_reasoning'):return Tier.FLAGSHIP
    if task_class in ('conversation','research','planning','writing'):return Tier.MINI
    text=objective.lower()
    if any(x in text for x in ('repository','implement','debug','refactor','architecture','formal proof','cryptographic')):return Tier.FLAGSHIP
    # Only tightly bounded tasks enter Nano without verified success data.
    if text.startswith(('classify ','extract labels ','reply exactly:')) or bounded_list_task(objective):return Tier.NANO
    return Tier.MINI


def load_catalog(path=None):
    name=path or os.getenv('PRIME_PROVIDER_CATALOG','')
    if not name:return []
    data=json.loads(Path(name).read_text())
    entries=data.get('models',[])
    if len(entries)>32:raise ValueError('Too many configured model entries')
    seen=set()
    for item in entries:
        if any(key in item for key in ('api_key','secret','credential','password','token')):
            raise ValueError('Catalog accepts secret references only')
        if item['id'] in seen:raise ValueError('Duplicate model entry')
        seen.add(item['id'])
        if item['tier'] not in Tier.__members__ or item['location'] not in ('local','cloud'):raise ValueError('Invalid model metadata')
        if item.get('enabled') and (not item.get('model') or not item.get('endpoint')):raise ValueError('Enabled model lacks endpoint/model')
        if item['location']=='cloud' and item.get('enabled') and not item.get('secret_ref','').startswith('env:'):raise ValueError('Cloud secret reference unavailable')
        kind=item.get('provider_kind','chat_completions')
        if kind not in ('chat_completions','huggingface'):raise ValueError('Unknown provider kind')
        if kind=='huggingface':
            if item['location']!='cloud' or item.get('endpoint')!=HuggingFaceProvider.ENDPOINT:
                raise ValueError('Hugging Face endpoint/location must be fixed')
            if item.get('secret_ref')!='env:HF_TOKEN':raise ValueError('Hugging Face credential reference must be HF_TOKEN')
            model_id=item.get('model')
            if not isinstance(model_id,str) or not HuggingFaceProvider._PINNED_MODEL.fullmatch(model_id):
                raise ValueError('Hugging Face model must pin an explicit provider')
            if item.get('enabled') and item.get('qualification_status')!='QUALIFIED':
                raise ValueError('Unqualified Hugging Face model cannot be enabled')
        if not 1<=int(item['output_tokens'])<int(item['context_tokens']):raise ValueError('Invalid model context limits')
        for field in ('expected_seconds','expected_cost_usd'):
            if field in item and (not math.isfinite(float(item[field])) or float(item[field])<0):
                raise ValueError('Invalid measurement')
        if not 1<=int(item.get('concurrency',1))<=16:raise ValueError('Invalid concurrency')
    return entries


def choose(entries,minimum,classification,text):
    if classification not in CLASSIFICATIONS:raise ValueError('Invalid data classification')
    eligible=[x for x in entries if x.get('enabled') and Tier[x['tier']]>=minimum and (x['location']=='local' or classify_for_cloud(classification,text))]
    # Measurements are deployment-supplied evidence; missing measurements sort last.
    eligible.sort(key=lambda x:(float(x.get('expected_seconds',float('inf'))),float(x.get('expected_cost_usd',float('inf'))),Tier[x['tier']],x['id']))
    return eligible


def model_spec(entry):
    def price(name):
        value=entry.get(name)
        if value is None:return None
        rate=Decimal(str(value))
        if not rate.is_finite() or rate<0:raise ValueError('Invalid price')
        return rate
    return ModelSpec(entry['model'],entry['id'],entry['tier'],int(entry['context_tokens']),int(entry['output_tokens']),price('input_usd_million'),price('output_usd_million'),price('cached_usd_million'))

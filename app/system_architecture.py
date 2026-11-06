"""Deterministic, system-owned answers for ORQEVIA architecture questions."""
from __future__ import annotations
import json,os,re
from pathlib import Path
from typing import Any
from .agent_registry import RegistryError,agent_record,load_agent_registry,orchestrator_id

PATTERNS=(r'how many agents',r'list (?:your|the) agents',r'which agent (?:answered|is answering)',
          r'what does agent\s+\w+',r'which tools can agent\s+\w+',r'can an agent change its own role',
          r'what (?:prime )?generation',r'(?:source|runtime) identity',
          r'(?:多少|几个|数量).{0,12}(?:已注册)?代理',r'(?:已注册)?代理.{0,12}(?:多少|几个|数量)',
          r'(?:列出|有哪些|什么).{0,12}(?:已注册)?代理')
GOVERNANCE_PATTERNS=(r'phase.?2.*(?:verified|production.ready|golden|accepted)',r'(?:verified|production.ready|golden|accepted).*phase.?2',
                     r'(?:is|are).*(?:prime|jarvis).*(?:verified|production.ready|golden|accepted)')
PLATFORM_PATTERNS=(r'(?:abex|dell|orqevia|prime|jarvis).*(?:architecture|system|host|computer|relationship|role)',
                   r'(?:architecture|system|host|computer|relationship|role).*(?:abex|dell|orqevia|prime|jarvis)')
ROOT=Path(__file__).resolve().parent.parent

def is_architecture_question(text: str)->bool:
    return any(re.search(pattern,text or '',re.I) for pattern in (*PATTERNS,*GOVERNANCE_PATTERNS,*PLATFORM_PATTERNS))

def _governance_answer(question: str)->dict[str,Any]:
    return {'status': 'UNVERIFIED', 'provenance': 'RETIRED_HISTORICAL_ACCEPTANCE',
            'text': ('PRIME/JARVIS Phase-2 and Golden acceptance are dated historical records. '
                     'They are retired as current ORQEVIA authority and remain in Git/history custody. '
                     'Current source identity, individual capabilities and actual live acceptance must be verified separately. '
                     'No historical generation or source declaration proves present runtime health.')}

def _runtime()->dict[str,Any]:
    source=os.getenv('ORQEVIA_INTERFACE_RUNTIME_REVISION',os.getenv('ORQEVIA_RUNTIME_REVISION','UNKNOWN')).strip().lower()
    image=os.getenv('ORQEVIA_RUNTIME_IMAGE_DIGEST','').strip() or 'UNAVAILABLE'
    if not re.fullmatch(r'[0-9a-f]{40}',source):source='UNAVAILABLE'
    return {'source_revision':source,'image_digest':image}

def _platform_answer()->dict[str,Any]:
    path = ROOT/'config/runtime-architecture.json'
    try:
        value = json.loads(path.read_text(encoding='utf8'))
        registry = load_agent_registry()
        if (value.get('schema') != 'orqevia.runtime-architecture.v1'
                or value.get('product') != 'ORQEVIA'
                or value.get('logical_coordinator') != orchestrator_id()
                or value.get('declaration_scope') != 'SOURCE_CONFIGURATION_NOT_LIVE_HEALTH_OR_ACCEPTANCE'
                or not value.get('service_roles')):
            raise ValueError('invalid current architecture declaration')
    except OSError:
        return {'status': 'UNAVAILABLE', 'provenance': 'CURRENT_SOURCE_ARCHITECTURE',
                'text': 'Current source architecture is unavailable. ORQEVIA will not infer live topology from model memory.'}
    except (ValueError, TypeError, RegistryError):
        return {'status': 'UNVERIFIED', 'provenance': 'CURRENT_SOURCE_ARCHITECTURE',
                'text': 'Current source architecture is unavailable or incomplete. ORQEVIA will not infer live topology from model memory.'}
    runtime = _runtime()
    bound = runtime['source_revision'] != 'UNAVAILABLE' and bool(re.fullmatch(r'sha256:[0-9a-f]{64}', runtime['image_digest']))
    lines = [f"SOURCE-DECLARED HOST: {value['host']}",
             f"LOGICAL COORDINATOR: {value['logical_coordinator']}",
             f"EXECUTION MODEL: {value['execution_model']}",
             f"REGISTERED AGENTS: {len(registry['agents'])}",
             f"DECLARED SERVICE ROLES: {', '.join(value['service_roles'])}",
             f"HTTPS ENTRYPOINT: {value['public_entrypoint']}",
             f"PROCESS SOURCE: {runtime['source_revision']}",
             f"PROCESS IMAGE: {runtime['image_digest']}",
             'LIVE SERVICE HEALTH AND COMPLETE ACCEPTANCE: NOT PROBED',
             'A Dell or physical phone connection requires its own actual round-trip.']
    return {'status': 'VERIFIED' if bound else 'UNVERIFIED',
            'provenance': 'CURRENT_SOURCE_ARCHITECTURE_AND_PROCESS_IDENTITY',
            'scope': 'SOURCE_DECLARATION_AND_PROCESS_IDENTITY_NOT_SERVICE_HEALTH', 'text': '\n'.join(lines)}

def architecture_answer(question: str)->dict[str,Any]:
    """Fail closed: registry/runtime absence becomes UNAVAILABLE, never model intuition."""
    if any(re.search(pattern,question or '',re.I) for pattern in GOVERNANCE_PATTERNS):return _governance_answer(question)
    if any(re.search(pattern,question or '',re.I) for pattern in PLATFORM_PATTERNS):return _platform_answer()
    try:registry=load_agent_registry()
    except (OSError,ValueError,RegistryError):
        return {'status':'UNAVAILABLE','provenance':'CANONICAL_REGISTRY','text':'ORQEVIA architecture information is currently UNAVAILABLE. ORQEVIA will not guess.'}
    agents=list(registry['agents']); lower=question.lower(); lines=[]
    chinese=bool(re.search(r'[\u3400-\u4dbf\u4e00-\u9fff]',question))
    asks_count='how many agents' in lower or bool(re.search(r'(?:多少|几个|数量).{0,12}(?:已注册)?代理|(?:已注册)?代理.{0,12}(?:多少|几个|数量)',question))
    if asks_count:
        lines=([f"我叫 ORQEVIA。已注册代理：{len(agents)} 个。",'本次任务实际参与：ORQEVIA 确定性控制平面；此架构查询未选择模型代理。'] if chinese else
               [f"REGISTERED AGENTS: {len(agents)}",'ACTIVE/INVOLVED IN THIS TASK: deterministic ORQEVIA control plane; no model agent selected for this architecture lookup.'])
    elif re.search(r'list (?:your|the) agents',lower):
        lines=[f"REGISTERED AGENTS: {len(agents)}"]+[f"{item['id']}: {item['role']}" for item in agents]
    elif 'which agent answered' in lower or 'which agent is answering' in lower:
        lines=['ACTIVE/INVOLVED IN THIS TASK: deterministic ORQEVIA control plane.','No model self-description is used as agent identity.']
    elif 'can an agent change its own role' in lower:
        lines=['NO. Agent roles and authority come from the canonical registry and cannot be self-modified by an agent or model.']
    elif 'generation' in lower or 'source' in lower or 'runtime identity' in lower:
        runtime=_runtime()
        if 'UNAVAILABLE' in runtime.values():
            return {'status':'UNAVAILABLE','provenance':'CANONICAL_RUNTIME','text':'Runtime identity is currently UNAVAILABLE. ORQEVIA will not guess.'}
        lines=[f"SOURCE REVISION: {runtime['source_revision']}",f"IMAGE IDENTITY: {runtime['image_digest']}"]
    else:
        match=re.search(r'agent\s+([a-z]\d{2}|prime)\b',lower)
        try:item=agent_record(match.group(1) if match else '')
        except RegistryError:return {'status':'UNAVAILABLE','provenance':'CANONICAL_REGISTRY','text':'That agent is not present in the current canonical registry. ORQEVIA will not invent a role or tools.'}
        lines=[f"AGENT: {item['id']}",f"ROLE: {item.get('role','UNAVAILABLE')}"]
        if 'tool' in lower:lines.append('ELIGIBLE TOOLS: '+(', '.join(item.get('tool_eligibility',[])) or 'NONE RECORDED'))
        else:lines.append('PURPOSE: '+str(item.get('public_description') or item.get('purpose') or 'UNAVAILABLE'))
    return {'status':'VERIFIED','provenance':'CANONICAL_REGISTRY_AND_RUNTIME','registry_id':registry['registry_id'],
            'registry_version':registry['registry_version'],'orchestrator_id':orchestrator_id(),'text':'\n'.join(lines)}

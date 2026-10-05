"""Deterministic, system-owned answers for PRIME architecture questions."""
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
PLATFORM_PATTERNS=(r'(?:abex|dell|prime|jarvis).*(?:architecture|system|host|computer|relationship|role)',
                   r'(?:architecture|system|host|computer|relationship|role).*(?:abex|dell|prime|jarvis)')
ROOT=Path(__file__).resolve().parent.parent

def is_architecture_question(text: str)->bool:
    return any(re.search(pattern,text or '',re.I) for pattern in (*PATTERNS,*GOVERNANCE_PATTERNS,*PLATFORM_PATTERNS))

def _governance_answer(question: str)->dict[str,Any]:
    # The old phase2-state.json describes an isolated pre-promotion candidate.
    # It must not override the accepted Gen2 deployment record.
    gen1=bool(re.search(r'(?:gen(?:eration)?[ -]?1|golden[ -]?1)',question,re.I))
    path=ROOT/'governance'/('golden-gen1-manifest.json' if gen1 else 'golden-gen2-manifest.json')
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError,TypeError):
        return {'status':'UNVERIFIED','provenance':'GOVERNANCE_MANIFEST','text':'The requested governance record is unavailable. Runtime or model assertions cannot replace it.'}
    acceptance=value.get('acceptance',{}).get('state','UNVERIFIED')
    source=value.get('source',{}).get('accepted_commit','UNAVAILABLE')
    image=value.get('build',{}).get('image_id','UNAVAILABLE')
    runtime=_runtime()
    live=not gen1 and runtime=={'source_revision':source,'image_digest':image}
    asks_all=bool(re.search(r'\ball\b',question,re.I))
    scope='HISTORICAL GOLDEN GEN1 ROLLBACK' if gen1 else 'RECORDED GOLDEN GEN2 NON-AUDIO ACCEPTANCE'
    text=(f"{scope}: {acceptance}\nRECORDED SOURCE: {source}\n"
          f"CURRENT RUNTIME IDENTITY MATCH: {'PASS' if live else 'UNVERIFIED'}\n"
          f"ALL CAPABILITIES ACCEPTED: {'NO' if not gen1 and asks_all else 'NOT ASSESSED'}\n"
          f"RECORDED INDEPENDENT REVIEW: {value.get('qualification',{}).get('independent_review','UNAVAILABLE')}\n"
          'CURRENT DELL ROUND-TRIP: UNVERIFIED\n'
          'Audio remains excluded from the Gen2 acceptance. Historical acceptance alone does not prove current runtime health.')
    return {'status':'VERIFIED' if live and not asks_all else 'UNVERIFIED',
            'provenance':'GOVERNANCE_MANIFEST_AND_RUNTIME', 'text':text}

def _runtime()->dict[str,Any]:
    source=os.getenv('PRIME_INTERFACE_RUNTIME_REVISION',os.getenv('PRIME_RUNTIME_REVISION','UNKNOWN')).strip().lower()
    image=os.getenv('PRIME_RUNTIME_IMAGE_DIGEST','').strip() or 'UNAVAILABLE'
    if not re.fullmatch(r'[0-9a-f]{40}',source):source='UNAVAILABLE'
    return {'source_revision':source,'image_digest':image}

def _platform_answer()->dict[str,Any]:
    path=ROOT/'governance'/'golden-gen2-manifest.json'
    try:value=json.loads(path.read_text(encoding='utf-8'));registry=load_agent_registry()
    except (OSError,ValueError,TypeError,RegistryError):
        return {'status':'UNAVAILABLE','provenance':'GOVERNANCE_MANIFEST_AND_AGENT_REGISTRY','text':f'Platform architecture is UNAVAILABLE because {path.name} or the agent registry could not be read. JARVIS will not infer it from model memory.'}
    authority=value.get('authority',{});source=value.get('source',{});interface=value.get('interface',{});build=value.get('build',{})
    required=(authority.get('production_authority'),source.get('accepted_commit'),
              interface.get('exposure'),build.get('image_id'))
    if (not all(isinstance(item,str) and item.strip() for item in required)
            or not isinstance(value.get('generation'),int) or value.get('generation')<1
            or not re.fullmatch(r'[0-9a-f]{40}',source.get('accepted_commit',''))
            or not registry.get('agents')):
        return {'status':'UNVERIFIED','provenance':'GOVERNANCE_MANIFEST_AND_AGENT_REGISTRY','text':'Platform architecture is UNVERIFIED because required host, generation, source, image, exposure or registry bindings are incomplete. JARVIS will not infer them from model memory.'}
    runtime=_runtime()
    live=runtime=={'source_revision':source['accepted_commit'],'image_digest':build['image_id']}
    lines=[f"PRODUCTION AUTHORITY/HOST: {authority.get('production_authority','UNAVAILABLE')}",
           f"GOLDEN GENERATION: {value.get('generation','UNAVAILABLE')}",
           f"RECORDED ACCEPTED SOURCE: {source.get('accepted_commit','UNAVAILABLE')}",
           f"REGISTERED AGENTS: {len(registry.get('agents',[]))}",
           f"INTERFACE EXPOSURE: {interface.get('exposure','UNAVAILABLE')}",
           f"CURRENT RUNTIME IDENTITY MATCH: {'PASS' if live else 'UNVERIFIED'}",
           'Dell live peer verification requires a separate current round-trip.']
    return {'status':'VERIFIED' if live else 'UNVERIFIED','provenance':'GOVERNANCE_MANIFEST_AGENT_REGISTRY_AND_RUNTIME','text':'\n'.join(lines)}

def architecture_answer(question: str)->dict[str,Any]:
    """Fail closed: registry/runtime absence becomes UNAVAILABLE, never model intuition."""
    if any(re.search(pattern,question or '',re.I) for pattern in GOVERNANCE_PATTERNS):return _governance_answer(question)
    if any(re.search(pattern,question or '',re.I) for pattern in PLATFORM_PATTERNS):return _platform_answer()
    try:registry=load_agent_registry()
    except (OSError,ValueError,RegistryError):
        return {'status':'UNAVAILABLE','provenance':'CANONICAL_REGISTRY','text':'PRIME architecture information is currently UNAVAILABLE. JARVIS will not guess.'}
    agents=list(registry['agents']); lower=question.lower(); lines=[]
    chinese=bool(re.search(r'[\u3400-\u4dbf\u4e00-\u9fff]',question))
    asks_count='how many agents' in lower or bool(re.search(r'(?:多少|几个|数量).{0,12}(?:已注册)?代理|(?:已注册)?代理.{0,12}(?:多少|几个|数量)',question))
    if asks_count:
        lines=([f"我叫 JARVIS。已注册代理：{len(agents)} 个。",'本次任务实际参与：PRIME 确定性控制平面；此架构查询未选择模型代理。'] if chinese else
               [f"REGISTERED AGENTS: {len(agents)}",'ACTIVE/INVOLVED IN THIS TASK: deterministic PRIME control plane; no model agent selected for this architecture lookup.'])
    elif re.search(r'list (?:your|the) agents',lower):
        lines=[f"REGISTERED AGENTS: {len(agents)}"]+[f"{item['id']}: {item['role']}" for item in agents]
    elif 'which agent answered' in lower or 'which agent is answering' in lower:
        lines=['ACTIVE/INVOLVED IN THIS TASK: deterministic PRIME control plane.','No model self-description is used as agent identity.']
    elif 'can an agent change its own role' in lower:
        lines=['NO. Agent roles and authority come from the canonical registry and cannot be self-modified by an agent or model.']
    elif 'generation' in lower or 'source' in lower or 'runtime identity' in lower:
        runtime=_runtime()
        if 'UNAVAILABLE' in runtime.values():
            return {'status':'UNAVAILABLE','provenance':'CANONICAL_RUNTIME','text':'Runtime identity is currently UNAVAILABLE. JARVIS will not guess.'}
        lines=[f"SOURCE REVISION: {runtime['source_revision']}",f"IMAGE IDENTITY: {runtime['image_digest']}"]
    else:
        match=re.search(r'agent\s+([a-z]\d{2}|prime)\b',lower)
        try:item=agent_record(match.group(1) if match else '')
        except RegistryError:return {'status':'UNAVAILABLE','provenance':'CANONICAL_REGISTRY','text':'That agent is not present in the current canonical registry. JARVIS will not invent a role or tools.'}
        lines=[f"AGENT: {item['id']}",f"ROLE: {item.get('role','UNAVAILABLE')}"]
        if 'tool' in lower:lines.append('ELIGIBLE TOOLS: '+(', '.join(item.get('tool_eligibility',[])) or 'NONE RECORDED'))
        else:lines.append('PURPOSE: '+str(item.get('public_description') or item.get('purpose') or 'UNAVAILABLE'))
    return {'status':'VERIFIED','provenance':'CANONICAL_REGISTRY_AND_RUNTIME','registry_id':registry['registry_id'],
            'registry_version':registry['registry_version'],'orchestrator_id':orchestrator_id(),'text':'\n'.join(lines)}

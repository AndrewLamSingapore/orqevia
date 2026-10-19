import pytest
from app import system_architecture as facts

@pytest.mark.parametrize('question',["How many agents do you have?","List your agents.","Which agent answered this?",
    "What does agent a02 do?","Which tools can agent a02 use?","Can an agent change its own role?",
    "What PRIME generation are you running?","What is your source/runtime identity?"])
def test_architecture_questions_use_canonical_system_facts(question,monkeypatch):
    monkeypatch.setenv('ORQEVIA_INTERFACE_RUNTIME_REVISION','f'*40);monkeypatch.setenv('ORQEVIA_RUNTIME_IMAGE_DIGEST','sha256:'+'a'*64)
    assert facts.is_architecture_question(question)
    answer=facts.architecture_answer(question)
    assert answer['provenance']=='CANONICAL_REGISTRY_AND_RUNTIME' and answer['status']=='VERIFIED'
    assert 'sole agent' not in answer['text'].lower()

def test_registered_count_defeats_model_single_agent_self_description():
    answer=facts.architecture_answer('How many agents do you have?')
    assert 'REGISTERED AGENTS: 21' in answer['text']
    assert 'ACTIVE/INVOLVED IN THIS TASK:' in answer['text']

def test_chinese_combined_identity_and_agent_count_uses_registry_not_model():
    question='请用中文回答：你叫什么名字？你有多少个已注册代理？'
    assert facts.is_architecture_question(question)
    answer=facts.architecture_answer(question)
    assert answer['status']=='VERIFIED'
    assert answer['provenance']=='CANONICAL_REGISTRY_AND_RUNTIME'
    assert 'ORQEVIA' in answer['text'] and '21' in answer['text']
    assert '三个' not in answer['text']

def test_unavailable_registry_abstains_instead_of_fabricating(monkeypatch):
    def unavailable():raise facts.RegistryError('offline')
    monkeypatch.setattr(facts,'load_agent_registry',unavailable)
    answer=facts.architecture_answer('How many agents do you have?')
    assert answer['status']=='UNAVAILABLE' and 'will not guess' in answer['text']

def test_unknown_agent_abstains():
    answer=facts.architecture_answer('What does agent a99 do?')
    assert answer['status']=='UNAVAILABLE' and 'will not invent' in answer['text']

@pytest.mark.parametrize('question',["Are all JARVIS Phase-2 capabilities production-ready?","Is Phase 2 independently verified?","Is Phase 2 Golden and accepted?"])
def test_governance_questions_use_gen4_record_not_superseded_candidate(question,monkeypatch):
    monkeypatch.delenv('ORQEVIA_INTERFACE_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('ORQEVIA_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('ORQEVIA_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer(question)
    assert answer['provenance']=='GOVERNANCE_MANIFEST_AND_RUNTIME'
    assert 'VERIFIED_WITH_EXPLICIT_AUDIO_EXCLUSION' in answer['text']
    assert '48648edd8d2640f12f8086b9910deec865519326' in answer['text']
    assert 'NOT_DEPLOYED' not in answer['text']
    assert answer['status']=='UNVERIFIED'  # no current runtime identity injected

def test_missing_governance_record_abstains(monkeypatch,tmp_path):
    monkeypatch.setattr(facts,'ROOT',tmp_path)
    answer=facts.architecture_answer('Is Phase 2 verified?')
    assert answer['status']=='UNVERIFIED' and 'governance record is unavailable' in answer['text']

def test_golden_governance_uses_accepted_gen4_and_retires_history(monkeypatch):
    monkeypatch.delenv('ORQEVIA_INTERFACE_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('ORQEVIA_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('ORQEVIA_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer('Is JARVIS PRIME Golden and accepted?')
    assert answer['status']=='UNVERIFIED' and '48648edd8d2640f12f8086b9910deec865519326' in answer['text']
    assert 'CURRENT RUNTIME IDENTITY MATCH: UNVERIFIED' in answer['text']
    gen1=facts.architecture_answer('Is JARVIS PRIME Golden Gen1 accepted?')
    assert gen1['status']=='UNVERIFIED'
    assert 'HISTORICAL GOLDEN GEN1/2/3 RECORDS ARE RETIRED' in gen1['text']
    assert 'orqevia-golden-gen4-20261016' in gen1['text']

def test_golden_runtime_match_requires_both_source_and_image(monkeypatch):
    monkeypatch.setenv('ORQEVIA_INTERFACE_RUNTIME_REVISION','48648edd8d2640f12f8086b9910deec865519326')
    monkeypatch.setenv('ORQEVIA_RUNTIME_IMAGE_DIGEST','sha256:aca892c4f19a4426e960d273ee0e9524f7bfe7f08bb80b902e7cbc73b82d36f3')
    assert facts.architecture_answer('Is Phase 2 Golden and accepted?')['status']=='VERIFIED'
    all_answer=facts.architecture_answer('Are all JARVIS Phase-2 capabilities production-ready?')
    assert all_answer['status']=='UNVERIFIED' and 'ALL CAPABILITIES ACCEPTED: NO' in all_answer['text']
    monkeypatch.setenv('ORQEVIA_RUNTIME_IMAGE_DIGEST','sha256:'+'0'*64)
    assert facts.architecture_answer('Is Phase 2 Golden and accepted?')['status']=='UNVERIFIED'

def test_runtime_identity_abstains_when_environment_is_unavailable(monkeypatch):
    monkeypatch.delenv('ORQEVIA_INTERFACE_RUNTIME_REVISION',raising=False);monkeypatch.delenv('ORQEVIA_RUNTIME_REVISION',raising=False);monkeypatch.delenv('ORQEVIA_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer('What is your source/runtime identity?')
    assert answer['status']=='UNAVAILABLE' and 'will not guess' in answer['text']

def test_platform_architecture_uses_gen4_registry_and_does_not_invent_live_dell(monkeypatch):
    monkeypatch.delenv('ORQEVIA_INTERFACE_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('ORQEVIA_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('ORQEVIA_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer('Explain the ABEX, Dell, and PRIME architecture relationship')
    assert answer['status']=='UNVERIFIED' and answer['provenance']=='GOVERNANCE_MANIFEST_AGENT_REGISTRY_AND_RUNTIME'
    assert 'PRODUCTION AUTHORITY/HOST: ABEX' in answer['text'] and 'REGISTERED AGENTS: 21' in answer['text']
    assert 'GOLDEN GENERATION: 4' in answer['text']
    assert 'Dell live peer verification requires a separate current round-trip.' in answer['text']

def test_incomplete_platform_manifest_abstains(monkeypatch,tmp_path):
    (tmp_path/'governance').mkdir();(tmp_path/'governance'/'golden-gen4-manifest.json').write_text('{}')
    monkeypatch.setattr(facts,'ROOT',tmp_path)
    answer=facts.architecture_answer('Explain the ABEX, Dell, and PRIME architecture relationship')
    assert answer['status']=='UNVERIFIED' and 'required host' in answer['text']

def test_architecture_objective_bypasses_model_and_returns_system_fact(monkeypatch,tmp_path):
    from app import objective_api
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(objective_api,'authenticate_owner',lambda authorization: {'role':'OWNER'})
    submitted=objective_api.submit(objective_api.ObjectiveRequest(objective='How many agents do you have?',context=''),authorization='fixture')
    task=objective_api.get(submitted['id'],authorization='fixture')
    assert task['state']=='COMPLETED' and task['result']['type']=='SYSTEM_FACT' and task['result']['authoritative'] is True
    assert 'REGISTERED AGENTS: 21' in task['result']['text']
    assert task['execution_metadata']['agent_execution']==[]

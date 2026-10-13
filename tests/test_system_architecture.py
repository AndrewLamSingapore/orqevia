import pytest
from app import system_architecture as facts

@pytest.mark.parametrize('question',["How many agents do you have?","List your agents.","Which agent answered this?",
    "What does agent a02 do?","Which tools can agent a02 use?","Can an agent change its own role?",
    "What PRIME generation are you running?","What is your source/runtime identity?"])
def test_architecture_questions_use_canonical_system_facts(question,monkeypatch):
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_REVISION','f'*40);monkeypatch.setenv('PRIME_RUNTIME_IMAGE_DIGEST','sha256:'+'a'*64)
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
    assert 'ORQEVIA · 奥启维亚' in answer['text'] and '21' in answer['text']
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
def test_governance_questions_use_gen2_record_not_superseded_candidate(question,monkeypatch):
    monkeypatch.delenv('PRIME_INTERFACE_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('PRIME_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('PRIME_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer(question)
    assert answer['provenance']=='GOVERNANCE_MANIFEST_AND_RUNTIME'
    assert 'VERIFIED_WITH_EXPLICIT_AUDIO_EXCLUSION' in answer['text']
    assert 'b171253566e7c879283d2aacf699ae6c1ec8988e' in answer['text']
    assert 'NOT_DEPLOYED' not in answer['text']
    assert answer['status']=='UNVERIFIED'  # no current runtime identity injected

def test_missing_governance_record_abstains(monkeypatch,tmp_path):
    monkeypatch.setattr(facts,'ROOT',tmp_path)
    answer=facts.architecture_answer('Is Phase 2 verified?')
    assert answer['status']=='UNVERIFIED' and 'governance record is unavailable' in answer['text']

def test_golden_governance_uses_accepted_gen2_and_bounds_gen1_history(monkeypatch):
    monkeypatch.delenv('PRIME_INTERFACE_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('PRIME_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('PRIME_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer('Is JARVIS PRIME Golden and accepted?')
    assert answer['status']=='UNVERIFIED' and 'b171253566e7c879283d2aacf699ae6c1ec8988e' in answer['text']
    assert 'CURRENT RUNTIME IDENTITY MATCH: UNVERIFIED' in answer['text']
    gen1=facts.architecture_answer('Is JARVIS PRIME Golden Gen1 accepted?')
    assert 'HISTORICAL GOLDEN GEN1 ROLLBACK' in gen1['text']
    assert '17fad78d410dca5d9101483cb777a2b9b619bac3' in gen1['text']

def test_golden_runtime_match_requires_both_source_and_image(monkeypatch):
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_REVISION','b171253566e7c879283d2aacf699ae6c1ec8988e')
    monkeypatch.setenv('PRIME_RUNTIME_IMAGE_DIGEST','sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5')
    assert facts.architecture_answer('Is Phase 2 Golden and accepted?')['status']=='VERIFIED'
    all_answer=facts.architecture_answer('Are all JARVIS Phase-2 capabilities production-ready?')
    assert all_answer['status']=='UNVERIFIED' and 'ALL CAPABILITIES ACCEPTED: NO' in all_answer['text']
    monkeypatch.setenv('PRIME_RUNTIME_IMAGE_DIGEST','sha256:'+'0'*64)
    assert facts.architecture_answer('Is Phase 2 Golden and accepted?')['status']=='UNVERIFIED'

def test_runtime_identity_abstains_when_environment_is_unavailable(monkeypatch):
    monkeypatch.delenv('PRIME_INTERFACE_RUNTIME_REVISION',raising=False);monkeypatch.delenv('PRIME_RUNTIME_REVISION',raising=False);monkeypatch.delenv('PRIME_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer('What is your source/runtime identity?')
    assert answer['status']=='UNAVAILABLE' and 'will not guess' in answer['text']

def test_platform_architecture_uses_gen2_registry_and_does_not_invent_live_dell(monkeypatch):
    monkeypatch.delenv('PRIME_INTERFACE_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('PRIME_RUNTIME_REVISION',raising=False)
    monkeypatch.delenv('PRIME_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer('Explain the ABEX, Dell, and PRIME architecture relationship')
    assert answer['status']=='UNVERIFIED' and answer['provenance']=='GOVERNANCE_MANIFEST_AGENT_REGISTRY_AND_RUNTIME'
    assert 'PRODUCTION AUTHORITY/HOST: ABEX' in answer['text'] and 'REGISTERED AGENTS: 21' in answer['text']
    assert 'GOLDEN GENERATION: 2' in answer['text']
    assert 'Dell live peer verification requires a separate current round-trip.' in answer['text']

def test_incomplete_platform_manifest_abstains(monkeypatch,tmp_path):
    (tmp_path/'governance').mkdir();(tmp_path/'governance'/'golden-gen2-manifest.json').write_text('{}')
    monkeypatch.setattr(facts,'ROOT',tmp_path)
    answer=facts.architecture_answer('Explain the ABEX, Dell, and PRIME architecture relationship')
    assert answer['status']=='UNVERIFIED' and 'required host' in answer['text']

def test_architecture_objective_bypasses_model_and_returns_system_fact(monkeypatch,tmp_path):
    from app import objective_api
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(objective_api,'authenticate_owner',lambda authorization: {'role':'OWNER'})
    submitted=objective_api.submit(objective_api.ObjectiveRequest(objective='How many agents do you have?',context=''),authorization='fixture')
    task=objective_api.get(submitted['id'],authorization='fixture')
    assert task['state']=='COMPLETED' and task['result']['type']=='SYSTEM_FACT' and task['result']['authoritative'] is True
    assert 'REGISTERED AGENTS: 21' in task['result']['text']
    assert task['execution_metadata']['agent_execution']==[]

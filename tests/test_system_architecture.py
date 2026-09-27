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
    assert 'JARVIS' in answer['text'] and '21' in answer['text']
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
def test_governance_questions_use_current_ssot_not_owner_or_model_claim(question):
    answer=facts.architecture_answer(question)
    assert answer['provenance']=='CANONICAL_GOVERNANCE_SSOT'
    assert 'NOT_DEPLOYED' in answer['text'] and 'PENDING_NEW_CANDIDATE_FREEZE' in answer['text']
    assert 'Owner statements are evidence of the Owner statement only' in answer['text']

def test_missing_governance_ssot_abstains(monkeypatch,tmp_path):
    monkeypatch.setattr(facts,'ROOT',tmp_path)
    answer=facts.architecture_answer('Is Phase 2 verified?')
    assert answer['status']=='UNVERIFIED' and 'canonical evidence is unavailable' in answer['text']

def test_golden_governance_uses_nested_canonical_manifest_fields():
    answer=facts.architecture_answer('Is JARVIS PRIME Golden and accepted?')
    assert answer['status']=='VERIFIED' and '17fad78d410dca5d9101483cb777a2b9b619bac3' in answer['text']

def test_runtime_identity_abstains_when_environment_is_unavailable(monkeypatch):
    monkeypatch.delenv('PRIME_INTERFACE_RUNTIME_REVISION',raising=False);monkeypatch.delenv('PRIME_RUNTIME_REVISION',raising=False);monkeypatch.delenv('PRIME_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer('What is your source/runtime identity?')
    assert answer['status']=='UNAVAILABLE' and 'will not guess' in answer['text']

def test_platform_architecture_uses_golden_ssot_registry_and_exact_dell_scope():
    answer=facts.architecture_answer('Explain the ABEX, Dell, and PRIME architecture relationship')
    assert answer['status']=='VERIFIED' and answer['provenance']=='CANONICAL_GOVERNANCE_SSOT_AND_REGISTRY'
    assert 'PRODUCTION AUTHORITY/HOST: ABEX' in answer['text'] and 'REGISTERED AGENTS: 21' in answer['text']
    assert 'DELL INDEPENDENT VERIFICATION: PASS' in answer['text']

def test_incomplete_platform_manifest_abstains(monkeypatch,tmp_path):
    (tmp_path/'governance').mkdir();(tmp_path/'governance'/'golden-gen1-manifest.json').write_text('{}')
    monkeypatch.setattr(facts,'ROOT',tmp_path)
    answer=facts.architecture_answer('Explain the ABEX, Dell, and PRIME architecture relationship')
    assert answer['status']=='UNVERIFIED' and 'mandatory canonical' in answer['text']

def test_architecture_objective_bypasses_model_and_returns_system_fact(monkeypatch,tmp_path):
    from app import objective_api
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(objective_api,'authenticate_owner',lambda authorization: {'role':'OWNER'})
    submitted=objective_api.submit(objective_api.ObjectiveRequest(objective='How many agents do you have?',context=''),authorization='fixture')
    task=objective_api.get(submitted['id'],authorization='fixture')
    assert task['state']=='COMPLETED' and task['result']['type']=='SYSTEM_FACT' and task['result']['authoritative'] is True
    assert 'REGISTERED AGENTS: 21' in task['result']['text']
    assert task['execution_metadata']['agent_execution']==[]

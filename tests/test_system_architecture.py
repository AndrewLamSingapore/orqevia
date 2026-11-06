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
def test_dated_governance_questions_cannot_establish_current_acceptance(question, monkeypatch):
    answer = facts.architecture_answer(question)
    assert answer['status'] == 'UNVERIFIED'
    assert answer['provenance'] == 'RETIRED_HISTORICAL_ACCEPTANCE'
    assert 'dated historical records' in answer['text']
    assert 'actual live acceptance must be verified separately' in answer['text']

def test_current_architecture_has_no_mandatory_historical_governance_record(monkeypatch, tmp_path):
    monkeypatch.setattr(facts, 'ROOT', tmp_path)
    answer = facts.architecture_answer('Is Phase 2 verified?')
    assert answer['status'] == 'UNVERIFIED'
    assert answer['provenance'] == 'RETIRED_HISTORICAL_ACCEPTANCE'

def test_all_old_golden_generations_remain_history_without_current_authority():
    for question in ('Is JARVIS PRIME Golden and accepted?', 'Is JARVIS PRIME Golden Gen1 accepted?'):
        answer = facts.architecture_answer(question)
        assert answer['status'] == 'UNVERIFIED'
        assert 'retired as current ORQEVIA authority' in answer['text']

def test_matching_an_old_source_and_image_cannot_promote_historical_acceptance(monkeypatch):
    monkeypatch.setenv('ORQEVIA_INTERFACE_RUNTIME_REVISION', '48648edd8d2640f12f8086b9910deec865519326')
    monkeypatch.setenv('ORQEVIA_RUNTIME_IMAGE_DIGEST', 'sha256:aca892c4f19a4426e960d273ee0e9524f7bfe7f08bb80b902e7cbc73b82d36f3')
    for question in ('Is Phase 2 Golden and accepted?', 'Are all JARVIS Phase-2 capabilities production-ready?'):
        assert facts.architecture_answer(question)['status'] == 'UNVERIFIED'

def test_runtime_identity_abstains_when_environment_is_unavailable(monkeypatch):
    monkeypatch.delenv('ORQEVIA_INTERFACE_RUNTIME_REVISION',raising=False);monkeypatch.delenv('ORQEVIA_RUNTIME_REVISION',raising=False);monkeypatch.delenv('ORQEVIA_RUNTIME_IMAGE_DIGEST',raising=False)
    answer=facts.architecture_answer('What is your source/runtime identity?')
    assert answer['status']=='UNAVAILABLE' and 'will not guess' in answer['text']

def test_platform_architecture_uses_current_source_and_does_not_invent_live_dell(monkeypatch):
    for name in ('ORQEVIA_INTERFACE_RUNTIME_REVISION', 'ORQEVIA_RUNTIME_REVISION', 'ORQEVIA_RUNTIME_IMAGE_DIGEST'):
        monkeypatch.delenv(name, raising=False)
    answer = facts.architecture_answer('Explain the ABEX, Dell, and ORQEVIA architecture relationship')
    assert answer['status'] == 'UNVERIFIED'
    assert answer['provenance'] == 'CURRENT_SOURCE_ARCHITECTURE_AND_PROCESS_IDENTITY'
    assert 'SOURCE-DECLARED HOST: ABEX' in answer['text']
    assert 'REGISTERED AGENTS: 21' in answer['text']
    assert 'LOGICAL COORDINATOR: orqevia' in answer['text']
    assert 'LIVE SERVICE HEALTH AND COMPLETE ACCEPTANCE: NOT PROBED' in answer['text']
    assert 'physical phone connection requires its own actual round-trip' in answer['text']

def test_incomplete_current_platform_declaration_abstains(monkeypatch, tmp_path):
    (tmp_path/'config').mkdir()
    (tmp_path/'config/runtime-architecture.json').write_text('{}')
    monkeypatch.setattr(facts, 'ROOT', tmp_path)
    answer = facts.architecture_answer('Explain the ORQEVIA architecture')
    assert answer['status'] == 'UNVERIFIED'
    assert 'will not infer live topology' in answer['text']

def test_architecture_objective_bypasses_model_and_returns_system_fact(monkeypatch,tmp_path):
    from app import objective_api
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(objective_api,'authenticate_owner',lambda authorization: {'role':'OWNER'})
    submitted=objective_api.submit(objective_api.ObjectiveRequest(objective='How many agents do you have?',context=''),authorization='fixture')
    task=objective_api.get(submitted['id'],authorization='fixture')
    assert task['state']=='COMPLETED' and task['result']['type']=='SYSTEM_FACT' and task['result']['authoritative'] is True
    assert 'REGISTERED AGENTS: 21' in task['result']['text']
    assert task['execution_metadata']['agent_execution']==[]


def test_current_process_identity_is_separate_from_source_and_health(monkeypatch):
    monkeypatch.setenv('ORQEVIA_INTERFACE_RUNTIME_REVISION', 'f'*40)
    monkeypatch.setenv('ORQEVIA_RUNTIME_IMAGE_DIGEST', 'sha256:'+'a'*64)
    answer = facts.architecture_answer('Explain the ORQEVIA architecture')
    assert answer['status'] == 'VERIFIED'
    assert answer['scope'] == 'SOURCE_DECLARATION_AND_PROCESS_IDENTITY_NOT_SERVICE_HEALTH'
    assert 'LIVE SERVICE HEALTH AND COMPLETE ACCEPTANCE: NOT PROBED' in answer['text']

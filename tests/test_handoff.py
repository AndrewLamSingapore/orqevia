import pytest
from app.handoff import validate_handoff


def fixture():
    return dict(schema_version='1.0', task_id='t', facts=['verified input'], results=['result'], evidence_refs=['sha256:abc'], artifact_refs=['artifact-id'], acceptance_criteria=['independent tests pass'])


def test_minimal_handoff_is_copied_and_bounded():
    original = fixture()
    result = validate_handoff(original)
    original['facts'].append('later')
    assert result['facts'] == ['verified input']
    for key, value in [('reasoning_history', ['raw thoughts']), ('facts', ['x'*1025]), ('results', [{'reasoning': 'raw'}])]:
        invalid = fixture(); invalid[key] = value
        with pytest.raises(ValueError): validate_handoff(invalid)


def test_aggregate_byte_budget():
    invalid = fixture()
    invalid['facts'] = ['x'*1024]*17
    with pytest.raises(ValueError): validate_handoff(invalid)


def extended_fixture():
    return {**fixture(), 'schema_version': '1.1', 'objective': 'Verify the supplied artifact',
            'constraints': ['Use provided evidence only'], 'changed_state': ['Artifact created'],
            'open_questions': ['Is independent verification complete?']}


def test_extended_packet_preserves_all_minimal_operational_fields():
    original = extended_fixture()
    copied = validate_handoff(original)
    assert copied == original
    original['constraints'].append('later mutation')
    assert copied['constraints'] == ['Use provided evidence only']
    assert validate_handoff(fixture()) == fixture()


@pytest.mark.parametrize('field', ['reasoning_history', 'chain_of_thought', 'conversation_history', 'messages'])
def test_raw_history_fields_are_rejected(field):
    invalid = extended_fixture()
    invalid[field] = ['raw transcript']
    with pytest.raises(ValueError): validate_handoff(invalid)


def test_extended_bounds_and_nested_payload_rejected():
    for key,value in [('objective','x'*2049),('changed_state',[{'analysis':'raw'}]),('open_questions',['x'*1025])]:
        invalid=extended_fixture(); invalid[key]=value
        with pytest.raises(ValueError):validate_handoff(invalid)

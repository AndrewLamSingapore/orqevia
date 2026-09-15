import pytest
from app.workflow_engine import Task, execute
from tests.test_handoff import fixture, extended_fixture


def test_invalid_handoff_stops_before_handlers_run():
    calls=[]
    packet=extended_fixture(); packet['reasoning_history']=['raw transcript']
    with pytest.raises(ValueError):
        execute((Task('a',(),'a09','capture'),),{'capture':lambda *args:calls.append(args)}, {'handoff':packet})
    assert calls==[]


@pytest.mark.parametrize('packet_factory',[fixture,extended_fixture])
def test_valid_handoff_preserved_between_handlers_and_caller(packet_factory):
    packet=packet_factory()
    def mutate(task,inputs,dependencies):
        inputs['handoff']['facts'].append('handler-local mutation')
        return 'done'
    def receive(task,inputs,dependencies):
        assert dependencies['a']['result']=='done'
        assert inputs['handoff']==packet
        return inputs['handoff']['task_id']
    result=execute((Task('a',(),'a09','mutate'),Task('b',('a',),'a18','receive')),
                   {'mutate':mutate,'receive':receive},{'handoff':packet})
    assert result['status']=='COMPLETED'
    assert packet['facts']==['verified input']


def test_workflow_without_handoff_is_unchanged():
    result=execute((Task('a',(),'a09','read'),),{'read':lambda task,inputs,deps:inputs['value']},{'value':7})
    assert result['tasks']['a']['result']==7

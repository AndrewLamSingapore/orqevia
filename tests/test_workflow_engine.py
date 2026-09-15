import threading
import pytest
from app.workflow_engine import Task,execute,save_template,load_template,validate


def test_real_dependencies_and_independent_parallel_progress(tmp_path):
    barrier=threading.Barrier(2,timeout=2)
    def independent(task,inputs,dependencies):
        barrier.wait()
        return inputs['value']*2
    def aggregate(task,inputs,dependencies):
        assert set(dependencies)=={'build','test'}
        return sum(row['result'] for row in dependencies.values())
    tasks=(Task('build',(),'a17','prepare'),Task('test',(),'a18','prepare'),
           Task('artifact',('build','test'),'a09','aggregate'))
    result=execute(tasks,{'prepare':independent,'aggregate':aggregate},{'value':3},workers=2)
    assert result['tasks']['artifact']['result']==12
    path=tmp_path/'workflow.json'
    digest=save_template(path,name='verified preparation',version='1',tasks=tasks,input_names=['value'])
    repeat=execute(load_template(path,digest),{'prepare':independent,'aggregate':aggregate},{'value':7},workers=2)
    assert repeat['tasks']['artifact']['result']==28


def test_failure_isolation_unknown_operation_and_cycle():
    tasks=(Task('bad',(),'a17','unknown'),Task('dependent',('bad',),'a18','good'),Task('independent',(),'a09','good'))
    result=execute(tasks,{'good':lambda *args:'ok'},{})
    assert result['tasks']['bad']['status']=='FAILED'
    assert result['tasks']['dependent']['status']=='BLOCKED'
    assert result['tasks']['independent']['status']=='COMPLETED'
    with pytest.raises(ValueError,match='cycle'):
        validate((Task('a',('b',),'a17','x'),Task('b',('a',),'a18','x')))

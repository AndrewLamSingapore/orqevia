import json
import pytest
from app import workspace_capabilities as work

def test_ideas_persist_without_executing_or_overwriting_other_records(tmp_path):
    assert work.ideas(tmp_path)['ideas']==[]
    first=work.ideas(tmp_path,{'title':'Investigate source provenance','body':'Preserve original records.'})
    second=work.ideas(tmp_path,{'title':'Follow up','body':'Review the first draft.'})
    assert len(second['ideas'])==2 and second['ideas'][0]==first['ideas'][0]
    assert all(i['state']=='DRAFT' for i in work.ideas(tmp_path)['ideas'])

def test_scaffolding_recovers_existing_generator_without_running_files(tmp_path):
    result=work.scaffold({'kind':'project','name':'Observed project','description':'Reviewable candidate only.'})
    assert result['files'] and result['execution_performed'] is False
    assert 'backend/app.py' in result['files'] and not list(tmp_path.iterdir())
    with pytest.raises(ValueError):work.scaffold({'kind':'arbitrary-shell','name':'x'})
    template=work.scaffold({'kind':'verification','name':'observed'})
    assert any('placeholder' in warning for warning in template['warnings'])

def test_workspace_status_does_not_invent_release_or_validation_success(tmp_path):
    status=work.workspace_status(tmp_path)
    assert status['release']['status']=='UNAVAILABLE'
    assert status['validation']['status']=='UNAVAILABLE'
    assert status['boundaries']['arbitrary_shell'] is False
    assert status['boundaries']['agent_registry_required'] is False

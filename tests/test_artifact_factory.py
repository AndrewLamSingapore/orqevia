import pytest
from app.artifact_factory import ArtifactFactory


@pytest.mark.parametrize('kind,content',[('python','def add(a,b):\n    return a+b\n'),('json','{"result":42}'),('csv','name,value\na,42\n'),('markdown','# Findings\n\nEvidence recorded.\n')])
def test_real_durable_artifact_roundtrip(tmp_path,kind,content):
    factory=ArtifactFactory(tmp_path/'artifacts')
    result=factory.create(kind=kind,content=content,task_id='task',creator='a17',provenance='isolated acceptance')
    metadata,raw=factory.retrieve(result['artifact_id'])
    assert raw.decode()==content and metadata['delivery_state']=='AVAILABLE'
    path=factory.root/result['artifact_id']/metadata['location']
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='integrity'):factory.retrieve(result['artifact_id'])


def test_traversal_invalid_structure_and_credentials_rejected(tmp_path):
    factory=ArtifactFactory(tmp_path)
    for artifact_id in ['../escape','/absolute','x'*32]:
        with pytest.raises(ValueError):factory.retrieve(artifact_id)
    for kind,content in [('json','{broken'),('python','def incomplete('),('markdown','password=secret')]:
        with pytest.raises((ValueError,SyntaxError)):
            factory.create(kind=kind,content=content,task_id='t',creator='a17',provenance='negative test')

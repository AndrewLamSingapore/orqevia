import hashlib
import pytest
from app.deterministic_ops import DeterministicOps


def test_content_and_source_version_invalidate(tmp_path):
    ops = DeterministicOps(source_version='a', max_entries=2)
    p = tmp_path/'evidence.json'
    p.write_bytes(b'{"a":1}')
    before = ops.retrieve_file(tmp_path, p.name)[1]
    assert ops.retrieve_file(tmp_path, p.name)[1] == before
    assert ops.metrics['hits'] == 1
    p.write_bytes(b'{"a":2}')
    assert ops.retrieve_file(tmp_path, p.name)[1] != before
    with pytest.raises(ValueError):
        ops.retrieve_file(tmp_path, p.name, expected_sha256=before)
    misses = ops.metrics['misses']
    ops.source_version = 'b'
    ops.retrieve_file(tmp_path, p.name)
    assert ops.metrics['misses'] == misses + 1
    assert ops.metrics['model_calls'] == 0


def test_exact_ops_and_schema():
    ops = DeterministicOps(source_version='fixture')
    assert ops.execute('sha256', b'abc') == hashlib.sha256(b'abc').hexdigest()
    assert ops.execute('json_format', b'{"b":2,"a":1}') == '{\n  "a": 1,\n  "b": 2\n}'
    assert ops.validate_schema({'a': 2}, {'a': 'integer'})
    assert not ops.validate_schema({'a': True}, {'a': 'integer'})
    assert not ops.validate_schema({'a': 2, 'extra': 3}, {'a': 'integer'})
    with pytest.raises(ValueError): ops.execute('json_validate', b'{"a": NaN}')
    with pytest.raises(ValueError): ops.execute('json_validate', b'{"a":1,"a":2}')
    with pytest.raises(ValueError): ops.execute('shell', b'anything')


@pytest.mark.parametrize('path', ['../outside', '..\\outside', 'C:\\Windows\\x', '\\\\host\\share\\x', 'x:stream', '/etc/passwd'])
def test_path_escapes(tmp_path, path):
    with pytest.raises(ValueError): DeterministicOps(source_version='a').retrieve_file(tmp_path, path)


def test_artifact_tamper_is_not_cached(tmp_path):
    from app.artifact_factory import ArtifactFactory
    factory = ArtifactFactory(tmp_path)
    receipt = factory.create(kind='json', content='{}', task_id='t', creator='fixture', provenance='test')
    ops = DeterministicOps(source_version='a')
    assert ops.retrieve_artifact(factory, receipt['artifact_id'])[1] == b'{}'
    (tmp_path/receipt['artifact_id']/receipt['location']).write_bytes(b'changed')
    with pytest.raises(ValueError): ops.retrieve_artifact(factory, receipt['artifact_id'])

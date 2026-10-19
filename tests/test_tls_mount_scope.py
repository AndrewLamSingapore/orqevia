from pathlib import Path


def test_interface_mounts_only_runtime_tls_files():
    compose = (Path(__file__).parents[1] / 'docker-compose.yml').read_text()
    tls = '${ORQEVIA_INTERFACE_TLS_DIR:-./deploy/unconfigured-tls}'
    assert f'{tls}:/run/orqevia-tls:ro' not in compose
    for name in ('server.crt', 'server.key', 'ca.crt'):
        assert f'source: {tls}/{name}' in compose
        assert f'target: /run/orqevia-tls/{name}' in compose
    assert compose.count('create_host_path: false') >= 3
    assert '/run/orqevia-tls/ca.key' not in compose

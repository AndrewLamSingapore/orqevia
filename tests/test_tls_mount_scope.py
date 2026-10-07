from pathlib import Path


def test_interface_mounts_only_runtime_tls_files():
    compose = (Path(__file__).parents[1] / 'docker-compose.yml').read_text()
    tls = '${PRIME_INTERFACE_TLS_DIR:-./deploy/unconfigured-tls}'
    assert f'{tls}:/run/prime-tls:ro' not in compose
    for name in ('server.crt', 'server.key', 'ca.crt'):
        assert f'source: {tls}/{name}' in compose
        assert f'target: /run/prime-tls/{name}' in compose
    assert compose.count('create_host_path: false') >= 3
    assert '/run/prime-tls/ca.key' not in compose

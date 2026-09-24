from pathlib import Path


def test_docker_engine_probe_is_bounded_and_kills_hung_child():
    probe = (
        Path(__file__).parents[1]
        / "deploy"
        / "windows"
        / "docker-engine-probe.ps1"
    ).read_text(encoding="utf-8")

    assert "WaitForExit($TimeoutMilliseconds)" in probe
    assert "$process.Kill()" in probe
    assert "return $false" in probe
    assert "docker info" not in probe.lower()

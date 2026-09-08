"""Verify rendered Compose isolation, without starting any services."""
import json
import sys


def verify(config):
    assert config["networks"]["inference"]["internal"] is True
    services = config["services"]
    for name, service in services.items():
        if name in {"prime", "ollama", "model-init"}:
            assert "inference" in service["networks"], name
        else:
            assert "inference" not in service.get("networks", {}), name
    runtime = services["ollama"]
    assert set(runtime["networks"]) == {"inference"}
    assert not runtime.get("ports") and not runtime.get("network_mode")
    assert runtime["environment"]["OLLAMA_NUM_PARALLEL"] == "1"
    assert runtime["environment"]["OLLAMA_MAX_LOADED_MODELS"] == "1"
    assert services["prime"]["environment"]["OLLAMA_BASE_URL"] == "http://ollama:11434"
    assert set(services["model-init"]["networks"]) == {"inference"}


if __name__ == "__main__":
    verify(json.load(sys.stdin))
    print("Rendered Compose inference isolation passed; live isolation is not asserted")

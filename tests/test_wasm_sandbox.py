import pytest

from app.action_records import ActionLedger
from app.connector_sdk import ConnectorRegistry, Sink
from app.wasm_sandbox import WasmSandbox


def test_actual_compilation_and_isolated_execution():
    result = WasmSandbox().run(
        '(module (func (export "add") (param i32 i32) (result i32) '
        "local.get 0 local.get 1 i32.add))",
        "add",
        [20, 22],
    )
    assert result["result"] == 42
    assert result["host_imports"] == 0
    assert result["fuel_consumed"] > 0


def test_imports_loops_and_memory_are_bounded():
    sandbox = WasmSandbox(fuel=100, memory_bytes=65536)
    with pytest.raises(PermissionError, match="imports"):
        sandbox.compile('(module (import "host" "filesystem" (func)))')
    with pytest.raises(Exception, match="fuel"):
        sandbox.run('(module (func (export "loop") (loop br 0)))', "loop", [])
    with pytest.raises(Exception, match="memory"):
        sandbox.run('(module (memory 100) (func (export "start")))', "start", [])


def test_registered_wasm_tool_executes_for_eligible_agents(tmp_path, monkeypatch):
    import app.action_records as records

    ledger = ActionLedger(tmp_path / "wasm-actions.jsonl")
    monkeypatch.setattr(records, "action_ledger", lambda: ledger)
    sandbox = WasmSandbox()
    catalog = ConnectorRegistry()
    catalog.register_tool(
        "sandbox.wasm.execute",
        "1.0.0",
        Sink(
            "wasm-sandbox",
            "sandbox.wasm.execute",
            "R0",
            "bounded no-import WebAssembly execution",
            True,
            "LOCAL_ONLY",
            "sandbox.wasm.execute",
        ),
        lambda payload: sandbox.run(payload["source"], payload["export"], payload["args"]),
    )
    payload = {
        "source": '(module (func (export "add") (param i32 i32) (result i32) '
        "local.get 0 local.get 1 i32.add))",
        "export": "add",
        "args": [20, 22],
    }
    for agent in ("a17", "a18"):
        assert "sandbox.wasm.execute" in {
            item["tool_id"] for item in catalog.discover_for_agent(agent)["tools"]
        }
        result = catalog.execute_for_agent(
            "sandbox.wasm.execute",
            "1.0.0",
            payload,
            task_id=f"wasm-{agent}",
            agent_id=agent,
        )
        assert result["result"] == 42
        assert result["host_imports"] == 0
    assert ledger.flush()

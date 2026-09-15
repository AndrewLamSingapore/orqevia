import pytest
from app.wasm_sandbox import WasmSandbox


def test_actual_compilation_and_isolated_execution():
    result=WasmSandbox().run('(module (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add))','add',[20,22])
    assert result['result']==42 and result['host_imports']==0


def test_imports_loops_and_memory_are_bounded():
    sandbox=WasmSandbox(fuel=100,memory_bytes=65536)
    with pytest.raises(PermissionError,match='imports'):
        sandbox.compile('(module (import "host" "filesystem" (func)))')
    with pytest.raises(Exception,match='fuel'):
        sandbox.run('(module (func (export "loop") (loop br 0)))','loop',[])
    with pytest.raises(Exception,match='memory'):
        sandbox.run('(module (memory 100) (func (export "start")))','start',[])

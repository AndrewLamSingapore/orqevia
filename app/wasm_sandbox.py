"""No-import WebAssembly execution with bounded guest memory and fuel.

This is a WebAssembly sandbox, not a general native command runner. It exposes
no WASI, filesystem, process, environment, socket or host callback capability.
"""
import hashlib
from collections import OrderedDict
import threading


class WasmSandbox:
    def __init__(self, *, fuel=2_000_000,memory_bytes=16*1024*1024):
        import wasmtime
        self.runtime=wasmtime
        self.fuel=max(1,min(fuel,10_000_000))
        self.memory_bytes=max(65536,min(memory_bytes,64*1024*1024))
        config=wasmtime.Config()
        config.consume_fuel=True
        self.engine=wasmtime.Engine(config)
        self._modules=OrderedDict()
        self._lock=threading.RLock()

    def compile(self,source: str):
        if len(source.encode())>256_000:raise ValueError('Sandbox source exceeds limit')
        digest=hashlib.sha256(source.encode()).hexdigest()
        with self._lock:
            if digest in self._modules:
                self._modules.move_to_end(digest)
                return self._modules[digest]
            module=self.runtime.Module(self.engine,source)
            if module.imports:raise PermissionError('Sandbox host imports are forbidden')
            self._modules[digest]=module
            if len(self._modules)>32:self._modules.popitem(last=False)
            return module

    def run(self,source: str,export: str,args: list[int]) -> dict:
        if len(args)>16 or any(type(x) is not int for x in args):raise ValueError('Only bounded integer arguments supported')
        module=self.compile(source)
        with self.runtime.Store(self.engine) as store:
            store.set_fuel(self.fuel)
            store.set_limits(memory_size=self.memory_bytes,table_elements=1024,instances=1,tables=1,memories=1)
            instance=self.runtime.Instance(store,module,[])
            function=instance.exports(store).get(export)
            if not isinstance(function,self.runtime.Func):raise ValueError('Function export required')
            value=function(store,*args)
            return {'result':value,'fuel_consumed':self.fuel-store.get_fuel(),
                    'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
                    'host_imports':0,'memory_limit_bytes':self.memory_bytes}

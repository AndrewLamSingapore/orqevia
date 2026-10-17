"""No-import WebAssembly execution with bounded memory and fuel.

The sandbox accepts only inline WebAssembly text and bounded integer arguments.
It exposes no WASI, filesystem, process, environment, socket, or host imports.
"""

from collections import OrderedDict
import hashlib
import threading


class WasmSandbox:
    """Compile and execute isolated WebAssembly modules in-process."""

    def __init__(self, *, fuel: int = 2_000_000, memory_bytes: int = 16 * 1024 * 1024):
        import wasmtime

        self.runtime = wasmtime
        self.fuel = max(1, min(int(fuel), 10_000_000))
        self.memory_bytes = max(65536, min(int(memory_bytes), 64 * 1024 * 1024))
        config = wasmtime.Config()
        config.consume_fuel = True
        self.engine = wasmtime.Engine(config)
        self._modules = OrderedDict()
        self._lock = threading.RLock()

    def compile(self, source: str):
        """Compile bounded text and reject every module with host imports."""
        if not isinstance(source, str) or not source or len(source.encode("utf-8")) > 256_000:
            raise ValueError("Sandbox source must be bounded WebAssembly text")
        encoded = source.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        with self._lock:
            if digest in self._modules:
                self._modules.move_to_end(digest)
                return self._modules[digest]
            module = self.runtime.Module(self.engine, source)
            if module.imports:
                raise PermissionError("Sandbox host imports are forbidden")
            self._modules[digest] = module
            if len(self._modules) > 32:
                self._modules.popitem(last=False)
            return module

    def run(self, source: str, export: str, args: list[int]) -> dict:
        """Execute one exported function under fuel and memory limits."""
        if not isinstance(export, str) or not export or len(export) > 128:
            raise ValueError("A bounded export name is required")
        if (
            not isinstance(args, list)
            or len(args) > 16
            or any(type(value) is not int for value in args)
        ):
            raise ValueError("Only up to sixteen integer arguments are supported")
        module = self.compile(source)
        with self.runtime.Store(self.engine) as store:
            store.set_fuel(self.fuel)
            store.set_limits(
                memory_size=self.memory_bytes,
                table_elements=1024,
                instances=1,
                tables=1,
                memories=1,
            )
            instance = self.runtime.Instance(store, module, [])
            function = instance.exports(store).get(export)
            if not isinstance(function, self.runtime.Func):
                raise ValueError("Requested function export is required")
            value = function(store, *args)
            return {
                "result": value,
                "fuel_consumed": self.fuel - store.get_fuel(),
                "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "host_imports": 0,
                "memory_limit_bytes": self.memory_bytes,
            }

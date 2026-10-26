"""Independent, sequential Factory worker; no inference queue or sandbox service."""

from contextlib import asynccontextmanager
import argparse
import json
import signal
import sys
import threading


class Worker:
    def __init__(self, factory, *, interval_seconds=2):
        if not 0.01 <= interval_seconds <= 60:
            raise ValueError("worker observation interval must be between 0.01 and 60 seconds")
        self.factory, self.interval = factory, interval_seconds
        self.stop_event = threading.Event()
        self.thread = None

    def once(self):
        try:
            self.factory.purge_expired_outputs()
            result = self.factory.tick()
            state = result["status"]
        except Exception as exc:
            # Surface a fixed failure type; leave the lease to fenced recovery.
            result, state = (
                {"status": "DEPENDENCY_UNAVAILABLE", "error_type": type(exc).__name__},
                "DEPENDENCY_UNAVAILABLE",
            )
        with self.factory.store.transaction() as db:
            db.execute(
                "INSERT INTO pocket_worker VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET "
                "observed=excluded.observed,state=excluded.state",
                (self.factory.clock(), state),
            )
        return result

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.once()
            except Exception as exc:
                # Storage itself can be temporarily unavailable; retry the next observation.
                print(
                    json.dumps(
                        {
                            "component": "activity-pocket-worker",
                            "status": "STORAGE_UNAVAILABLE",
                            "error_type": type(exc).__name__,
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )
            self.stop_event.wait(self.interval)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name="activity-pocket-worker", daemon=True)
            self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=25)


@asynccontextmanager
async def lifespan(application):
    from .api import default_factory

    worker = Worker(default_factory()).start()
    try:
        yield
    finally:
        worker.stop()


def main():
    from .api import default_factory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="execute one durable transition and print its receipt")
    args = parser.parse_args()
    worker = Worker(default_factory())
    if args.once:
        print(json.dumps(worker.once(), sort_keys=True))
        return
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: worker.stop_event.set())
    try:
        while not worker.stop_event.is_set():
            print(json.dumps(worker.once(), sort_keys=True), flush=True)
            worker.stop_event.wait(worker.interval)
    finally:
        worker.stop()


if __name__ == "__main__":
    main()

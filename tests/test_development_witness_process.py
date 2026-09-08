"""Process crash/clone tests with the root surviving in a separate supervisor.

The manager is a synthetic test capsule, not a shipped network service. Its
random test authentication is never a production credential. Workers receive
only RPC methods; no signing key, root storage or provider capability.
"""
import multiprocessing as mp
import threading
import time
from multiprocessing.managers import BaseManager

from app.action_harness import ActionEnvelopeIssuer, ActionHarness
from app.development_witness import bootstrap_development, authorize_development, Denied
from app.job_queue import JobQueue, QueuePolicy
from app.spine import StableSpine, SpineStore
from tests.test_harness_execution import SECRET, queued


class Supervisor:
    def __init__(self, directory):
        from pathlib import Path
        root = Path(directory)
        rig = (ActionEnvelopeIssuer(SECRET), ActionHarness(root / "h.db", {"authority-v0": SECRET}),
               StableSpine(SpineStore(str(root / "s.db"))), JobQueue(root / "q.db", QueuePolicy(global_concurrency=1)))
        self.job, self.envelope = queued(rig)
        self.cap, _ = bootstrap_development(root / "root.db", rig[2], rig[1])
        authorize_development(self.cap, self.envelope)

    def block(self):
        self.cap.provider.wait = threading.Event()

    def release(self):
        self.cap.provider.wait.set()

    def execute(self):
        try:
            self.cap.execute(self.envelope, self.job["prompt"])
            return "completed"
        except Denied:
            return "denied"

    def counts(self):
        return self.cap.provider.starts, self.cap.provider.active, self.cap.provider.max_active

    def status(self):
        return self.cap.status()["slot"]


class Manager(BaseManager):
    pass


Manager.register("Supervisor", Supervisor)


def call_from_worker(proxy):
    proxy.execute()


def test_worker_death_after_provider_start_never_duplicates(tmp_path):
    context = mp.get_context("spawn")
    with Manager(ctx=context) as manager:
        proxy = manager.Supervisor(str(tmp_path))
        proxy.block()
        worker = context.Process(target=call_from_worker, args=(proxy,))
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while proxy.counts()[0] == 0 and time.monotonic() < deadline:
                time.sleep(.02)
            assert proxy.counts() == (1, 1, 1)
            worker.terminate()  # synthetic requesting worker only
            worker.join(5)
            assert not worker.is_alive()
            assert proxy.execute() == "denied"
            assert proxy.status() is not None
            proxy.release()
            deadline = time.monotonic() + 5
            while proxy.status() is not None and time.monotonic() < deadline:
                time.sleep(.02)
            assert proxy.status() is None
            assert proxy.execute() == "denied"
            assert proxy.counts() == (1, 0, 1)
        finally:
            proxy.release()
            if worker.is_alive():
                worker.terminate()
                worker.join(5)


def test_cloned_worker_processes_share_one_consumption(tmp_path):
    context = mp.get_context("spawn")
    with Manager(ctx=context) as manager:
        proxy = manager.Supervisor(str(tmp_path))
        workers = [context.Process(target=call_from_worker, args=(proxy,)) for _ in range(3)]
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(15)
                assert worker.exitcode == 0
            assert proxy.counts() == (1, 0, 1)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)

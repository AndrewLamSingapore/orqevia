"""Offline, fake-executor checks for the bounded queue parallelism gate.

The test runtime need not import FastAPI/httpx just to exercise queue policy.
The policy function is extracted from its production source without executing
module-level app initialization or opening a production queue database.
"""

import ast
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

from app.job_queue import JobQueue, Provider, QueuePolicy, WorkerPool


def candidate_global_concurrency(environment, profile):
    source = Path(__file__).resolve().parents[1] / "app" / "compute_queue_api.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "candidate_global_concurrency")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[function.name](environment, profile)


class QueueParallelCandidateTests(unittest.TestCase):
    def setUp(self):
        # Exercise scheduler overlap with a fake executor; admission is N=1
        # until a measured backend authorizes more than one local generation.
        guard = mock.patch('app.job_queue.backend_admission.reserve')
        guard.start()
        self.addCleanup(guard.stop)

    def test_default_and_invalid_overrides_remain_one(self):
        profile = {"normal_concurrency": 2}
        for environment in ({}, {"PRIME_QUEUE_CONCURRENCY": "3", "OLLAMA_NUM_PARALLEL": "3"},
                            {"PRIME_QUEUE_CONCURRENCY": "2"},
                            {"PRIME_QUEUE_CONCURRENCY": "2", "OLLAMA_NUM_PARALLEL": "bad"},
                            {"PRIME_QUEUE_CONCURRENCY": "2", "OLLAMA_NUM_PARALLEL": "1"}):
            with self.subTest(environment=environment):
                self.assertEqual(candidate_global_concurrency(environment, profile), 1)

    def test_requires_measured_envelope(self):
        environment = {"PRIME_QUEUE_CONCURRENCY": "2", "OLLAMA_NUM_PARALLEL": "2"}
        for profile in (None, {}, {"normal_concurrency": 1}, {"normal_concurrency": True},
                        {"normal_concurrency": "2"}):
            with self.subTest(profile=profile):
                self.assertEqual(candidate_global_concurrency(environment, profile), 1)
        self.assertEqual(candidate_global_concurrency(environment, {"normal_concurrency": 2}), 2)

    def test_three_requires_matching_backend_and_measured_envelope(self):
        environment = {"PRIME_QUEUE_CONCURRENCY": "3", "OLLAMA_NUM_PARALLEL": "3"}
        self.assertEqual(candidate_global_concurrency(environment, {"normal_concurrency": 3}), 3)
        self.assertEqual(candidate_global_concurrency(environment, {"normal_concurrency": 2}), 1)
        self.assertEqual(candidate_global_concurrency({**environment, "OLLAMA_NUM_PARALLEL": "2"},
                                                       {"normal_concurrency": 3}), 1)

    def test_fake_executor_two_distinct_agents_and_per_agent_limit(self):
        policy = QueuePolicy(global_concurrency=candidate_global_concurrency(
            {"PRIME_QUEUE_CONCURRENCY": "2", "OLLAMA_NUM_PARALLEL": "2"},
            {"normal_concurrency": 2}), per_agent_concurrency=1,
            local_ram_mb=8192, local_vram_mb=0)
        self.assertEqual(policy.global_concurrency, 2)
        self.assertEqual(policy.per_agent_concurrency, 1)
        provider = Provider("fixture", "local", "fixture-model", 8192, 0, 2)
        entered = []
        mutex = threading.Lock()
        two_started = threading.Event()
        release = threading.Event()

        def fake_execute(job, _provider):
            with mutex:
                entered.append(job["id"])
                if len(entered) >= 2:
                    two_started.set()
            release.wait(3)
            return {"result": "fixture", "input_tokens": 1, "output_tokens": 1}

        with tempfile.TemporaryDirectory() as directory:
            queue = JobQueue(Path(directory) / "fixture.db", policy)
            first = queue.submit(agent="planner", prompt="first", max_retries=0)
            second = queue.submit(agent="critic", prompt="second", max_retries=0)
            third = queue.submit(agent="planner", prompt="same-agent", max_retries=0)
            pool = WorkerPool(queue, [provider], fake_execute)
            try:
                pool.start()
                self.assertTrue(two_started.wait(3), "two distinct agents did not execute concurrently")
                self.assertEqual(set(entered), {first["id"], second["id"]})
                self.assertEqual(queue.get(third["id"])["status"], "queued")
            finally:
                release.set()
                deadline = time.monotonic() + 3
                while queue.get(third["id"])["status"] != "completed" and time.monotonic() < deadline:
                    time.sleep(0.01)
                pool.stop()
            self.assertEqual(queue.get(first["id"])["status"], "completed")
            self.assertEqual(queue.get(second["id"])["status"], "completed")
            self.assertEqual(queue.get(third["id"])["status"], "completed")


if __name__ == "__main__":
    unittest.main()

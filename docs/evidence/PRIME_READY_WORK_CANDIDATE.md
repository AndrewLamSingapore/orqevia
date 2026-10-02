# PRIME ready-work candidate

The opt-in `app.ready_work` module executes a validated acyclic graph of
non-inference functions. It uses a bounded thread pool, orders ready work by
P0/P1/P2/P3 with an owner fast lane and aging for deferred work, and excludes
simultaneous writes to the same named resource. It fills idle slots with any
eligible independent work when higher-priority work is write-locked.
Failures block descendants and leave unrelated branches runnable. It does not
retry, persist, create background workers, or alter the production compute queue.

Callers must classify work and identify all shared write resources accurately.
The owner fast lane is dispatch priority, not preemption of running work.
Inference remains governed by the existing compute queue and its separate
capacity settings. The branch now calls this scheduler from both the actual
`objective_api.submit` and continuation dispatch paths mounted by
`production_entry`; a focused route test verified that call with two real
registered capabilities, 53 relevant tests passed, and the full branch suite
passed 1,078 tests. This schedules the
bounded submission/deterministic stage only. It does not wait for model job
completion, construct a full objective dependency DAG, or prove 21-agent live
execution. The branch has no production activation or promotion.

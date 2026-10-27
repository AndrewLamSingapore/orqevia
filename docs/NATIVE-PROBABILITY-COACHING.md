# Native probability learning and coaching

The existing Academy, coaching SQLite journal, direct compute executor and PIF
kernel own this program. No additional agent, worker pool, database or fabric
identifier is introduced. The reasoning and evaluator model is `gemma3:12b`.

The fourteen lessons cover counting, probability axioms, conditioning,
independence, Bayes, joint distributions, random variables, moments, Markov
transitions, long-run behavior, offline hidden states, forecast scoring, expected
utility and evidence provenance. All 21 specialists have a learning path in the
existing autonomy-safety room. Lesson methods are original explanatory text.

Each durable session observes a baseline, submits separate practice, receives
field-level feedback and takes an unseen probability assessment. Role coaching
retains its original repeat-baseline contract. Question data and the independent
mathematical oracle are separate: the model receives facts and an answer-free
schema, never the answer key. Failures remain failures in the journal. Practice
retries stay bounded; an assessment does not award certification or new tool
authority. Recorded execution duration comes from original job timestamps.

Only fixed, versioned lesson methods backed by an original passing acceptance
event are retained in `agent-coaching.db`. The normal dispatch adapter can add
those methods as task-subordinate educational context. No model-generated
instructions or executable text enter retained methods. Retention records include
their assessment event, job and source revision. Completed programs remain idle
until new source/program work or a real observed ordinary output-contract gap.
The controller reopens only the affected completed role session for such a gap.

Open Coaching through the existing HTTPS workspace to inspect the curriculum and
per-agent retention records. The existing same-origin Owner bridge serves
`/pwa/api/academy/probability` and `/pwa/api/academy/agents/{agent}`. An authenticated
notification for an already-persisted, source-bound coaching job wakes the existing
executor; it cannot create another job. Notifications require HTTPS, certificate
and hostname verification, and reject redirects. Backend restart recovery remains
available if notification fails. Existing private service transports are unchanged.

The sidecar Compose file requires its pinned source/image, existing data volume,
`ORQEVIA_COACHING_NOTIFY_ORIGIN` and `ORQEVIA_TLS_CA_FILE` (public CA only).
`ORQEVIA_PROBABILITY_COACHING_ENABLED=1` runs the probability program after role
coaching. One active coaching inference proceeds at a time without a shared-queue
admission guard. Heavy acceptance work must be paced with other production work.

Educational fixture results do not establish empirical forecast calibration,
causal effects, production hidden-state inference, external tool execution,
hardware attestation or full role competence. PIF production quality flags and
observed-history qualification retain their existing meaning.

Primary references used for mathematical cross-checks:

- [Chen and Blitzstein probability reference](https://www.wzchen.com/probability-cheatsheet)
- [Harvard Stat 110](https://stat110.hsites.harvard.edu/)
- [Cambridge Markov chain notes](https://www.statslab.cam.ac.uk/~rrw1/markov/M.pdf)
- [scikit-learn calibration documentation](https://scikit-learn.org/stable/modules/calibration.html)

These links are references. Their PDFs or protected explanatory text are not
redistributed in the program. Deployment and live acceptance require separate
source-bound runtime receipts.

The first live v1 cycle completed operationally but its learner failed the
unseen numerical assessment. Version 2 adds explicit binary table axes and
rounding instructions, disjoint worked examples and compact arithmetic before
the result fields. The independent numerical oracle is unchanged. Arithmetic
notes are learner output, not trusted instructions or independent evidence;
only independently correct result fields can pass. Live learning quality remains
separate from source tests and controller health.

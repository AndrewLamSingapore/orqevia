# 21-agent acceptance matrix

Observed baseline 2026-10-13T08:07:50.433219+00:00; follow-up observation 2026-10-13T08:50:25.392777+00:00.

Original unchanged normal-role batch: 15/21 PASS; 6/21 FAIL.
Gate A below remains a bounded normal-case result, not full responsibility coverage. Gate B full end-to-end acceptance: 0/21 established. Gate C independent Azure L7: NOT ESTABLISHED.

| Agent | Registered role | Original normal case | Latest reassessment | Latest failure | Gate B | Gate C |
| --- | --- | --- | --- | --- | --- | --- |
| a01 | Strategy Lead | FAIL | FAIL | chosen_project_under_three_day_limit, higher_efficiency_project, higher_total_project | NOT ESTABLISHED | NOT ESTABLISHED |
| a02 | Planning and Roadmap Agent | FAIL | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a04 | Decision and Comparison Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a05 | Portfolio and Capacity Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a06 | Research Lead | FAIL | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a07 | Evidence Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a09 | Knowledge Agent | FAIL | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a10 | Data Lead | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a12 | Metrics and Analysis Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a13 | Forecast Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a14 | Data Quality Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a15 | Engineering Lead | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a16 | Architecture Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a17 | Implementation Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a18 | Test and Verification Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a19 | Reliability Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a20 | Commercial and Economic Lead | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a21 | Cost and Value Agent | FAIL | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a26 | Independent Quality Lead | FAIL | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a28 | Risk Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |
| a29 | Release Agent | PASS | PASS | — | NOT ESTABLISHED | NOT ESTABLISHED |

Exact follow-up scope and counts: `{"full_role_accepted_count": 0, "jobs_submitted": 36, "known_cost_usd": 0.00218943, "normal_denominator": 21, "normal_failed": 1, "normal_passed": 20, "practice_assessed": 6, "practice_passed": 1, "reassessed": 21, "retained_reassessment_attempts": 30, "state": "BLOCKED", "unknown_cost_count": 8, "wave": "hf-normal-21-20261013-v1"}`.
All failed attempts remain in the follow-up receipt; latest per-agent counts never add two attempts as two agents.

Strict grading: unchanged `review_role_output` and `review_practice`. Answer-free clarification changes the learner prompt contract explicitly; original task facts and semantic assertions are preserved.
Full responsibility criteria: [full-role-acceptance.md](../../full-role-acceptance.md). Original and follow-up output hashes/jobs are in local retained JSON receipts.

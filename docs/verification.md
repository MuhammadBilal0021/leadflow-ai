# Verification report

Date: 27 October 2026. Local verification on Windows, Python 3.13.7 and Node 24.13.0.

| Check | Result |
| --- | --- |
| Clean dependency environment | Created .venv and installed the reduced project dependencies |
| Backend regression suite | 32 tests passed |
| Frontend security suite | 2 tests passed |
| Offline qualification rules | 6/6 manually labelled fictional cases passed |
| Dependency consistency | pip check passed |
| Runtime lockfile advisory scan | No known vulnerabilities found in 50 pinned runtime packages |
| Full test-environment advisory scan | No known vulnerabilities found after upgrades |
| Browser walkthrough | Sample launch, categories, evidence expansion, saved history, and reopening after reload verified |
| CSV and access controls | Export contents and cross-session isolation verified through HTTP tests |
| Live provider quality | Not measured; no paid provider requests were made during implementation |
| CI execution on GitHub | Workflow added; remote workflow has not been run in this workspace |

An initial environment scan found advisories in langgraph-sdk, urllib3 and the environment's pip. The final environment uses LangGraph 1.2.18, langgraph-sdk 0.4.10, urllib3 2.8.0, and pip 26.2.2. Findings were resolved by upgrading and rerunning tests and scans.

The scan commands used pip-audit 2.10.1 and the public PyPI advisory service. An advisory-free scan is a point-in-time result, not proof of complete security.

## What the evaluation numbers mean

The offline fixture evaluation reports accuracy/precision/recall of 1.0 on six synthetic cases, using supplied assessments. This verifies the gate's behavior on full matches, explicit contradictions, and missing evidence. It is not evidence of 100% model or discovery accuracy.

Use `python -m evals.evaluate --live` to measure the configured model on the same fictional evidence, and expand the corpus before claiming broader results. Failed scoring is retained as needs-review rather than silently counted as a successful assessment.

## Reproducible performance check

`python -m scripts.benchmark` measures the actual SSE endpoint and shared-event-loop responsiveness with a mocked 200 ms provider workflow. It records elapsed time, a 10 ms heartbeat delay and API usage in `docs/benchmark.json`. This is an offline concurrency regression, not a live latency benchmark.

Real runs measure stage durations, elapsed time, provider calls and token/credit usage. Cost is calculated only when provider rates are configured. The sample's cost and provider usage are zero.

![Verified sample results](screenshots/sample-results.png)

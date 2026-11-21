# Optimization experiment — 2026-11-21

The experiment is isolated from production plans and the published application.
The existing objective and allocation policy are unchanged.

Results: [full report](../../redistricting/data/processed/pipeline_runs/optimization_experiment_20261121/rapport_experience.md),
[machine-readable summary](../../redistricting/data/processed/pipeline_runs/optimization_experiment_20261121/summary.json).

## Completed retrospective analysis

- Replayed 4,800 archived proposal attempts in departments 01, 03, 13, 31, 50, 75.
- Rescored and revalidated 4,138 distinct local assignments, including rejected proposals and preserved starts.
- Compared the production score, an exploratory national-population-RMS / compactness / population-fragmentation score, and a guarded variant.
- Found no better v1 winner in this pool. The observed v2 Pareto archive contains 276 plans.
- All assignments pass partition, seats, certified-graph contiguity and local population checks. Independent geometry checks find no cross-district unit overlap exceeding the project's 1 m² tolerance.
- The retrospective analysis is not a new stochastic search benchmark, a representative ensemble, a national acceptance certificate or a policy change.

## Prospective benchmark prepared, not executed

`scripts/benchmark_optimization.py` compares single-start annealing, multi-start
annealing, and Pareto short bursts at 800 proposals per arm, three fixed seeds,
six departments and two objectives. Elapsed time is measured, not matched.
Synthetic-graph tests cover objective arithmetic, invariance, reproducibility,
budget and validity; the real-data comparison has not run.

The current execution environment refuses to initialize macOS Seatbelt
(`sandbox_apply: Operation not permitted`). Generation continues to fail closed.
`run_blind.py` now checks that the sandbox can start an innocuous command before
interpreting the quarantine-read denial probe. No guard was bypassed or relaxed.

Run from `redistricting/`, in an environment permitting the required isolation:

```bash
.venv/bin/python scripts/run_blind.py benchmark_optimization.py --output data/processed/pipeline_runs/optimization_benchmark_next
```

The retrospective scripts only inspect named non-electoral artifacts. They
neither invoke proposal generation nor claim an OS generation certificate.

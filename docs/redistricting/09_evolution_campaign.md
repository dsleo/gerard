# ReCom benchmark and bounded policy evolution — 2026-11-21

[Report](../../redistricting/data/processed/pipeline_runs/recom_evolve_pilot_20261121_report/rapport_benchmark_evolution.md)
and [summary](../../redistricting/data/processed/pipeline_runs/recom_evolve_pilot_20261121_report/summary.json).

The real benchmark and real evolutionary pilot could not start: the required
macOS OS sandbox still returns `sandbox_apply: Operation not permitted`. No
generation guard was bypassed and no real-data performance claim is made.

## Executed synthetic rehearsal

- 88 trials and 6,016 proposal calls on formula-defined nonuniform toy grids.
- Compared ReCom annealing, multi-start annealing, short bursts, and ReCom/flip hybrid search.
- Evaluated 12 distinct bounded policies: eight nominal policy evaluations per arm, with four shared seeds, in evolution and a matched random-search control.
- Evolution did not beat the best seed policy or the random-search control on training. Validation retained multi-start annealing. No new policy was promoted.
- Fresh final auditing passed for 227 distinct retained synthetic maps.
- Toy results do not identify the best method for French departments.

## Prepared real pilot

`scripts/run_evolution_campaign.py` fixes production score v1, its weights, D53
allocation and hard checks. Only bounded search-policy parameters can evolve.
No external LLM is called and no arbitrary candidate Python is executed.

Training departments: 01/03/50. Validation: 13/31/75. Final held-out evaluation:
06/33/69. The validation shortlist and selection are frozen before opening the
next split. Incomplete proposal budgets cannot enter rankings. Runtime is
measured, not matched. The real pilot is capped at 30 minutes.

```bash
cd redistricting
.venv/bin/python scripts/run_blind.py run_evolution_campaign.py --output data/processed/pipeline_runs/recom_evolve_real
```

## Prepared national refinement

`scripts/run_next_optimization_series.py` refuses synthetic pilots and verifies
the real pilot's source hashes and retained-map audit. A novel policy requires
real holdout confirmation; otherwise the validation-selected baseline is used.
It refines non-frozen multi-seat departments with three seeds and 800 proposals
per department/seed. Its one-hour budget can leave an explicitly partial run.
Incumbents remain candidates and cannot regress in v1 score. Outputs are
isolated and do not update the app; national acceptance/export remains separate.

```bash
.venv/bin/python scripts/run_blind.py run_next_optimization_series.py --pilot-result data/processed/pipeline_runs/recom_evolve_real --output data/processed/pipeline_runs/recom_evolve_national
```

The full protocol is preserved in
`data/processed/pipeline_runs/recom_evolve_pilot_20261121_v2_prepared/`.

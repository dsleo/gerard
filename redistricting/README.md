# Redistricting engine

See [../docs/redistricting/README.md](../docs/redistricting/README.md) and [06_code_architecture.md](../docs/redistricting/06_code_architecture.md).

```bash
.venv/bin/python -m pytest -q
.venv/bin/redistrict check-config ../docs/redistricting/config.example.yaml
```

## National map build and acceptance

Run the vote-blind, fail-closed build with:

```bash
.venv/bin/python scripts/run_national_pipeline.py
```

The command rebuilds the population map and gates, samples and optimizes only on physical or source-approved connections, validates every district, and exports only after the national acceptance report passes. A rejected run exits nonzero and writes `data/processed/pipeline_runs/latest.json` and `data/processed/acceptance/current.md`. The browser atlas separately displays a saved exploratory mixed-map draft; its methodology page describes its uncertified status. This preview is not the pipeline’s accepted national export. `ACCEPTED_MACHINE_CHECKS` means encoded checks passed; legal review remains separate.

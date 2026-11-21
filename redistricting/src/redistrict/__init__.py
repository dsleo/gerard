"""Vote-blind redistricting engine for French legislative constituencies.

Layers (see docs/redistricting/06_code_architecture.md):

    config      control plane: load and validate config.yaml
    sources     registry of input datasets (what, where, licence, status)
    ingest      guarded file access; quarantine enforcement; input manifests
    allocate    seat allocation across departments (D'Hondt / Webster)
    validate    hard constitutional constraints (pure functions)
    metrics     fitness and audit metrics (pure functions)
    parallel    fan-out over departments with deterministic per-department seeds
    cli         command-line entry point
"""

__version__ = "0.1.0"

# Redistricting Engine — France (legislative constituencies)

Open, auditable redistricting reference engine for French constituencies, with a configurable seat total (577 baseline, 400 reform). It does not yet establish neutrality or legal compliance.

## Reading order

1. [01_decisions.md](01_decisions.md) — what was decided and why (D1–D10), and open legal items.
2. [02_architecture.md](02_architecture.md) — pipeline, layout, interfaces, outputs, gates, tests.
3. [03_neutrality_metrics.md](03_neutrality_metrics.md) — audit metrics adapted to France.
4. [04_roadmap.md](04_roadmap.md) — phases with acceptance criteria; v2 (NSGA-II, AlphaEvolve) explicitly next.
5. [config.example.yaml](config.example.yaml) — the control plane.
6. [05_legal_notes.md](05_legal_notes.md) — every legal claim with its source and verification status.
7. [blocs.draft.yaml](blocs.draft.yaml) — draft party/nuance → bloc mappings (not usable until the nuance grid is verified).
8. [07_tour2_estimation.md](07_tour2_estimation.md) — second-round scenarios, ecological report-of-vote limits, and validation plan.

## Status

- Design: v1 scope settled (this folder).
- Code: an exploratory end-to-end draft exists; Gate 1 is blocked and current ReCom outputs are candidate plans, not a validated representative ensemble.
- Legal/data: several items remain open. Until the population, boundary, contiguity and legal checks are resolved, outputs are labelled **reference study only**.

## Non-negotiables

- Generation uses legal residents only. Electoral data is quarantined and never read by generation code (enforced by allowlist and tests).
- Hard constraints are checked by one validator used everywhere.
- Every run should store its config, input manifest and outputs; the current exploratory scripts do not yet provide the full certification pipeline.
- Anything marked [VERIFY] is a legal claim that needs a qualified check before it is relied on.

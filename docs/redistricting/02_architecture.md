# 02 — Architecture and Implementation Spec

Read [01_decisions.md](01_decisions.md) first. This file says *what to build*; the decision log says *why*.

---

## 1. Principles

1. **Stages are files.** Every stage reads files and writes files. A run can stop after any stage and resume.
2. **One validator.** Hard constraints and fitness are computed by one module, used by the optimizer, the sampler, the manual recalculator and the compliance report. No second implementation.
3. **Generation must never touch electoral data.** D10 is the intended rule; the allowlist is not yet enforced end-to-end, so certification is blocked until the scripts are audited and guarded.
4. **Config is the only place for numbers and thresholds.** No constant in Python that a user might want to change.
5. **Plugins where we know we'll compare.** Optimizers and allocation methods are pluggable. Everything else is plain functions.

---

## 2. Pipeline

```
ingest ──► graph ──► [Gate 1] ──► allocate ──► [Gate 2] ──► optimize / sample ──► [Gate 3 telemetry]
                                                                  │
                                                                  ▼
                                                    validate ──► compliance report
                                                                  │
                                                                  ▼
                                              (quarantined) audit ──► neutrality report
                                                                  │
                                                                  ▼
                                                     viz (kepler.gl diff) ◄── manual edit ──► recalc
```

| Stage | Command | Input | Output |
|---|---|---|---|
| Ingest | `redistrict ingest` | raw downloads | `data/processed/*.parquet`, `manifest.json` |
| Graph | `redistrict graph` | Admin Express, precincts, population | `graph/G_<dept>.gpickle`, `step1_graph_audit.json`, `step1_graph_audit.html` |
| Allocate / Gate 2 | `python scripts/run_blind.py run_gate2.py` | rebuilt Gate 1 population table | `data/processed/gate2/seat_allocation_comparison.csv` and `gate2_report.md` |
| Optimize | `redistrict optimize --scheme <name>` | graph, allocation, config | `runs/<id>/<dept>/plans.parquet`, `front.json`, `telemetry.jsonl` |
| Sample | `redistrict sample --size 5000` | graph, allocation | `runs/<id>/ensemble/<dept>.parquet` |
| Validate | `redistrict validate <plan>` | plan file | `validation.json` |
| Certify | `redistrict certify <run>` | run folder | `compliance_report.md` |
| Audit | `redistrict audit <run>` | run folder, quarantine, exact electoral geography | `neutrality_report.md` with observed/modelled/estimated status and coverage |
| Viz | `redistrict map <run>` | run folder | `diff_map.html` |
| Recalc | `redistrict recalc plan.csv` | edited CSV | validation + fitness + audit in < 1 s (validation and fitness only; audit on demand) |
| Benchmark | `redistrict benchmark --schemes a,b` | config | `benchmark.md`, comparison table |

---

## 3. Repository layout

```
redistricting/
├── config/
│   ├── config.yaml              # the control plane (see §5)
│   └── blocs.yaml               # party → bloc mapping (audit only)
├── data/
│   ├── raw/                     # downloaded official files, read-only
│   ├── processed/               # generation-eligible
│   └── quarantine/electoral/    # NOT on the generation allowlist
├── src/redistrict/
│   ├── io/                      # loaders, allowlist enforcement
│   ├── graph/                   # build dual graph, subdivision, islands
│   ├── allocate/                # dhondt.py, webster.py (same interface)
│   ├── validate/                # hard constraints + fitness (single source)
│   ├── optimize/                # base.py + schemes/ (weighted_sum_recom_sa.py …)
│   ├── sample/                  # ReCom Markov chain
│   ├── audit/                   # neutrality metrics, quarantine-only imports
│   ├── report/                  # gates, compliance, neutrality reports
│   ├── viz/                     # kepler.gl export
│   └── cli.py
├── tests/
├── runs/                        # outputs, one folder per run id
└── docs/redistricting/
```

Enforced rule: generation entry points install the runtime input guard and fail closed unless launched via `scripts/run_blind.py`. On macOS the runner probes and applies an OS Seatbelt rule that denies reads and writes beneath `data/quarantine/`; each Python process records project-input hashes, and the runner emits a compliance PASS only for a successful process tree with complete manifests. This covers only runs made through the wrapper. The current national optimizer predates the control and remains uncertified until rerun. The wrapper fails closed on unsupported platforms. Audit-only code remains separate from generation.

---

## 4. Core interfaces

### 4.1 Validator (single source of truth)

```python
def validate(plan, graph, targets, cfg) -> ValidationResult:
    """Returns hard-constraint results, deviations, fitness terms.
    Pure function. Used by optimizer, sampler, recalc, certify."""
```

Checks, in order (fail fast on the first hard violation, but report all for the compliance report):

1. Exact partition: every commune in exactly one district.
2. Contiguity: each district's induced subgraph is connected in the physical adjacency graph plus source-backed, explicitly approved transport links. Distance-derived and centroid-derived links remain candidates; they may be used for exploratory plans only and never make Gate 1 pass by themselves.
3. Population: `|Pop(D_j) − P̄_d| / P̄_d ≤ hard_pop_tolerance`, unless the department is in `constraints.exceptions` (then ≤ the listed max, flagged EXCEPTION).
4. Zero cross-department assignments.
5. Seat sum: `Σ k_d = K`, per allocation.

Fitness terms (all in `[0, 1]` or documented range):

- `L_pop = max_j |Pop(D_j) − P̄_d| / P̄_d`
- `L_comp = mean_j (1 − 4π·Area / Perimeter²)`
- `L_epci` as defined in D7/D16 (normalized avoidable excess-split burden; raw count, lower bound, and maximum also reported)
- `L = w_pop·L_pop + w_comp·L_comp + w_epci·L_epci`; this is an optimization preference, not a legal or neutrality score.

### 4.2 Optimizer plugin

```python
class Scheme(Protocol):
    name: str
    def init(self, graph, targets, cfg, rng) -> State: ...
    def propose(self, state) -> Candidate: ...          # ReCom move
    def accept(self, state, candidate) -> bool: ...
    def front(self, state) -> list[Plan]: ...           # best plans so far
```

v1 implements `weighted_sum_recom_sa`. The interface must allow `nsga2` (returns a multi-plan front) without changes to callers.

### 4.3 Allocation plugin

```python
def allocate(populations: dict[str, int], K: int, method: str, min_seats: int = 1) -> dict[str, int]:
    """method in {'dhondt', 'webster'}. Divisors: k+1 (dhondt), k+0.5 (webster)."""
```

Both methods start at `min_seats` per department and add one seat at a time to the argmax. Ties broken by department code (deterministic).

### 4.4 Sub-commune splits (D4)

- Candidate communes: `pop > subdivision_factor × P̄_d`.
- Split units: municipal arrondissements where they exist, otherwise IRIS units under D4-r/D17, with resident population apportioned under D1-r. Electoral votes are not inferred from those resident-population shares in the primary audit (D20).
- Every split is recorded in `graph_splits.csv` with the source population and the allocation key.

---

## 5. `config.yaml` (control plane)

The full annotated example is in [config.example.yaml](config.example.yaml). Summary of sections:

| Section | Purpose | Decision |
|---|---|---|
| `global` | scenario name, K, overseas mode, seed, output | D3 |
| `allocation` | method dhondt or webster | D8 |
| `constraints` | hard/target tolerance, subdivision factor, exceptions | D4, D5 |
| `inputs` | file paths; electoral path marked quarantine | D1, D2 |
| `optimization` | list of schemes, budgets, weights, EPCI definition | D6, D7 |
| `sampler` | ensemble size per department | — |
| `audit` | elections, bloc file, metrics, CI | D9 |
| `gates` | interactive mode, pause points | — |
| `viz` | kepler.gl options | — |

Rules:
- Unknown keys are an error (typos must not be silent).
- The config is hashed and stored in every run folder.
- `manual_overrides.locked_assignments` are checked by the validator before optimization. If a lock makes a department infeasible, the run stops with a clear message, not a silent failure.

---

## 6. Tests

Minimum set, kept small (per the ponytail rule: one runnable check per non-trivial logic path):

| Test | What it proves |
|---|---|
| `test_allocation.py` | Seat sum equals K; floor of 1 holds; dhondt and webster differ on a known case |
| `test_validator.py` | Accepts a known-good 4-square toy graph; rejects a disconnected district and a ±25% district |
| `test_recom.py` | A ReCom step keeps both districts contiguous across 1000 random seeds on the toy graph |
| `test_blindness.py` | Importing `redistrict.graph`, `optimize`, `sample` or `validate` never opens a path under `data/quarantine/` |
| `test_recalc.py` | Edited CSV with one commune moved: re-validation runs and the result matches the validator |

Toy graph: a 4×4 grid of unit squares with known populations. It is the fixture for every algorithmic test, so no real data is needed to run tests.

---

## 7. Outputs (per run)

```
runs/<run_id>/
├── config.snapshot.yaml        # the exact config used (hash in manifest)
├── data/processed/blindness/runs/<id>/
│   ├── process-<pid>.json      # per-process input paths and SHA-256 values
│   └── compliance_report.json  # OS denial probe, process coverage, PASS/NOT CERTIFIED
├── step1_graph_audit.json/.html
├── step2_seat_allocation.csv
├── <dept>/plans.parquet        # candidate plans
├── <dept>/front.json           # Pareto front (when available)
├── telemetry.jsonl
├── validation.json
├── compliance_report.json      # process-level blindness evidence (D10)
├── neutrality_report.md        # quarantine-only audit
├── benchmark.md                # when comparing schemes
└── diff_map.html               # kepler.gl
```

---

## 8. Compliance certificate (`compliance_report.md`)

Generated by `certify`, from the validator and the manifest only. Lines:

```
[PASS]      Exact seat sum (Σ k_d = K)                       K = 558 departmental seats
[PASS]      Zero cross-department assignments
[PASS]      100% contiguity (0 disconnected districts)
[PASS|EXC]  Max intra-departmental deviation ≤ 20.0%         worst: 19.2% (dept XX)
[PASS]      Blindness: no quarantined file opened; allowlist enforced; manifest attached
[INFO]      Target ±5%: N of M districts within target
```

`EXC` lines appear only for departments in `constraints.exceptions`, with the justification copied in.

---

## 9. Gates

- **Gate 1 — `step1_graph_audit.html`:** per department: connected components in the physical graph, population total vs INSEE (must be 0.00% difference), list of split communes, and separately listed link candidates with basis and approval status. Unapproved links do not satisfy contiguity; the gate remains blocked until disconnected pieces have a reviewed, source-backed treatment.
- **Gate 2 — `step2_seat_allocation.csv`:** department, population, `k_d`, `P̄_d`, deviation from national average; plus a second column for the other method if `--compare-methods`. With `--interactive`, the run pauses until the user types `approve` or edits the file and re-runs.
- **Gate 3 — telemetry:** every N iterations, a line in `telemetry.jsonl` and a CLI progress line: best `L`, `max |ΔPop|`, number of split EPCIs, valid acceptance rate. SIGINT writes the current front to disk before exiting.

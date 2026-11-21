# 06 — Code Architecture

Code lives in `redistricting/` (package `redistrict`). Decisions are in [01_decisions.md](01_decisions.md); this file says where each piece of code lives and why.

## 1. The four questions the code answers

Every module belongs to one of these, so you can always tell where to look.

| Question | Package | Pure? |
|---|---|---|
| **What data goes in, and may we read it?** | `sources.py`, `ingest/` | I/O only |
| **What counts as a legal map?** | `validate/` | Pure |
| **How do we score a map?** | `metrics/` | Pure |
| **How many seats does each department get?** | `allocate/` | Pure |

Plus cross-cutting modules: `config.py` (configuration), `parallel.py` (fan-out over departments), `optimize/` (candidate plan search), and `sample/` (exploratory ReCom candidate generation).

**Rule:** pure modules (`validate`, `metrics`, `allocate`) never open files, never read config, never use global randomness. They take values and return values. This is what lets the same code run in the optimizer, the sampler, the recalculator and the compliance report.

## 2. Layout

```
redistricting/
├── pyproject.toml
├── .venv/                       # local environment (not committed)
├── data/
│   ├── raw/                     # official downloads, checksummed, read-only
│   │   └── population/          # INSEE populations légales (generation-eligible)
│   ├── processed/               # derived tables written by ingest
│   └── quarantine/electoral/    # audit-only; NOT on the generation allowlist
├── src/redistrict/
│   ├── __init__.py              # layer map (docstring)
│   ├── config.py                # load + validate config.yaml (strict)
│   ├── sources.py               # registry: what each dataset is, URL, sha256, quarantine flag
│   ├── parallel.py              # run_per_department(job, depts, seed, workers)
│   ├── cli.py                   # `redistrict <command>`
│   ├── ingest/
│   │   ├── guard.py             # InputGuard for explicit guarded byte reads
│   │   └── generation.py        # runtime input allowlist, quarantine denial, per-process hashes
│   ├── allocate/
│   │   └── apportion.py         # dhondt / webster across departments
│   ├── optimize/
│   │   └── sa.py                # simulated-annealing candidate plan search
│   ├── sample/
│   │   ├── department.py        # per-department sampler state and output
│   │   └── recom.py             # ReCom proposal logic
│   ├── audit/
│   │   └── round2.py            # audit-only L.162 and conditional 2024 winner diagnostic
│   ├── graph/
│   │   ├── build.py             # units geometry, physical rook adjacency (shared border > 0.5 m), components
│   │   ├── links.py             # source-backed approved links; distance-derived candidates are exploratory only
│   │   ├── subdivision.py       # D4-r: units above 1.20 x target, flagged INFEASIBLE_UNDER_RULE or UNRESOLVED
│   │   └── feasibility.py       # per-department component check: can whole districts fit each piece?
│   ├── validate/
│   │   └── constraints.py       # partition, contiguity, population (D5)
│   ├── metrics/
│   │   └── population.py        # L_pop, L_epci (D7)
│   └── report/
│       └── gate1.py             # Gate 1 report (JSON + markdown)
└── tests/
    ├── conftest.py              # 4x4 toy grid: the fixture for all algorithmic tests
    ├── test_config.py
    ├── test_allocation.py
    ├── test_constraints.py
    ├── test_blindness.py
    └── test_parallel.py
```

Implemented: graph construction, D4-r subdivision/feasibility, simulated annealing, ReCom candidate generation, a narrow audit-only D11 historical diagnostic, and run-time quarantine enforcement via `scripts/run_blind.py`. The official 2024 map has a historical baseline for M1, M2, M4, and M5; M3 is deferred. Exact proposed-map results remain blocked on validated unit-to-election-result geography and an accepted map. The optimizer and sampler currently have no accepted national result, and neither a national neutrality claim nor a statistically interpretable ensemble is certified. Still to build: exact proposed-map audit coverage, a certified rerun of every national build stage, and `viz/` beyond the current webapp/export path.

## 3. Data flow

```
config.yaml ──► config.py ──► Config (typed, hashed)
                                   │
sources.py ──► ingest/generation.py ──► inputs (allowlisted, sha256 recorded)
                                   │
                                   ▼
                        processed tables (population, graph units)
                                   │
          ┌────────────────────────┼─────────────────────────┐
          ▼                        ▼                         ▼
   allocate/apportion      validate/constraints       metrics/population
   (K seats per dept)      (is this plan legal?)      (how good is it?)
          │                        │                         │
          └──────────── parallel.run_per_department ─────────┘
                                   │
                                   ▼
                          data/processed/blindness/runs/<id>/ (process manifests + compliance report)
```

Electoral data is not part of generation. `audit/round2.py` is the audit-only reader and processes 2024 constituency-level validation inputs. Runtime guards and OS isolation are implemented, but a national build is not certified until every generation stage is rerun through `scripts/run_blind.py` and carries its own PASS report.

## 4. Constraints (what "legal" means in code)

Implemented in `validate/constraints.py`, one function per rule, one entry point `validate_plan`:

| Rule | Function | Decision |
|---|---|---|
| Every unit in exactly one district | `check_partition` | Municipal integrity |
| Each district connected | `check_contiguity` | Physical adjacency plus source-backed approved links only; candidates are not legal contiguity |
| Each district within ±hard tolerance of target | `check_population` | D5 (±20% hard) |

`validate_plan` reports **every** violation, not just the first, so the compliance report can list them all. Exception handling (D5 exceptions list) is applied by the caller, not by this module, so the rule itself stays strict.

## 5. Metrics (how maps are scored)

Implemented in `metrics/population.py`:

| Term | Function | Decision |
|---|---|---|
| `L_pop` | `max_population_deviation` | Fitness term |
| `L_epci` (normalized avoidable excess split burden) | `epci_split_term` | D7, D16; raw excess, theoretical lower bound, and maximum are reported too |

Still to build: `L_comp` (Polsby-Popper, needs geometry from ingest) and the audit metrics (`audit/`, quarantined). The implemented objective includes normalized avoidable EPCI fragmentation; its raw, theoretical minimum, and maximum are reported separately.

Each metric is a pure function of a plan plus its inputs. Fitness combines them with weights from config; the weights are not inside the metric code.

## 6. Parallelism over departments

`parallel.run_per_department(job, departments, global_seed, workers)`:

- Each department is an independent job: its graph, seats, optimizer and sampler never need another department's result. (Assumption 2, D5: constraints are per department.)
- Jobs run in a process pool. `workers=1` runs in-process for debugging.
- **Determinism:** each department gets a seed from `sha256(global_seed, dept)`. Results are identical for any worker count or scheduling order. A test checks this.
- Results come back sorted by department code, so output files never depend on scheduling.
- **Constraint:** `job` must be a module-level function (picklable). Closures and lambdas will not run in parallel.

The modeled scope contains 101 departments and 558 departmental seats (577 minus 19 COM and French-abroad seats). Mayotte uses the latest official commune population available for the 2024 snapshot (2017 vintage); other modeled territories use INSEE 2021. All 101 departments participate in the divisor allocation; D’Hondt assigns Mayotte two seats in the 577-seat baseline. Department jobs are independent plus one allocation step (which needs all populations).

## 7. Blindness in code (D10)

- Generation scripts install `redistrict.ingest.generation` before reading project inputs. It blocks the quarantine tree, unapproved `data/raw/` paths, and unapproved `data/processed/` inputs; direct script invocation fails closed.
- `scripts/run_blind.py` is the supported entry point. On macOS it probes an OS Seatbelt rule that denies reads and writes under `data/quarantine/`, then runs the requested generation command under that policy.
- Each Python process records SHA-256 hashes for project inputs it opens. The runner aggregates process manifests and writes `compliance_report.json`; it emits PASS only if the probe is denied, the whole command succeeds, all process manifests are present, no blocked input was attempted, and every recorded input hash is available.
- A guarded Gate 2 run passed. The active national optimizer was launched before D10 enforcement and is not certifiable; rerun every national build stage with the wrapper before certifying its outputs. The wrapper currently supports macOS only and fails closed elsewhere.
- `audit/` remains a separate, audit-only reader. The generation guard never allows it to consume quarantine data.

## 8. Conventions

- Thresholds, weights and the department list come from config, never from code constants.
- Config validation is strict: unknown keys and sections fail, so a typo cannot change a result.
- The target full-run format stores `config.snapshot.yaml` and its hash, seed, and plan metadata. Current guarded commands store process input hashes and `compliance_report.json` under `data/processed/blindness/runs/<id>/` (D38).
- Department codes are strings (`"01"`, `"2A"`, `"971"`). Never integers.
- Tests use the 4×4 toy grid, so they run without any downloaded data.

## 9. Data status (Phase 0)

| Source | Status | Note |
|---|---|---|
| INSEE populations légales, millésime 2021 | **Downloaded**, sha256 recorded | `data/raw/population/populations_legales_2021_ensemble.zip`; 34,970 communes rows incl. Paris/Lyon/Marseille arrondissements; legal population = `PMUN` |
| Mayotte official commune population, reference 2017 | **Downloaded**, sha256 recorded | `data/raw/population/mayotte_population_reference_2017.xlsx`; 17 communes, 256,518 municipal residents; latest official commune table for the 2024 snapshot (D31) |
| IGN ADMIN EXPRESS COG 3.2, edition 2024-02-22 (SHP, Lambert-93) | **Downloaded**, sha256 recorded | `data/raw/admin_express/`; contains COMMUNE and ARRONDISSEMENT_MUNICIPAL, same 2024 codes as the INSEE file. Link from the Géoplateforme download API (`data.geopf.fr/telechargement`) |
| Contours IRIS, edition 2024-01-01 (SHP): metropolitan France (FXX) and the five DROM | **Downloaded**, sha256 recorded, FXX MD5 verified against the publisher's file | `data/raw/iris/` (SHA256SUMS). The 2023 provisional copy was removed. There is no national (FRA) 2024 file: metropolitan and overseas parts are separate files. Mayotte included; Saint-Pierre, Saint-Martin, Saint-Barthélemy, Wallis and Polynesia excluded (COM) |
| Current constituency boundaries (O7) | **Source/vintage found; exact layer not ready** | Official INSEE 2022 simplified map is stored at `data/raw/constituencies/`; visual context only under D34. The publisher warns against precise assignment near borders, and two features are invalid. Exact membership/diff requires detailed geometry or an authoritative crosswalk. |
| Legislative 2024 results (quarantine) | **Downloaded and checksummed** | Official commune and polling-station extracts for both rounds; exact municipal-arrondissement/IRIS linkage remains unresolved |

Open data points found while inspecting the INSEE file:
- The current engine uses INSEE 2021 legal population on COG 2024 for all covered territories except Mayotte; Mayotte uses its latest official reference-2017 population because the 2021 France release excludes it (D1/D31). INSEE 2021 commune-déléguée rows resolve 60054/60694 (D28). For sub-commune splitting only, INSEE 2022 IRIS populations on 2024 geography provide relative weights, scaled to preserve each parent's chosen legal total (D39). The mixed-vintage exception and purpose of each vintage are explicit; a future rebase must update every population-dependent input together.
- `donnees_arrondissements.csv` lists administrative arrondissements of départements, **not** municipal ones. Municipal arrondissements of Paris, Lyon and Marseille are in `donnees_communes.csv` with codes 75101 onwards.
- The "csv" link on the INSEE page is a zip archive.

### 9.1 Join check results (Phase 0)

Script: `redistricting/scripts/check_join.py`. Report: `redistricting/data/processed/join_report.md`.

| Check | Result |
|---|---|
| Arrondissements municipaux (INSEE vs ADMIN EXPRESS) | **45 / 45 match**, no differences |
| Communes present in INSEE 2021 but absent from ADMIN EXPRESS 2024 | **13 codes, 16,261 people** (for example 08294, 16355, 69152 Pierre-Bénite, 95282). Unresolved |
| Communes in ADMIN EXPRESS 2024 but absent from INSEE 2021 | 6 codes: Paris, Lyon, Marseille (expected, INSEE uses their arrondissements); 60694, 85165, 85212 (probably created or changed after 2021, unresolved) |
| Total population (metropolitan) | INSEE 65,505,213 vs ADMIN EXPRESS 65,492,588: difference 12,625 (0.019%) |

**Resolution:** the 16 codes are now mapped (section 9.2). O12 was resolved using official commune-déléguée values from the same 2021 population release (D28).

**DROM (added):** the national ADMIN EXPRESS 2024 file (`ADMIN-EXPRESS-COG_3-2__SHP_WGS84G_FRA_2024-02-22.7z`, 560 MB, MD5 verified, sha256 recorded in `sources.py` as `admin_express_fra`) covers the DROM. Its 2024 communes match the INSEE 2021 file exactly for Guadeloupe, Martinique, Guyane and Réunion: 112 communes, and population 384,315 / 360,749 / 286,618 / 871,157 identical per department.

**Mayotte (976; D31):** INSEE's 2021 national file excludes Mayotte. The separate official 2017 commune table, authenticated by decree, reports 256,518 municipal residents across 17 communes. Use it for the 2024 snapshot and keep its reference vintage visible; do not use the non-legal 2024 estimate or the preliminary 2026 census results.

### 9.2 Mapping official population references onto COG 2024

Script: `redistricting/scripts/map_to_cog2024.py`. Outputs: `data/processed/cog2024_mapping.csv` (one row per population contribution, including the component rows used by R5) and `data/processed/cog2024_population.csv` (one row per target unit). Inputs: INSEE COG 2024 files `v_commune_2024.csv` (TYPECOM, COMPARENT) and `v_mvt_commune_2024.csv` (movements), downloaded to `data/raw/insee_cog2024/`.

| Rule | Meaning | Count |
|---|---|---|
| R1 | Commune in COG 2024: same unit | 34,911 |
| R2 | Commune déléguée in COG 2024: rolled up into its parent (COMPARENT) | 11 |
| R3 | Code changed or merged: follow the movement row | 2 (18131 → 18173, 95282 → 95169) |
| R4 | A 2021 commune included communes that are communes again in 2024 (rétablies): subtract them from the parent and give them their own population | 2 (85165 L'Oie and 85212 Sainte-Florence, carved out of 85084 Essarts en Bocage) |
| R5 | Allocate the 60054 parent total by official 2021 commune-déléguée PMUN | 3 components: 335 to 60054; 254 + 289 to 60694 |
| R6 | Mayotte: latest official commune population available for the 2024 snapshot | 17 communes, INSEE reference 2017 |
| Arrondissement | Municipal arrondissements of Paris, Lyon, Marseille | 45 |

**Checks:** for territories covered by the INSEE 2021 release, source and mapped totals both equal 67,408,052; 0 unresolved and 0 unmatched. Mayotte separately maps 256,518 official municipal residents from its 2017 table. Combined modeled population is 67,664,570 across mixed reference years. The processed table has 34,977 distinct target units, including Paris/Lyon/Marseille municipal arrondissements and all 17 Mayotte communes.

**Resolved group (60054 / 60694; D28):** the official INSEE 2021 `donnees_communes_deleguees.csv` gives Beaumont-les-Nonains 335, La Neuville-Garnier 254, and Villotran 289. Their sum (878) equals the 2021 parent commune total. Under COG 2024, map Beaumont to unit 60054 and the other two components to unit 60694. The mapper asserts this component-total identity and the national conservation check. O12 is resolved; this does not clear the separate graph, legal, or feasibility blockers in Gate 1.

**R4 assumption:** Essarts en Bocage's 2021 population (9,399) includes L'Oie and Sainte-Florence, which were its communes déléguées (INSEE 2021 communes déléguées file). It is subtracted for the 2024 parent, giving 6,807. This relies on INSEE's commune/déléguée reporting convention and remains recorded explicitly in the mapping table.

## 10. Running it

```bash
cd redistricting
.venv/bin/python -m pytest -q                       # optional local suite; not a certification gate
.venv/bin/redistrict check-config ../docs/redistricting/config.example.yaml
```

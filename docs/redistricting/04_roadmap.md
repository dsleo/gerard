# 04 — Roadmap

Principle: each phase ends with something runnable and a check that can fail. No phase starts until the previous phase's acceptance criteria pass.

## Status (latest)

| Step | Status | Notes |
|---|---|---|
| National build and map acceptance | **Fail-closed pipeline implemented; current data rejects at Gate 1** | The latest guarded Gate 1 rebuild (D52/D55) cleared 15 of the original 27 component flags: 14 through IRIS/parent geometry repair, including Aix, and one by adding four source-verified permanent road bridges (Ré, Oléron, Rance, Noirmoutier). Twelve departments remain. D53/D56 preserve their current official seats and boundaries only after an exact unit assignment and dedicated validator are implemented. The Ministry correspondence and official IGN GEOFLA 2010 geometry were checked together: GEOFLA's split-city polygons are unlabeled pseudo-cantons, so they do not identify every current IRIS piece; Mayotte is absent from the 2012 table. Other detailed contours are comparison sources, not a certified complete crosswalk. The webapp button and API endpoint reject launches while Gate 1 is blocked. No sampling or optimization ran on this repaired build. A strict recheck of the stored prior plan also fails in 34 departments (67 disconnected districts; 24 departments have cross-district overlaps >1 m²). Machine acceptance does not close legal-review items. |
| IRIS splits (D4-r/D17) | **Rebuilt; coverage and conservation confirmed** | Guarded Gate 1 now uses 2022 IRIS weights on COG 2024 and retains 2021 legal totals (D39). All 131 split parents conserve exactly; `d17_missing_iris_population` is empty; `graph_splits.csv` records each weight, scale, and piece population. The parent-boundary repair uses a 1 cm ceiling for point-contact slivers and rejects larger nonlocal assignments. O16's 93059/Pierrefitte-sur-Seine source issue is resolved; O8 legal review remains open. |
| Island and enclave links (D13, D14) | **Partially resolved; remaining links unapproved** | D55 adds four source-verified road bridges to the certified graph. The latest report has 29 unapproved candidates remaining; ferry and enclave cases are not treated as general physical continuity. Any documented exception for a D53 carry-forward must be limited to that unchanged official constituency; generated districts cannot reuse it. |
| D17 IRIS split for six departments | Candidate generation updated for 59, 69, 92, 93, 94, 95. Validity checks pass for the currently exported candidates; this does not establish convergence or representative sampling |
| Sampler (ReCom) | **Prior outputs stale for acceptance; certified-graph rebuild required** | The earlier 302/303 validity count was computed on the exploratory graph containing unapproved links. D48 changes the default sampler to the certified graph. The national pipeline will regenerate samples only after certified-graph Gate 1 feasibility passes; convergence and effective sample size remain unassessed. |
| Sampler state storage | **Rebuilt and confirmed** | Unit WKB is stored in `unit_geometry_wkb.pkl` separately from the compact 3.1 MB `sampler_state.pkl` (D26); the geometry file is about 401 MB and is loaded only by geometry-dependent consumers |
| Webapp | **Official-map metrics and monitored run controls implemented** | The home page displays the observed 2024 official-map baseline, with coarse/fine mapping toggle and limits. A local control starts the full fail-closed national pipeline only when readiness permits; it is disabled while Gate 1 remains blocked. Live department rows show proposal number, temperature, current/best components, and motion status. Per-run traces, configs, outcomes, and recent history are retained. Previous optimized files appear as a rejected legacy candidate set with missing run metadata clearly identified. The current proposed map stays gated off unless its hash-matched certificate passes. |
| Audit (election metrics) | **Official-map baseline computed; proposed-map exact audit still blocked (D42, D46, D50, D59)** | `official_map_metrics_2024.json` reports observed constituency metrics on 577 first-round seats and 501 runoffs: M1 restricted (402/403 distinct-bloc two-candidate contests), M2 all 577, descriptive cross-round M4, and L.162 diagnostic M5 (40 coarse / 25 fine shut-out constituencies). The home page now presents one bloc table for MMD, seat–vote gap, and M5, with M1 retained as a separate restricted diagnostic. Seat–vote response scenarios (formerly M3) are deferred. Five rows have candidate-vote sums differing from `Exprimés` by 1–2 votes and are disclosed. Proposed-map results remain estimated only under the separate sensitivity report; no exact M1, M2, M4, or M5, neutrality PASS/FAIL, or ensemble percentiles. |
| Optimizer (weighted-sum SA over ReCom, D19) | **No valid new map; national rerun blocked at Gate 1** | The stored 101 results used the exploratory graph and are rejected. The latest guarded Gate 1 rebuild has 12 remaining component-feasibility diagnostics (down from 27); the D53 official carry-forward crosswalk and validation path are not implemented. A fixed-seat D’Hondt helper now preserves the 74 official seats and allocates the other 484, but it is not wired into the run until the carry-forward assignments validate. No sampling or optimization ran on the repaired graph. D44's 800-proposal cap and plateau rule remain provisional; the 189-minute run retained no proposal trace, so the stopping threshold is not calibrated. D49's exact coverage-union fast path cut a fixed 40-proposal department 01 profile from 9.09 s to 1.00 s with Polsby–Popper difference below 5e-15 across six saved department plans. Measure a certified multi-department run after Gate 1 is repaired; do not extrapolate the microbenchmark as a national runtime guarantee. |
| Constituency layer (O7) | **National reference available; exact layer blocked** | Official INSEE simplified map dated 2022-05-04 is stored and hashed. INSEE warns it cannot assign locations precisely near boundaries; two geometries are invalid. D34 permits broad visual context only. The data.gouv.fr “Limites des circonscriptions électorales” dataset is catalogued for Le Havre, not national coverage, and has no specified licence; D41 records it as a possible local reference only. Exact national membership and the diff map still need detailed authoritative geometry (O10). |

| Phase | Status | Notes |
|---|---|---|
| 0 — Data and legal | **In progress; v1 reference basis fixed** | INSEE legal population 2021 + COG 2024, with the explicit 2017 official-population exception for Mayotte (D1/D31). IRIS weights use INSEE 2022 on COG 2024 and scale to those totals (D39); Gate 1 confirms exact conservation for all 131 split parents and complete source coverage. O12 is resolved using 2021 commune-déléguée data (D28), with exact conservation for all 2021-covered territory. Remaining legal reviews include O1, O2, O8, and O9. O16's missing source row was identified as 93059 Pierrefitte-sur-Seine and is resolved by D39; keep O8 open for legal basis. |
| 1 — Graph and Gate 1 | **89-department search enabled; frozen departments out of scope (D65/D66)** | Gate 1 still reports component diagnostics for 17, 21, 22, 29, 54, 56, 59, 65, 84, 85, 971, 976. They are frozen and excluded from search readiness, sampling, and optimization; the remaining 89 have no additional component-feasibility failures under D53's fixed-seat allocation. The app may launch this scoped search. The current phase leaves the 74 existing constituencies untouched and does not require an atom crosswalk for them. Search wiring is in place but has not been exercised by a run. See D56/D57/D62/D65/D66. |
| 2 — Allocation and Gate 2 | **D53 fixed-seat policy wired; mixed-map draft assembled, acceptance pending** | `scripts/run_gate2.py` compares D’Hondt/Webster across 577/400 seats and fixed/proportional overseas modes. Its 577-seat fixed-overseas D’Hondt row preserves the 74 official seats in the 12 carry-forward departments and allocates 484 seats among the other 89; the national validator requires this policy to match Gate 1. A run-scoped visual draft now combines the 484 generated districts and 74 carried-forward outlines (D74). The 74 remain fixed constituency records; their model-unit crosswalk is still needed for exact national scoring and mixed-map validation. |
| 3 — Validator | **Generated-plan validator implemented; mixed carry-forward validation pending** | `scripts/validate_national_plan.py` currently checks exact atom partition, seat allocation, population, strict/source-approved contiguity, unit geometry validity, and cross-district overlap for all 101 departments. The D74 mixed-map draft is not accepted by this validator: it uses simplified outlines for the 74 unchanged official constituencies and does not invent atom assignments for them. Add a mixed validator using the 89 generated atom assignments plus 74 unchanged official records with authoritative IDs/geometries. Keep any atom-level population join as a separately scoped check. |
| 4 — Optimizer | **First 89-department search audited; mixed national draft scored with a documented estimate, not certified** | Run `20261120T001804Z-3bed7d8e` completed population, Gate 1, Gate 2, sampling, and optimization. Independent audit passed for 89/89 generated plans and replayed every proposal trace. D74 assembled a run-scoped draft with 484 generated districts and 74 unchanged official constituencies (558 departmental seats; 577 including overseas/abroad seats). D75 adds a whole-territory heuristic score: exact whole-commune links first, virtual IRIS for usable split communes, then largest-area overlap. It preserves total population and makes the assumptions and weak matches inspectable. The estimated national composite is 0.5290 for the official map and 0.6565 for the mixed proposal; the proposal improves average population deviation and compactness but worsens the national maximum population deviation and EPCI ratio, with Indre's one-seat D53 allocation the largest outlier. These are heuristic estimates, not exact membership, legal validation, or certification. The 74 are copied unchanged; the 56 incomplete official crosswalks are in the 89 redistricted departments and affect estimation of the old baseline, not whether the new plans exist. The 19 seat-count mismatches block only department-level comparisons. Of 13 direct same-seat official comparisons, 11 had a strictly lower v1 objective; departments 23 and 48 have one seat and cannot change under this unit model. See D73–D75 and `data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts/national_draft/report.md`. |
| 5 — Sampling | Exploratory only | Candidate plans do not constitute a statistically validated ensemble |
| 6 — Certification | **Generation and export passed blindness enforcement** | Generation entry points fail closed outside `scripts/run_blind.py`; macOS Seatbelt denies reads and writes under `data/quarantine/`, and manifests hash opened project inputs. Guarded Gate 1, sampler, optimizer, Gate 2, and export runs passed. The optimizer report is `data/processed/blindness/runs/20261118T220055Z-7ad9cd08/compliance_report.json`; export report is `data/processed/blindness/runs/20261119T004717Z-38876787/compliance_report.json`. Both national outputs have complete manifests and no blocked attempts. This certifies the named runs, not the method's legal acceptability or a passing Gate 1. Other operating systems fail closed. |
| 7 — Election metrics | **Partial; exact proposed-map audit remains blocked** | A first-round estimated bloc-plurality sensitivity exists for 541 metropolitan districts (D46), using the rejected stored candidate and a two-seat-different allocation scenario. It is not candidate-level or a runoff simulation. M1, M2, M4, and M5 are computed for the official baseline; exact results on an accepted new map remain unavailable. Seat–vote response scenarios (formerly M3) are deferred until a candidate/turnout/transfer scenario is approved. No neutrality percentile or PASS/FAIL conclusion. |
| 8 — Manual editing | Not started | |

Details: [06_code_architecture.md](06_code_architecture.md) §9 and §9.1.

---

## v1 — Working engine (current scope)

### Phase 0 — Data and legal foundation
**Work**
- Pin one vintage for Admin Express, INSEE legal population and INSEE commune codes. Build a code-mapping table for communes that merged or split between vintages.
- Download and store raw files with checksums in `data/raw/`.
- ~~Acquire 2024 legislative results and registered-voter counts~~ Official commune and polling-station result files for both rounds are downloaded to `data/quarantine/electoral/` with SHA-256 checksums. The commune files merge Paris/Lyon/Marseille municipal arrondissements; polling-station rows need a validated small-area crosswalk before they can support exact split-unit audits.
- Open legal items O1–O6 (see [01_decisions.md](01_decisions.md#open-items)); legal sources and status in [05_legal_notes.md](05_legal_notes.md).
- ~~Obtain the 2024 nuance grid~~ Done: the 24-nuance grid is verified from Annexe 1 of the instruction (see [05_legal_notes.md](05_legal_notes.md) L4). Still to do: a visual check of the PDF, and a separate mapping for the 2022 presidential election.

**Done when**
- Every raw file has a checksum in `manifest.json`.
- National population total from the chosen vintage matches the official published figure.
- Legal items O1–O3 have a written answer, or a note saying the engine stays in "reference study" mode until they do.

### Phase 1 — Graph and Gate 1
**Work**
- Build the commune dual graph (rook contiguity, shared border length > 0), with manual ferry edges from config.
- Apply subdivision rule D4 (`pop > 1.20 × P̄_d`). Record every split.
- Gate 1 report (JSON and HTML with kepler.gl or folium map).

**Done when**
- Every department graph has one connected component.
- Population sum per department equals the INSEE figure (0.00% difference).
- The list of split communes matches the rule and is reviewed.

### Phase 2 — Allocation and Gate 2
**Work**
- `allocate` with `dhondt` and `webster`, `--compare-methods` output.
- Gate 2 CSV, with interactive approval mode.

Current artifacts are regenerated by `redistricting/scripts/run_blind.py run_gate2.py`. The report checks divisor arithmetic across all 101 departments, including Mayotte; interactive policy approval is not implemented.

**Done when**
- Seat sum equals K for both scenarios (577, and 400 with both overseas modes).
- The two methods' allocations are shown side by side; any difference is listed.

### Phase 3 — Validator
**Work**
- Single validator module (§4.1 of the architecture spec).
- Hard constraints, fitness terms, EPCI split per D7 (count-based).
- Toy 4×4 fixture and `test_validator.py`.

**Done when**
- Known-good toy plan passes, disconnected and ±25% plans fail, with clear messages.
- Fitness values on the toy plan match hand calculations.

### Phase 4 — Single optimizer (`weighted_sum_recom_sa`)
**Work**
- ReCom move using weighted spanning trees (weights from config, default uniform).
- Simulated annealing on the weighted fitness.
- Checkpointing, telemetry, SIGINT save.
- `benchmark` command with one scheme (the table format is fixed now, so v2 schemes slot in).

**Done when**
- On one department, the run reduces `L` monotonically in the best-so-far sense, every accepted plan is valid, and the telemetry values match recomputed values from the validator.
- A killed run resumes from its last checkpoint and reaches the same final state with the same seed.

### Phase 5 — Ensemble sampler
**Work**
- Develop a statistically characterized reference sampler per department. Current ReCom output is exploratory candidate generation, not an ensemble suitable for inference.
- Define the target distribution over legal plans before sampling; document transition probabilities, restart/selection behavior, and any weighting induced by the graph and unit geography.
- Run multiple independently initialized chains with explicit burn-in and thinning choices; retain chain metadata and convergence diagnostics.
- Report effective sample size and between-chain agreement for the audit quantities, not just the number of saved plans.
- Stores plans in a compact format (parquet, district assignment per commune).

**Done when**
- Plans pass the validator and are sampled from the documented target distribution.
- Convergence and effective-sample-size criteria are met across multiple chains and seeds for the quantities used downstream.
- Diagnostics and the run metadata travel with every stored plan set; failure to meet criteria disables percentile or PASS/FAIL reporting.

### Phase 6 — Certify (compliance report) and blindness enforcement
**Work**
- Runtime quarantine/raw-input allowlist in `redistrict.ingest.generation`.
- `scripts/run_blind.py` with a macOS Seatbelt deny rule, preflight denial probe, per-process SHA-256 manifests, and aggregate `compliance_report.json`.
- Wrapped generation is required; direct invocation and unsupported platforms fail closed.
- Re-run every stage of the national build through the wrapper after input and allocation corrections.

**Done when**
- Every generation entry point is guarded, and direct runs stop before opening project data.
- A run through `scripts/run_blind.py` proves quarantine-read denial before launch, records hashes for every project input in each process, and produces PASS only after a successful complete process tree.
- The national run and its exported artifacts carry matching PASS reports for every generation stage.

### Phase 7 — Audit (neutrality)
**Work**
- L.162 eligibility analysis plus named runoff scenarios (actual filing/withdrawal assumptions, no-transfer baseline, and any evidence-supported transfer sensitivity).
- ~~Validate the no-transfer baseline on 2024 history~~ Done as a conditional historical diagnostic: zero observed L.162 violations, zero identity mismatches, but only 65.2% winner match overall (59.2% in two-candidate runoffs). Keep it as sensitivity only, not a forecast; see `data/quarantine/electoral/derived/round2_validation_2024.md`.
- Metrics M1, M2, M4, and M5 by bloc and election (see [03_neutrality_metrics.md](03_neutrality_metrics.md)); M3 seat–vote response scenarios are deferred.
- `blocs.yaml` with at least two mappings.
- Descriptive metric output first. Ensemble percentile comparison is disabled until Phase 5's target distribution and convergence criteria pass.
- `neutrality_report.md` must label modelled second-round outcomes and cannot present candidate-plan metrics as factual election outcomes.

**Done when**
- Metrics reproduce on a hand-checked district (one district, all numbers by hand).
- Not-auditable districts are listed, never estimated.
- A plan known to be strongly biased in a toy example is flagged.

### Phase 8 — Visualization and manual editing
**Work**
- Maintain the webapp overview and finish the remaining visual comparison features: a current-constituency reference (D34 limits the simplified INSEE layer to broad context), generated plan layer, and commune/unit tooltips. Per-district population deviations are implemented in a department disclosure (D27); tablet-width verification remains pending.
- Add manual assignment editing with immediate validation and recalculation; editing and persistence behavior are not implemented yet.
- `recalc` command: reads the edited CSV, runs validator and fitness in under 1 second. Audit is on demand, because it reads quarantine data.

**Done when**
- The diff map opens in a browser and tooltips match the CSV.
- Moving one commune in the CSV changes only the affected districts' values in `recalc`.

### v1 exit criteria
- All phases' "Done when" items pass on at least two departments of different types (one large urban, one rural with islands).
- One full national run (all 101 departments) completes and produces a certificate and an audit report.
- The benchmark table has at least one scheme. The team can add a second scheme without changing callers.

---

## v2 — More optimizers

Explicitly **next**, after v1 exit:

### v2.1 — NSGA-II (`nsga2`)
- Pareto front over `(L_pop, L_comp, L_epci)` instead of a weighted sum.
- Plugs into the same `Scheme` interface, returns a front.
- Benchmark against `weighted_sum_recom_sa` on the same seeds and budget. Keep whichever wins on the stated criteria; keep both if neither dominates.

### v2.2 — AlphaEvolve-style evolution of tree weights (`alphaevolve_weights`)
- Evolves the edge-weight function `w(u, v) = f_θ(pop, epci, shared_border_length)` used by ReCom's spanning-tree draws.
- Requires a stable v1 benchmark first, so there is something to beat.
- Keep the search space small (a few parameters, not free-form code) until it shows a gain.
- Risk to state: an evolved sampler can drift from neutrality. Any evolved weight function must be run through the Phase 5 ensemble check and the Phase 7 audit before its output is used.

### v2 exit criteria
- Benchmark table covers all schemes on the same departments and seeds.
- The chosen scheme (or schemes) is recorded in the config with the benchmark that justified it.

---

## Explicitly out of scope (for now)

- Automatic seat-allocation reform proposals beyond the two methods in D8.
- Any use of socio-economic variables (income, employment) in generation. Blocked by assumption 3.
- Manual visual editing is not yet part of the delivered interface. The existing webapp is an exploratory overview and comparison surface; it does not certify plans.
- Legal sign-off. The engine produces reference material; it does not decide constituencies.

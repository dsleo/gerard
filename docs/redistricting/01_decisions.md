# 01 — Decision Log

Status: **accepted for v1** unless marked *open*. Each decision lists the rationale and the config key that implements it. Legal points marked **[VERIFY]** must be checked against the Code électoral or Conseil constitutionnel case-law by someone qualified before the output is used for anything beyond a reference study.

---

## D1 — Population used for constraints: legal residents only

- **Decision:** All population constraints (Module 1 seat allocation, Module 2 parity and sub-commune splits) use **INSEE legal municipal population** only.
- **Registered voters (*inscrits*)** are collected per polling station (bureau de vote) but are **never used in generation**. They live in the quarantined electoral store (see D2, D10).
- **Why:** The Constitutional Council's reference is residents. Registered voters are electoral data and fall under the blindness rule (spec assumption 3).
- **Consequence:** Sub-commune splits need a *resident* key. Polling-station population does not exist as an official figure, so see D4 (threshold change) which removes most sub-commune splitting.
- **Config:** `constraints.population_basis: legal_residents` (only accepted value in v1).

**Reference-year decision (2026-11-18):** use INSEE millésime 2021 (reference date 1 Jan 2021, in force 1 Jan 2024) on COG 2024 for all territories covered by that release. Mayotte is the explicit exception: use its latest official commune population (INSEE reference 2017) for the 2024 snapshot because Mayotte's special census cycle omitted it from the 2021 release (D31). The vintage exception is reported; no unofficial estimate is substituted. A later edition may rebase all input populations together.

## D2 — Collect both, use one

- **Decision:** The ingestion step collects **both** registered voters and legal residents per bureau and per commune, storing them in separate folders:
  - `data/raw/population/` (legal residents, generation-eligible)
  - `data/quarantine/electoral/` (registered voters, results; audit-only)
- **Why:** The audit needs registered voters (the 12.5% second-round threshold is computed on *inscrits*, see [03_neutrality_metrics.md](03_neutrality_metrics.md)). Collecting them now avoids re-downloading later, but keeping them physically separate is what makes blindness enforceable (D10).
- **Config:** `inputs.population_legal`, `inputs.electoral_quarantine`.

## D3 — Overseas seats: explicit, fixed by default

- **Problem:** The spec gives `K_fixed = 19` for 577 and `13` for 400 "scaled proportionally". Only one value can live in the config.
- **Decision:** Overseas and abroad seats are a **per-scenario explicit value**, not derived from total seats by default.
  - `overseas_seats_mode: fixed` (default): `K_fixed = 19` in both scenarios, so 400 total → 381 departmental seats.
  - `overseas_seats_mode: proportional`: `K_fixed = round(19 × K_total / 577)` → 13 for 400, so 387 departmental seats. This is the spec's example.
- **Why:** Overseas seats are set by statute per territory, not as a share of the national total. Scaling them is a political choice, so it must be a visible setting, not a hidden formula.
- **Recommendation:** Keep `fixed` as default. Make the 400 scenario's overseas count a value someone signs off on.
- **Config:** `global.overseas_seats_mode`, `global.fixed_seats_overseas`.

## D4 — Sub-commune subdivision threshold (fixed)

- **Problem:** The spec's `0.8 × P̄_d` triggers splits that are not needed for feasibility.
- **Decision:** A commune is subdivided **only if it cannot fit in any single constituency** under the hard tolerance:
  - split if `pop(commune) > subdivision_factor × P̄_d`, with `subdivision_factor = 1 + hard_pop_tolerance = 1.20`.
- **Why:** Above 1.20 × target, no constituency containing the commune can satisfy the hard ±20% rule. Below it, the commune can be kept whole, which keeps the graph at commune level and avoids the population-basis problem in D1.
- **Legal position (corrected):** Splitting a commune is **not** generally forbidden. Parliamentary reports on the 2009 redistricting state that a commune under 5,000 inhabitants must lie wholly within one constituency, and that larger communes may be divided. This is a secondary source, so **[VERIFY]** the exact rule in Code électoral article L.125 and its annexed table on Légifrance before implementing it.
- **Hard rule to encode (provisional):** communes under 5,000 inhabitants are never split (they are below the threshold anyway, so this is a check, not a constraint on the optimizer). Communes above the D4 threshold are candidates for splitting, as the engine does.
- **Expected effect:** Only the largest communes (Paris arrondissements, Marseille, Lyon, etc.) are candidates. Gate 1 lists the exact set per department.
- **Config:** `constraints.subdivision_factor` (default derived, can be overridden).

## D5 — The ±20% rule: hard by default, with a documented exception path

- **Legal position (corrected):** The ±20% limit is **case-law of the Conseil constitutionnel**, not a statutory number. It was accepted in 1986 and has been applied since; the Conseil reviews it strictly. Deviations above 20% are allowed only in exceptional cases with specific justification. The 2008 decision (2008-573 DC) reserved the possibility of exceptions for geographic continuity and for not following commune limits. The 2009 parliamentary reports note a district at +26.44% that was still accepted. Secondary sources only, so **[VERIFY]** against the decision texts on conseil-constitutionnel.fr (2008-573 DC, and 2010-602 DC, which I have not read).
- **Decision:**
  1. **Default:** 20% is a hard ceiling for every constituency, enforced by the validator. This matches how strictly the Conseil applies it.
  2. **Exception path:** A department can be listed in `constraints.exceptions` with a justification (geographic or natural-realities grounds) and a maximum tolerance. An exception is shown as **EXCEPTION** (not PASS) in the compliance report, with its justification text. Exceptions are meant to be rare, so the report also counts them.
  3. **Operational target:** ±5% is the optimization target, reported on every run.
- **Why:** Hard-by-default matches the case-law. The exception list makes any deviation explicit and auditable.
- **Open point for legal review:** what counts as a sufficient justification, and whether exceptions can apply to communes as well as territories (O2).
- **Config:** `constraints.hard_pop_tolerance`, `constraints.target_pop_tolerance`, `constraints.exceptions`.

## D6 — Multiple optimization schemes, compared on the same benchmark

- **Decision:** The optimizer is a **plugin**. Each scheme implements one interface (`propose`, `score`, `accept`) and is selected by config. Several schemes can run on the same department with the same seeds.
- **v1 schemes:** `weighted_sum_recom_sa` (ReCom + simulated annealing on the weighted fitness).
- **Next schemes (v2):** `nsga2` (Pareto front) and `alphaevolve_weights` (evolved spanning-tree weights). See [04_roadmap.md](04_roadmap.md).
- **Comparison:** A `benchmark` command runs every listed scheme with the same seeds and budget, then writes one table: best feasible loss, Pareto front size, runtime, acceptance rate. The best scheme is chosen from that table, not assumed.
- **Config:** `optimization.schemes: [...]`.

## D7 — Strongest definition of EPCI split

- **Problem:** The spec counts cut *edges* inside an EPCI and divides by total edges. That depends on border density, not on how many EPCIs are actually split.
- **Decision:** Count **excess district touches per EPCI**, not cut edges:
  - For each EPCI `e` in department `d`, let `c_e` = number of distinct constituencies containing at least one commune of `e`.
  - Raw excess splits: `Σ_e (c_e − 1)`.
  - The normalized optimization term is defined in D16; the previous division by number of EPCIs is superseded.
  - A population-weighted raw variant may be reported separately, but is not mixed with the normalized optimization term.
- **Why:** It measures what the objective says (how many basins are broken), is independent of border geometry, and is easy to explain. The population-weighted version shows whether large or small EPCIs are being broken.
- **Caveat:** An EPCI that spans two departments is counted only for its communes inside `d`. This is logged.
- **Telemetry:** Logs the number of split EPCIs, raw excess splits, normalization denominator, and normalized `L_epci` separately.

## D8 — Apportionment method is a config option

- **Decision:** `allocation.method: dhondt | webster`.
  - `dhondt`: highest averages with divisor `k + 1`, i.e. `argmax P_d / (k_d + 1)`.
  - `webster`: highest averages with divisor `k + 0.5`, i.e. `argmax P_d / (k_d + 0.5)`.
- **Why:** D'Hondt slightly favours large departments. Webster (Sainte-Laguë) is less biased, and the gap between them is itself worth reporting. Gate 2 shows both allocations side by side when `--compare-methods` is used.
- **Note:** The allocation in force today is set by statute. Any engine output is a *proposal* for a reform scenario, not a replacement for current law. **[VERIFY]** the legal basis before a reform scenario is presented.

## D9 — Neutrality metrics adapted to France

- **Decision:** Compute metrics only where their definitions fit the data. Candidate-level results are aggregated exactly to proposed districts; bloc mappings are sensitivity assumptions. Second-round outputs on proposed maps are model scenarios. See D20–D22 and [03_neutrality_metrics.md](03_neutrality_metrics.md).
- **Why:** Standard US metrics assume two parties and a single-round plurality vote. France has multi-party first rounds, a two-round system with a 12.5%-of-registered-voters qualification threshold, and no fixed two-party structure.
- **Config:** `audit.metrics`, `audit.blocs_file`, `audit.elections`.

## D10 — Blindness is enforced by process, not a hash

- **Problem:** The spec's "cryptographic hash verification that zero electoral files were accessed" proves nothing about access. A hash shows what a file *contains*, not whether it was *read*.
- **Decision:** Blindness is enforced in three layers, and the compliance report shows each:
  1. **Input allowlist:** `generation.py` denies access to the entire quarantine tree, any `data/raw/` directory outside the documented population, ADMIN EXPRESS, COG, IRIS, and IRIS-population inputs, and any processed input outside the named pipeline artifacts.
  2. **Input manifest:** Each Python process records SHA-256 hashes for opened project inputs in `data/processed/blindness/runs/<id>/`.
  3. **OS isolation:** Generation must run through `scripts/run_blind.py`. On macOS, its Seatbelt profile denies all file reads and writes under `data/quarantine/`; the runner probes read denial before execution. Only a successful run with complete per-process manifests can emit `PASS`.
- **Report line:** `[PASS] Blindness: no quarantined file opened; input allowlist enforced; manifest attached.` The report wording states this is a process guarantee.
- **Why:** Honest about what is proven, and still auditable by a third party re-running the manifest.

**Implementation status (2026-11-18): ENFORCEMENT IMPLEMENTED; NATIONAL RUN NOT YET CERTIFIED.** The allowlist/audit hook is installed in all generation entry points and direct invocation now stops. The macOS wrapper probes the OS deny rule, records per-process input hashes, and issues `PASS` only when the wrapped command exits successfully with complete manifests. A wrapped Gate 2 run passed. The current national optimizer was launched before this enforcement was added, so its output cannot receive a blindness certificate; rerun the full input-to-export chain through `run_blind.py` before certifying the national build. This implementation is macOS-specific; other platforms currently fail closed.

---

## Revisions (latest decisions, supersede earlier text where they conflict)

### D4-r — Where sub-commune splitting is allowed

Supersedes the sub-commune rules in D4 above. Three cases only:

1. **Paris, Lyon, Marseille:** split at **municipal arrondissement** level. INSEE publishes legal population per arrondissement, so no proxy is needed.
2. **Communes that cannot fit in one constituency** (population above `subdivision_factor × P̄_d`) and are not in case 1, for example Toulouse, Nice, Nantes, Montpellier, Strasbourg, Bordeaux, Lille: split at **IRIS** level (INSEE small areas). Each IRIS population is reconciled so the IRIS sum equals the commune's legal population. Gate 1 lists every such commune per department.
3. **Communes currently divided among several constituencies:** their current boundaries are retrieved from the official 2024 map. They are used as reference (Layer 1 of the diff map and a benchmark), not forced on generation.

No polling-station splitting anywhere. This removes O6.

**Open legal check (O8):** IRIS population is a census count, not electoral data, so it should be allowed under assumption 3. Socio-economic variables stay excluded. Confirm this reading.

### D1-r — Population key for sub-commune units

- Arrondissements (case 1): legal population from INSEE.
- IRIS (case 2): census population per IRIS, scaled to the commune's legal population. The scaling factor per commune is logged in `graph_splits.csv`. The exact source vintages are fixed by D39: 2022 IRIS counts on COG 2024 geography are only within-parent weights; pieces are scaled to the selected 2021 legal total.
- Registered voters are never used as a population key.

### D11 — Round-2 model: strong, simple heuristic, validated on history

- **Statutory source check:** the current text of [Code électoral L.162 on Légifrance](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006353380/2026-10-23) confirms the 12.5%-of-registered-voters threshold and the one-/zero-qualifier fallback rules. The implementation mirrors those rules. This source check does not settle the tied-cutoff interpretation added by D33 or replace qualified legal review.

- **Generation** never uses round-2 logic.
- **Audit** replays past elections with a single heuristic, `r2_heuristic_v1`:
  1. Candidates who may stand at the second round are those who obtained at least 12.5% of registered voters under Code électoral L.162. If exactly one qualifies, the next highest first-round candidate may stand; if none qualifies, the top two may stand. This is an eligibility rule, not an automatic nomination rule: candidates may withdraw or not file.
  2. Proposed-map scenarios must state which eligible candidates are assumed to file and remain; the no-transfer baseline awards the seat to the highest first-round vote-getter among that stated slate.
  3. Transfers and turnout changes are scenario assumptions, not facts.
- **Validation on history:** do not score legal eligibility as a prediction of who files or withdraws. For each historical constituency, verify that observed round-two candidates were legally eligible under L.162 (including fallback); then compare the observed winner with a no-transfer baseline conditional on the actual round-two slate. Report eligibility violations, candidate-identity coverage, winner match rate, and winner-bloc match rate under both bloc mappings. Do not report a finalist prediction match rate.
- **Tie handling (D33):** if the one/zero-qualifier fallback cutoff is tied on first-round votes, include all candidates tied at that cutoff in the possible eligibility set. This avoids source-row ordering deciding who is considered eligible; it can yield more than two candidates at the fallback boundary. This conservative implementation choice remains for legal confirmation under O9.
- **Acceptance:** any proposed-map no-transfer scenario is described as a baseline, not a validated forecast. Calibrated transfer scenarios require separate evidence and sensitivity reporting; historical winner agreement alone does not validate voter behavior under a new map.
- **2024 diagnostic:** all 501 observed round-two constituencies had zero L.162 eligibility violations and zero unmatched candidate identities. Conditional no-transfer winner match was 326/500 (65.2%), excluding one single-candidate record; it was 59.2% in two-candidate runoffs (242/409) and 92.1% in three-candidate runoffs (82/89). This is a weak historical diagnostic in two-candidate contests and does not validate the heuristic as a forecast.
- **Limit:** validation shows agreement with the 2024 outcomes, not with what voters would have done under a different map.

### D12 — Validation data

- Candidate-level round-one results at commune/arrondissement or finer geography, with registered-voter denominators at matching geography, are needed to aggregate votes to proposed districts (D20).
- Round-two 2024 results, candidacy/withdrawal data, and current constituency boundaries are needed to validate D11 on the existing map, not to assign observed outcomes to hypothetical districts.
- Current constituency boundaries (O7) are needed for Layer 1 and to identify the official historical constituency for each validation record.

## Decisions taken (second round)

### D13 — Enclaves (O14)

- **Superseded by D23.** A nearest-centroid attachment is a visible exception and exploratory graph edge; it cannot silently satisfy a legal-contiguity check. Any exception requires a case-specific rationale and review.

### D14 — Islands and bridges (O15)

- **Superseded by D23.** A straight-line threshold can discover candidate links, but distance is not proof of a bridge, ferry, practical connection, or legal continuity. Only explicitly approved and sourced links may be used for a continuity PASS.


### D15 — Sampler: how legal plans are generated (decided, implemented)

- **Start:** region growing per connected piece, capped at (1 + tol) × target. Restarts from new seeds, keeping the least unbalanced start. Restarts never accept a plan that leaves units unassigned (a bug found and fixed while testing).
- **Repair:** a shift along a chain of neighbouring districts from an overfull district to an underfull one. Each hop moves one boundary unit and keeps the giver connected. Pairwise ReCom cannot repair a district whose neighbours are also overfull.
- **ReCom:** random spanning tree of two adjacent districts, balanced cut. Pairs with an out-of-tolerance district are chosen with probability 0.9, with more tree draws.
- **Tolerance schedule:** starts at ±50% and tightens to the hard ±20% over the first 70% of steps. The final plan is checked against the hard ±20% and contiguity; plans that fail are kept and marked `valid: false`.
- **Why:** this is the standard ReCom approach (DeFord, Duchin and Solomon 2019), with the repairs needed for French departments with dense cities.

### D16 — L_epci for a department that is one EPCI

- **Problem:** Dividing excess splits by the number of EPCIs is not bounded by 1 and gives a constant positive offset when all the units of a single EPCI are in a department. Missing EPCI membership must not be grouped under a shared blank identifier.
- **Decision:** Ignore units with no EPCI membership, but report missing membership counts and fix municipal-arrondissement/IRIS joins through their parent commune. Report raw excess splits `E = Σ_e(c_e − 1)`. For optimization, subtract a transparent theoretical minimum `E_min = max(0, k_d − m − n_E)`, where `m` is the number of units with no EPCI and `n_E` the number of represented EPCIs. Normalize avoidable excess as `(E − E_min) / (E_max − E_min)`, clamped to [0,1], where `E_max = Σ_e(max(0, min(k_d, n_e) − 1))`; `k_d` is the plan's district count and `n_e` the number of units in EPCI `e`. Define the term as 0 if `E_max = E_min`. This avoids giving a constant optimization penalty for EPCI splits that are unavoidable at the seat count. Report raw `E`, `E_min`, `E_max`, matched EPCI count, and missing-membership count alongside normalized `L_epci`. The minimum is a combinatorial lower bound; it does not claim that a plan attaining it is geographically feasible.
- **Interpretation:** This remains a modeling preference, not a legal measure of intercommunal cohesion. EPCI boundary fit and population-weighted split burden are reported separately where useful.

### D20 — Electoral data and geographic auditability

- **Decision:** Constituency-level result files are used only to validate historical second-round heuristics on the current map. They are not redistributed to proposed districts. The primary audit requires candidate-level round-one votes and registered-voter denominators at the smallest available geographic unit that can be exactly aggregated into each generated district.
- **Split units:** If exact results are unavailable below commune/municipal-arrondissement level for a generated split unit, mark affected districts `NOT AUDITABLE` in the primary audit. A population-weighted allocation may appear only as a separately labelled sensitivity analysis; estimated results never count toward a PASS.
- **Coverage:** Every report gives auditable district count and share of population/votes covered. If coverage is incomplete, omit a national PASS/FAIL conclusion and explain the limitation.

### D21 — Second-round results are model outputs on proposed maps

- **Decision:** The 2024 second-round results validate a heuristic against observed constituencies; they are not treated as observed outcomes for hypothetical districts. The candidate set can change with boundaries, qualification and withdrawals. Proposed-map round-two outcomes are labelled scenarios, not forecasts, and uncertainty/assumptions are shown.
- **Qualification:** Apply L.162's 12.5%-of-registered-voters eligibility rule and its one/zero-qualifier fallback exactly. Model candidate withdrawals and transfer behavior as explicit assumptions; absent evidence, report multiple scenarios rather than a single predicted winner.
- **Legal reference:** L.126 covers first-round election requirements and second-round majority; it is not the second-round candidacy threshold. See L.162 and [05_legal_notes.md](05_legal_notes.md).

### D22 — Current ReCom outputs are exploratory candidates, not an ensemble

- **Decision:** Until the sampling target, transition kernel and convergence diagnostics are established, call current outputs an `exploratory candidate set`, not a `neutral` or inferential ensemble. Do not make percentile PASS/FAIL claims from them. Record chain seeds, initialization, burn-in, thinning, transition failures, and diagnostics. A future inferential comparison requires multiple chains, effective sample size and stability/convergence criteria set before looking at the proposed plan's results.
- **Current scope:** The present small sample supports visual exploration and optimizer comparisons only. It does not establish a probability distribution over all legal plans or an objective fairness baseline.

### D23 — Contiguity links are explicit modeling assumptions

- **Decision:** Distance-generated links are candidate links only; they do not establish legal or practical geographic continuity by themselves. Each non-geometric edge must have provenance (documented bridge/ferry/route, explicit exception, or unresolved candidate status). Unverified candidate links cannot support a PASS on contiguity. Reports separate ordinary shared-border adjacency from accepted and unresolved exceptions.
- **Enclaves:** A centroid-nearest attachment is recorded as an exception and remains visible in all maps/reports. It is not silently described as ordinary contiguity.
- **Link-kind labels:** `adjacency_fix` means the polygon data report zero distance but omit a shared-border edge; `generated_link` means the graph builder proposed a nearest-polygon connection across a positive gap. Both remain unapproved candidates until source-reviewed. Neither label by itself establishes legal or practical continuity.

### D24 — Population and seat accounting for the current national draft

- **Decision:** The current draft covers 101 departments and 558 seats: 577 total − 19 COM and French-abroad seats. All 101 departments, including Mayotte, participate in D’Hondt/Webster seat allocation using the documented population references. Under D’Hondt at 577 seats, Mayotte receives two seats; its 400-seat result is allowed to follow the divisor method. O12 is mapped from official 2021 commune-déléguée components (D28). Gate 1 still fails on graph and feasibility conditions.
- **Reporting:** Every national summary must show modeled departments, modeled seats, population vintages, and excluded territories separately. Do not describe this as a complete 577-seat plan.

### D25 — Re-score and rerun after objective changes

- **Decision:** Existing optimizer assignments may be re-scored under corrected metrics for comparison, but are not described as optimized under the new objective. Rerun optimization after the corrected Gate 1/sampler state is rebuilt. While source-backed contiguity links and unresolved inputs block Gate 1, any such run remains exploratory and cannot be presented as a cleared national plan.

### D26 — Store unit geometry separately from sampler state

- **Decision:** Keep unit WKB geometry in `unit_geometry_wkb.pkl` beside `sampler_state.pkl`; store only the geometry filename in the compact sampler state. Optimizer and map exporter load geometry explicitly, while sampler jobs avoid deserializing it.
- **Why:** The sampler state was about 423 MB largely because it carried geometry every sampler worker did not need. Separating the payload reduces sampler startup and memory without changing map geometry or scoring inputs.
- **Status:** Implemented and regenerated. The current `sampler_state.pkl` is about 3.1 MB and `unit_geometry_wkb.pkl` is about 401 MB. Geometry-dependent optimization/export consumers load the separate geometry file; the compact sampler state no longer embeds it.

### D27 — Show deviations for the displayed candidate plan

- **Decision:** The webapp's national/department summary uses the optimized candidate plan's maximum population deviation. A department-level disclosure lists each displayed candidate district's population deviation from its target; sampled-candidate ranges remain separate and are not presented as the displayed plan's values.
- **Why:** A single maximum does not show which district drives it. The view is descriptive only while Gate 1 is blocked and must not imply legal compliance.
- **Status:** Implemented in the webapp/export labels and per-district disclosure. The exported `optimized_max_deviation` is explicitly the metric for the displayed optimized plan; sampled-plan maxima remain separate. Per-district rows include screen-reader text with district number, population, and signed deviation. The refreshed proposal loads in the browser and its national metrics render. Tablet-width verification of this current page remains pending; the earlier 634 px check was performed on a stale page and is not evidence for the current layout.

### D28 — Resolve the 60054/60694 population mapping within the 2021 vintage

- **Decision:** Keep the 2021 vintage for territories covered by that release. Allocate Beaumont-les-Nonains (335) to 2024 unit 60054; allocate La Neuville-Garnier (254) and Villotran (289) to 2024 unit 60694. The three official INSEE commune-déléguée PMUN values sum exactly to the 2021 Les Hauts-Talican parent total (878). Mayotte's separate reference-vintage exception is D31.
- **Why:** The 2021 commune-déléguée source provides component populations for these units, so the former `UNRESOLVED` flag was caused by a mapper omission. This is same-vintage data and conserves the national total.
- **Validation:** The mapper now checks the component total against the parent and the national population conservation check returns 67,408,052 on both sides, with zero unmatched units.
- **Consequence:** O12 is resolved; Gate 1, compact sampler state, candidate plans, and the guarded national optimizer have been rebuilt. The corrected optimizer and web export are complete. This does not clear other Gate 1 failures.

### D29 — Require candidate plans to cover the current unit set

- **Decision:** An optimizer starting plan must assign every current unit exactly once; reject stale sampled plans whose assignment keys do not match the current department unit set.
- **Why:** Population/geography corrections can change the unit inventory while old candidate files remain on disk. Silently optimizing an incomplete partition would make the result unusable even if its assigned districts appear individually valid.
- **Consequence:** After a Gate 1 rebuild changes units, regenerate candidates for every affected department before optimization. The optimizer now checks for missing or extra unit keys; department 60 was refreshed for O12 and department 976 was added under D31.

### D30 — Gate 2 reports modeled seat arithmetic separately from approval

- **Decision:** Compare D’Hondt and Webster for 577/400 national seats under fixed/proportional overseas-seat modes. Subtract 19 or the proportional value, then allocate all remaining departmental seats among all 101 departments, including Mayotte. The report’s PASS means the seat sum and one-seat floor are correct, not that the allocation is legally or politically approved.
- **Why:** Mayotte now has an official population input, so fixing its seats separately would bypass the documented divisor methods. Modeled departmental totals are 558, 558, 381, and 387; Mayotte receives two seats under 577 D’Hondt/Webster and one under each 400-seat calculation on the current inputs.
- **Status:** `scripts/run_gate2.py` generated the four-scenario CSV and Markdown report. All arithmetic checks pass; approval/legal review remains separate, and Gate 1 remains upstream-blocked.

### D31 — Use Mayotte's latest official population for the 2024 snapshot

- **Decision:** Include Mayotte's 17 communes in the plan set using INSEE's official 2017 municipal population (256,518), the latest commune-level official population available for the 2024 snapshot. Include Mayotte in D’Hondt/Webster allocation with the other departments. Do not fix its seat count independently or substitute the non-legal 2024 estimate or preliminary 2026 census counts.
- **Why:** INSEE's [2017 Mayotte commune table](https://www.insee.fr/fr/statistiques/3291775) links to the authenticating decree. The 2021 national release excludes Mayotte under its special census cycle, and the 2017 table remained the latest official commune population available for the 2024 snapshot.
- **Consequence:** O11 is resolved for the 2024 reference snapshot with an explicit vintage exception (2017 for 976, 2021 elsewhere). On current inputs, D’Hondt and Webster each assign two Mayotte seats in the 577-seat baseline and one in the 400-seat scenarios. Gate 1 must still assess Mayotte's physical components and candidate transport links; its inclusion does not imply contiguity certification.
- **Display rule:** Show the reference year with each department's population; the national summary and export must preserve the Mayotte 2017 exception.

### D32 — Partial sampler runs preserve a national summary

- **Decision:** A sampler run limited to selected departments updates those plan files but rebuilds `summary.csv` from the latest plan file for every department.
- **Why:** Refreshing only one department must not replace the national summary with a one-row partial report.
- **Status:** Implemented in `sample_departments.py`; after updating departments 60 and 976, the script rebuilt the 101-row national summary from saved department plan files.

### D34 — Use the official simplified constituency map only as a reference layer

- **Decision:** Record the INSEE constituency map published 4 May 2022 as the official reference source for the 2024 constituency geography. It may be used for broad visual context only. Do not use its simplified geometry to assign coordinates or communes near constituency borders, or to claim an exact diff map.
- **Why:** INSEE explicitly warns that the simplified contours cannot determine precise membership, especially near constituency boundaries. The downloaded shapefile has 558 departmental features, matching the 558 seats inside departments; the 19 COM/French-abroad seats are outside the department layer. Two geometries fail the GIS validity check, which is another reason not to use this file for exact overlay or measurement.
- **Source:** `data/raw/constituencies/insee_circonscriptions_2022_simplified.zip`; SHA-256 is recorded beside it and in `src/redistrict/sources.py`.
- **Consequence:** O7 is resolved for provenance and vintage, but its exact mapping requirement remains open. O10 and the exact current-boundary diff layer remain unimplemented pending a suitable detailed geometry or authoritative commune/BV crosswalk.

### D35 — Interpret normalized EPCI burden within departments

- **Decision:** Keep normalized `L_epci` bounded by [0, 1] using D16 and report it alongside raw excess `E`, unavoidable lower bound `E_min`, maximum `E_max`, and EPCI membership coverage.
- **Interpretation:** This is a department-relative optimization preference. Scores should not be compared as absolute cohesion levels across departments with different seat counts, unit counts, or EPCI coverage; national comparison should use the accompanying raw/bound/coverage fields.
- **Status:** Implemented in the scorer and export path; documented after the focused methodological review on 2026-11-18.

### D36 — Compress web map geometry losslessly

- **Decision:** Store department, district-map, and atomic-cell GeoJSON as gzip-compressed `.geojson.gz` in `export/`; create lazy browser JavaScript payloads as base64-wrapped gzip and decode with the browser's `DecompressionStream` API.
- **Why:** The export was dominated by duplicated coordinate text. Gzip reduces that text without changing geometry coordinates, properties, or precision; unlike lowering the simplification tolerance, this has no cartographic detail tradeoff.
- **Compatibility:** The standalone webapp consumes browser payloads and requires a browser with `DecompressionStream` gzip support. The `.geojson.gz` artifacts can be decompressed by standard gzip tools for GIS use.
- **Status:** Implemented in the export scripts. The guarded national export completed at 54.5 MB and the current proposal loads in the browser. Coordinate precision is unchanged.

### D37 — Isolate the superseded 556-seat allocation artifact

- **Decision:** Move the old `seat_allocation_dhondt_556.csv` out of the active processed-data directory and retain it under `data/processed/legacy/` with a warning. The current authoritative comparison is `data/processed/gate2/seat_allocation_comparison.csv`.
- **Why:** The old file describes the superseded 100-department scope and could be mistaken for current data even though no active script references it.

### D38 — Make blindness a run-time gate

- **Decision:** Every generation/data-build script must install the generation guard, and must be launched through `scripts/run_blind.py`. The runner denies reads and writes under `data/quarantine/` at the OS level, probes read denial, and aggregates process manifests. Direct invocation and unsupported platforms fail closed.
- **Evidence:** The guarded national optimizer at `data/processed/blindness/runs/20261118T220055Z-7ad9cd08/compliance_report.json` and export at `data/processed/blindness/runs/20261119T004717Z-38876787/compliance_report.json` passed with complete manifests and no blocked attempts. Guarded Gate 1, sampler, and Gate 2 reports are also recorded in the roadmap. This verifies those process trees only; it does not certify Gate 1 feasibility, legal assumptions, or the plans themselves.
- **Limit:** This certifies the named process tree only. It does not certify past runs or output artifacts from a process tree without a PASS report.

### D33 — Include ties at the L.162 fallback cutoff

- **Decision:** When exactly one candidate reaches the 12.5% threshold, include every other candidate tied at the highest remaining first-round vote count. When none reaches the threshold, include every candidate tied at the second-highest vote count or above. Do not let CSV row order select one candidate from a tie.
- **Why:** The current single-candidate fallback selected an arbitrary tied candidate, so the eligibility result could depend on input row order. The 2024 constituency inputs contain no fallback-cutoff ties, so this correction does not change the reported 2024 diagnostics.
- **Limit:** This conservative eligibility set can contain more than two candidates. Confirm the legal treatment of tied fallback ranks under O9 before relying on eligibility classifications.

### D17 — IRIS split for departments whose sampling fails (decided, implemented)

- **Problem:** six departments (59, 69, 92, 93, 94, 95) gave no fully valid plans with commune-level units. Dense departments with few, large communes cannot always be cut into districts within ±20%.
- **Rule:** in each of these departments, every commune with population above **0.25 × P̄_d** is split into its IRIS pieces, using the same scaling as D4-r case 2. Communes at or below that size stay whole. Apply D39's 2022-on-2024 IRIS weights and 2021 legal totals.
- **Why 0.25:** a commune of a quarter of a target is small enough that the district boundaries can move in steps well below the ±20% band, and large enough that splitting it does not multiply the unit count. This is a tunable, and the value is recorded in the config; it is chosen here, not derived from law.
- **Scope:** this rule is applied only to the six named departments, and only after sampling at commune level has failed. Other departments keep commune-level units.

### D39 — Preserve the 2021 population snapshot with COG 2024 IRIS weights

- **Decision (user-confirmed 2026-11-18):** retain INSEE 2021 legal populations for the 2024 map snapshot (with Mayotte's documented 2017 exception under D31). Use INSEE's 2022 IRIS population release, published on geography in force on 2024-01-01, only to derive relative population weights among IRIS pieces when a parent commune must be split. Scale each parent's IRIS weights to its selected legal total and assign rounding remainder deterministically so piece populations sum exactly to that total.
- **Reason:** the 2021 IRIS release uses 2023 geography and lacks codes needed to cover all 2024 geometry; the 2022 release aligns to the project's COG/IRIS 2024 geography. This is a spatial allocation proxy, not a replacement of the legal population snapshot.
- **Coverage check:** require a source population for every IRIS geometry used in a split; missing codes must fail the split rather than silently receive zero weight. The 2022 source supplies all codes in the current 2024 geometry (with one non-split delegated-unit record outside that geometry).
- **Build evidence (2026-11-18):** the guarded Gate 1 rebuild split 131 parent units into 4,406 IRIS pieces with exact per-parent conservation and no missing D17 source codes. `data/processed/gate1/graph_splits.csv` preserves the source weights, scaling factors, and assigned piece populations.
- **Source:** INSEE, [2022 IRIS population on 2024 geography](https://www.insee.fr/fr/statistiques/8647014), raw archive `data/raw/insee_iris_pop/base_ic_population_2022_iris_cog2024_csv.zip`; checksum is recorded in `src/redistrict/sources.py` and the raw-data checksum list.
- **Limit:** the legal permissibility of using census population as the within-commune allocation key remains open under O8; this data-vintage choice is not legal approval.

### D40 — Do not treat the 2024 polling-station/IRIS estimate as an authoritative crosswalk

- **Decision:** Do not use data.gouv.fr's *Liaison IRIS / Bureaux de vote de 2024* to claim that the active metrics are validated or computed on exact commune/arrondissement units. Keep the proposed-map neutrality audit blocked until polling-station identifiers are reconciled to Ministry result identifiers and an authoritative, full-territory geography is available.
- **Finding:** The table estimates population shares using proposed 2024 polling-station contours, IRIS boundaries, and INSEE's 2019 200 m FiLoSoFi population grid. Its own metadata warns that contour identifiers do not always match Ministry result identifiers, with particular care needed in central Bordeaux and the first four Paris arrondissements. The source contours are expressly approximate Voronoi reconstructions and “not intended to be authoritative”; INSEE's grid covers metropolitan France, Martinique, and Réunion, not all overseas territories. These limitations prevent exact assignment of registered voters and election results to the project's units.
- **Possible limited use:** after identifier reconciliation, the table may be used for a separately labeled, approximate sensitivity analysis only. Never present its estimated allocations as observed vote counts or use them to establish a neutrality PASS/FAIL result.
- **Sources:** [data.gouv.fr liaison table and its caveats](https://www.data.gouv.fr/datasets/liaison-iris-bureaux-de-vote-de-2024); [data.gouv.fr proposed polling-station contours and non-authoritative status](https://www.data.gouv.fr/datasets/proposition-de-contours-des-bureaux-de-vote); [INSEE 2019 200 m grid, geographic coverage](https://www.insee.fr/fr/statistiques/7655475?sommaire=7655515); [data.gouv.fr note that national polling-station geography is unavailable and published case by case](https://www.data.gouv.fr/pages/donnees-geographiques). Official 2024 Ministry results are published at polling-station level for both rounds, but no authoritative national crosswalk to 2024 IRIS/arrondissement geography was found.

### D41 — Treat the Le Havre constituency dataset as local reference material only

- **Finding:** The data.gouv.fr dataset [Limites des circonscriptions électorales](https://www.data.gouv.fr/datasets/limites-des-circonscriptions-electorales) is spatially catalogued for Le Havre, describes boundaries from the 2010 redistricting, and offers resources including a file named `CIRCONSCRIPTION_2012`. It is not a France-wide 2024 polling-station boundary/crosswalk dataset. Its licence is not specified in the catalog.
- **Decision:** Do not use it as the national current-constituency layer or as a polling-station-to-IRIS/arrondissement crosswalk. It may be evaluated for a local Le Havre constituency comparison after checking the actual geometry and reuse terms.
- **Source:** data.gouv.fr dataset metadata, updated 26 February 2026; spatial coverage is listed as Le Havre and licence as unspecified.

### D42 — Use the 2024 bureau-to-IRIS table only for estimated sensitivity analysis

- **Decision:** Use the data.gouv.fr *Liaison IRIS / Bureaux de vote de 2024* as an explicitly estimated sensitivity input after reconciling its bureau identifiers to the Ministry result identifiers and checking territory/record coverage. Keep the exact-geography primary audit blocked wherever counts cannot be assigned exactly.
- **Reporting:** Any results from the table must be marked estimated, report matched and unmatched bureau coverage, and must not support a neutrality PASS/FAIL or be described as observed IRIS votes/registered voters. The table's weights are based on population-grid allocation, so they assume voter and vote distributions track resident population within each bureau.
- **Status:** The sensitivity calculation is complete and reported under D46. The Ministry extracts and derived outputs remain in quarantine; none of this data is used in generation.
- **Source:** [2024 bureau-to-IRIS liaison table and method/caveats](https://www.data.gouv.fr/datasets/liaison-iris-bureaux-de-vote-de-2024).

### D43 — Reclassify zero-distance link candidates before interpreting Gate 1

- **Finding:** The current `adjacency_fix` label is assigned solely when nearest-polygon distance is under 1 m. A geometry check of the 58 such candidates found 48 pairs with overlap area above 1 m², nine zero-distance cases without a positive shared border or point touch, and one point-only contact. For example, Aix-en-Provence IRIS `130010404` overlaps commune `13060` by 84.5 m² but has no shared-boundary length; that is not a rook-adjacency edge.
- **Consequence:** Do not interpret `adjacency_fix` as a verified omitted border. The 27 component-feasibility failures are results under the current strict graph and geometry; their geographic cause must be reviewed before treating them as intrinsic impossibilities. Reclassify geometry-overlap/point-contact cases and repair or adjudicate the underlying boundaries before a final Gate 1 conclusion.
- **Evidence:** Current candidate rows are in `data/processed/gate1/ferry_bridge_edges.csv`; geometric check used the exported unit geometries in `data/processed/gate1/unit_geometry_wkb.pkl`.

### D44 — Record optimizer proposal histories and stop on a logged plateau

- **Decision:** Future optimizer runs retain one compressed JSONL trace per department with a row for every ReCom proposal, including temperature, proposal status, candidate/current/best metric components, and score. The final result also records the seed, proposal count, accepted moves, and round summary. Full assignments are not duplicated per proposal; the final best assignment remains in the result JSON.
- **Early stopping:** Keep the default maximum of 800 proposals per department, in rounds of 100. Stop after at least four completed rounds if the best weighted score fails to improve by at least `1e-4` over the three-round patience window. This means at least 400 and at most 800 proposal attempts; set patience to 0 to disable the rule. The criterion is heuristic and does not establish convergence or optimality.
- **Status:** Implemented for future runs. The previous 189-minute run did not save iteration-level metrics, and its history cannot be reconstructed; its final plans are unchanged.

### D45 — Treat the 91 Gate 1 links as candidate graph connections

- **Decision:** The 91 entries are candidate edges that let the graph builder and optimizer explore whether units on either side of a suspected gap can belong to one district. They do not merge the underlying units, direct the optimizer to merge them, or prove that the resulting district is legally contiguous. The existing commune/IRIS units remain distinct and retain their populations and geometries.
- **Interpretation:** A district is the final group of units assigned to one seat. A graph component is a group of units reachable from one another through the accepted physical edges. Without a path between components, a district cannot contain units from both while satisfying graph contiguity. A candidate edge proposes a possible path across missing/uncertain geometry, a positive gap, or an enclave attachment. It is therefore a question to review, not a merge approval. All 91 links remain unapproved; they cannot support a Gate 1 PASS.
- **Aix example:** IRIS `130010404` and commune `13060` (Meyreuil) are listed as an `adjacency_fix`, but the source polygons overlap by 84.5 m² and have no shared-border length. That label currently signals a geometry discrepancy, not a verified shared boundary.

### D46 — Keep whole IRIS as Aix-en-Provence split atoms; run a first-round bloc sensitivity

- **Aix decision:** Aix-en-Provence itself does not need to be cut into fragments smaller than IRIS. It has 147,478 residents, above the department 13 maximum for one district (137,130 at the ±20% hard tolerance), so keeping the entire commune intact cannot satisfy the project constraint. The candidate map uses its 54 whole IRIS as the smallest available atoms and assigns them across districts, with neighboring communes available to complete district populations. No IRIS polygon is itself subdivided. The present candidate allocates 16 Aix IRIS plus nearby communes to one district (131,821 residents) and the remaining 38 IRIS to another (98,153); those figures meet the population band. The strict physical graph currently isolates all 54 Aix IRIS as one 147,478-person component: one district would exceed the maximum, while two districts need at least 182,840 residents together. That is why Gate 1 flags this component. The flag means the component needs a verified connection to neighboring units before it can be partitioned into legal-sized, contiguous districts; it does not mean more subdivision inside an IRIS is needed. The Aix–Meyreuil physical edge and broader Gate 1 contiguity remain unresolved, so this candidate is not certified feasible.
- **Official-map comparison:** The current statutory map also divides Aix within the municipality, between the 11th and 14th Bouches-du-Rhône constituencies. The 2009 delimitation describes a portion of Aix Nord-Est for the 11th using railway, commune boundaries, the A51 and roads; the 14th contains Aix Centre and the remaining Aix Nord-Est. It uses legal boundary descriptions, not IRIS. See the [Code électoral constituency table](https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000020950777/2026-04-07). This is evidence that a commune-wide unit is not required for the current map; it does not by itself establish the legal acceptability of the project's IRIS-based partition (O8 remains open).
- **Electoral sensitivity decision:** Use the data.gouv.fr 2024 bureau-to-IRIS weights to make a separately labeled first-round geographic replay. Compare observed 2024 metropolitan constituency bloc pluralities (539 constituencies) with estimated bloc pluralities on the optimized metropolitan candidate map (541 districts), under both draft nuance-to-bloc mappings. Report exact-ID coverage and the fact that weights are population estimates. The candidate map has two more metropolitan seats under the project's allocation scenario, so the comparison combines boundary and seat-allocation effects. This is a scenario for how bloc pluralities could shift if vote geography followed those weights; it is not a candidate-level winner prediction, second-round forecast, or neutrality PASS/FAIL. Keep exact proposed-map M1, M2, M4, and M5 blocked; M3 is deferred.
- **Status (2026-11-19):** Run completed. The metropolitan registered-voter denominator coverage assigned to proposal districts is 97.9% (44,820,255 of 45,761,133); unmatched areas remain uncovered. Across all Ministry rows, including non-metropolitan territories outside the table's coverage, it is 90.9%. In the coarse mapping, bloc-leading counts change from current to proposed as follows: left 166→189, right 28→12, centre 56→53, far right 286→286, other 3→1. In the fine mapping: left 152→170, right 29→12, centre 63→59, far right 291→299, ecologist 1→0, other 3→1. Differences reflect both the map and two additional metropolitan seats; they are sensitivity outputs under the stated mapping and population-weighting assumptions, not predicted winners.
- **Artifacts:** [`first_round_map_sensitivity_2024.md`](../../redistricting/data/quarantine/electoral/derived/first_round_map_sensitivity_2024.md), JSON and coverage/bloc CSVs in the same quarantine-derived folder. Sensitivity script: [`audit_first_round_map_sensitivity_2024.py`](../../redistricting/scripts/audit_first_round_map_sensitivity_2024.py).

### D47 — Do not approve any of the 91 inferred links on current evidence

- **Decision:** None of the 91 candidates is approved as a physical/legal-contiguity edge. Keep them marked unapproved and available only in explicitly exploratory graphs. A candidate is not a decision that the units should be merged; it is a possible connection that would let a district graph cross a gap. Approval requires source-backed evidence of a qualifying shared boundary, documented bridge/ferry connection, or a reviewed legal exception. Distance, polygon overlap, centroid proximity, and a manual config entry without provenance do not suffice.
- **Disposition by type:** The 58 `adjacency_fix` entries are held for geometry repair, except the one point-only case which is rejected under the current rook rule (≥0.5 m shared border). Their geometry review found 48 overlaps above 1 m², nine zero-distance cases with neither shared border nor point contact, and one point-only contact; none has ≥0.5 m shared border. The 24 `generated_link` entries remain unapproved pending mapped bridge/ferry/land-connection evidence. The 8 `enclave_attach` entries remain unapproved because nearest-centroid attachment is not a continuity path; each needs a source-backed legal/geographic exception. The single `manual_override` is rejected as an approved edge until its source is supplied.
- **Aix validation:** Rebuilding the department 13 rook graph from saved unit geometries and applying the validator to the actual optimized assignment confirms one strict-graph violation: displayed district 17 contains two disconnected pieces, 16 Aix IRIS (49,325 people) and 18 neighboring communes (82,496). The optimizer's exploratory graph includes `130010404`↔`13060` (Meyreuil), which connects those pieces; that pair is not physically verified because the polygons overlap by 84.5 m² and share no border. Displayed district 18's 38 Aix IRIS form one connected piece. Thus the district-contiguity question has been checked: district 17 fails the current physical graph, and passes only under the unapproved assumption edge.
- **Artifacts/status:** Per-candidate reasoning and geometric measurements are in [`link_review_2026-11-19.csv`](../../redistricting/data/processed/gate1/link_review_2026-11-19.csv). This records a review decision, not a corrected geometry or a Gate 1 pass. Rebuild the graph and rerun affected plans after source geometry is repaired or a specific connection is documented.

### D48 — Accept and export maps only after national fail-closed validation

- **Decision:** Standard sampling and optimization use only `certification_edges`: actual rook borders of at least 0.5 m plus individually documented links from `config/approved_contiguity_links.csv`. Unapproved distance, centroid, or manual candidates remain in a separate exploratory graph and cannot validate a proposed map.
- **Acceptance checks:** `scripts/validate_national_plan.py` validates the exact 101-department optimized assignment before export: complete one-to-one coverage of every unit; all expected district labels and 558 departmental seats; D24's 577-seat, fixed-19, D'Hondt allocation; ±20% population in every district; connected induced districts on `certification_edges`; valid non-empty unit geometries; and no cross-district unit overlap above 1 m². Export independently checks the simplified district polygons remain valid and non-overlapping. The validator records per-department results and SHA-256 hashes of every plan and validation input. Any missing input, failed district, changed hash, or scope mismatch rejects the map.
- **Pipeline:** Run `.venv/bin/python scripts/run_national_pipeline.py`. It rebuilds population mapping, Gate 1, and Gate 2 through `run_blind.py`; rejects infeasible certified-graph components before sampling; generates and optimizes only on the certified graph; runs the national validator; and exports only when the certificate and hashes match. A failed run writes `REJECTED` and a reasoned run report. The webapp refuses to display a map without the matching accepted certificate.
- **Status semantics:** `ACCEPTED_MACHINE_CHECKS` means the encoded machine constraints passed. It is not a legal opinion. Existing open legal items (including O1, O2, O8, O9) remain a separate legal-release blocker and must not be described as resolved by this pipeline.
- **Current result:** The new national run rebuilt the population mapping with exact conservation, then rejected at Gate 1: 27 certified-graph component-feasibility failures. The stored prior optimized assignments were also rechecked independently: 34 departments fail, with 67 disconnected districts and 24 departments reporting cross-district unit overlaps above 1 m². Department 13 district 17 is among the disconnected districts. The pipeline did not sample, optimize, or export a new map. This is the intended safe result, not an acceptance.
- **Run records:** [Latest pipeline report](../../redistricting/data/processed/pipeline_runs/latest.json), [national validation report](../../redistricting/data/processed/acceptance/current.md), and [webapp acceptance status](../../redistricting/export/acceptance.json).

### D49 — Speed up compactness scoring without changing its geometry definition

- **Decision:** When a district's polygons pass Shapely's coverage validity check, compute their union with `coverage_union_all`; otherwise use the existing general `unary_union(...).buffer(0)` path. If the complete department layer is a valid coverage, validate once and reuse that guarantee for every district subset. Overlapping or invalid geometry therefore continues to use the conservative general union.
- **Evidence:** On department 01, a fixed-seed 40-proposal profile fell from 9.09 seconds to 1.00 second. For six saved department plans (01, 13, 59, 75, 92, 971), the maximum absolute Polsby–Popper difference from the previous general-union formula was 4.7×10⁻¹⁵. A one-time layer check found valid complete coverages in 76 of 101 departments. This is a microbenchmark, not a national runtime guarantee; benchmark the full certified run after Gate 1 passes.
- **Stopping-rule review:** Keep D44's current rule provisionally: at least four 100-proposal rounds, stop after three consecutive rounds without a ≥1e-4 best-score improvement, and cap at 800 proposals. The old 189-minute run did not retain per-proposal histories, so this threshold has not been calibrated against quality-versus-runtime curves. It is a plateau heuristic, not a convergence test. Record elapsed time and compare same-seed budgets (200/400/800) on valid departments before revising the threshold.
- **Current status:** Do not rerun the national optimizer yet. The latest end-to-end run rejected at Gate 1 on 27 certified-graph component feasibility failures; a national optimizer run cannot repair those physical graph/data blockers. No new map was sampled or exported. The existing stored candidate remains rejected.
- **Election metrics at the time of D49:** The only map comparison then available was the separately labeled first-round population-weighted sensitivity in D46; its proposed-map side uses a rejected candidate. D50 later adds exact metrics for the official-map baseline, not the proposed map.

### D50 — Publish an exact 2024 official-map metric baseline

- **Decision:** Compute constituency-level baseline metrics directly from the Ministry's official 2024 constituency totals, without reallocating votes or registered voters. Report coarse and fine draft nuance-to-bloc mappings side by side. Defer M3 seat–vote response scenarios as specified in D59; label M4 as a descriptive comparison of final seats with first-round vote shares.
- **Results:** M1 is restricted to actual two-candidate runoffs with distinct mapped blocs: 402/501 contests in the coarse mapping and 403/501 in the fine mapping. M2 covers all 577 first-round constituencies. M4 uses all 577 official winners. M5 is a candidate-level diagnostic under the provisional L.162 interpretation: 40 distinct bloc-district shut-outs in coarse mapping and 25 in fine mapping; legal item O9 remains open.
- **Source detail:** Five constituency rows have candidate-vote sums off the published `Exprimés` total by one or two votes. They are listed in the audit JSON; first-round shares retain the official `Exprimés` denominator. Inputs are checksum-verified against the source registry.
- **Artifacts:** Audit JSON `data/quarantine/electoral/derived/official_map_metrics_2024.json`; webapp-only aggregate `export/browser/official-map-metrics.js`. These official-map baselines do not imply that metrics are available or valid for the proposed map.

### D51 — Let the local dashboard launch and monitor the gated national run

- **Decision:** The dashboard's launch control starts the full fail-closed national pipeline, not a stand-alone optimizer. It exposes maximum proposals, patience rounds, worker count, seed, and sampling replicates. Per-department progress records each proposal's configuration, temperature, candidate/current/best metric components, and proposal result. Compressed proposal traces and run summaries are retained under a unique run folder; history shows prior status, configuration, and outcome metrics. Existing optimized files are shown as a separately labeled legacy candidate set because their run ID, seed, runtime, and proposal history were not retained.
- **Safety boundary:** A run remains user-initiated, single-instance, and local to `127.0.0.1`. The pipeline must pass population mapping, Gate 1, Gate 2, sampling, optimization, and national validation before export. A failed gate is recorded as a stopped/rejected run; no proposal is displayed as an accepted map from that run.
- **Dashboard:** Show the D50 official-map baseline on the home page with coarse/fine toggles and coverage/interpretation notes. The proposed map remains unavailable unless its matching acceptance certificate is `ACCEPTED_MACHINE_CHECKS`.

### D52 — Treat component-balance failures as graph diagnostics; repair IRIS topology at parent boundaries

- **Decision:** A component-population failure diagnoses the current atomic-unit graph; it does not prove that no constituency partition exists. Clip each IRIS piece to its parent commune or municipal-arrondissement geometry and reconcile uncovered slivers to the piece with the longest shared boundary. For a sliver with no positive-length contact, use nearest-piece assignment only when the distance is at most 1 cm (floating precision); fail closed for anything farther away. Require the repaired pieces to partition the parent without material gaps or overlaps. Keep the existing rook-contiguity threshold; do not turn distance-only candidate links into certified edges.
- **Aix finding and fix:** Aix's 54 IRIS geometries extended slightly outside their parent commune. IRIS `130010404` overlapped Meyreuil (`13060`) by 84.5 m², hiding a 269 m shared boundary after clipping. The split routine now clips IRIS to the 2024 parent geometry and reconciles only small source-layer remnants, checking parent coverage and overlap. A point-contact remnant may use nearest-piece assignment only within 1 cm; larger nonlocal gaps stop the build. The guarded Gate 1 rerun with this bound passed blindness and reduced component-balance flags from 27 departments to 13. Aix is no longer flagged; 14 departments total were cleared by the geometry correction. This is a topology repair, not a relaxation of contiguity.
- **Remaining diagnostics:** The 13 still flagged are 17, 21, 22, 29, 35, 54, 56, 59, 65, 84, 85, 971, and 976. They include outlying, island, or enclave components whose residents cannot make a full district alone. The graph test is not evidence that their current legally established constituencies are invalid.
- **Source limits:** The stored INSEE 2022 map is too simplified for exact assignment. INSEE's commune/constituency correspondence is non-unique for split communes. The 2024 data.gouv contours and bureau-to-IRIS weights are useful references but do not by themselves certify exact legal membership. Do not silently promote them to an exact unit crosswalk.
- **Sources:** [INSEE commune/constituency correspondence](https://www.insee.fr/fr/statistiques/6436476), [INSEE simplified-map precision warning](https://www.insee.fr/fr/statistiques/6441661), [2024 constituency contours on data.gouv.fr](https://www.data.gouv.fr/datasets/contours-geographiques-des-circonscriptions-legislatives).

### D53 — Carry forward current official constituencies where Gate 1 has no certified component partition

- **Decision (user-approved):** In the remaining 12 departments, keep the current official constituencies unchanged as a frozen legal baseline rather than forcing the optimizer to redraw across disconnected components. Validate their exact unit membership against an authoritative crosswalk and label them `OFFICIAL_CARRY_FORWARD`, distinct from a generated-plan machine PASS. If the crosswalk reveals a geometry defect, repair it; if the official layout relies on geographically separated territory, retain it only as a documented exception for the unchanged official district. Do not generalize that exception to new boundaries.
- **Failure handling (user-confirmed):** A failed crosswalk or validator must identify the concrete cause. Repair the input geometry when it is wrong; revise a modeling assumption only when the governing source supports the change; otherwise record a narrowly scoped permitted exception on the unchanged official district. Never turn an inferred distance link into general contiguity permission.
- **Allocation consequence (updated after D55):** The 12 remaining carry-forward seat counts sum to 74; the current D'Hondt allocation assigns them 75. Preserve the 74 incumbent seats and allocate the remaining 484 of 558 departmental seats across the other 89 departments using D'Hondt. This is constrained D'Hondt for the 577-seat run. Keep the ordinary D'Hondt/Webster comparisons in Gate 2 as separate policy scenarios; recheck every generated department's ±20% feasibility after the constrained allocation.
- **Implementation status:** The fixed-seat D’Hondt allocation helper is implemented in `src/redistrict/allocate/apportion.py`, but it is not wired into the national pipeline because the exact unit-to-constituency crosswalk and carry-forward validation path are still missing. The 2022 INSEE bureau crosswalk plus the 2024 bureau-to-IRIS weights is useful for sensitivity analysis but is not an exact assignment source for split IRIS units. Until an exact or legally authoritative unit assignment is available and validated, Gate 1 remains blocked and no national optimizer run is ready.

### D54 — Diagnose the 12 remaining component flags and distinguish carry-forward from generation

- **Finding:** These are not 12 cases where the official map has been shown invalid. The Gate 1 graph is land-polygon rook adjacency (shared border >=0.5 m) plus the four source-verified bridge links from D55; it has no ferry edges unless individually approved. Its component test then assumes every component must hold a whole number of districts under the current modeled seat count and ±20% range. That is a necessary condition for generating districts under those assumptions, not a validator for the extant legal map.
- **Component causes (2024 geography and current modeled population):**

| Department | Remaining component(s) reported by Gate 1 after D55 | Diagnosis |
|---|---|---|
| 17 | Île-d'Aix (207) | Ré and Oléron now connect through source-verified road bridges (D55); the remaining ferry-served island cannot form a district alone. |
| 21 | Ménessaire (82) | Côte-d'Or exclave between Nièvre and Saône-et-Loire. |
| 22 | Île-de-Bréhat (402) | Offshore island. |
| 29 | Batz (449), Sein (273), Molène (164), Ouessant (838) | Offshore islands. |
| 35 | none (cleared) | The source-verified RD168 crossing at the Rance barrage connects La Richardais and Saint-Malo; adding this road link joins the six-commune cluster to the main component (D55). |
| 54 | Othe (40) | Confirmed Meurthe-et-Moselle enclave inside the Meuse; the Senate identifies it as such. This needs a frozen-district exception, not a fabricated bridge edge. |
| 56 | Belle-Île (5,553), Groix (2,282), Hœdic (100), Houat (216), Île-aux-Moines (628), Île-d'Arz (287) | Offshore islands. |
| 59 | Boursies, Doignies, Mœuvres (1,201 total) | Historical Nord exclave surrounded by Pas-de-Calais. |
| 65 | Escaunets/Séron/Villenave-près-Béarn (521); Gardères/Luquet (861) | Two enclaves of Hautes-Pyrénées inside Pyrénées-Atlantiques. |
| 84 | Grillon/Richerenches/Valréas/Visan (13,549) | Enclave des Papes inside Drôme. |
| 85 | Île-d'Yeu (4,877) | Noirmoutier now connects through its source-verified road bridge (D55); the remaining ferry-served island cannot form a district alone. |
| 971 | Basse-Terre group (182,599); Grande-Terre group (187,445); Marie-Galante (10,467); La Désirade (1,391); Terre-de-Bas (917); Terre-de-Haut (1,496) | Archipelago. Under the current modeled three seats, neither large island can independently contain a whole number of districts within ±20%; the small islands cannot form districts alone. |
| 976 | Grande-Terre (227,245); Petite-Terre: Dzaoudzi/Pamandzi (29,273) | Two islands separated by water; Petite-Terre cannot form a district alone. |

- **Separate allocation mismatch:** Among the 12 remaining carry-forward departments, current official district counts differ from the present D'Hondt model in 21 (official 5/model 4), 59 (21/23), 85 (5/6), and 971 (4/3). Their official counts sum to 74 versus 75 modeled seats. Carry-forward therefore requires preserving those 74 and allocating the remaining 484 of 558 seats among the other 89; that reallocation must then be checked for new ±20% failures. Department 35 no longer needs carry-forward after D55.
- **Implementation conclusion:** We can preserve the 12 remaining flagged departments. The blocker is that the generator and validator have no `OFFICIAL_CARRY_FORWARD` plan type or exact mapping from every current atom (including split IRIS pieces) to its current constituency. The INSEE commune mapping is non-unique for split communes, and the available 2024 bureau-to-IRIS weights are estimates; neither is an exact constituency assignment for every split atom. Build a separate, source-backed official seed and validation path, attach narrowly scoped ferry/enclave exceptions only to unchanged official districts, and keep the existing strict graph for all generated departments. Do not report the official seed as a generated-plan PASS.
- **Source checks:** The Rance barrage carries the RD168 road across the estuary ([Ille-et-Vilaine Department](https://www.ille-et-vilaine.fr/rd-168-barrage-de-la-rance-fin-des-travaux-en-cours-reportee-au-jeudi-16-octobre)); the Senate identifies Othe as a Meurthe-et-Moselle enclave in the Meuse ([Senate record](https://www.senat.fr/questions/base/2006/qSEQ060924338.html)); INSEE confirms that the commune-to-constituency relationship is non-unique ([INSEE correspondence tables](https://www.insee.fr/fr/statistiques/6436476)).

### D55 — Count four source-verified road bridges as transport-contiguity edges

- **Decision:** Add only these four permanent road crossings to the certified graph: Rivedoux-Plage–La Rochelle (Île de Ré), Bourcefranc-le-Chapus–Le Château-d'Oléron, La Richardais–Saint-Malo (RD168 at the Rance barrage), and Barbâtre–La Barre-de-Monts (Noirmoutier). The endpoints and bridge/road connection are documented in departmental or official destination sources in `config/approved_contiguity_links.csv`.
- **Why:** These are actual public road connections omitted because the administrative land polygons stop at the shoreline. They are not nearest-distance guesses, ferry routes, or general permissions to connect separated units.
- **Limits:** Keep ferry-only and enclave cases unapproved for generated districts. Rebuild Gate 1 and confirm each edge links the intended component before treating any resulting department as generation-feasible. D47's rejection of the remaining inferred links stays in force.

### D56 — Keep the 12 carry-forward departments blocked until their official assignment is evidenced

- **Decision (confirmed):** Implement D53's unchanged-official-map route; do not clear Gate 1 by relaxing rook adjacency, approving inferred links, or suppressing the component diagnostic. The 12 departments must enter the national result as `OFFICIAL_CARRY_FORWARD`, with a separate validator and scoped official-map exceptions, while the other 89 remain subject to generated-plan checks.
- **Source audit (2026-11-19, expanded):** The data.gouv.fr dataset *Limites des circonscriptions électorales* is a Le Havre-only layer (two features), not a national crosswalk. The Ministry-origin 2012 commune/canton/circonscription workbook is a usable legal-era correspondence for commune × former-canton keys. IGN's official GEOFLA 2010 canton and commune archives provide historical mainland geography, but the canton layer represents split urban centres with whole-city pseudo-cantons (codes 96/98/99); internal boundary linework has no canton/circonscription labels. Consequently, those two official sources together still cannot assign 2024 IRIS pieces inside the split centres. They also do not cover Mayotte in the 2012 workbook. The detailed 2017 Mapotempo/OSM reconstruction contains the expected 74 district IDs, but its union differs from current Admin Express department geometry by roughly 2–17% in the 12 departments and it is not an authoritative boundary release. It remains a comparison source until those differences are resolved against legal boundaries. The 2024 bureau-to-IRIS weights remain sensitivity estimates, not an exact unit assignment. A 2024 contributor-produced contour dataset is formed by aggregating proposed polling-station contours using Ministry bureau-to-circonscription associations and cleaning/simplifying the result; it can support comparison and election sensitivity work, but its documented production method does not make it a legally authoritative boundary source for certification.
- **Release gate:** Do not run sampling or optimization until a reproducible, source-backed assignment covers every current unit (including split IRIS), district IDs and seat counts match the unchanged official map, population and geometry reconcile, and the carry-forward validator passes. After reserving the 74 official seats, allocate the remaining 484 among the other 89 under D53 and recheck their ±20% feasibility. While this prerequisite is unmet, both the webapp control and its launch endpoint reject a run rather than starting a chain that will stop at Gate 1.
- **Sources:** [Ministry-origin 2012/2017 commune/canton correspondence](https://www.data.gouv.fr/datasets/circonscriptions-legislatives-table-de-correspondance-des-communes-et-des-cantons-pour-les-elections-legislatives-de-2012-et-sa-mise-a-jour-pour-les-elections-legislatives-2017), [Mapotempo detailed 2012 constituency reconstruction](https://www.data.gouv.fr/datasets/contours-detailles-des-circonscriptions-des-legislatives), [INSEE warning on simplified constituency geometry](https://www.insee.fr/fr/statistiques/6441661).

### D57 — Record the historical-geometry source audit; keep Gate 1 fail-closed

- **Legal-source finding:** The 2009 ordinance ratified in 2010 is the authoritative written composition for all 12 departments. Its Table 2 assigns constituencies to the historical cantons, describes split-city areas by named streets/municipal arrondissements, and lists Mayotte's two constituencies by canton. This supplies the legal basis missing from the 2012 workbook for Mayotte, but it is text rather than a complete labeled GIS crosswalk. The 2012 Ministry correspondence remains a useful structured check for mainland commune × canton assignments.
- **Geometry finding:** The official IGN GEOFLA 2010 canton archive is useful for reconstructing unsplit commune/canton assignments, but its `CANTON` polygons do not encode labeled sub-canton boundaries inside split urban communes; its boundary-line layer carries no canton or constituency identifier. Thus the ordinance's street descriptions still need a reproducible geometry reconstruction for split-city atoms, and old Mayotte canton geometry must be linked to current units. Neither can be replaced with centroid/area-weighted guesses.
- **Cross-check:** A reproducible overlay audit of current Gate 1 atoms against the stored 2022 INSEE simplified constituency layer found only 2,320 of 4,607 atoms wholly within exactly one polygon; 2,287 intersect a simplified boundary or are not fully covered by one polygon. INSEE explicitly warns that this geometry is too simplified to determine membership precisely. The per-atom diagnostic is `data/processed/gate1/official_boundary_overlay_audit.csv`, generated by `scripts/audit_carry_forward_crosswalk.py`; it is not an assignment file.
- **Allocation check:** Applying the fixed-seat D’Hondt rule to preserve the current 74 seats in those 12 departments allocates 484 seats across the other 89. Relative to ordinary D’Hondt, only department 73 changes (3 to 4 seats); the current component-feasibility check finds no new failures among those 89. This is an allocation feasibility result only; it does not certify the carry-forward assignments or clear Gate 1.
- **Decision:** Do not mark the 12 departments Gate 1-ready merely because the legal text exists, or by using centroid/area-weighted assignment to guess IRIS membership. Use the ordinance's descriptions as the legal specification, reconstruct and record its split-centre/canton geometry, resolve each current atom including Mayotte, then validate frozen assignments for complete coverage, seat counts, population, and plan consistency. Continue to block launch until those steps pass. The official unchanged map may use narrowly scoped exceptions only after that assignment is evidenced.
- **Current operational effect:** This does not alter the approved carry-forward policy or clear any of the 12 departments. UI and API launch guards remain active; no optimizer run is running or should be started from this Gate 1 state.
- **Sources:** [2009 ordinance establishing constituency composition, ratified by the 2010 law](https://www.legifrance.gouv.fr/jorf/id/JORFARTI000020915503), [IGN GEOFLA 2010 canton archive](https://data.geopf.fr/telechargement/resource/GEOFLA/GEOFLA_1-1_CANTONS_SHP_LAMB93_FXX_2010-01-01), [Ministry-origin 2012/2017 correspondence](https://www.data.gouv.fr/datasets/circonscriptions-legislatives-table-de-correspondance-des-communes-et-des-cantons-pour-les-elections-legislatives-de-2012-et-sa-mise-a-jour-pour-les-elections-legislatives-2017), [2024 contributor-produced constituency contours and methodology](https://www.data.gouv.fr/datasets/contours-geographiques-des-circonscriptions-legislatives).

### D58 — Render the Assembly's published seat positions and parliamentary groups

- **Decision:** Replace the invented row-major semicircle with the seat outlines and seat numbers published by the National Assembly. Place each currently seated deputy at the published seat number and color the shape by the deputy's current parliamentary group, using the group's published color. Display the 574 currently seated members and report the three vacancies separately; do not synthesize a seat position for a vacancy.
- **Reason:** The Assembly allocates contiguous sectors to parliamentary groups, then assigns seats inside each sector. The previous UI sorted `placeHemicycle` values into a separately invented set of rows, which scrambled the group sectors. The group is the authoritative displayed affiliation; broader electoral blocs remain separate and are not used to color the hemicycle.
- **Source/build:** The official seat plan is snapshotted locally by `scripts/build_hemicycle_layout.py` into `export/browser/hemicycle-layout.js`; the seat/deputy assignment and group counts come from the Assembly's open-data roster in `scripts/build_current_assembly.py`.
- **Sources:** [Assembly explanation of group sectors](https://www.assemblee-nationale.fr/dyn/synthese/fonctionnement-assemblee-nationale/travail-legislatif/la-seance-pleniere), [official deputy seat map](https://www.assemblee-nationale.fr/dyn/vos-deputes/hemicycle), [official group counts](https://www2.assemblee-nationale.fr/instances/liste/groupes_politiques/effectif).

### D59 — Simplify the official-map metrics table and defer M3

- **Decision:** On the webapp, retain M1 as its own restricted diagnostic and merge the bloc-level M2, M4, and M5 values into one table. The table has one row per bloc and only three metric columns: MMD, final seat share minus first-round vote share, and M5 shut-outs (shown as shut-outs / districts where the bloc reached 20%). Remove the separate M2, M3, and M5 metric cards.
- **M3:** Remove seat–vote response scenarios from the v1 metrics output. Record them as deferred until fixed candidate slates, turnout, withdrawals, and voter-transfer assumptions are approved. No M3 result is presented as zero or as an unavailable data point in the current table.
- **Scope:** This display is for the observed 2024 official-map baseline. Proposed-map exact metrics remain unavailable while split-unit election counts are unresolved. O9's legal review of the M5/L.162 interpretation remains open.

### D60 — Keep start-plan control concise

- **Decision:** Keep the number of candidate starting plans configurable under the short label “Plans de départ / département.” Remove the inline sampler explanation at the user's request.

### D61 — Preserve the 12 official departments, but require their validated carry-forward before national launch

- **Decision (reconfirmed):** Keep the current legal constituencies unchanged in departments 17, 21, 22, 29, 54, 56, 59, 65, 84, 85, 971, and 976. Optimize only the other 89 once the unchanged official assignment for all units in the 12 has been reconstructed and separately validated; reserve their 74 seats and allocate 484 to the other departments with fixed-seat D'Hondt.
- **Safety condition:** Do not allow a national run to omit the 12 or treat 89 optimized departments as a complete map. Current pipeline sampling, validation, and export expect all 101 departments and 558 departmental seats. The legal text identifies the official composition, but its split-city and Mayotte descriptions still need verified geometry and unit/population reconciliation. Keep the run button disabled until the carry-forward artifact and validator pass.
- **Current status:** The fixed-seat allocation is connected to Gate 1, Gate 2, and the national validator (D63). Its 89-department feasibility check passes. The official-unit crosswalk and carry-forward validator are not complete; Gate 1 remains blocked.

### D62 — Name the unresolved official-boundary units; do not infer their constituency membership

- **Finding:** The ordinance plus the 2012 Ministry commune/canton table assigns whole current units wherever a unique old-canton/commune key exists. Exact membership remains ambiguous for 13 current commune parents: Royan (17306), Dijon (21231), Brest (29019; 64 IRIS atoms), Nancy (54395), Avesnes-sur-Helpe (59036), Dunkerque (59183; 43 IRIS atoms), Lille (59350; 110 IRIS atoms), Roubaix (59512; 38 IRIS atoms), Tourcoing (59599; 41 IRIS atoms), Tarbes (65440), Carpentras (84031), La Roche-sur-Yon (85191), and Mamoudzou (97611). The legal text splits these across constituencies; a commune-level or centroid join would assign them incorrectly. Other current atoms in the 12 departments, including the whole-commune units in 971, resolve under the available correspondence.
- **Geometry limitation:** IGN GEOFLA 2010 uses whole-city pseudo-cantons in the split mainland cities and does not label internal canton boundaries. GEOFLA 2015 gives Mayotte 12 canton features but Mamoudzou remains a single pseudo-canton (`CODE_CANT=99`), so it cannot distinguish the ordinance's Mamoudzou I/II from III. IRIS cuts inside Brest, Dunkerque, Lille, Roubaix, and Tourcoing provide smaller units but must not be assumed to follow historical canton lines.
- **Next repair:** Obtain or reconstruct a labeled, legally traceable boundary for each listed parent; split current units at those boundaries where necessary; publish a reproducible atom-to-official-constituency crosswalk and reconciliation report. Use the contributor-produced detailed contours only as a comparison layer, never as the assignment authority. Then validate exact coverage, one constituency per atom, population conservation, 74 seats, district continuity, and agreement with the ordinance before allowing the carry-forward to pass Gate 1.
- **Operational consequence (historical status):** At the time of this audit, the carry-forward policy was not yet operationalized. D65 later removed these 12 departments from the 89-department search scope, so their detailed official atom crosswalk is not a Gate 1 blocker for that scoped run. A complete national certification still needs a separately validated carry-forward artifact.
- **Evidence:** Read-only source probe of the Légifrance 2009 ordinance, Ministry 2012/2017 tables, IGN GEOFLA 2010/2015 geometry, and current Gate 1 units (2026-11-19). No assignment data were changed.

### D63 — Apply the approved fixed-seat allocation in Gate 1 and Gate 2

- **Decision:** For the 558 departmental seats, preserve the current official seat counts in departments 17 (5), 21 (5), 22 (5), 29 (8), 54 (6), 56 (6), 59 (21), 65 (2), 84 (5), 85 (5), 971 (4), and 976 (2). Allocate the remaining 484 seats among the other 89 departments using D’Hondt.
- **Implementation:** `allocate/policy.py` is now the shared policy entry point. Gate 1 uses it before and after subdivision; Gate 2 labels the 577-seat fixed-overseas scenario `D53_FIXED_12`; the national validator requires the same policy in both artifacts.
- **Safety boundary:** This connects the seat calculation through the national build, but it does not assign current units to official districts. Component failures for the 12 remain in the report; there is no bypass, carry-forward assignment, or launch readiness until the exact geography and separate validator pass.
- **Legal basis:** Department seat counts follow Table 1 and district composition Table 2 of [Ordinance 2009-935](https://www.legifrance.gouv.fr/jorf/id/JORFARTI000020915503), whose district boundaries remain current for the 2024 baseline.
- **Rebuild result (2026-11-19):** Guarded Gate 1 rebuilt in 145 seconds with D53 seats and still reports exactly the 12 frozen departments as component-infeasible, with no population/unit flags. Guarded Gate 2 reports all four allocation totals passing; the 577/fixed row uses `D53_FIXED_12`, sums to 558, preserves all 12 counts above, and assigns 484 seats to the remaining 89. Compliance records: Gate 1 `data/processed/blindness/runs/20261119T213918Z-715406cc/compliance_report.json`; latest Gate 2 `data/processed/blindness/runs/20261119T214344Z-f354a105/compliance_report.json`.

### D64 — Simplify the map summary and show stopping logic on demand

- **Decision:** Remove the demographic summary labels/numbers and the title/legend beneath the hemicycle, while retaining the published seat positions and vacancy caption. Remove the requested election explanations and no-run Gate 1 status panel. Keep live progress/history and leave the launch button disabled when checks are not ready.
- **Stopping rule display:** Put the search rule inside a collapsed “Comment la recherche s’arrête” disclosure. Explain batches, minimum work, plateau counter, proposal cap, score weights, and population tolerance in plain language; update it when the user changes settings.

### D65 — Exclude the 12 carry-forward departments from search, not from national validation

- **Decision:** The 12 departments identified in D53 (`17, 21, 22, 29, 54, 56, 59, 65, 84, 85, 971, 976`) are fixed to their current official constituencies and must be excluded from Gate 1 component-feasibility blocking, sampling, and optimization. Search feasibility applies to the other 89 departments, whose current fixed-seat allocation has no additional component failures.
- **Separate release check:** The 74 constituencies are the frozen districts themselves; they need not be re-created by assigning the model's commune/IRIS atoms. National output and validation should support two explicit record types: generated districts, validated from atom assignments, and unchanged official carry-forward districts, validated from their official identifiers and authoritative geometry/source. An atom-to-district crosswalk is needed only for operations that aggregate or audit those frozen districts through the atom model (for example, atom-level population joins), not to establish that the existing constituencies remain unchanged.
- **Geometry limit:** The available 2022 INSEE layer contains simplified reference contours. The overlay audit finds 2,287 of 4,607 model atoms cross or miss a unique simplified polygon, so those contours cannot determine atom membership or serve as exact boundary evidence. This does not invalidate the 74 existing constituencies. An authoritative detailed geometry source is still needed for an exact national map display/geometry check if the current simplified reference is insufficient.
- **Scope correction:** D56/D57's instruction to require an atom crosswalk before any sampling/optimization is superseded: the 89-department search is independent of such a crosswalk. For full national acceptance, preserve the 74 official districts as carry-forward records and validate them on that basis; require an atom crosswalk only when a stated metric or geometry audit actually needs one. Do not describe it as a general prerequisite to preserving their legal validity.
- **Implementation update:** Gate 1 readiness now treats only non-frozen feasibility failures as search blockers; default sampler/optimizer runs reject frozen department codes; the monitored app path launches the 89-department search and ends as `SEARCH_COMPLETED_NOT_CERTIFIED`. It leaves national acceptance/export untouched. This wiring has not yet been exercised by a search run. The mixed carry-forward/generated output and validator remain to be implemented; the exact atom crosswalk is not a blanket requirement for them.

### D66 — Keep this phase focused on the other 89 departments

- **Decision:** The current objective is to search and optimize the 89 non-frozen departments. Preserve the 74 existing constituencies in the other 12 departments without attempting to reconstruct their atom crosswalk as a prerequisite or parallel task. Their reported component diagnostics are informational for this scoped search.
- **Operational meaning:** The webapp run is a search over those 89 departments; it does not claim to publish a new 101-department map. Do not spend this phase resolving geometry/crosswalk questions for the 12 frozen departments. Revisit whole-map packaging only if/when it is needed after the 89-department redistricting work.

### D67 — One valid plan starts each department's optimizer

- **Decision:** The optimizer needs one valid starting plan per searched department. The sampler inserts a verified current official plan first when it can map it exactly to the model units and it passes the same hard checks; otherwise the optimizer starts from the first valid sampled candidate. Other candidates are fallback/comparison records, not separate optimizer searches.
- **How candidates are made:** For each candidate, the sampler starts from the department's model units and certified adjacency graph, randomly grows connected districts from seed units, applies a repair step and then ReCom proposals. By default it tries 300 proposals per attempt and allows up to five attempts to find a candidate meeting the project's contiguity and ±20% population checks. A new random seed produces a different candidate. These checks make it a usable search start, not an official or legally certified map.
- **UI wording:** Label these as “Candidats initiaux” rather than “Plans de départ” and state that one valid candidate is enough. Keep the count configurable for now; the current default of three has not yet been compared against one-candidate runs for valid-start rate or runtime.

### D68 — Include the current official plan as the first start when it validates

- **Decision:** For each of the 89 searched departments, include its current official division as an extra starting candidate if it can be mapped unambiguously onto the project's model units and passes the same hard checks as any other start (complete unit assignment, certified-graph contiguity, and ±20% population). Put a valid official candidate first so the optimizer starts from it; retain random candidates as fallback. If the official assignment cannot be established or fails a hard check, skip it without blocking the search.
- **Implementation and audit (2026-11-19, refreshed 2026-11-20):** Added the INSEE June 2026 commune/circonscription table as a hashed, generation-eligible source. The sampler inserts the official candidate first when exact whole-commune membership covers the current units, official/project seat totals match, and the shared validator passes. The guarded audit (`data/processed/official_seed_audit/report.md`, latest compliance PASS `data/processed/blindness/runs/20261119T232218Z-e6279b9c/compliance_report.json`) checked all 89 departments: 13 official plans pass current project checks and qualify as starting plans; 19 pass using their current official seat counts but D53 changes their seat totals, so they cannot start the D53 plan unchanged; 56 lack a complete crosswalk (113 partial-commune entries and 2,636 unassigned model units); one complete official assignment, department 91, fails only the current-population ±20% project check by 23.6%. D69 checks that case against the 2006 historical reference. No national sampling/optimization run was started.
- **Limit:** INSEE's table marks split communes but does not locate their internal constituency boundary. The simplified polygons are not used to guess those memberships. Therefore the official plan is now a starting candidate where the table supports an exact, constraint-passing assignment; it is not yet available as an exact candidate in every one of the 89 departments.

- **Integration check:** The initial guarded smoke run covered the 10 departments then identified as eligible. D70 replaces that earlier mapping; its latest guarded sampler smoke run confirms that the official plan is first, marked valid, and covers every model unit in all 13 qualifying departments (`data/processed/blindness/runs/20261119T231904Z-5c8175e3/compliance_report.json`). This did not start the national sampling or optimization run.

### D70 — Reconcile official 2021 commune codes through COG history

- **Decision:** Map the INSEE constituency correspondence’s 2021 commune codes to current 2024 model units through the official COG 2024 inventory and movement history. Do not use the population-mapping table for this purpose: that table converts population records onto 2024 geography and omits some 2021 commune/commune-déléguée components. Where several 2021 communes now form one current model unit, assign that unit only if every component has an exact whole-commune membership and all point to the same constituency. Keep splits and conflicting memberships unresolved.
- **Reason:** This removes false gaps caused by commune merges/code changes without inferring a boundary. For example, 02077 and 02564 both map to 02564 in COG 2024 and are both in circonscription 02004; by contrast 01039 and 01138 now form one model unit but map to different constituencies, so that unit cannot be assigned as a whole.
- **Audit result (2026-11-20):** The updated 89-department audit moved from 10 to 13 exact, current-project-valid official starts and from 17 to 19 fully mapped official plans with a D53 seat-count mismatch. Remaining gaps include 113 genuinely partial-commune rows, 2,636 unassigned model units, a current-atom cross-constituency conflict, and six Meuse communes with no constituency value in the INSEE table. Guarded sampling integration passed for all 13 eligible departments (`data/processed/blindness/runs/20261119T231904Z-5c8175e3/compliance_report.json`).

### D69 — Separate historical legality checks from current project constraints

- **Decision:** Keep the project's ±20% threshold as a hard requirement for generated plans, evaluated against the selected 2021 population snapshot and the D53 seat count. For the existing official map, do not treat a 2021-vintage deviation as a retroactive legal failure. The 2009 redistricting law applied its ±20% rule to that redistricting operation using the population figures authenticated by the first decree under the census law; the 2009 operation used the INSEE 2006 reference population. Record historical-baseline checks separately from present-day drift and optimizer-start eligibility. Do not silently waive the ±20% project rule for new plans.
- **Legal evidence:** Article 2 II of Law 2009-39 establishes the rule and the population reference; the report accompanying Ordinance 2009-935 states that after the 2009 redistricting no domestic constituency exceeded ±17.5% on that basis. Constitutional Council decisions 2008-573 DC and 2010-602 DC address narrow, justified exceptions and upheld the ratified map. See the [law](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000020088496), [ordinance report](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000020915474), [2008 decision](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000020088543), and [2010 decision](https://www.legifrance.gouv.fr/juri/id/CONSTEXT000021879636).
- **Audit result (2026-11-20):** Added the INSEE 2006 legal-population file and a guarded historical audit. It exactly joins 30 departments to the current INSEE whole-commune correspondence; all 30 pass ±20% on both 2006 municipal and total population. The other 71 are unresolved by this direct-code method because of partial communes, code changes, or missing 2006 entries; they are not marked as failures. In department 91, all 194 communes map exactly: official constituency 91005 has 100,743 municipal residents versus a mean of 118,365.5 in 2006 (−14.89%); it passes. With 2021 population and the official 10 seats it is −23.60%, a current demographic-drift/project-criterion result. The unchanged 10-seat map still cannot seed D53, which assigns 11 seats to department 91.
- **Limits and follow-up:** The audit proves historical population compliance only for departments with an exact, direct-code crosswalk. It does not independently certify every boundary, contiguity exception, or any partial-commune assignment. Reconcile the 2026 INSEE commune codes to the 2006/2024 COG history before drawing conclusions for the 71 unresolved departments. Historical input: `data/raw/population/insee_populations_legales_2006_ensemble.xls`; output: `data/processed/official_historical_population_audit/`.

### D71 — Treat official-seed gaps as optional comparison gaps, not search blockers

- **Decision:** For the 89 non-frozen departments, the D53 search may start from any saved ReCom plan that passes the shared hard validator and has the D53 seat count. A fully mapped current-official plan remains the preferred first candidate only where its exact assignment also matches D53 seats and passes project checks. Do not change D53 seat counts, relax the ±20% rule, or infer missing official memberships to force an official map into the search.
- **19 seat-count mismatches:** These official partitions use a different number of seats than D53. Keep them as the official-map comparison baseline, but use D53-sized valid ReCom candidates for the new-map search. The mismatch is not a failure of official-map legality and is not a search blocker.
- **56 incomplete crosswalks:** Do not derive exact legal membership from 2024 election counts, estimated bureau-to-IRIS weights, simplified constituency polygons, or proposed bureau contours. The 2022 INSEE bureau-to-constituency table is exact at polling-station level but lacks an authoritative link from polling stations to current model atoms; its coverage also omits Marseille, Lyon, and Paris under their aggregate commune codes. Use the bureau/IRIS table only for the explicitly labeled election-sensitivity analysis (D20), not as the hard assignment or contiguity source. Keep exact official crosswalk reconstruction open for legal map comparisons and full territory certification.
- **Validation and repair:** Added `scripts/audit_residual_search_readiness.py`. Its guarded run revalidated every saved candidate against the current Gate 1 units, D53 seat count, exact unit partition, certified contiguity, and ±20% population rule. All 89 non-frozen departments now have at least one valid ReCom start (`data/processed/residual_search_readiness_audit/report.md`; compliance PASS `data/processed/blindness/runs/20261119T233845Z-a56a3f1d/compliance_report.json`). The audit surfaced stale D53 candidates in department 73; its plans were regenerated, and the official plan is now the first valid candidate there. Department 13 has some failed candidates, but also has valid candidates; failed candidates are retained and must be excluded by the shared validator.
- **Operational scope:** This clears the 19 and 56 from search-start readiness; it does not certify a converged ensemble, start the national optimization, complete the legal atom crosswalk, or satisfy mixed-map national acceptance. The exact-crosswalk and mixed-map certification work remains separately tracked under D57/D66/D68 and O7/O10.

### D72 — Preserve reproducible search histories and run-scoped artifacts

- **Decision:** Every future app-launched search keeps its configuration, stage logs/status, seeded starting plan and its source hash, every optimizer proposal's metrics/status/temperature, a canonical plan fingerprint, and the per-unit assignment delta needed to reconstruct each proposed state from the accepted chain. At every round boundary, retain current/best assignments and round stopping diagnostics; keep the final assignments, sampled candidate plans, and their run-specific copies with SHA-256 manifests. Write an append-only per-department JSONL trace during the run so an interruption leaves readable progress; compress it to JSONL+gzip on normal completion and record its hash. Direct optimizer invocations also receive unique trace folders so later runs do not overwrite their histories.
- **Why:** Proposal metrics alone show whether a move helped but cannot explain which units moved. Fingerprints, deltas, round snapshots, seeds, and input/output hashes connect observed scores to the actual plans and preserve enough evidence to compare algorithm/configuration changes.
- **Scope:** This applies to runs started after the change. Existing legacy optimizer files remain incomplete: their original run IDs, seeds, and per-proposal traces cannot be recreated. The trace preserves candidate metrics and map transitions; input-file hashes in the blindness reports and run-scoped artifact manifests identify the data and plan files used. This is search diagnostics, not a statistical ensemble certificate or national-map certification.
- **Files:** Proposal trace schema v2 is written in `scripts/optimize_departments.py` and `src/redistrict/optimize/sa.py`; `scripts/run_national_pipeline.py` preserves sampled starts, optimized assignments, benchmark output, sizes, and SHA-256 hashes under each pipeline run's `artifacts/` directory. An interrupted optimizer leaves any unfinished `<department>.jsonl.partial` file in that run's trace folder.

### D73 — Record the first independently audited D53 search result

- **Run:** The app-launched search `20261120T001804Z-3bed7d8e` / pipeline `20261120T001804Z-6d568ab9` completed its population mapping, Gate 1, Gate 2, 89-department sampling, and optimization stages successfully. Configuration: 3 sampled candidates per department, 300 sampling steps, 800 proposal cap, 100 proposals per round, minimum 4 rounds, stop after 3 stale rounds, minimum improvement `0.0001`, objective weights 0.50 population / 0.30 compactness / 0.20 EPCI, 3 workers, seed 42.
- **Validity and trace audit:** `scripts/audit_search_run_results.py` independently validated the 89 generated plans for exact unit coverage, D53 seat count, certified-graph contiguity, ±20% population, valid non-empty unit geometry, and no cross-district overlap above 1 m². It recomputed objective metrics and checked run-specific artifact hashes. All 89 passed. It also replayed all proposal traces from their starting assignments, checked every unit delta and plan fingerprint, and matched round checkpoints/final assignments; guarded audit PASS is `data/processed/blindness/runs/20261120T011813Z-1e053a19/compliance_report.json`.
- **Official comparison:** Only the 13 departments with a complete exact official assignment and the same D53 seat count have a direct objective comparison. Eleven have a strictly lower v1 objective than their official starting plan: `03, 16, 19, 26, 40, 70, 73, 79, 82, 89, 973`. Departments `23` and `48` have one D53 seat each, so the whole department is the only possible district; their official and optimized plans are identical and no better alternative exists under this unit model.
- **Counts and metric change in those 13:** Sampling produced 267 ReCom candidates (3 per department); adding the 13 qualifying official plans gives 280 valid candidate records. Canonicalizing away district labels leaves 246 distinct assignments within departments; 34 records repeat an already-seen partition. The optimizer wrote 89 final plans, independently audited. Mean starting official components were `L_pop=0.0585`, `L_comp=0.8013`, `L_epci=0.1727`, combined `L=0.3042`; optimized means were `0.0177`, `0.7691`, `0.1488`, and `0.2693`. Mean absolute reduction in L was 0.0348 (10.65% mean relative reduction); mean maximum population deviation across departments fell from 5.85% to 1.77% (largest single-department value from 16.41% to 5.44%).
- **Limits:** The 19 seat-count-mismatch departments and 56 incomplete official crosswalk departments, plus department 91's current-rule mismatch, are not valid same-seat/exact-boundary official comparisons. Their D53 plans passed generated-plan checks, but this run does not establish that they are better than the official map. The v1 objective measures population balance, compactness, and EPCI splits; it is not an electoral-neutrality score or legal finding. The 12 frozen departments were not changed. The result is `SEARCH_COMPLETED_NOT_CERTIFIED`; D74 records a visual mixed-map draft, but it is not accepted or exported as a certified national map. No second run was needed to find strict improvement in every comparable multi-seat department.
- **Artifacts:** Per-department validation and comparison: `data/processed/optimizer_monitor/runs/20261120T001804Z-3bed7d8e/analysis/`; preserved starting and optimized maps plus hash manifests: `data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts/`; proposal traces and live-run history: `data/processed/optimizer_monitor/runs/20261120T001804Z-3bed7d8e/`. The webapp run history now shows the 89/89 validity result, direct official-comparison count, strict-improvement count, and a link to the audit report.

### D74 — Assemble a mixed national draft without implying certification

- **Decision:** The 89 audited D53 plans can be assembled for visual review with the 74 unchanged official constituency records from the 12 carry-forward departments. Keep the output run-scoped and label it `ASSEMBLED_DRAFT_NOT_CERTIFIED`; do not replace the webapp's accepted/exported map.
- **Artifact:** `data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts/national_draft/national_mixed_assignment_draft.geojson.gz` contains 34,719 map features representing 484 generated constituencies plus 74 carried-forward official constituencies. The generated atom geometries are simplified by 30 m for display. Carry-forward polygons come from INSEE's 2022 simplified constituency layer. The current guarded assembly passed blindness enforcement: `data/processed/blindness/runs/20261120T112658Z-d70b2242/compliance_report.json`.
- **Scope and metrics:** The mixed draft has 558 departmental seats; with 19 overseas/abroad seats the scenario totals 577. Exact generated-scope population covers 58,691,828 residents (2021 reference except the project's 2017 Mayotte population). For the 89 generated departments, exact stored optimizer components are max local `L_pop` 17.99%, unweighted mean department `L_pop` 3.68%, district-count-weighted `L_comp` 0.7666, and pooled avoidable EPCI split ratio 0.1397. The district-count-weighted mean of department objective values is 0.2867; this is descriptive and is not defined as a national objective score.
- **Comparison rule (superseded for exploratory scoring by D75):** A national comparison uses the common total of 558 departmental constituencies (577 including the 19 overseas/abroad seats); department allocation differences do not prevent a national comparison. The exact official population-unit crosswalk was unavailable for some districts, so this decision initially withheld a national score. D75 now reports a clearly labeled IRIS-informed estimate using one documented formula; it does not claim exact membership or certification. The 13 exact same-seat department comparisons from D73 remain the only exact department-level comparisons available in this run.
- **Consequence:** The assembled map remains a visual draft, not a validated national map or legal approval. D75 provides the requested exploratory nationwide comparison and retains uncertainty indicators; exact official membership remains an open data limitation.

### D75 — Use an IRIS-informed heuristic for nationwide score comparison

- **Decision:** When an official constituency splits a commune that remains whole in the new-plan model, create virtual IRIS pieces for the *scoring view only* where the 2024 IRIS geometry and INSEE 2022 population weights exist. Scale IRIS weights to the parent's chosen legal population (2021, except Mayotte 2017), as in D4-r/D39. Assign each virtual IRIS to the official constituency with the largest intersected area. Reuse model IRIS atoms already present. If no usable IRIS geometry/weight exists, assign the entire model unit to the official contour with the largest area overlap; nearest-contour assignment is reserved for zero-overlap geometry gaps. Never fractionalize a unit's population across multiple constituencies. Preserve the total population exactly and log every heuristic assignment.
- **Why:** The 74 carry-forward constituencies remain unchanged; they need no redrawing. The scoring view still needs population assigned to them so their contribution can be included. The 56 departments with incomplete official crosswalks are among the 89 redistricted departments: their new plan is generated, while this heuristic estimates the official baseline for comparison. Exact whole-commune INSEE rows take precedence; IRIS and then whole-unit overlap provide explicit fallback tiers.
- **Clarification:** “74 carried forward” means their official constituency outlines and assignments are copied as-is into the mixed draft. No population reallocation or optimization is performed in these districts. Assigning their resident population to those fixed districts is needed only to calculate comparable population metrics; the same scoring procedure is applied to the generated and official maps.
- **National metrics:** Compare 558 departmental districts per map (577 seats including 19 overseas/abroad seats). Population deviation is measured against the shared national mean `total legal population / 558`. Compactness is the mean `1 − Polsby–Popper` over the same model geometries. EPCI is the pooled avoidable excess ratio. For this report only, define `L_national = 0.50 × max national population deviation + 0.30 × mean compactness loss + 0.20 × pooled avoidable EPCI ratio`. Do not call this the department-local optimizer objective or a legal/neutrality score.
- **Run result:** The official heuristic assignment used 35,930 exact whole-commune model units, 90 virtual-IRIS communes (1,438 pieces), 4,313 IRIS area-overlap assignments, and 408 whole-unit area-overlap fallbacks. Three partial communes could not use virtual IRIS data/coverage. Seven fallback units had under 50% area overlap with the selected contour; 2,079 fallback units intersected more than one official contour. Total population was conserved at 67,664,570.
- **Comparison:** Under this heuristic and the stated national formula, official `L_national = 0.5290`; the mixed proposed map `L_national = 0.6565` (higher/worse by 0.1275). The proposal improves mean absolute deviation (11.85% → 8.59%) and compactness loss (0.8028 → 0.7803), but worsens the maximum national population deviation (52.59% → 79.14%) and pooled EPCI ratio (12.63% → 13.37%). The proposed worst district is Indre's single D53 constituency (217,228 residents, +79.14% vs national mean); official Indre has two districts. The official maximum is Corse-du-Sud's estimated 57,493-resident constituency (−52.59%). Report and unit-level crosswalks: `data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts/national_draft/report.md`, `heuristic_national_comparison.json`, `official_unit_assignment_heuristic.csv`, and `national_plan_assignments_heuristic.csv`.
- **Limit:** This is an exploratory estimate based on generalized 2022 constituency contours; it is not exact official membership, legal validation, neutrality evidence, or acceptance. Small-area assignment errors may alter scores. The 12 unchanged departments stay unchanged in both maps. The 19 seat-count differences across departments do not block a national comparison when the total remains 558; they explain some differences in the national population metric.

### D18 — Audit of districts that split a commune (decided)

- **Problem:** results are published per commune (and per arrondissement in Paris, Lyon, Marseille), not per IRIS. A district that takes only part of a commune cannot be replayed exactly.
- **Superseded by D20.** Exact small-area electoral counts are required for the primary audit. Population-weighted allocations may be shown only as sensitivity analysis, never as observed votes or as evidence for PASS.

### D19 — Optimizer objective (decided, v1)

- **Objective:** L = 0.50 L_pop + 0.30 L_comp + 0.20 L_epci, with L_comp = mean (1 − Polsby-Popper) and normalized L_epci per D16. Weights come from config.
- **Search:** simulated annealing over ReCom moves at the hard tolerance (±20%). Geometric cooling from 0.02 to 0.0005. Only valid plans can be returned.
- **Start:** the first valid plan returned by the sampler; per D67/D68 this is the official plan when it qualifies, otherwise the first valid sampled plan. The optimized plan is compared with the candidates recorded for that department.
- **Limit:** the weights are a judgment. The objective is a search preference, not a legal or neutrality score. Compare plans only under the same documented metric version and config.

## Open items

| # | Item | Owner | Blocks |
|---|---|---|---|
| O1 | Verify L.125 and annexed table: communes under 5,000 kept whole; rules for splitting large communes | Legal | D4 |
| O2 | Verify 20% case-law (2008-573 DC, 2010-602 DC) and what justifies exceptions | Legal | D5 |
| O3 | Legal basis of any 400-seat scenario | Legal | D3, D8 |
| O4 | **Superseded by D34/O7:** official INSEE 2022 simplified reference source recorded; exact geometry/membership remains open under O7/O10 | — | Exact diff layer |
| O5 | Bloc mapping: draft provided in [blocs.draft.yaml](blocs.draft.yaml) with placeholder nuance labels. Replace with official codes and have the team review both mappings | Team + data | Audit |
| O6 | Resolved: no polling-station splitting (D4-r) | — | — |
| O7 | **Partially resolved by D34:** official INSEE 2022 simplified reference map acquired; exact membership/diff still needs detailed geometry or an authoritative crosswalk | Data | Layer 1, D11 |
| O8 | Confirm IRIS census population is allowed under assumption 3; 2022 counts on COG 2024 are used only as within-parent weights scaled to 2021 legal totals (D39) | Legal | D4-r case 2 |
| O9 | Primary L.162 text confirms the threshold and ordinary fallback; qualified review remains open for candidacy/withdrawal application and D33's inclusive tied-cutoff interpretation | Legal | D11 |
| O10 | Identify which communes are currently split across constituencies | Data | D4-r case 3 |
| O11 | **Resolved by D31:** use INSEE's latest official commune population for Mayotte (2017 vintage; explicit exception to 2021 elsewhere) | — | Gate 1 review of 976 contiguity |
| O12 | **Resolved by D28:** map INSEE 2021 commune-déléguée components (335 / 254 / 289) to COG 2024 units 60054 / 60694 | — | — |
| O13 (policy decided: D4-r/D17) | IRIS units are used under the documented D4-r/D17 rules. Confirm legal scope and population basis under O8; physical feasibility is still evaluated separately at Gate 1. | Legal | Gate 1 |
| O14 (policy superseded: D23) | Enclaves remain explicit attachment candidates; decide case-by-case legal treatment and source-backed approval. The centroid-nearest edge alone does not certify continuity. | Legal + decision | Gate 1 |
| O15 (policy superseded: D23) | Build and source-review bridge/ferry/continuity links for islands and estuaries. Distance-only candidates do not certify continuity. | Data + legal review | Gate 1 |
| O16 | **Data issue resolved by D39:** prior IRIS source omitted code 93059, which is Pierrefitte-sur-Seine (not La Courneuve; La Courneuve is 93027). The 2022-on-COG-2024 source contains all nine IRIS; its counts are weights only and are scaled to the 2021 legal total. O8 legal review remains open. | — | Rebuild and verify IRIS split inputs |

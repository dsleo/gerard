# 03 — Neutrality Metrics for France

Scope: Module 3 only (post-generation audit). Electoral data is read only from `data/quarantine/electoral/` by `src/redistrict/audit/`. This document supersedes the earlier specification where it called modelled results observed outcomes or called the current ReCom samples a neutral ensemble. Decisions D20–D22 in [01_decisions.md](01_decisions.md) govern auditability and interpretation.

---

## 1. Why the standard metrics need adapting

The usual redistricting metrics (efficiency gap, mean-median difference, partisan bias) were designed for US-style systems: two main parties, one round, plurality winner. France differs in four ways that change the numbers:

| French feature | Effect on a naive metric |
|---|---|
| **Multi-party first round** (typically 4–6 significant blocs) | "Wasted votes" and "majority" are undefined without choosing a pair. |
| **Two-round system** | The winner is decided in round 2 among qualified candidates, not in round 1. Round-1 results alone misstate who wins. |
| **Qualification threshold: 12.5% of *registered voters*** (not votes cast) | A candidate can be ineligible for round 2 despite a large share of votes. The candidacy threshold and fallback are in Code électoral L.162, not L.126. |
| **Turnout varies strongly by district** | Vote-share metrics that use votes cast can flip with turnout. Registered voters give a stable denominator for threshold tests. |

Conclusion: a French audit must use registered voters for qualification and must distinguish observed historical outcomes from modelled outcomes on proposed maps. A generic per-bloc-pair treatment is not automatically valid for a multi-candidate system.

---

## 2. Inputs (quarantine only)

| Dataset | Use |
|---|---|
| Legislative elections, round 1, 2024, official commune and polling-station extracts | Primary vote input, only at exact available geography; registered voters for L.162 eligibility come from this round |
| Legislative elections, round 2, 2024, official commune and polling-station extracts | Historical outcome/candidate validation after exact aggregation to the existing constituencies; never redistributed as observed votes to proposed districts. Constituencies filled in round 1 are absent from round-2 totals |
| Presidential round 1, 2022, candidate-level commune results | Separate first-round robustness analysis; not a legislative second-round outcome |
| Registered voters at the same or finer geographic unit as the vote input | Qualification threshold, denominators |
| Bloc mapping (`config/blocs.yaml`) | Party → bloc. Political judgment, see §5. |

Aggregation: sum exact small-area results into generated districts. The Ministry commune extracts aggregate Paris, Lyon, and Marseille as whole communes; they do not provide the 45 municipal arrondissement rows needed by this project. Polling-station extracts are available, but an authoritative crosswalk to the project's arrondissement/IRIS units is still needed. A population-grid crosswalk is an estimate, not exact voter geography. Constituency totals cannot be reallocated to new districts. If a generated district contains only part of a commune/arrondissement and exact vote plus registered-voter counts are unavailable for the split unit, mark it **NOT AUDITABLE** in the primary audit. Any population-weighted allocation is a separately labelled sensitivity analysis and cannot support a PASS. Report auditable coverage by districts and population/votes; if coverage is incomplete, do not issue a national PASS/FAIL conclusion.

The four official Ministry extracts are stored in quarantine and checksummed in `data/quarantine/electoral/SHA256SUMS`. Commune-level and aggregated polling-station totals match exactly for all six turnout/count fields in every commune for each round; this verifies the raw extraction and aggregation consistency only.

---

## 3. Second-round simulation

For each district `D` and election `e`:

1. **Eligibility set:** candidates with votes ≥ 12.5% of registered voters may stand, under Code électoral L.162. If exactly one meets the threshold, the next-highest candidate may also stand; if none meet it, the top two may stand. Candidates tied at the fallback cutoff are all included in the possible eligibility set (D33), pending legal confirmation under O9. Eligibility does not force a candidate to file or remain after withdrawals.
2. **Historical validation:** on the 2024 constituency map, check that the observed round-two candidates were legally eligible under L.162 (including fallback). Then evaluate a no-transfer baseline conditional on the actual candidates who stood: predict the winner as the highest first-round vote-getter among that observed slate. Report eligibility violations, candidate-identity coverage, winner and winner-bloc match rates, and results by number of candidates/withdrawals. Do not score legal eligibility as a prediction of filing/withdrawal or report a finalist-set match rate.
3. **Proposed-map scenarios:** any second-round winner on a proposed map is a model output. Candidate choice, withdrawals, transfers and turnout may change with district boundaries. Run named scenarios (including a transparent no-transfer baseline and any calibrated transfer scenarios); report disagreement/sensitivity rather than a single factual forecast.
4. Never describe `leader_wins` as a floor unless a formal bound is established. It is a simple baseline assumption, not a guaranteed lower or upper bound on any bloc's seats.

All scenario outputs are labelled as estimates. Disagreement between them is itself a result. The 2024 check found no L.162 eligibility violations and 0 unmatched identities, but the no-transfer winner baseline matched only 65.2% overall (59.2% in 409 two-candidate runoffs; 92.1% in 89 three-candidate runoffs). Do not present that baseline as a validated forecast; keep it as a named sensitivity scenario. Detailed results are in `data/quarantine/electoral/derived/round2_validation_2024.md`.

---

## 4. Metrics

Metrics are calculated only when their definitions match the data. Report each metric's coverage and whether inputs are observed or modelled.

### M1 — Efficiency gap (restricted two-candidate diagnostic), `EG_AB`

```
W_A = Σ_D wasted votes for A in D
W_B = Σ_D wasted votes for B in D
EG_AB = (W_A − W_B) / Σ_D total votes in D
```

This definition applies only to a two-candidate contest with known or explicitly modelled candidate votes. Do not extend it to a multi-candidate runoff by counting every non-winning candidate as a loser in a pairwise bloc comparison. For any pairwise report, include only districts where those two blocs are the actual finalists and report the fraction of districts and votes covered. Treat it as a diagnostic with that selection limitation, not a complete multi-party neutrality measure.

- Reported: `EG` for every pair, and `max |EG|` over pairs with the pair name.
- Reason for round-2 basis: the seat is decided in round 2, so waste must be counted there.

### M2 — Mean-median difference, `MMD_AB`

```
MMD_AB = mean_D(share_A(D)) − median_D(share_A(D))
```

Share is the round-1 vote share among votes cast, for bloc A, across districts of `d`. Reported for every bloc.
- Reason: robust to one or two extreme districts; it still works with several blocs because each bloc is compared to its own median.

### Deferred for later — Seat–vote response scenarios (formerly M3)

This scenario metric is removed from the current v1 scorecard because there is no approved candidate, turnout, withdrawal, or voter-transfer scenario. Reintroduce it only after those assumptions are specified and reviewed. If resumed, report seat share across the swing range and the baseline vote share; interpolate a 50% vote point only when the simulated curve brackets it, and state the interpolation method and uncertainty. Do not present the result as a causal prediction.

### M4 — Seat share vs vote share (proportionality gap), `PG_A`

`PG_A = seat_share_A − vote_share_A`. State which vote share is used (round one or modelled round two); do not mix a round-two winner seat count with an unrelated first-round vote denominator. Report both versions separately if both are useful.

Computed per bloc on the round-2 outcome. This is the most intuitive number for a non-specialist and is included for that reason.

### M5 — Shut-out count, `SO_A`

Number of districts where bloc `A` has ≥ 20% of round-one votes but no candidate mapped to `A` is eligible under L.162. A bloc is not itself a legal candidate; candidate qualification must be evaluated before aggregation to blocs. Report coverage and whether district vote totals are exact or estimated.

- Reason: France-specific. It catches a plan that technically treats blocs evenly but removes a bloc from the second round in many places.

---

## 5. Bloc mapping and robustness

- **Mapping:** `config/blocs.yaml` maps each Ministry nuance to a bloc (draft: [blocs.draft.yaml](blocs.draft.yaml); the nuance codes are still unverified, see [05_legal_notes.md](05_legal_notes.md) L4). Mapping is a political judgment, so it is:
  - published in the repo,
  - versioned,
  - run against **at least two mappings** (a "coarse" and a "fine" version) in every audit.
- **Elections:** the 2024 legislative round 1 is primary. The 2022 presidential round 1 is a robustness check. Results are reported per election, not pooled.
- **Reporting rule:** no PASS/FAIL from ensemble percentiles until the sampler has a documented target distribution, a valid transition kernel, adequate multi-chain diagnostics, effective sample size and stability criteria set in advance. Until then, show exploratory comparisons only and call the outputs an **exploratory candidate set** (D22). A plan's position within one heuristic sample is not evidence of neutrality.

---

## 6. Reference-plan comparison

- The current sampler yields exploratory candidate plans under its stated proposal and population constraints. It does not establish that all legal plans are sampled uniformly or that a stationary distribution has been reached.
- Until D22's diagnostics are met, compare distributions descriptively only; do not use percentiles, 5th–95th interval status, PASS/FAIL, or multiple-comparison counts as inferential evidence.
- After a sampling design is validated, publish its target distribution, transition details, constraints, initialization, burn-in/thinning, number of chains, acceptance/transition-failure rates, effective sample size and convergence/stability results alongside any percentile.

---

## 7. Report contents (`neutrality_report.md`)

1. Election, mapping, and round-2 model used.
2. Table: metric value, input status (observed/modelled/estimated), geographic coverage, and descriptive candidate-plan range when diagnostics do not support inference.
3. Not-auditable districts, with reason.
4. Mapping-sensitivity flags.
5. The disclaimer: the audit is conditional on its election data, geography, bloc mapping, and scenario assumptions. It does not prove the map is fair in any other sense and does not replace legal review.

Current status artifact: [`data/quarantine/electoral/derived/neutrality_report.md`](../../redistricting/data/quarantine/electoral/derived/neutrality_report.md). It reports M1, M2, M4, and M5 on the observed official-map baseline; exact proposed-map results remain unavailable pending voter geography and validation. The seat–vote response scenario formerly called M3 is deferred.

---

## 8. Limits to state plainly

- Proposed-map round-two outcomes are estimates; historical second-round outcomes cannot be transferred as if they were observed under new boundaries.
- Bloc mapping can change conclusions. The sensitivity check is the defence, not a single "correct" mapping.
- Ecological inference: commune- and polling-station-level results are aggregated; individual voting is not inferred.
- An audit comparison is evidence only relative to the stated model and validated reference distribution; it is not a legal finding.

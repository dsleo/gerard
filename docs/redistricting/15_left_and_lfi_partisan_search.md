# Broad-left and LFI-attached first-round searches

## Results

Using the same 289-district first-round target as the RN experiment, the broader left bloc leads in **179 of 577 official 2024 districts** under the project's pooled-bloc proxy. Across 81 departments with usable search starts and sufficiently covered vote data, the best independently rechecked candidates add 51 leads, reaching **230 districts** by replacing maps in 33 departments. The target was not reached in this candidate pool; these results do not establish that reaching it is impossible.

A second, narrower experiment treats votes for candidates financially attached to La France insoumise (LFI) as the target, compares them to other pooled blocs, and removes those candidates' votes from the other left votes. That reference is **58 leading districts**; the best candidates in 67 tested departments add 11, reaching **69 districts** by replacing 7 departments. Financial attachment is not a verified statement of membership, endorsement, or ideology. More importantly, many constituencies had a different New Popular Front candidate in 2024: their votes are not treated as latent LFI votes. This model cannot forecast how those voters or candidate slates would behave under new boundaries.

Both comparisons use the official 2024 map as reference and preserve each department's official district count. The first broad-left scan used seeds 1801–1803, 500 proposals for each of annealing/ReCom and greedy flips, retaining the better map per seed; an additional twelve-department scan used seeds 2001–2003 and 2,000 proposals per method. The LFI-attached scan used seeds 1901–1903 and the same 500-proposal budget, followed by 2,000 proposals for seven departments with seeds 2101–2103. Best-found results select a single best candidate from all runs for each department. The best minimum across selected batches gives 221 for the broad-left and 66 for the LFI-attached target. These minima are selected after seeing the batches, mostly from three seeds and one starting map per department: they are not estimates of the chance of a national result.

The broad-left best gains include Yvelines (78) +6, Seine-et-Marne (77) +5, Essonne (91) +4, and Hérault (34) and Seine-Maritime (76) +3 each. The detailed [broad-left scenario](15_broad_left_scenario.json) and [LFI-attached scenario](15_lfi_attachment_scenario.json) record all selected assignments, source batches, seed gains, and validation. The displayed candidate pools are incomplete, so no minimum number of departments for 289 can be established.

## Distinguishing LFI from the left union

The Ministry's 2024 `FI` nuance appears on only three candidates; most Nouveau Front populaire candidates carry `UG`, a union-of-the-left nuance encompassing several parties. Consequently, treating `FI` as the complete set of LFI candidates would be misleading. The narrow comparison uses the separately published [candidate financial-attachment dataset](https://www.data.gouv.fr/datasets/rattachement-des-candidats-aux-elections-legislatives), supplied from Ministry records following an access request, which names **229 candidates attached to LFI**. It is a financial designation and not a party-membership database.

The loader normalizes name and department, checks for unique matches, and compares each candidate's constituency-level vote total to the official 2024 result. All **4,009 candidates** match one-to-one and their totals agree; overseas code aliases are handled explicitly. It fails closed on mismatches. Of the 229 LFI-attached candidates, 225 have nuance UG, three FI, and one DVG. The source xlsx has SHA-256 `79d305854d804d62b99794208ce34399bcfdc040477160c325eb810f3054cca0`.

The broad-left target pools the repository's coarse mapping: EXG, COM, FI, SOC, RDG, VEC, UG, DVG and ECO. It therefore includes parties and candidates outside LFI. The previous RN experiment targeted an RN candidate nuance, not the whole far-right bloc; the numerical results are not a symmetric comparison of equally defined political groups or equally exhaustive searches.

## Round two and limitations

The existing atlas second-round heuristic was applied **after** map search. For the 33 departments in the broad-left scenario, it projects **80 left-bloc wins on the candidate maps, versus 66 on the official-map inputs**. For the seven departments in the LFI-attached scenario, it projects **25 left-bloc wins versus 21**. These are left-bloc projections, not projected LFI seats, and only cover the departments changed in each scenario. They use hypothetical top-two-bloc duels, not actual candidates, qualification, withdrawals, individual vote transfers, or campaign responses. Official-map model predictions use historical outcomes included in training; the difference is illustrative rather than an out-of-sample evaluation. See [the runoff methodology](07_tour2_estimation.md).

Every retained department plan was independently checked for full assignment, exact district count, graph contiguity, and ±20% population relative to the department's target. This does not certify legal compliance, compactness, or unchanged departments. Whole-commune results use exact commune totals. Split communes use the bureau-to-IRIS/arrondissement crosswalk with at least 95% registered-voter coverage per relevant source commune. Missing registered voters are conservatively allowed to favor an opposing bloc in any district intersecting their source commune. Geographic allocation by population weights is itself an estimate, and the bounds do not cover model error in those weights. Coverage, selected assignments and deviations are recorded in the scenario files.

## Reproduction

The campaign reports are in [the archived search runs](15_left_campaign_runs.tar.gz). Raw electoral data remains quarantined and is not included in the archive. The financial-attachment workbook is available at the dataset page above and should be saved as `redistricting/data/quarantine/electoral/rattachement-candidats-leg-2024.xlsx`; verify its SHA-256 before use. With the repository's local data and Python environment, after extracting the archive to `/tmp/gerard-left-runs/` and from `redistricting/`:

```sh
.venv/bin/python scripts/summarize_partisan_campaign.py --bloc left /tmp/gerard-left-runs/gerard-left-national.json /tmp/gerard-left-runs/gerard-left-deeper.json --output /tmp/reproduced-left.json
.venv/bin/python scripts/summarize_partisan_campaign.py --lfi-attachment /tmp/gerard-left-runs/gerard-lfi-national.json /tmp/gerard-left-runs/gerard-lfi-deeper.json --output /tmp/reproduced-lfi.json
.venv/bin/python -m pytest tests/test_partisan_search.py tests/test_recom.py tests/test_constraints.py -q
```

The experiment is separate from the vote-blind pipeline and does not alter the published atlas.

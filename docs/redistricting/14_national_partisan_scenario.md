# Expanded first-round partisan search

## Result

Using the 2024 RN candidate nuance as the target, the saved candidates contain a hybrid scenario with **289 RN-leading districts out of 577** under the project's first-round proxy. The official-map reference has 246; the selected replacements add at least 43. This uses 30 changed departments, containing 150 districts, and leaves the other departments on their official 2024 maps. The selected assignments and independent revalidation are in [the scenario data](14_national_partisan_scenario.json).

Among the 78 departments for which the campaign found and evaluated a starting map, 30 is the fewest departments needed using the **best individual candidates actually found**: sort each department's best verified positive gain in descending order and take enough to reach 43. This is an exact selection for that finite pool and equal department cost. It does not establish a global minimum, and it does not establish that searches almost always find those gains. Some departments were never searched; a higher-scoring unseen map could reduce the number.

This is a first-round comparison between RN's nuance and pooled opposing blocs. It is not a prediction of first-round candidate slates, elected deputies, or a second-round majority. The model assumes 2024 first-round votes can be reassigned to new boundaries; political behavior and candidacies can change.

The earlier report counted 246 RN-leading districts in a 559-district snapshot and left 18 unknown. The original Ministry constituency file covers all 577, and the 18 omitted districts contribute zero additional RN leads under the same proxy. Thus 246 is now the measured full-reference value.

## Search and repeatability

The wider search regenerated vote-blind starting partitions using each department's *official* district count. An exact INSEE official seed, an independently validated and repaired official-boundary overlay, or the existing sampler supplied the start. Searches use annealing with ReCom and greedy border-unit flips. Every selected assignment was independently checked for complete partition, exact district count, certification-graph contiguity and ±20% population balance relative to its departmental average. The maximum observed deviation among the selected maps is about 19.99%. These checks are not a legal certification and do not assess compactness, municipal integrity beyond the chosen atomic units, or all other legal criteria. The unchanged official departments are not certified under the project's constraints, so the hybrid is not a fully validated national plan.

The result combines the single best found candidate for each selected department. The scenario data includes all tested seed gains for each selected department; in nine of the 30, the selected gain was not achieved in every seed of its source batch. A few independent seeds are evidence of search repeatability only; selecting the best across batches also creates selection bias. A separate selection using the minimum result within each chosen batch reaches 289 with 34 departments. The batch was chosen after observing its results, usually contains only three seeds, and shares one starting map. This is useful evidence for further testing, but the experiment has **not** demonstrated that the 289 outcome is achieved almost always.

## Data and second round

Most tested model units are entire communes, using exact 2024 commune-level vote totals. For subdivided communes, the separate crosswalk experiment distributes observed polling-station votes over IRIS or arrondissement units using population weights, with at least 95% registered-voter coverage in each affected source commune. The selected scenario's lowest such coverage is about 96.6%. The summary independently recalculates votes, validates each assignment, and counts a target lead only if its margin exceeds all unmatched registered voters who could be attributed to that district under the source-commune model. Unmatched extra commune records are conservatively allowed to affect every district in the relevant department. These bounds address missing records, not errors in the population-weighted allocation; those allocations remain estimates.

The existing atlas runoff heuristic is applied separately, after the first-round optimization. In the 30 changed departments it projects **30 far-right-bloc wins on the selected candidates versus 26 under the official-map inputs**. RN is pooled back into the wider far-right bloc for that model, so these are not projected RN seats. This is a hypothetical top-two-bloc duel model; it does not simulate real qualification, candidate withdrawals, or individual transfers. Official-map predictions use historical outcomes also included in model training, so the comparison is illustrative rather than out-of-sample. Missing-vote sensitivity is not propagated into this runoff estimate.

## Reproduction and artifacts

[The selected maps and trial summaries](14_national_partisan_scenario.json) contain each changed department's unit assignment, seed, source batch, verified vote count, graph/population check and second-round bloc projection. Source batches and their SHA-256 hashes are recorded there. The source campaign reports are preserved in `14_national_campaign_runs.tar.gz`. The script [experiment_partisan_campaign.py](../../redistricting/scripts/experiment_partisan_campaign.py) creates batches; [summarize_partisan_campaign.py](../../redistricting/scripts/summarize_partisan_campaign.py) independently reaggregates and validates them before combining maps. Raw electoral inputs remain quarantined and are used only by this separate experiment; the vote-blind pipeline and published atlas are unchanged.

After extracting the archive into `/tmp/gerard-campaign-runs/`, and with the project's local data and `.venv` installed:

```sh
.venv/bin/python scripts/summarize_partisan_campaign.py /tmp/gerard-campaign-runs/*.json --output /tmp/reproduced-scenario.json
.venv/bin/python -m pytest tests/test_partisan_search.py tests/test_recom.py tests/test_constraints.py -q
```

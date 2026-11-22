# Exploratory partisan search: three methods

This is a separate, explicitly vote-aware experiment. It does not modify or certify the vote-blind national pipeline or its published map. RN is an illustrative target, not an endorsement. The target is the Ministry's 2024 `RN` candidate nuance; it is compared with aggregate opposing blocs. Those blocs are political groupings, not individual candidates or parties.

## Experiment

We used first-round 2024 commune vote totals for Ain (01), Allier (03), and Manche (50). Every model unit in these departments is a whole commune and every unit matched the election data exactly by code; no votes were split spatially. When a commune has multiple electoral rows, their votes are summed. Results use the repository's draft coarse nuance-to-bloc mapping, except that RN votes are separated from the far-right bloc. All other nuances within each bloc are pooled. The pre-existing fine mapping was evaluated on the selected maps as a sensitivity check, without optimizing for it.

The baseline is the first plan in each department's existing sampler file that passes the independent assignment, adjacency, district-count and population checks. It is not the official map. The target population is the department's population divided by its allocated district count. The hard population tolerance is ±20% of that departmental target. Contiguity uses the repository's certification graph; its links and the tolerance are model assumptions, not a legal determination. No compactness or community-split restrictions were imposed. Search does not change departmental seat allocations.

Each run starts from the same map in its department and makes 1,500 proposal attempts, with independent random seeds 101, 202, and 303. The objective first maximizes the number of districts where RN has more first-round votes than any *pooled opposing bloc* (alphabetical tie break), then uses a smooth margin score to distinguish maps with the same count. This is an optimization proxy, **not an estimated number of elected deputies or a forecast**.

- **Annealing + ReCom:** repeatedly merge and repartition adjacent districts; accept some worse moves according to a cooling schedule.
- **Greedy boundary flips:** propose moving one border commune into a neighboring district, reject invalid moves, and accept only moves that do not reduce the objective.
- **Random ReCom bursts:** run 30-step random walks, retain the best map encountered, and restart each burst from that best map. These are directed bursts, not an unbiased ensemble.

ReCom is used by two methods, but their acceptance and exploration strategies differ. Proposal counts are matched, not wall-clock time; a flip proposal is much smaller than a ReCom proposal, and invalid flips count against its budget. All retained maps were checked independently for partition, graph contiguity, population tolerance, and exact district count. The searches are heuristics: none establishes a global optimum or a representative distribution of maps.

## Results

Each cell lists the three seed results as the number of RN-leading districts under the coarse mapping. The baseline and results use the same electoral proxy, geographic units, district counts and constraints.

| Department | Districts | Baseline | Annealing + ReCom | Greedy flips | Random ReCom bursts |
|---|---:|---:|---|---|---|
| Ain (01) | 5 | 3 | 4, 4, 4 | 4, 4, 4 | 4, 4, 4 |
| Allier (03) | 3 | 2 | 3, 3, 3 | 3, 3, 3 | 3, 3, 3 |
| Manche (50) | 4 | 0 | 2, 2, 2 | 2, 2, 2 | 1, 1, 2 |

On these same retained maps, the fine mapping gave the same target plurality counts. This is only a sensitivity check of two related bloc definitions, not validation of the election model. Greedy maps frequently approach the ±20% population limit; precise maximum deviations, proposal counts, timings, assignments, source hashes and both mapping scores are in [the results JSON](12_partisan_search_results.json). The selection objective imposes no compactness penalty, so maps may be geographically unattractive despite passing the listed machine checks.

## Limitations and reproduction

French legislative elections have two rounds. This calculation pools first-round candidate votes by nuance, assumes those votes remain fixed under new boundaries, and compares one party nuance with broader blocs. It does not simulate candidate availability, turnout, tactical behavior, qualification, withdrawals, vote transfers, or second-round results. It therefore cannot establish that RN would win these seats. Commune totals also conceal intra-commune variation. The same first-round data are used for both optimization and evaluation, and the three seeds share a single starting map, so these results do not demonstrate generalization to other elections or starting maps.

With the local project data and `.venv` available, from `redistricting/`:

```sh
.venv/bin/python scripts/experiment_partisan_search.py --budget 1500 --seeds 101 202 303 --output /tmp/new-partisan-results.json
.venv/bin/python -m pytest tests/test_partisan_search.py tests/test_recom.py tests/test_constraints.py -q
```

Use `--nuance RN` (the default) to choose an exact 2024 candidate nuance, or `--target far_right` to optimize an entire bloc present in both mappings. The commune-only loader deliberately fails if units are split or if vote and model unit codes do not match; other departments may require a documented small-area crosswalk. Output is never overwritten. Source electoral data remains quarantined, and this script intentionally reads it only for this separate experiment.

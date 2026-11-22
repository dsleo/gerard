# Cross-scoring the partisan scenarios

Conservative first-round plurality counts for all target definitions on each saved map:

| Target | Official | RN scenario | Broad-left scenario | LFI-attached scenario |
|---|---:|---:|---:|---:|
| RN nuance | 246 | 289 | 216 | 239 |
| Broad left bloc | 179 | 156 | 230 | 189 |
| LFI financial attachment | 58 | 50 | 53 | 69 |

These are first-round leads, not second-round seats. Each target is compared with the remaining pooled blocs, so the three rows are different definitions and are not an additive seat allocation. LFI is defined using candidates' 2024 financial attachment, not inferred voter preferences. The conservative bounds handle unmatched registered voters, but do not capture errors in population-weighted polling-station allocation or changes in candidate slates. The selected maps are heuristic discoveries, not proven optimal, and the broad-left and LFI searches had different budgets and available candidates.

Reproduce with the election data installed in the `redistricting` data directory:

```sh
.venv/bin/python scripts/compare_partisan_scenarios.py
```

For a separate checkout with the local data in another directory, pass `--data-root /path/to/redistricting`.

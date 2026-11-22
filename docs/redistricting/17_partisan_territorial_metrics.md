# Partisan-map territorial metrics

The three saved partisan scenarios use the same territorial comparison as the neutral scenario. Population and EPCI calculations retain the official-map audit values for unchanged departments and recalculate the selected departments from their model units. The MMD comparison reaggregates first-round 2024 votes using the existing bureau–IRIS allocation and the coarse bloc mapping. It covers metropolitan constituencies, as does the neutral-map comparison.

Compactness uses mean `1 − Polsby–Popper`, where each district's score is `4π × area / perimeter²`. A higher loss means lower compactness. The calculation reconstructs the official audit's virtual IRIS geometries from the same source layers and computes every district in Lambert-93. It checks the reconstructed official mean against the saved audit to within `1e-8` before combining unchanged official districts with the selected partisan districts. Each hybrid contains 558 departmental districts. The official assignments are an existing geographic heuristic and the scenarios are not certified maps.

| Map | Mean compactness loss |
|---|---:|
| Official reference | 0.802771 |
| RN scenario | 0.812688 |
| Broad-left scenario | 0.813061 |
| LFI-attached scenario | 0.806301 |

The values are estimates; geographic simplifications, official-boundary attribution, and the unit definitions affect the results. See [the existing territorial audit methodology](07_tour2_estimation.md) and [scenario limitations](15_left_and_lfi_partisan_search.md).

With the local input data available, rebuild and independently check the compactness before updating the browser snapshot:

```sh
.venv/bin/python scripts/compute_partisan_compactness.py --data-root . --output /tmp/partisan-compactness.json
.venv/bin/python scripts/augment_partisan_metrics.py --data-root . --compactness /tmp/partisan-compactness.json
```

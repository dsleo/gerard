# Additional partisan scenarios

These scenarios extend the 2024 first-round search to the remaining coarse electoral groups used in the atlas. Each search screened the same 21 departments (01, 03, 14, 16, 19, 26, 27, 37, 40, 43, 45, 50, 60, 63, 64, 68, 73, 79, 81, 87 and 89), with three seeds, 300 attempts per method and two search methods. The candidate assignments are independently validated and scored with the same conservative treatment of unallocated votes as the existing partisan campaigns. The search stops selecting replacements when the 289-district target is reached; otherwise it retains all verified positive-gain replacements found. Unchanged departments retain the official map.

| Target | Official first-round leads | Conservative scenario leads | Departments changed |
|---|---:|---:|---:|
| Centre | 67 | 73 | 5 |
| Right | 34 | 35 | 1 |
| National right | 288 | 291 | 1 |
| Other | 9 | 9 | 0 |

The national-right group aggregates RN with other nuances in that coarse bloc, and is therefore distinct from the RN-only scenario. “Other” combines heterogeneous residual electoral categories; it is not a single party or political alliance. The search found no positive gain for this group, so its map remains the official reference. These are bounded results from a small, deliberately selected sample, not national optima or probabilities of success. Results are based on 2024 votes; the second-round hemicycle uses the atlas's existing model and its assumptions, not observed outcomes of the redrawn election.

The selected plans and their audit summaries are in `18_<bloc>_scenario.json`. The compressed `18_remaining_bloc_runs.tar.gz` contains the underlying campaign reports; each summary records their SHA-256 hashes. The browser displays the same all-bloc second-round estimates, first-round representation measures and territorial comparisons as the other partisan scenarios. Compactness follows the reconstruction documented in [the territorial metrics notes](17_partisan_territorial_metrics.md).

# Department screening for a first-round majority

This exploratory, vote-aware experiment asks how many departments would need new constituency maps for a target 2024 candidate nuance to lead in 289 of the 577 Assembly districts on the first-round proxy. It uses RN as the example; the script accepts another `--nuance`. A first-round lead is not a seat won. Opposing candidates are pooled into the existing coarse blocs, while RN is separated from its bloc; this is an asymmetric, draft-grouping-dependent proxy, not a candidate-level election simulation.

## Result and coverage

The available official-map snapshot covers 559 districts, of which RN leads in **246** under this proxy. The remaining 18 districts are unobserved, not assumed to have an actual zero RN count. Out of 101 departments, the screen tested 30; it excluded 52 with a different seat allocation in the existing sampler, 9 with split-commune units, 9 without a valid saved starting plan, and 1 with unmatched commune codes. Exclusion means **unknown**, not impossible to flip.

An initial screen used seeds 101, 202, 303, with 500 proposals each for annealing/ReCom and greedy flips, taking the better map in each paired run. Twelve departments improved on their official baseline in all three runs. Ten fresh follow-up seeds, 401–410, each repeated the same two-method 500-proposal search on these 12. Every follow-up seed again improved in each department. This is a search repeatability measure with one common starting map per department, not a probability of an electoral outcome or a statistical guarantee that other starts succeed.

Across these 12 departments, summing each department's **smallest gain among the ten follow-up runs** adds 15 first-round leads to the 246 observed in the official reference, for **261 observed leads**. Even adding all 18 unobserved districts hypothetically would yield 279. This does not prove a national majority is impossible: it leaves most departments unsearched and uses a limited heuristic budget. It establishes that this screen did not find a 289-district solution or the requested national minimum.

| Department | Districts | Official first-round RN leads | Follow-up RN leads (10 runs) | Minimum gain | Official bloc runoff projection | Candidate bloc runoff projection |
|---|---:|---:|---:|---:|---:|---:|
| 01 Ain | 5 | 3 | 4–5 | +1 | 3 | 3 |
| 03 Allier | 3 | 2 | 3 | +1 | 1 | 1 |
| 16 Charente | 3 | 1 | 2 | +1 | 0 | 0 |
| 26 Drôme | 4 | 2 | 3 | +1 | 2 | 2 |
| 40 Landes | 3 | 2 | 3 | +1 | 0 | 0 |
| 43 Haute-Loire | 2 | 0 | 1 | +1 | 0 | 0 |
| 45 Loiret | 6 | 4 | 5 | +1 | 2 | 2 |
| 50 Manche | 4 | 0 | 1–2 | +1 | 0 | 0 |
| 63 Puy-de-Dôme | 5 | 1 | 3 | +2 | 0 | 0 |
| 73 Savoie | 4 | 0 | 2 | +2 | 0 | 0 |
| 87 Haute-Vienne | 3 | 0 | 2 | +2 | 0 | 0 |
| 89 Yonne | 3 | 2 | 3 | +1 | 2 | 3 |

The runoff columns use the **existing atlas model**, applied after first-round optimization. It combines RN back into the far-right bloc, chooses the top two blocs as a hypothetical duel, and estimates its result from similar observed 2024 duels or a no-transfer fallback. Thus the runoff column describes a broader bloc, not an RN candidate. The candidate column uses only the first follow-up run (seed 401), not a ten-run range. Predictions on the official map include data used to train the model, so their comparison is illustrative and not an out-of-sample accuracy test. Model assumptions and limitations are in [the runoff methodology](07_tour2_estimation.md).

## Selection and validity

Departments in this campaign are independent and keep their official 2024 district counts; this avoids silently changing the size of the Assembly when replacing a department. The existing sampled map uses a separate allocation, so differing departments are excluded until compatible starts can be generated. For a specified target, `minimum_departments` sorts independently measured positive departmental gains from largest to smallest. With equal department costs and additive, independently available gains, this gives the fewest **among the tested candidates and the measured minimum-across-runs gains**. If their sum falls short, no such minimum is reported. That is not a proof of a global geographic optimum.

All retained plans pass partition completeness, exact district count, certification-graph contiguity, and ±20% population deviation relative to the departmental target. No compactness, municipal/community integrity beyond the atomic units, or full legal constraints were imposed. The starting plan is a previously saved sampler map, while the baseline is the official 2024 map; both use commune vote totals, but candidate maps can change which candidates would have run. Split-commune departments require the separate bureau–IRIS vote allocation workflow, not guessed intra-commune votes. No out-of-sample election or model robustness assessment is implied.

The [initial detailed results](13_partisan_campaign_full.json) and [follow-up results](13_partisan_campaign_followup.json) contain source hashes, per-seed maps and diagnostics. From `redistricting/`, with local raw data and `.venv` installed:

```sh
.venv/bin/python scripts/experiment_partisan_campaign.py --nuance RN --budget 500 --seeds 101 202 303 --workers 4 --output /tmp/campaign-initial.json
.venv/bin/python scripts/experiment_partisan_campaign.py --nuance RN --departments 01 03 16 26 40 43 45 50 63 73 87 89 --budget 500 --seeds 401 402 403 404 405 406 407 408 409 410 --workers 4 --output /tmp/campaign-followup.json
```

The experiment uses quarantined electoral inputs intentionally and does not modify the vote-blind pipeline or publish a map.

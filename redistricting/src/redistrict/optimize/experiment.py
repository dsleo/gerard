"""Experimental objectives and search, separate from the production optimizer.

No I/O or electoral inputs. The v2 score is a hypothesis, not a replacement
policy. Keep its components so alternative preferences can be evaluated later.
"""
from __future__ import annotations

import math
import random
import time
from collections import defaultdict

from redistrict.metrics.population import _valid_epci
from redistrict.optimize.sa import Scorer, assignment_fingerprint
from redistrict.sample.recom import plan_population, recom_step


class ExperimentScorer:
    def __init__(self, base: Scorer, pops: dict, epci: dict, local_target: float,
                 national_target: float, tolerance: float = .20):
        self.base, self.pops, self.epci = base, pops, epci
        self.local_target, self.national_target = local_target, national_target
        self.tolerance = tolerance

    def components(self, plan: dict) -> dict:
        old = self.base.components(plan)
        dp = plan_population(plan, self.pops)
        members, epci_parts = defaultdict(set), defaultdict(lambda: defaultdict(int))
        missing_population = 0
        for u, d in plan.items():
            members[d].add(u)
            e = _valid_epci(self.epci.get(u))
            if e is None:
                missing_population += self.pops[u]
            else:
                epci_parts[e][d] += self.pops[u]
        pp = sorted(self.base._pp(frozenset(m)) for m in members.values())
        mse = sum((p / self.national_target - 1) ** 2 for p in dp.values()) / len(dp)
        # A district contains at most cap residents. At least P_EPCI - cap
        # residents of an oversized EPCI must lie outside its largest piece.
        # This is only a population-cap lower bound, not a geographic optimum.
        cap = (1 + self.tolerance) * self.local_target
        epci_pop = sum(sum(parts.values()) for parts in epci_parts.values())
        outside = sum(sum(parts.values()) - max(parts.values()) for parts in epci_parts.values())
        unavoidable = sum(max(0., sum(parts.values()) - cap) for parts in epci_parts.values())
        avoidable = outside - unavoidable
        if avoidable < -1e-7:
            raise ValueError("population-cap EPCI bound violated; input plan may be invalid")
        fraction = max(0., avoidable) / epci_pop if epci_pop else 0.
        rms = math.sqrt(mse)
        out = dict(old, L_v1=old['L'], pop_national_mse=mse, pop_national_rms=rms,
                   pop_national_max=max(abs(p / self.national_target - 1) for p in dp.values()),
                   pp_min=pp[0], pp_worst_quintile_mean=sum(pp[:max(1, math.ceil(len(pp)/5))]) / max(1, math.ceil(len(pp)/5)),
                   epci_outside_largest_population=outside,
                   epci_population_cap_lower_bound=unavoidable,
                   epci_avoidable_population_fraction=fraction,
                   epci_covered_population=epci_pop, epci_missing_population=missing_population,
                   district_count=len(dp))
        out['L_v2'] = .5 * rms + .3 * old['l_comp'] + .2 * fraction
        return out


def vector(metrics: dict) -> tuple[float, float, float]:
    return (metrics['pop_national_mse'], metrics['l_comp'], metrics['epci_avoidable_population_fraction'])


def dominates(a: tuple, b: tuple, epsilon: float = 1e-12) -> bool:
    return all(x <= y + epsilon for x, y in zip(a, b)) and any(x < y - epsilon for x, y in zip(a, b))


def pareto_indices(rows: list[dict]) -> list[int]:
    front: list[int] = []
    for i, row in enumerate(rows):
        v = vector(row)
        if any(dominates(vector(rows[j]), v) for j in front):
            continue
        front = [j for j in front if not dominates(v, vector(rows[j]))]
        front.append(i)
    return front


def search(starts: list[dict], adjacency: dict, pops: dict, scorer: ExperimentScorer,
           target: float, seed: int, method: str, objective: str = 'L_v1',
           proposals: int = 800, burst_length: int = 10, tolerance: float = .20) -> dict:
    """Equal-proposal-budget experiment; elapsed time is reported, not matched.

    sa_single matches production cooling but disables plateau stopping to match
    proposal budgets. sa_multistart divides that same budget among all starts.
    pareto_bursts explores all three v2 criteria, choosing restart points from
    its observed non-dominated archive. It does not certify a global frontier.
    Every proposed state is retained for analysis, including rejected states.
    """
    if not starts or proposals < 1 or burst_length < 1:
        raise ValueError('nonempty valid starts and positive budgets required')
    if method not in {'sa_single', 'sa_multistart', 'pareto_bursts'}:
        raise ValueError(method)
    if objective not in {'L_v1', 'L_v2'}:
        raise ValueError(objective)
    rng = random.Random(seed)
    plans, metrics, lookup = [], [], {}

    def keep(p):
        h = assignment_fingerprint(p)
        if h not in lookup:
            lookup[h] = len(plans)
            plans.append(dict(p)); metrics.append(scorer.components(p))
        return lookup[h]

    begun = time.perf_counter()
    for p in starts:
        keep(p)
    current = keep(starts[0])
    best = min(range(len(plans)), key=lambda j: metrics[j][objective])
    changed = accepted = 0
    checkpoints = []
    restart_count = 1 if method == 'sa_single' else min(len(starts), proposals)
    for i in range(proposals):
        if method == 'pareto_bursts':
            if i % burst_length == 0:
                current = rng.choice(pareto_indices(metrics))
        else:
            section = i * restart_count // proposals
            section_start = math.ceil(section * proposals / restart_count)
            section_end = math.ceil((section + 1) * proposals / restart_count)
            if i == section_start:
                current = keep(starts[section])
            temp = .02 * (.0005/.02) ** ((i - section_start) / max(1, section_end-section_start-1))
        p = recom_step(plans[current], adjacency, pops, target, tolerance, rng)
        candidate = keep(p)
        if candidate != current:
            changed += 1
            delta = metrics[candidate][objective] - metrics[current][objective]
            if method == 'pareto_bursts' or delta <= 0 or rng.random() < math.exp(-delta/temp):
                current = candidate
                accepted += 1
        # Archive-best includes rejected proposals and every supplied start for
        # all arms. It is the same evaluation rule for all methods.
        if metrics[candidate][objective] < metrics[best][objective]:
            best = candidate
        if (i+1) % 100 == 0 or i+1 == proposals:
            checkpoints.append({'proposal': i+1, 'best': metrics[best][objective],
                                'elapsed_seconds': time.perf_counter()-begun})
    return {'method': method, 'objective': objective, 'seed': seed,
            'proposals': proposals, 'changed_proposals': changed, 'accepted': accepted,
            'elapsed_seconds': time.perf_counter()-begun, 'unique_states': len(plans),
            'best_assignment': plans[best], 'best_metrics': metrics[best],
            'front': [{'assignment': plans[i], 'metrics': metrics[i]} for i in pareto_indices(metrics)],
            'checkpoints': checkpoints}

"""Small evolutionary search over bounded redistricting heuristics.

Inspired by program evolution, not an AlphaEvolve implementation: no external
LLM, arbitrary code execution, evolved evaluator, or electoral features. The
JSON policy is interpreted by fixed code. Score v1 and hard checks stay fixed.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from dataclasses import asdict, dataclass

from redistrict.optimize.sa import assignment_fingerprint
from redistrict.optimize.experiment import dominates
from redistrict.sample.recom import (
    _descendants, _district_members, _root_tree, _stays_connected,
    plan_population, recom_step,
)
from redistrict.validate.constraints import validate_plan


DOMAINS = {
    'controller': ('anneal', 'bursts', 'pareto'),
    'multistart': (False, True),
    'burst_length': (5, 10, 25),
    'temperature': (.005, .02, .08),
    'cooling_power': (.5, 1., 2.),
    'population_pair_bias': (0., 1., 4.),
    'epci_tree_bias': (0., .5, 2.),
    'flip_probability': (0., .1, .3),
}


@dataclass(frozen=True)
class Policy:
    controller: str = 'anneal'
    multistart: bool = False
    burst_length: int = 10
    temperature: float = .02
    cooling_power: float = 1.
    population_pair_bias: float = 0.
    epci_tree_bias: float = 0.
    flip_probability: float = 0.

    def __post_init__(self):
        for key, value in asdict(self).items():
            if value not in DOMAINS[key]:
                raise ValueError(f'unsupported policy field {key}={value}')
        # Remove inactive genes before hashing/deduplication: different JSON
        # encodings of the same strategy must not spend extra tuning budget.
        if self.controller == 'anneal':
            object.__setattr__(self,'burst_length',10)
        else:
            object.__setattr__(self,'multistart',False)
            object.__setattr__(self,'temperature',.02)
            object.__setattr__(self,'cooling_power',1.)

    @property
    def id(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


def initial_policies():
    return [Policy(), Policy(multistart=True), Policy(controller='bursts'),
            Policy(multistart=True, flip_probability=.3)]


def random_policy(rng):
    return Policy(**{k: rng.choice(v) for k, v in DOMAINS.items()})


def mutate(parent, rng, donor=None):
    fields = asdict(parent)
    if donor is not None:
        other = asdict(donor)
        for key in fields:
            if rng.random() < .35:
                fields[key] = other[key]
    for key in rng.sample(list(DOMAINS), rng.choice([1, 2])):
        fields[key] = rng.choice([x for x in DOMAINS[key] if x != fields[key]])
    return Policy(**fields)


def _biased_tree(nodes, adjacency, epci, bias, rng):
    edges = sorted({tuple(sorted((u, v))) for u in nodes for v in adjacency[u] if v in nodes})
    ranked = []
    for u, v in edges:
        # Missing EPCI membership does not count as shared membership.
        same = bool(epci.get(u)) and epci.get(u) == epci.get(v)
        ranked.append((rng.random() + (0 if same else bias), u, v))
    ranked.sort()
    parent = {u:u for u in nodes}
    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]; u = parent[u]
        return u
    tree = {u:set() for u in nodes}
    for _,u,v in ranked:
        a,b = find(u),find(v)
        if a != b:
            parent[a] = b; tree[u].add(v); tree[v].add(u)
    return tree


def propose(plan, adjacency, pops, epci, target, tolerance, policy, rng, tree_attempts=64):
    """ReCom or a boundary flip; every changed proposal stays hard-valid.

    Tree attempts are fixed by the evaluator, never evolved. The unbiased arm
    calls the existing production ReCom kernel with this shared attempt cap.
    A flip call tries at most 16 boundary-unit/recipient combinations.
    """
    if policy.flip_probability and rng.random() < policy.flip_probability:
        members = _district_members(plan); dp = plan_population(plan,pops)
        boundary = sorted((u,plan[v]) for u in plan for v in adjacency[u] if plan[u] != plan[v])
        rng.shuffle(boundary)
        lo,hi = target*(1-tolerance),target*(1+tolerance)
        for u,receiver in boundary[:16]:
            donor = plan[u]
            if lo <= dp[donor]-pops[u] <= hi and lo <= dp[receiver]+pops[u] <= hi \
                    and _stays_connected(members[donor]-{u},adjacency):
                new = dict(plan); new[u] = receiver; return new
        return plan
    if not policy.population_pair_bias and not policy.epci_tree_bias:
        return recom_step(plan,adjacency,pops,target,tolerance,rng,max_tries=tree_attempts)
    members = _district_members(plan); dp = plan_population(plan,pops)
    pairs = sorted({tuple(sorted((plan[u],plan[v]))) for u in plan for v in adjacency[u] if plan[u] != plan[v]})
    if not pairs:return plan
    weights = [1 + policy.population_pair_bias * (abs(dp[a]/target-1)+abs(dp[b]/target-1)) for a,b in pairs]
    a,b = rng.choices(pairs,weights=weights,k=1)[0]
    merged = members[a] | members[b]; total = sum(pops[u] for u in merged)
    lo,hi = target*(1-tolerance),target*(1+tolerance)
    for _ in range(tree_attempts):
        tree = _biased_tree(merged,adjacency,epci,policy.epci_tree_bias,rng)
        root = min(merged); parent,order = _root_tree(tree,root)
        sub = {u:pops[u] for u in merged}
        for u in reversed(order):
            if u != root:sub[parent[u]] += sub[u]
        cuts = [u for u in order if u != root and lo <= sub[u] <= hi and lo <= total-sub[u] <= hi]
        if cuts:
            side = _descendants(tree,parent,rng.choice(cuts)); new = dict(plan)
            for u in merged:new[u] = a if u in side else b
            return new
    return plan


def _vector(metrics):
    return (metrics['l_pop'],metrics['l_comp'],metrics['l_epci'])


def front_indices(metrics):
    front = []
    for i,m in enumerate(metrics):
        v = _vector(m)
        if any(dominates(_vector(metrics[j]),v) for j in front):continue
        front = [j for j in front if not dominates(v,_vector(metrics[j]))]
        front.append(i)
    return front


def run_policy(case, policy, seed, proposals=192, tree_attempts=64, max_seconds=None):
    """Fixed evaluator. `case['make_scorer']()` returns a fresh scoring cache.

    Every arm starts from the common incumbent and receives the same pool of
    valid starts. Incumbent elitism prevents regression under the FIXED v1 score.
    All unique proposed maps are hard-validated before scoring or retention.
    """
    if proposals < 1 or tree_attempts < 1:raise ValueError('positive budgets required')
    begun = time.perf_counter(); rng = random.Random(seed); scorer = case['make_scorer']()
    plans,metrics,lookup = [],[],{}
    units = set(case['pops']); seats = case['seats']; target = sum(case['pops'].values())/seats
    def keep(plan):
        h = assignment_fingerprint(plan)
        if h not in lookup:
            checked = validate_plan(plan,units,case['pops'],case['adjacency'],target,.2)
            if not checked.ok or len(set(plan.values())) != seats:
                raise ValueError('policy returned a hard-invalid map')
            lookup[h] = len(plans); plans.append(dict(plan)); metrics.append(scorer.components(plan))
        return lookup[h]
    starts = []
    for p in case['starts']:
        i = keep(p)
        if i not in starts:starts.append(i)
    current = starts[0]; best = min(starts,key=lambda j:metrics[j]['L_v1'])
    initial_score = metrics[best]['L_v1']
    initial_incumbent = metrics[starts[0]]['L_v1']
    changed = accepted = completed = 0; checkpoints = []
    segments = min(len(starts),proposals) if policy.multistart else 1
    for step in range(proposals):
        if max_seconds is not None and time.perf_counter()-begun >= max_seconds:break
        section = step*segments//proposals
        lo = math.ceil(section*proposals/segments); hi = math.ceil((section+1)*proposals/segments)
        if step == lo and policy.controller == 'anneal':current = starts[section]
        if policy.controller != 'anneal' and step % policy.burst_length == 0:
            if policy.controller == 'pareto':current = rng.choice(front_indices(metrics))
            else:current = best
        candidate = keep(propose(plans[current],case['adjacency'],case['pops'],case['epci'],target,.2,policy,rng,tree_attempts))
        if candidate != current:
            changed += 1
            delta = metrics[candidate]['L_v1']-metrics[current]['L_v1']
            frac = ((step-lo)/max(1,hi-lo-1))**policy.cooling_power
            temperature = policy.temperature*(.0005/policy.temperature)**frac
            if policy.controller != 'anneal' or delta <= 0 or rng.random() < math.exp(-delta/temperature):
                current = candidate; accepted += 1
        if metrics[candidate]['L_v1'] < metrics[best]['L_v1']:best = candidate
        completed += 1
        if completed % 32 == 0 or completed == proposals:
            checkpoints.append({'proposals':completed,'best_L_v1':metrics[best]['L_v1'],
                                'seconds':time.perf_counter()-begun})
    return {'policy_id':policy.id,'policy':asdict(policy),'seed':seed,'proposal_budget':proposals,
            'proposals_completed':completed,'complete':completed==proposals,'tree_attempt_cap':tree_attempts,
            'seconds':time.perf_counter()-begun,'unique_states':len(plans),'changed':changed,'accepted':accepted,
            'initial_best_L_v1':initial_score,'incumbent_L_v1':initial_incumbent,
            'relative_gain':(initial_score-metrics[best]['L_v1'])/max(initial_score,1e-15),
            'gain_vs_incumbent':(initial_incumbent-metrics[best]['L_v1'])/max(initial_incumbent,1e-15),
            'best_metrics':metrics[best],'best_assignment':plans[best],
            'observed_front':[{'metrics':metrics[j],'assignment':plans[j]} for j in front_indices(metrics)],
            'checkpoints':checkpoints}


def evolve(evaluate, seed=73, evaluations=10):
    """Mutation/crossover population vs a budget-matched random-policy control.

    evaluate receives ONLY a Policy, not a dataset split. Its implementation is
    bound to training cases. Validation and holdout happen outside this loop.
    Shared seed policies are evaluated once and credited equally to both arms.
    """
    if evaluations < 4:raise ValueError('at least four seed policies required')
    rng = random.Random(seed); cache = {}; records = []
    def assess(p,arm,parent=None):
        if p.id not in cache:cache[p.id] = evaluate(p)
        record = {'policy':asdict(p),'policy_id':p.id,'arm':arm,'parent':parent,
                  'fitness':cache[p.id],'index':len(records)}
        records.append(record);return record
    population = [assess(p,'shared_seed') for p in initial_policies()]
    evo = list(population); random_arm = list(population)
    while len(evo) < evaluations:
        parent = min(rng.sample(evo,min(3,len(evo))),key=lambda r:r['fitness'])
        donor = rng.choice(evo)
        child = mutate(Policy(**parent['policy']),rng,Policy(**donor['policy']))
        if any(r['policy_id']==child.id for r in evo):continue
        evo.append(assess(child,'evolution',parent['policy_id']))
    # Separate stream: random control is unaffected by evolutionary duplicate
    # draws, fitness values, or parent selection.
    rrng = random.Random(seed+1)
    while len(random_arm) < evaluations:
        child = random_policy(rrng)
        if any(r['policy_id']==child.id for r in random_arm):continue
        random_arm.append(assess(child,'random_control'))
    return {'evolution':sorted(evo,key=lambda r:r['fitness']),
            'random_control':sorted(random_arm,key=lambda r:r['fitness']),
            'records':records,'unique_evaluations':len(cache),
            'nominal_evaluations_per_arm':evaluations}


def audit_results(cases, records):
    """Recompute retained-map metrics with fresh caches, outside policy search.

    Check geometric overlaps using the production 1 m² threshold as well as
    the independent shared graph/partition/population validator. A failed audit
    prevents a completed campaign status or promotion to a national series.
    """
    from shapely import STRtree
    checked = {}; sources = {}; worst_error = max_overlap = 0.
    for record in records:
        name = record['case'];case = cases[name]
        if name not in sources:
            scorer = case['make_scorer']()
            units = sorted(case['pops']); shapes = [scorer.base._geom[u] for u in units]
            if not all(g.is_valid and not g.is_empty for g in shapes):
                raise ValueError('invalid/empty unit geometry in campaign')
            tree = STRtree(shapes); overlaps = []
            for i,g in enumerate(shapes):
                for j in tree.query(g,predicate='intersects'):
                    j = int(j)
                    if j > i:
                        area = g.intersection(shapes[j]).area
                        if area > 0:overlaps.append((units[i],units[j],area))
            sources[name] = (scorer,overlaps)
        scorer,overlaps = sources[name]
        retained = [{'assignment':record['best_assignment'],'metrics':record['best_metrics']}]+record['observed_front']
        for item in retained:
            p = item['assignment']; key = (name,assignment_fingerprint(p))
            if key not in checked:
                target = sum(case['pops'].values())/case['seats']
                if not validate_plan(p,set(case['pops']),case['pops'],case['adjacency'],target,.2).ok \
                        or len(set(p.values())) != case['seats']:
                    raise ValueError('retained map fails final hard-constraint audit')
                for a,b,area in overlaps:
                    if p[a] != p[b]:
                        max_overlap = max(max_overlap,area)
                        if area > 1.:raise ValueError('retained map has cross-district overlap above 1 m²')
                checked[key] = scorer.components(p)
            recomputed = checked[key]
            error = max(abs(recomputed[k]-item['metrics'][k]) for k in ['L_v1','L_v2','l_pop','l_comp','l_epci'])
            worst_error = max(worst_error,error)
            if error > 1e-9:raise ValueError('retained-map score failed fresh recomputation')
    return {'status':'PASS_RETAINED_MAP_CHECKS','distinct_retained_maps_checked':len(checked),
            'max_metric_error':worst_error,'max_cross_district_unit_overlap_m2':max_overlap,
            'national_acceptance_certified':False}

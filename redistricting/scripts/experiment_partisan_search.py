"""Exploratory partisan search; deliberately outside the vote-blind pipeline.

First-round bloc pluralities are descriptive proxies, not projected seats. Run from
any directory with redistricting/.venv/bin/python scripts/experiment_partisan_search.py.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import pickle
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import yaml
from redistrict.sample.recom import recom_step
from redistrict.validate.constraints import validate_plan

BLOCS = ROOT.parent / 'docs/redistricting/blocs.draft.yaml'
VOTES = ROOT / 'data/quarantine/electoral/legislatives_2024_t1_communes.csv'
STATE = ROOT / 'data/processed/gate1/sampler_state.pkl'
METHODS = ('anneal_recom', 'greedy_flip', 'recom_bursts')


def load_votes(path, departments, mappings, target_nuance=None, candidate_affiliations=None):
    maps = {name: {nuance: bloc for bloc, nuances in data['blocs'].items() for nuance in nuances}
            for name, data in mappings.items()}
    votes = {name: defaultdict(lambda: defaultdict(float)) for name in maps}
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle, delimiter=';')
        slots = [int(c.rsplit(' ', 1)[1]) for c in reader.fieldnames if c.startswith('Nuance candidat ')]
        for row in reader:
            dep = row['Code département'].strip().upper().zfill(2)
            if dep not in departments:
                continue
            unit = row['Code commune'].strip().upper().zfill(5)
            for slot in slots:
                nuance = row[f'Nuance candidat {slot}'].strip()
                raw = row[f'Voix {slot}'].strip().replace(' ', '')
                if not nuance or not raw:
                    continue
                target_affiliation = False
                if candidate_affiliations is not None:
                    from partisan_affiliations import affiliation_for, PARTY_LFI
                    target_affiliation = affiliation_for(candidate_affiliations, row, slot) == PARTY_LFI
                for name, mapping in maps.items():
                    label = ('party:LFI' if target_affiliation else
                             ('party:' + nuance if nuance == target_nuance else mapping.get(nuance, 'other')))
                    votes[name][unit][label] += int(raw)
    return {name: dict(data) for name, data in votes.items()}


def metrics(plan, votes, target):
    totals = defaultdict(lambda: defaultdict(float))
    for unit, district in plan.items():
        for bloc, count in votes[unit].items():
            totals[district][bloc] += count
    wins = 0
    smooth = 0.0
    margins = []
    for bloc_votes in totals.values():
        total = sum(bloc_votes.values())
        if total <= 0:
            raise ValueError('district has no observed votes')
        target_votes = bloc_votes.get(target, 0)
        opponent = max((v for b, v in bloc_votes.items() if b != target), default=0)
        margin = (target_votes - opponent) / total
        # Deterministic tie rule shared with the existing audit: alphabetical bloc name.
        winner = min(bloc_votes, key=lambda b: (-bloc_votes[b], b))
        wins += winner == target
        smooth += 1 / (1 + math.exp(-max(-50, min(50, margin / .04))))
        margins.append(margin)
    return {'pluralities': int(wins), 'smooth_score': smooth, 'margins': sorted(margins)}


def rank(m):
    return (m['pluralities'], m['smooth_score'])


def flip(plan, adjacency, pops, target_pop, tolerance, rng):
    boundary = [(u, v) for u in sorted(plan) for v in sorted(adjacency[u]) if plan[u] != plan[v]]
    if not boundary:
        return plan
    u, v = rng.choice(boundary)
    candidate = dict(plan)
    candidate[u] = plan[v]
    if len(set(candidate.values())) != len(set(plan.values())):
        return plan
    if not validate_plan(candidate, set(plan), pops, adjacency, target_pop, tolerance).ok:
        return plan
    return candidate


def search(start, adjacency, pops, target_pop, tolerance, votes, bloc, method, budget, seed):
    if method not in METHODS:
        raise ValueError(method)
    rng = random.Random(seed)
    current = dict(start)
    current_metrics = metrics(current, votes, bloc)
    best, best_metrics = dict(current), current_metrics
    accepted = changed = 0
    for step in range(budget):
        if method == 'recom_bursts' and step and step % 30 == 0:
            current, current_metrics = dict(best), best_metrics
        if method == 'greedy_flip':
            candidate = flip(current, adjacency, pops, target_pop, tolerance, rng)
        else:
            candidate = recom_step(current, adjacency, pops, target_pop, tolerance, rng)
        if candidate == current:
            continue
        changed += 1
        candidate_metrics = metrics(candidate, votes, bloc)
        if method == 'recom_bursts':
            accept = True  # unbiased random walk, periodically restart at best discovered
        elif method == 'greedy_flip':
            accept = rank(candidate_metrics) >= rank(current_metrics)
        else:
            # Seat count dominates smooth tie-breaker; temperature decreases over run.
            old = current_metrics['pluralities'] + current_metrics['smooth_score'] / (len(set(start.values())) + 1)
            new = candidate_metrics['pluralities'] + candidate_metrics['smooth_score'] / (len(set(start.values())) + 1)
            temp = .3 * (.01 / .3) ** (step / max(1, budget - 1))
            accept = new >= old or rng.random() < math.exp((new - old) / temp)
        if accept:
            current, current_metrics = candidate, candidate_metrics
            accepted += 1
        if rank(candidate_metrics) > rank(best_metrics):
            best, best_metrics = dict(candidate), candidate_metrics
    return best, {'metrics': best_metrics, 'changed_proposals': changed, 'accepted': accepted}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--departments', nargs='+', default=['01', '03', '50'])
    choice = p.add_mutually_exclusive_group()
    choice.add_argument('--target', help='target bloc in both mappings')
    choice.add_argument('--nuance', help='exact 2024 Ministry candidate nuance (default: RN)')
    p.add_argument('--seeds', nargs='+', type=int, default=[101, 202, 303])
    p.add_argument('--budget', type=int, default=600)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.budget < 1 or args.output.exists():
        p.error('budget must be positive and output must not exist')
    definitions = yaml.safe_load(BLOCS.read_text())['mappings']
    nuance = (args.nuance or 'RN').upper() if not args.target else None
    target = args.target or 'party:' + nuance
    if args.target and any(args.target not in definitions[name]['blocs'] for name in ('coarse', 'fine')):
        p.error('target must be a bloc in both coarse and fine mappings')
    state = pickle.loads(STATE.read_bytes())
    votes = load_votes(VOTES, set(args.departments), definitions, nuance)
    if nuance and not any(target in row for row in votes['coarse'].values()):
        p.error(f'no votes found for nuance {nuance}')
    report = {'target': target, 'election': '2024 legislative first round',
              'objective': 'coarse bloc plurality, then smooth margin; not seats or forecasts',
              'budget_proposals': args.budget, 'seeds': args.seeds, 'tolerance': .2,
              'hashes': {str(x.relative_to(ROOT.parent)): sha(x) for x in [STATE, VOTES, BLOCS]},
              'departments': {}}
    for dep in args.departments:
        units = {u for u in state['units'] if state['unit_dept'][u] == dep}
        if not units or any(len(u) != 5 for u in units):
            raise ValueError(f'{dep}: this commune-only experiment requires unsplit commune units')
        missing = units - votes['coarse'].keys()
        extra = {u for u in votes['coarse'] if u.startswith(dep)} - units
        if missing or extra:
            raise ValueError(f'{dep}: unmatched units {sorted(missing)[:10]}, extra communes {sorted(extra)[:10]}')
        adj = {u: frozenset(v for v in state['certification_edges'].get(u, []) if v in units) for u in units}
        pop = state['pops']; target_pop = state['dept_pop'][dep] / state['seats'][dep]
        path = ROOT / 'data/processed/plans' / f'{dep}.json'
        candidates = json.loads(path.read_text())['plans']
        valid = [x['assignment'] for x in candidates if validate_plan(x['assignment'], units, pop, adj, target_pop, .2).ok and len(set(x['assignment'].values())) == state['seats'][dep]]
        if not valid:
            raise ValueError(f'{dep}: no valid starting plan')
        start = valid[0]
        entry = {'units': len(units), 'districts': state['seats'][dep], 'start_hash': sha(path),
                 'baseline': {name: metrics(start, votes[name], target) for name in ('coarse', 'fine')}, 'runs': []}
        report['departments'][dep] = entry
        for seed in args.seeds:
            for method in METHODS:
                now = time.monotonic()
                best, details = search(start, adj, pop, target_pop, .2, votes['coarse'], target, method, args.budget, seed)
                checked = validate_plan(best, units, pop, adj, target_pop, .2)
                if not checked.ok or len(set(best.values())) != state['seats'][dep]:
                    raise ValueError(f'{dep} {method}: invalid result')
                details.update({'method': method, 'seed': seed, 'seconds': time.monotonic()-now,
                                'max_population_deviation': checked.max_deviation,
                                'fine_metrics': metrics(best, votes['fine'], target), 'assignment': best})
                entry['runs'].append(details)
                print(dep, seed, method, details['metrics']['pluralities'], round(details['seconds'], 2), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

if __name__ == '__main__':
    main()

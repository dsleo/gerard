"""Screen departments for repeatable first-round party gains.

Separate vote-aware research; no production plans are changed. The official
2024 map is the reference; generated starts use official district counts.
"""
from __future__ import annotations
import argparse
import base64
import collections
import concurrent.futures
import csv
import gzip
import importlib.util
import json
import multiprocessing
import pickle
import re
import random
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import experiment_partisan_search as exp
import yaml
from redistrict.validate.constraints import validate_plan
from redistrict.sample.official import build_official_seed
from redistrict.sample.department import sample_department, connected_pieces
from redistrict.sample.recom import flip_repair, recom_step

SNAPSHOT = ROOT / 'export/browser/projection-2026.js'
SECOND = ROOT / 'data/quarantine/electoral/legislatives_2024_t2_circonscriptions.csv'
FIRST = ROOT / 'data/quarantine/electoral/legislatives_2024_t1_circonscriptions.csv'
CORRESPONDENCE = ROOT / 'data/raw/constituencies/insee_commune_circonscription_2026.xlsx'
COG = ROOT / 'data/raw/insee_cog2024/v_commune_2024.csv'
MOVEMENTS = ROOT / 'data/raw/insee_cog2024/v_mvt_commune_2024.csv'
CROSSWALK = ROOT / 'data/quarantine/electoral/liaison_iris_bureaux_de_vote_2024.csv'
BUREAUX = ROOT / 'data/quarantine/electoral/legislatives_2024_t1_bureaux.csv'
AFFILIATION = ROOT / 'data/quarantine/electoral/rattachement-candidats-leg-2024.xlsx'
HEURISTIC = ROOT / 'data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts/national_draft/official_unit_assignment_heuristic.csv'
BLOCKS = ['left', 'centre', 'right', 'far_right', 'other']
STATE = VOTES = OFFICIAL = None
SPLIT_COVERAGE = MISSING_REGISTRATIONS = SPLIT_DETAILS = None
HEURISTIC_STARTS = EXTRA_REGISTERED = None
MINIMUM_SPLIT_COVERAGE = .99
TARGET_NUANCE = TARGET_BLOC = TARGET_KEY = None


def snapshot():
    found = re.search(r'atob\("([A-Za-z0-9+/=]+)"\)', SNAPSHOT.read_text())
    if not found:
        raise ValueError('unrecognized projection snapshot')
    return json.loads(gzip.decompress(base64.b64decode(found.group(1))))


def map_official_votes(votes, mapping, nuance):
    out = collections.defaultdict(float)
    for n, v in votes.items():
        out['party:' + n if n == nuance else mapping.get(n, 'other')] += v
    return dict(out)


def projected_rows(dep, plan, votes):
    groups = collections.defaultdict(lambda: collections.defaultdict(float))
    for unit, district in plan.items():
        for block, count in votes[unit].items():
            # The existing second-round model works at bloc, not party, level.
            block = TARGET_BLOC if TARGET_KEY and TARGET_KEY.startswith('party:') and block == TARGET_KEY else block
            groups[district]['model:' + block] += count
    return [{'department': dep, 'district_number': int(d), 'estimated': True,
             'votes_by_nuance': dict(v)} for d, v in groups.items()]


def robust_pluralities(plan, votes, target, missing_registered, split_details=None, extra_registered=0):
    totals = collections.defaultdict(lambda: collections.defaultdict(float))
    sources = collections.defaultdict(set)
    for unit, district in plan.items():
        for bloc, count in votes[unit].items():
            totals[district][bloc] += count
        if split_details:
            parent = unit[:5] if len(unit) >= 9 else unit
            sources[district].update(split_details['parent_sources'].get(parent, ()))
    def unknown_for(district):
        if split_details is None:
            return missing_registered
        return extra_registered + sum(split_details['source_missing_registered'].get(source, 0)
                                      for source in sources[district])
    return sum(1 for district, counts in totals.items()
               if counts.get(target, 0) > max((v for b, v in counts.items() if b != target), default=0)
               + unknown_for(district))


def calculate(dep, budget, seeds, methods, generate_starts=False, start_timeout=45):
    state = STATE
    units = {u for u in state['units'] if state['unit_dept'][u] == dep}
    official = OFFICIAL[dep]
    if not official:
        return {'status': 'excluded_missing_official_results'}
    seat_count = len(official)
    if seat_count != state['seats'][dep] and not generate_starts:
        return {'status': 'excluded_seat_count_differs', 'official_seats': seat_count, 'model_seats': state['seats'][dep]}
    split_parents = {u[:5] for u in units if len(u) >= 9}
    if SPLIT_COVERAGE is not None:
        split_parents |= {u for u in units if u in SPLIT_COVERAGE}
    if split_parents and SPLIT_COVERAGE is None:
        return {'status': 'excluded_split_units', 'official_seats': len(official)}
    if split_parents and min(SPLIT_COVERAGE.get(p, 0) for p in split_parents) < MINIMUM_SPLIT_COVERAGE:
        return {'status': 'excluded_split_coverage_below_threshold', 'official_seats': len(official),
                'coverage_by_split_commune': {p:SPLIT_COVERAGE.get(p, 0) for p in sorted(split_parents)}}
    votes = VOTES['coarse']
    if TARGET_KEY.startswith('party:') and not any(votes.get(unit, {}).get(TARGET_KEY, 0) > 0 for unit in units):
        return {'status': 'excluded_no_target_votes', 'official_seats': seat_count}
    missing = units - votes.keys()
    extra = {u for u in votes if u.startswith(dep)} - units
    nonzero_missing = {u for u in missing if state['pops'].get(u, 0) != 0}
    if nonzero_missing or any(u not in EXTRA_REGISTERED for u in extra):
        return {'status': 'excluded_unmatched_communes', 'missing': sorted(nonzero_missing), 'extra': sorted(extra)}
    # Model units with zero population and no recorded votes contribute zero.
    for unit in missing:
        votes[unit] = {}
    extra_registered = sum(EXTRA_REGISTERED[u] for u in extra)
    adj = {u: frozenset(v for v in state['certification_edges'].get(u, []) if v in units) for u in units}
    pop = state['pops']; target_pop = state['dept_pop'][dep] / seat_count
    path = ROOT / 'data/processed/plans' / f'{dep}.json'
    starts = []
    start_source = None
    if path.exists() and seat_count == state['seats'][dep]:
        plans = json.loads(path.read_text())['plans']
        starts = [p['assignment'] for p in plans if len(set(p['assignment'].values())) == seat_count
                  and validate_plan(p['assignment'], units, pop, adj, target_pop, .2).ok]
        if starts: start_source = 'saved_sampler:' + exp.sha(path)
    if not starts and generate_starts:
        # Reuse the strict INSEE whole-commune correspondence, with the actual
        # constituency count, not the alternative national allocation.
        adjusted = dict(state)
        adjusted['seats'] = {**state['seats'], dep: seat_count}
        official_seed = build_official_seed(dep, adjusted, CORRESPONDENCE, COG, MOVEMENTS)
        if official_seed['candidate'] is not None:
            starts = [official_seed['candidate']]
            start_source = 'exact_insee_official_seed'
    if not starts and generate_starts and HEURISTIC_STARTS:
        source = HEURISTIC_STARTS.get(dep, {})
        heuristic_plan = {}
        for unit in sorted(units):
            options = (collections.Counter({source[unit]: 1}) if unit in source else
                       collections.Counter(value for key, value in source.items()
                                           if key.startswith(unit) and len(key) > len(unit)))
            if options:
                heuristic_plan[unit] = min(options, key=lambda value: (-options[value], value))
        if len(heuristic_plan) == len(units) and len(set(heuristic_plan.values())) == seat_count:
            labels = {key:i for i,key in enumerate(sorted(set(heuristic_plan.values())))}
            heuristic_plan = {unit: labels[value] for unit, value in heuristic_plan.items()}
            checked = validate_plan(heuristic_plan, units, pop, adj, target_pop, .2)
            if not checked.ok:
                # The overlay is only a starting guess. Join disconnected
                # fragments to adjacent districts, then use existing repair
                # moves; accept nothing unless the independent validator passes.
                for label in sorted(set(heuristic_plan.values())):
                    pieces = connected_pieces([u for u in heuristic_plan if heuristic_plan[u] == label], adj)
                    for piece in pieces[1:]:
                        adjacent_labels = {heuristic_plan[v] for u in piece for v in adj[u]
                                           if heuristic_plan[v] != label}
                        if adjacent_labels:
                            piece_pop = sum(pop[u] for u in piece)
                            destination = min(adjacent_labels, key=lambda n: (
                                abs(sum(pop[u] for u in heuristic_plan if heuristic_plan[u] == n)
                                    + piece_pop - target_pop), n))
                            for u in piece:
                                heuristic_plan[u] = destination
                def repair_timeout(_signum, _frame):
                    raise TimeoutError('heuristic repair time limit exceeded')
                previous = signal.signal(signal.SIGALRM, repair_timeout)
                try:
                    signal.alarm(start_timeout)
                    heuristic_plan = flip_repair(heuristic_plan, adj, pop, target_pop, .2)
                    rng = random.Random(20241122)
                    for _ in range(30):
                        checked = validate_plan(heuristic_plan, units, pop, adj, target_pop, .2)
                        if checked.ok: break
                        heuristic_plan = recom_step(heuristic_plan, adj, pop, target_pop, .2, rng, max_tries=200)
                except TimeoutError:
                    pass
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, previous)
            checked = validate_plan(heuristic_plan, units, pop, adj, target_pop, .2)
            if checked.ok and len(set(heuristic_plan.values())) == seat_count:
                starts = [heuristic_plan]
                start_source = 'repaired_validated_official_overlap_heuristic'
    if not starts and generate_starts:
        # Search for a vote-blind starting partition, with bounded work per
        # department so a difficult graph cannot stall the entire campaign.
        def timeout(_signum, _frame):
            raise TimeoutError('starting-plan time limit exceeded')
        previous = signal.signal(signal.SIGALRM, timeout)
        try:
            signal.alarm(start_timeout)
            sample = sample_department(sorted(units), pop, adj, state['epci_of'], seat_count,
                                       .2, replicates=1, steps=30, seed=20241122, max_attempts=3)
            starts = [p['assignment'] for p in sample.get('plans', [])
                      if len(set(p['assignment'].values())) == seat_count
                      and validate_plan(p['assignment'], units, pop, adj, target_pop, .2).ok]
            if starts: start_source = 'new_vote_blind_sampler_seed_20241122'
        except TimeoutError:
            return {'status': 'excluded_start_generation_timeout', 'official_seats': seat_count}
        except (ValueError, TypeError, KeyError) as error:
            return {'status': 'excluded_start_generation_failed', 'official_seats': seat_count,
                    'reason': str(error)}
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    if not starts:
        return {'status': 'excluded_no_valid_start', 'official_seats': seat_count}
    start = starts[0]
    base = sum(row['target_leads'] for row in official)
    start_score = exp.metrics(start, votes, TARGET_KEY)['pluralities']
    runs = []
    missing_registrations = (MISSING_REGISTRATIONS.get(dep, 0) if split_parents else 0) + extra_registered
    for seed in seeds:
        options = []
        for method in methods:
            best, details = exp.search(start, adj, pop, target_pop, .2, votes, TARGET_KEY, method, budget, seed)
            valid = validate_plan(best, units, pop, adj, target_pop, .2)
            if not valid.ok or len(set(best.values())) != seat_count:
                raise ValueError(f'invalid search result {dep}, {seed}, {method}')
            options.append((exp.rank(details['metrics']), best, details, method, valid.max_deviation))
        _, best, detail, method, deviation = max(options, key=lambda x: x[0])
        # Missing registered voters are allowed to strengthen any single
        # opponent in any district; count only individually secure leads.
        robust_leads = robust_pluralities(best, votes, TARGET_KEY, missing_registrations,
                                             SPLIT_DETAILS if split_parents else None, extra_registered)
        runs.append({'seed': seed, 'robust_leading': robust_leads,
                     'robust_gain_vs_official': robust_leads - base, 'method': method, 'leading': detail['metrics']['pluralities'],
                     'gain_vs_official': detail['metrics']['pluralities'] - base,
                     'maximum_population_deviation': deviation, 'assignment': best,
                     'round_two_inputs': projected_rows(dep, best, votes)})
    return {'status': 'tested', 'official_seats': len(official), 'official_target_leads': base,
            'sampler_start_target_leads': start_score, 'runs': runs,
            'minimum_observed_gain': min(r['robust_gain_vs_official'] for r in runs),
            'improved_runs': sum(r['robust_gain_vs_official'] > 0 for r in runs),
            'unallocated_registered_upper_bound': missing_registrations, 'extra_communes': sorted(extra),
            'start_source': start_source, 'start_assignment': start,
            'split_coverage_by_commune': {p:SPLIT_COVERAGE[p] for p in sorted(split_parents)} if split_parents else {}}


def second_round_inputs():
    spec = importlib.util.spec_from_file_location('atlas_builder', ROOT / 'scripts/build_results_view_data.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    rows = []
    with SECOND.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f, delimiter=';'):
            dep = builder.department(row.get('Code département'))
            if not builder.in_department_scope(dep): continue
            code = str(row.get('Code circonscription législative') or '').strip()
            try: number = int(code[len(dep):])
            except ValueError: continue
            vs = collections.defaultdict(float); count = 0
            for field, nuance in row.items():
                found = re.fullmatch(r'Nuance candidat (\d+)', field or '')
                if not found: continue
                slot = found.group(1)
                if not (row.get(f'Nom candidat {slot}') or row.get(f'Prénom candidat {slot}') or '').strip(): continue
                count += 1
                vs[str(nuance or '').strip()] += builder.number(row.get(f'Voix {slot}'))
            rows.append({'department': dep, 'district_number': number, 'candidate_count': count,
                         'expressed': builder.number(row.get('Exprimés')), 'votes_by_nuance': dict(vs)})
    return builder, rows


def minimum_departments(results, base, goal):
    # Exact for these measured additive gains and equal departmental cost only.
    gains = sorted(((v['minimum_observed_gain'], dep) for dep, v in results.items()
                    if v['status'] == 'tested' and v['minimum_observed_gain'] > 0), reverse=True)
    selected = []; total = base
    for gain, dep in gains:
        if total >= goal: break
        selected.append({'department': dep, 'conservative_observed_gain': gain}); total += gain
    return {'goal': goal, 'baseline_observed_official': base, 'selected': selected,
            'result_lower_bound': total, 'reached': total >= goal,
            'scope': 'minimum among screened departments and measured minimum-across-run gains; excluded departments contribute zero gains'}


def main():
    global STATE, VOTES, OFFICIAL, TARGET_NUANCE, TARGET_BLOC, TARGET_KEY, SPLIT_COVERAGE, MISSING_REGISTRATIONS, SPLIT_DETAILS, MINIMUM_SPLIT_COVERAGE, HEURISTIC_STARTS, EXTRA_REGISTERED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=int, default=250)
    parser.add_argument('--seeds', nargs='+', type=int, default=[101, 202, 303])
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--departments', nargs='+')
    parser.add_argument('--goal', type=int, default=289)
    parser.add_argument('--generate-starts', action='store_true', help='build starts with official seat counts')
    parser.add_argument('--split-crosswalk', action='store_true', help='use estimated bureau-to-IRIS votes for split units')
    parser.add_argument('--minimum-split-coverage', type=float, default=.95)
    parser.add_argument('--start-timeout', type=int, default=45)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--nuance', help='2024 Ministry candidate nuance (default RN)')
    choice.add_argument('--bloc', help='coarse first-round political bloc')
    choice.add_argument('--lfi-attachment', action='store_true', help='target candidates financially attached to LFI in 2024')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.budget < 1 or args.workers < 1 or args.start_timeout < 1 or not 0 < args.minimum_split_coverage <= 1: parser.error('positive budget/workers and new output required')
    definitions = yaml.safe_load(exp.BLOCS.read_text())['mappings']
    coarse = {n:b for b, ns in definitions['coarse']['blocs'].items() for n in ns}
    TARGET_NUANCE = None if args.bloc or args.lfi_attachment else (args.nuance or 'RN').strip().upper()
    if TARGET_NUANCE and TARGET_NUANCE not in coarse: parser.error('nuance must be present in the coarse bloc mapping')
    TARGET_BLOC = 'left' if args.lfi_attachment else (args.bloc if args.bloc else coarse[TARGET_NUANCE])
    if TARGET_BLOC not in BLOCKS: parser.error('unknown coarse bloc')
    TARGET_KEY = 'party:LFI' if args.lfi_attachment else ('party:' + TARGET_NUANCE if TARGET_NUANCE else TARGET_BLOC)
    candidate_affiliations = None
    if args.lfi_attachment:
        from partisan_affiliations import load_affiliations
        candidate_affiliations = load_affiliations(AFFILIATION, FIRST)
    snap = snapshot(); OFFICIAL = collections.defaultdict(list)
    with FIRST.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream, delimiter=';'):
            dep = row['Code département'].strip().upper().zfill(2)
            code = row['Code circonscription législative'].strip()
            number = int(code[len(dep):])
            votes = collections.defaultdict(float)
            attached_votes = 0
            for key, nuance in row.items():
                if not key.startswith('Nuance candidat ') or not nuance.strip():
                    continue
                slot = key.rsplit(' ', 1)[1]
                raw = row.get('Voix ' + slot, '').strip().replace(' ', '')
                count = int(raw or 0)
                votes[nuance.strip()] += count
                if candidate_affiliations is not None:
                    from partisan_affiliations import affiliation_for, PARTY_LFI
                    if affiliation_for(candidate_affiliations, row, slot) == PARTY_LFI:
                        if coarse.get(nuance.strip(), 'other') != 'left':
                            raise ValueError('LFI attachment outside left bloc requires a revised model')
                        attached_votes += count
            grouped = map_official_votes(votes, coarse, TARGET_NUANCE)
            if candidate_affiliations is not None:
                # All LFI-attached candidates are in the left coarse bloc.
                grouped['left'] = grouped.get('left', 0) - attached_votes
                grouped[TARGET_KEY] = attached_votes
            if sum(grouped.values()) <= 0:
                raise ValueError(f'no observed first-round votes for {dep}-{number}')
            winner = min(grouped, key=lambda b: (-grouped[b], b))
            OFFICIAL[dep].append({'department': dep, 'district_number': number,
                                  'votes_by_nuance': dict(votes),
                                  'target_leads': winner == TARGET_KEY})
    official_leads = sum(row['target_leads'] for rows in OFFICIAL.values() for row in rows)
    STATE = pickle.loads(exp.STATE.read_bytes())
    departments = args.departments or sorted(STATE['seats'])
    EXTRA_REGISTERED = collections.defaultdict(float)
    with exp.VOTES.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream, delimiter=';'):
            dept = row['Code département'].strip().upper().zfill(2)
            if dept in departments:
                unit = row['Code commune'].strip().upper().zfill(5)
                EXTRA_REGISTERED[unit] += float((row['Inscrits'] or '0').replace(' ', ''))
    VOTES = exp.load_votes(exp.VOTES, set(departments), definitions, TARGET_NUANCE, candidate_affiliations)
    MINIMUM_SPLIT_COVERAGE = args.minimum_split_coverage
    HEURISTIC_STARTS = None
    if args.generate_starts and HEURISTIC.exists():
        HEURISTIC_STARTS = collections.defaultdict(dict)
        with HEURISTIC.open(newline='') as stream:
            for row in csv.DictReader(stream):
                HEURISTIC_STARTS[row['department']][row['unit']] = row['official_constituency']
    SPLIT_COVERAGE = MISSING_REGISTRATIONS = SPLIT_DETAILS = None
    if args.split_crosswalk:
        from partisan_split_votes import allocate_split_votes
        VOTES, SPLIT_COVERAGE, MISSING_REGISTRATIONS, SPLIT_DETAILS = allocate_split_votes(STATE, set(departments), VOTES, definitions,
                                                     TARGET_NUANCE, CROSSWALK, BUREAUX, candidate_affiliations)
    results = {}
    started = time.monotonic()
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('fork')) as pool:
        jobs = {pool.submit(calculate, dep, args.budget, args.seeds, ('anneal_recom','greedy_flip'), args.generate_starts, args.start_timeout): dep for dep in departments}
        for future in concurrent.futures.as_completed(jobs):
            dep = jobs[future]
            results[dep] = future.result()
            x = results[dep]
            print(dep, x['status'], x.get('minimum_observed_gain', ''), flush=True)
    # Run exactly the existing bloc-level atlas model, after search, on the
    # first retained candidate from each tested department and on its start.
    builder, runoff = second_round_inputs()
    projected = [row for dep, x in results.items() if x['status'] == 'tested' for row in x['runs'][0]['round_two_inputs']]
    projected += [{'department': dep, 'district_number': 1000 + int(row['district_number']),
                   'estimated': True, 'votes_by_nuance': row['votes_by_nuance']}
                  for dep, x in results.items() if x['status'] == 'tested' for row in OFFICIAL[dep]]
    augmented = dict(coarse); augmented.update({'model:' + b: b for b in BLOCKS})
    model = builder.round_two_mapping_model(snap['official_first_round'], runoff, projected, augmented, BLOCKS, 2024)
    per_dept = collections.defaultdict(list)
    for row in model['districts']: per_dept[row['department']].append(row)
    for dep, rows in per_dept.items():
        candidate_rows = [r for r in rows if r['district_number'] < 1000]
        official_rows = [r for r in rows if r['district_number'] >= 1000]
        results[dep]['run_0_target_bloc_second_round_wins'] = sum(r['estimated'] and r['winner_bloc'] == TARGET_BLOC for r in candidate_rows)
        results[dep]['run_0_second_round_estimated_districts'] = sum(r['estimated'] for r in candidate_rows)
        results[dep]['official_target_bloc_second_round_model_wins'] = sum(r['estimated'] and r['winner_bloc'] == TARGET_BLOC for r in official_rows)
    report = {'target_nuance': TARGET_NUANCE, 'target_key': TARGET_KEY, 'second_round_target_bloc': TARGET_BLOC, 'official_reference_districts': sum(len(x) for x in OFFICIAL.values()),
              'official_reference_target_first_round_leads': official_leads,
              'unobserved_of_577': 577-sum(len(x) for x in OFFICIAL.values()),
              'goal': args.goal, 'budget_per_method': args.budget, 'seeds': args.seeds,
              'methods': ['anneal_recom', 'greedy_flip'], 'generate_starts': args.generate_starts, 'split_crosswalk': args.split_crosswalk, 'minimum_split_coverage': MINIMUM_SPLIT_COVERAGE, 'start_timeout': args.start_timeout, 'seconds': time.monotonic()-started,
              'input_hashes': {str(x.relative_to(ROOT.parent)):exp.sha(x) for x in [exp.VOTES, exp.STATE, exp.BLOCS, SNAPSHOT, FIRST, SECOND] + ([CORRESPONDENCE, COG, MOVEMENTS] if args.generate_starts else []) + ([CROSSWALK, BUREAUX] if args.split_crosswalk else []) + ([HEURISTIC] if args.generate_starts and HEURISTIC.exists() else []) + ([AFFILIATION] if args.lfi_attachment else [])},
              'model_validation': model['validation'], 'results': dict(sorted(results.items())),
              'selection': minimum_departments(results, official_leads, args.goal)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

if __name__ == '__main__': main()

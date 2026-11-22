"""Independently revalidate, score, and combine saved partisan campaign candidates."""
from __future__ import annotations
import argparse
import collections
import csv
import json
from pathlib import Path
import yaml
import experiment_partisan_campaign as c
from partisan_split_votes import allocate_split_votes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('reports', nargs='+', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--goal', type=int, default=289)
    choice = ap.add_mutually_exclusive_group()
    choice.add_argument('--nuance')
    choice.add_argument('--bloc')
    choice.add_argument('--lfi-attachment', action='store_true')
    args = ap.parse_args()
    if args.output.exists(): ap.error('output already exists')
    reports = [(p, json.loads(p.read_text())) for p in sorted(args.reports, key=lambda path: path.name)]
    nuance = None if args.bloc or args.lfi_attachment else (args.nuance or 'RN').strip().upper()
    target = 'party:LFI' if args.lfi_attachment else (args.bloc if args.bloc else 'party:' + nuance)
    if any(report.get('target_key', 'party:' + str(report.get('target_nuance'))) != target for _, report in reports):
        raise ValueError('reports do not match the requested target')
    state = __import__('pickle').loads(c.exp.STATE.read_bytes())
    departments = {dep for _, report in reports for dep, row in report['results'].items() if row['status'] == 'tested'}
    definitions = yaml.safe_load(c.exp.BLOCS.read_text())['mappings']
    mapping = {n:b for b, ns in definitions['coarse']['blocs'].items() for n in ns}
    bloc = 'left' if args.lfi_attachment else (args.bloc if args.bloc else mapping[nuance])
    affiliations = None
    if args.lfi_attachment:
        from partisan_affiliations import load_affiliations
        affiliations = load_affiliations(c.AFFILIATION, c.FIRST)
    votes = c.exp.load_votes(c.exp.VOTES, departments, definitions, nuance, affiliations)
    votes, coverage, missing_by_dep, detail = allocate_split_votes(state, departments, votes, definitions, nuance, c.CROSSWALK, c.BUREAUX, affiliations)
    registered = collections.defaultdict(float)
    with c.exp.VOTES.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f, delimiter=';'):
            if row['Code département'].strip().upper().zfill(2) in departments:
                registered[row['Code commune'].strip().upper().zfill(5)] += float((row['Inscrits'] or '0').replace(' ', ''))
    official = collections.defaultdict(list)
    with c.FIRST.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f, delimiter=';'):
            dep = row['Code département'].strip().upper().zfill(2)
            code = row['Code circonscription législative'].strip()
            by_nuance = collections.defaultdict(float)
            attached_votes = 0
            for key, candidate_nuance in row.items():
                if key.startswith('Nuance candidat ') and candidate_nuance.strip():
                    slot = key.rsplit(' ', 1)[1]
                    count = int((row.get('Voix ' + slot) or '0').replace(' ',''))
                    by_nuance[candidate_nuance.strip()] += count
                    if affiliations is not None:
                        from partisan_affiliations import affiliation_for, PARTY_LFI
                        if affiliation_for(affiliations, row, slot) == PARTY_LFI:
                            attached_votes += count
            grouped = c.map_official_votes(by_nuance, mapping, nuance)
            if affiliations is not None:
                grouped['left'] = grouped.get('left', 0) - attached_votes
                grouped[target] = attached_votes
            winner = min(grouped, key=lambda b: (-grouped[b], b))
            official[dep].append({'department': dep, 'district_number': int(code[len(dep):]),
                                  'votes_by_nuance': dict(by_nuance), 'target_leads': winner == target})
    count_official = sum(len(x) for x in official.values())
    if count_official != 577: raise ValueError(f'expected 577 official districts, got {count_official}')
    baseline = sum(row['target_leads'] for rows in official.values() for row in rows)
    best = {}; batch_minima = {}; batches = collections.defaultdict(list); tested = set(); discrepancies = []
    for path, report in reports:
        for dep, item in report['results'].items():
            if item['status'] != 'tested': continue
            tested.add(dep)
            units = {u for u in state['units'] if state['unit_dept'][u] == dep}
            seats = len(official[dep]); target_pop = state['dept_pop'][dep] / seats
            adjacency = {u: frozenset(v for v in state['certification_edges'].get(u, ()) if v in units) for u in units}
            unit_votes = votes['coarse']
            for u in units:
                if u not in unit_votes:
                    if state['pops'][u]: raise ValueError(f'missing votes for {dep} {u}')
                    unit_votes[u] = {}
            extra = {u for u in unit_votes if u.startswith(dep)} - units
            extra_registered = sum(registered[u] for u in extra)
            split_parents = {u[:5] for u in units if len(u) >= 9} | {u for u in units if u in coverage}
            unknown = extra_registered + (missing_by_dep.get(dep, 0) if split_parents else 0)
            observed_baseline = sum(row['target_leads'] for row in official[dep])
            batch = []
            for run in item['runs']:
                plan = run['assignment']
                validated = c.validate_plan(plan, units, state['pops'], adjacency, target_pop, .2)
                if not validated.ok or len(set(plan.values())) != seats:
                    raise ValueError(f'invalid selected plan {dep} seed {run["seed"]}')
                metrics = c.exp.metrics(plan, unit_votes, target)
                robust = c.robust_pluralities(plan, unit_votes, target, unknown,
                                               detail if split_parents else None, extra_registered)
                gain = robust-observed_baseline
                original_nominal = run['leading']
                if original_nominal != metrics['pluralities']:
                    discrepancies.append({'department': dep, 'seed': run['seed'], 'source': path.name,
                                          'original': original_nominal, 'recomputed': metrics['pluralities']})
                entry = {'department': dep, 'official_leads': observed_baseline, 'districts': seats,
                         'nominal_leads': metrics['pluralities'], 'bounded_leads': robust, 'bounded_gain': gain,
                         'seed': run['seed'], 'method': run['method'], 'campaign': path.name,
                         'budget_per_method': report['budget_per_method'], 'assignment': plan,
                         'max_population_deviation': validated.max_deviation,
                         'unallocated_registered_upper_bound': unknown,
                         'split_coverage_by_commune': {p:coverage[p] for p in sorted(split_parents)}}
                batch.append(entry)
                if dep not in best or gain > best[dep]['bounded_gain']:
                    best[dep] = entry
            batch_min = min(row['bounded_gain'] for row in batch)
            if dep not in batch_minima or batch_min > batch_minima[dep]['gain']:
                batch_minima[dep] = {'department': dep, 'gain': batch_min, 'campaign': path.name, 'seeds': len(batch)}
            batches[dep].append({'campaign': path.name, 'seeds': len(batch),
                                 'gain_range': [min(r['bounded_gain'] for r in batch), max(r['bounded_gain'] for r in batch)],
                                 'positive_runs': sum(r['bounded_gain'] > 0 for r in batch),
                                 'gains': [r['bounded_gain'] for r in batch]})
    if discrepancies:
        raise ValueError(f'vote-reaggregation differences: {discrepancies[:5]}')
    # Each replacement preserves its official count; gains add independently.
    ordered = sorted((v for v in best.values() if v['bounded_gain'] > 0),
                     key=lambda x: (-x['bounded_gain'], x['department']))
    total = baseline; selected=[]
    for row in ordered:
        if total >= args.goal: break
        total += row['bounded_gain']; selected.append(row)
    # Apply the unchanged, existing bloc-level second-round projection on the
    # chosen maps and official reference for the very same departments.
    c.TARGET_NUANCE=nuance; c.TARGET_BLOC=bloc; c.TARGET_KEY=target
    projected = []
    for item in selected:
        dep=item['department']
        projected.extend(c.projected_rows(dep, item['assignment'], votes['coarse']))
        projected.extend({'department':dep, 'district_number':1000+row['district_number'],
                          'votes_by_nuance':row['votes_by_nuance'], 'estimated':True} for row in official[dep])
    builder, second = c.second_round_inputs()
    augmented = dict(mapping); augmented.update({'model:'+b:b for b in c.BLOCKS})
    model = builder.round_two_mapping_model(c.snapshot()['official_first_round'], second, projected, augmented, c.BLOCKS, 2024)
    bydep = collections.defaultdict(lambda: {'official':0, 'candidate':0})
    for row in model['districts']:
        key='official' if row['district_number'] >= 1000 else 'candidate'
        bydep[row['department']][key] += int(row['estimated'] and row['winner_bloc']==bloc)
    for item in selected:
        item['runoff_target_bloc_wins'] = bydep[item['department']]
        item['search_batches'] = batches[item['department']]
    batch_order = sorted((row for row in batch_minima.values() if row['gain'] > 0),
                         key=lambda row: (-row['gain'], row['department']))
    batch_total = baseline
    batch_selected = []
    for row in batch_order:
        if batch_total >= args.goal: break
        batch_total += row['gain']; batch_selected.append(row)
    output = {'batch_minima_summary': {'total': batch_total, 'reached': batch_total >= args.goal,
                                       'selected': batch_selected,
                                       'interpretation': 'best minimum among tested batches per department; selection-biased, not a probability'},
              'target_key': target, 'second_round_target_bloc': bloc, 'official_districts':count_official, 'official_target_leads':baseline,
              'goal':args.goal, 'tested_departments':len(tested), 'selected_departments':len(selected),
              'total_bounded_target_leads':total, 'goal_reached':total >= args.goal,
              'search_scope':'fewest departments among these verified candidate maps, not a global minimum',
              'second_round_target_bloc_wins_in_selected_departments':{
                  'official':sum(v['official'] for v in bydep.values()),
                  'candidate':sum(v['candidate'] for v in bydep.values())},
              'reports':[{'file':p.name, 'sha256':c.exp.sha(p)} for p,_ in reports],
              'selected':selected,
              'other_tested_departments': sorted(tested-{x['department'] for x in selected}),
              'vote_reaggregation_discrepancies':discrepancies}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
    print('tested',len(tested),'selected',len(selected),'baseline',baseline,'result',total,'reached',total>=args.goal)

if __name__=='__main__':main()

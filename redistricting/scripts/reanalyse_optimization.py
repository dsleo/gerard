"""Read-only rescore of EXISTING proposal traces; does not run a sampler/search.

This analysis deliberately cannot claim a new search benchmark or a generation
blindness certificate. New searches remain fail-closed behind run_blind.py.
All project data reads are restricted to named non-electoral input artifacts.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from redistrict.allocate.apportion import apportion_with_fixed
from redistrict.allocate.policy import D53_FIXED_SEATS
from redistrict.optimize.sa import Scorer, Weights, assignment_fingerprint
from redistrict.optimize.experiment import ExperimentScorer, pareto_indices
from redistrict.validate.constraints import validate_plan

PIPELINE = '20261120T001804Z-6d568ab9'
MONITOR = '20261120T001804Z-3bed7d8e'
DEPARTMENTS = ['01', '03', '13', '31', '50', '75']
WEIGHTS = [(0.5,0.3,0.2), (0.7,0.2,0.1), (0.3,0.5,0.2),
           (0.3,0.2,0.5), (1/3,1/3,1/3), (0.5,0.2,0.3), (0.5,0.4,0.1)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')


def locked_protocol():
    return {
        'analysis_type': 'retrospective_rescoring_not_new_search',
        'source_pipeline': PIPELINE, 'source_monitor': MONITOR,
        'departments': DEPARTMENTS,
        'selection': '01 medium rural; 03 small/official start; 13 dense IRIS; 31 urban/rural; 50 coastal; 75 dense urban',
        'candidate_pool': 'all unique replayable proposal states including rejected proposals, plus valid preserved starting plans',
        'v1': '.50 local maximum population deviation + .30 mean(1-PP) + .20 existing normalized EPCI excess',
        'v2': '.50 national RMS population deviation + .30 mean(1-PP) + .20 avoidable EPCI population fraction',
        'epci_fraction': '(population outside each EPCI largest part minus population-cap lower bound) / covered EPCI population',
        'epci_lower_bound': 'sum_E max(0, population_E - 1.2*department_target); lower bound only, not exact unavoidable fragmentation',
        'v2_guard': 'local max <= max(.05, archived final local max); minimum PP >= archived final minimum PP - .02',
        'pareto': ['national population MSE', 'mean(1-PP)', 'avoidable EPCI population fraction'],
        'sensitivity_weights': WEIGHTS,
        'scaled_sensitivity': 'components divided by fixed references (.10, .80, .10); exploratory, not fitted',
        'allocation_comparison': 'D\u2019Hondt and Webster; 558 seats and 74 D53 frozen seats; optimistic perfect-local-balance bounds, no redrawing',
        'claims_excluded': ['global optimality', 'new chain performance', 'effective independent sample size', 'electoral or legal superiority', 'national mixed-map certification'],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--departments', nargs='+', default=DEPARTMENTS)
    args = ap.parse_args()
    if not set(args.departments) <= set(DEPARTMENTS):
        ap.error('scope must be a subset of the recorded six-department protocol')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    protocol = locked_protocol()
    protocol_path = out / 'protocol.json'
    if protocol_path.exists() and json.loads(protocol_path.read_text()) != json.loads(json.dumps(protocol)):
        raise ValueError('protocol changed; use a new output directory')
    if not protocol_path.exists():
        write_json(protocol_path, protocol)
    input_paths = [ROOT/'data/processed/gate1/sampler_state.pkl',
                   ROOT/'data/processed/gate1/unit_geometry_wkb.pkl']
    for d in args.departments:
        input_paths.extend([ROOT/f'data/processed/optimizer_monitor/runs/{MONITOR}/traces/{d}.jsonl.gz',
                            ROOT/f'data/processed/pipeline_runs/{PIPELINE}/artifacts/starting_plans/{d}.json',
                            ROOT/f'data/processed/pipeline_runs/{PIPELINE}/artifacts/optimized_plans/{d}.json'])
    permitted = {p.resolve() for p in input_paths}
    opened = set()

    def audit(event, args):
        if event != 'open' or not args or not isinstance(args[0], (str, bytes)):
            return
        p = Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).resolve()
        mode = args[1] if len(args)>1 else None
        if p.is_relative_to(ROOT/'data/quarantine') or p.is_relative_to(ROOT/'data/raw'):
            raise PermissionError('retrospective analysis forbids quarantine and raw inputs')
        read = not isinstance(mode,str) or mode.startswith('r') or '+' in mode
        if read and p.is_relative_to(ROOT/'data'):
            if p not in permitted and not p.is_relative_to(out):
                raise PermissionError(f'unlisted retrospective input: {p}')
            if p in permitted:
                opened.add(str(p))

    sys.addaudithook(audit)
    state = pickle.loads(input_paths[0].read_bytes())
    geometry = pickle.loads(input_paths[1].read_bytes())
    national_target = sum(state['dept_pop'].values())/558
    input_hashes = {str(p.relative_to(ROOT)): digest(p) for p in input_paths}
    write_json(out/'inputs.json', input_hashes)
    for dept in args.departments:
        output = out/f'{dept}.json'
        if output.exists():
            print(f'{dept}: using completed analysis', flush=True)
            continue
        begun = time.perf_counter()
        units = {u for u in state['units'] if state['unit_dept'][u] == dept}
        adjacency = {u: frozenset(v for v in state['certification_edges'].get(u, []) if v in units) for u in units}
        target = state['dept_pop'][dept]/state['seats'][dept]
        base = Scorer({u:geometry[u] for u in sorted(units)}, state['pops'], target, state['epci_of'], Weights())
        scorer = ExperimentScorer(base,state['pops'],state['epci_of'],target,national_target)
        rows, plans, seen = [], [], {}
        trace_path = ROOT/f'data/processed/optimizer_monitor/runs/{MONITOR}/traces/{dept}.jsonl.gz'
        starts_path = ROOT/f'data/processed/pipeline_runs/{PIPELINE}/artifacts/starting_plans/{dept}.json'
        final_doc = json.loads((ROOT/f'data/processed/pipeline_runs/{PIPELINE}/artifacts/optimized_plans/{dept}.json').read_text())
        baseline_hash = assignment_fingerprint(final_doc['assignment'])
        validation_failures = []
        max_metric_error = 0.

        def add(p, source, step=None, expected=None):
            nonlocal max_metric_error
            h = assignment_fingerprint(p)
            if h not in seen:
                valid = validate_plan(p,units,state['pops'],adjacency,target,.20)
                if not valid.ok or len(set(p.values())) != state['seats'][dept]:
                    validation_failures.append({'source':source, 'step':step, 'violations':[v.detail for v in valid.violations]})
                    return
                m = scorer.components(p)
                seen[h] = len(rows)
                plans.append(dict(p))
                rows.append(dict(m, fingerprint=h, source=source, step=step))
            if expected:
                actual = rows[seen[h]]
                error = max(abs(actual[k]-expected[k]) for k in ('L','l_pop','l_comp','l_epci'))
                max_metric_error = max(max_metric_error,error)
                if error>1e-8:
                    raise ValueError(f'{dept}: replayed metric mismatch {error}')

        proposals=changed=accepted=rejected=0
        current=None
        for_trace=set()
        with gzip.open(trace_path,'rt') as f:
            for line in f:
                rec=json.loads(line)
                if rec['event']=='run_metadata':
                    if rec['sampled_plan_file_sha256'] != input_hashes[str(starts_path.relative_to(ROOT))]:
                        raise ValueError('preserved start hash differs from trace provenance')
                    trace_config=rec['configuration']
                elif rec['event']=='run_start':
                    current=rec['assignment']; add(current,'trace_start',0,rec['metrics'])
                    for_trace.add(assignment_fingerprint(current))
                elif rec['event']=='proposal':
                    if assignment_fingerprint(current)!=rec['current_before_hash']:
                        raise ValueError('trace current-before fingerprint mismatch')
                    proposed=dict(current);proposed.update(rec['candidate_delta'])
                    if assignment_fingerprint(proposed)!=rec['candidate_hash']:
                        raise ValueError('trace proposal fingerprint mismatch')
                    proposals+=1
                    if rec['proposal_status']!='no_op':
                        changed+=1; add(proposed,'proposal_'+rec['proposal_status'],rec['step'],rec['candidate'])
                        for_trace.add(assignment_fingerprint(proposed))
                    if rec['proposal_status']=='accepted':
                        current=proposed;accepted+=1
                    elif rec['proposal_status']=='rejected':
                        rejected+=1
                    if assignment_fingerprint(current)!=rec['current_hash']:
                        raise ValueError('trace current-after fingerprint mismatch')
                elif rec['event']=='run_end':
                    if assignment_fingerprint(rec['best_assignment']) != baseline_hash:
                        raise ValueError('trace final differs from preserved baseline')
        trace_count=len(rows)
        for p in json.loads(starts_path.read_text())['plans']:
            if p['valid']:
                add(p['assignment'],'preserved_start_'+p.get('source','unknown'))
        add(final_doc['assignment'],'archived_final',expected=final_doc['optimized'])
        bi=seen[baseline_hash];baseline=rows[bi]
        guard_pop=max(.05,baseline['l_pop'])
        eligible=[i for i,r in enumerate(rows) if r['l_pop'] <= guard_pop+1e-12 and r['pp_min'] >= baseline['pp_min']-.02-1e-12]
        choices={'baseline':bi, 'best_v1':min(range(len(rows)),key=lambda i:rows[i]['L_v1']),
                 'best_v2':min(range(len(rows)),key=lambda i:rows[i]['L_v2']),
                 'best_v2_guarded':min(eligible,key=lambda i:rows[i]['L_v2'])}
        front=pareto_indices(rows)
        sensitivity=[]
        for weights in WEIGHTS:
            for scale in [(1,1,1),(.10,.80,.10)]:
                def score(i):
                    r=rows[i];v=(r['pop_national_rms'],r['l_comp'],r['epci_avoidable_population_fraction'])
                    return sum(w*x/s for w,x,s in zip(weights,v,scale))
                j=min(eligible,key=score)
                sensitivity.append({'weights':weights,'scales':scale,'fingerprint':rows[j]['fingerprint'],
                                    'improvement_vs_baseline':score(bi)-score(j)})
        if validation_failures:
            raise ValueError(f'{dept}: archived candidates failed revalidation: {validation_failures[:2]}')
        selected={name:{'metrics':rows[i], 'assignment':plans[i]} for name,i in choices.items()}
        with gzip.open(out/f'{dept}_archive.json.gz','wt') as f:
            json.dump([{'metrics':r,'assignment':p} for r,p in zip(rows,plans)],f,separators=(',',':'))
        result={'department':dept,'units':len(units),'seats':state['seats'][dept],
                'population':state['dept_pop'][dept], 'national_target':national_target,
                'proposals':proposals,'changed_proposals':changed,'accepted':accepted,'rejected':rejected,
                'unique_trace_states':trace_count,'unique_states_total':len(rows),'guard_eligible_states':len(eligible),
                'front_size':len(front),'front_fingerprints':[rows[i]['fingerprint'] for i in front],
                'all_candidates_pass_partition_contiguity_population_and_seat_count':True,
                'geometry_is_coverage':bool(base._geometry_is_coverage),
                'all_unit_geometries_valid_nonempty':all(g.is_valid and not g.is_empty for g in base._geom.values()),
                'max_replayed_v1_metric_error':max_metric_error,
                'guards':{'max_local_population_deviation':guard_pop,'min_pp':baseline['pp_min']-.02},
                'selected':selected,'weight_sensitivity':sensitivity,'source_search_configuration':trace_config,
                'analysis_elapsed_seconds':time.perf_counter()-begun}
        write_json(output,result)
        print(f'{dept}: {len(rows)} valid distinct states; {len(front)} nondominated; analysis {result["analysis_elapsed_seconds"]:.1f}s',flush=True)
    # Pure arithmetic allocation comparison; no new district assignments.
    allocations={}
    for method in ['dhondt','webster']:
        seats=apportion_with_fixed(state['dept_pop'],558,method,D53_FIXED_SEATS)
        mse=sum(seats[d]*(state['dept_pop'][d]/seats[d]/national_target-1)**2 for d in seats)/558
        allocations[method]={'optimistic_rms_floor':math.sqrt(mse),'seats':seats,
                             'changed_departments':sum(seats[d]!=state['seats'][d] for d in seats)}
    write_json(out/'allocation_bounds.json',allocations)
    write_json(out/'analysis_manifest.json',{'type':'RETROSPECTIVE_NOT_GENERATION_CERTIFIED',
        'completed_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'inputs_sha256':input_hashes,
        'data_inputs_opened':sorted(opened),'protocol_sha256':digest(protocol_path),
        'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__).resolve(),ROOT/'src/redistrict/optimize/experiment.py',ROOT/'src/redistrict/optimize/sa.py']}})


if __name__=='__main__':
    main()

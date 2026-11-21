"""Refine national incumbents using a FROZEN strategy from a real pilot.

Run via run_blind.py only, after run_evolution_campaign.py completes on real
data. Synthetic winners are categorically ineligible. Outputs remain isolated
from production/export. Incomplete scope or budgets cannot claim completion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from redistrict.ingest.generation import install_generation_guard
from redistrict.allocate.policy import D53_FIXED_SEATS
from redistrict.optimize.evolve import Policy,initial_policies,run_policy,audit_results
from redistrict.parallel import dept_seed
from run_evolution_campaign import real_cases,write


def frozen_policy(pilot):
    """Predeclared deployment gate; no retuning on final-test observations.

    Prefer a new strategy only if it beats the validation-selected baseline on
    the real holdout mean AND on at least two of three department means.
    Otherwise deploy that baseline. Score/constraints never change.
    """
    summary=json.loads((pilot/'summary.json').read_text())
    if summary['status']!='COMPLETED_REAL_SEARCH_NOT_NATIONAL_CERTIFICATION':
        raise ValueError('a completed REAL pilot is required; synthetic results cannot select a real-map policy')
    if summary['retained_map_audit']['status']!='PASS_RETAINED_MAP_CHECKS':
        raise ValueError('real pilot retained-map audit did not pass')
    if summary['selection']['holdout_seen_for_selection']:
        raise ValueError('pilot selection was not frozen before holdout')
    for raw,expected in json.loads((pilot/'source_hashes.json').read_text()).items():
        path=ROOT/raw
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError(f'pilot source changed: {raw}')
    by_case={}
    for row in summary['holdout_pairs']:
        by_case.setdefault(row['case'],[]).append(row['extra_gain_percentage_points'])
    positive=sum(sum(v)/len(v)>1e-12 for v in by_case.values())
    new_policy_confirmed=(len(by_case)==3 and positive>=2 and
                          summary['holdout_selected_mean_gain']>summary['holdout_baseline_mean_gain']+1e-12)
    if new_policy_confirmed:
        return Policy(**summary['selection']['policy']),'new_policy_confirmed_on_real_holdout'
    baseline_id=summary['selection']['best_validation_baseline_id']
    baseline=next(p for p in initial_policies() if p.id==baseline_id)
    return baseline,'validation_baseline_fallback_no_confirmed_evolutionary_gain'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pilot-result',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--departments',nargs='+')
    ap.add_argument('--seeds',nargs='+',type=int,default=[509,1009,2029])
    ap.add_argument('--proposals',type=int,default=800)
    ap.add_argument('--max-seconds',type=float,default=3600)
    args=ap.parse_args()
    install_generation_guard(ROOT,'run_next_optimization_series.py')
    policy,reason=frozen_policy(args.pilot_result.resolve())
    state_path=ROOT/'data/processed/gate1/sampler_state.pkl'
    state=pickle.loads(state_path.read_bytes())
    expected=sorted(d for d,k in state['seats'].items() if d not in D53_FIXED_SEATS and k>1)
    scope=expected if args.departments is None else sorted(set(args.departments))
    if not set(scope)<=set(expected) or not scope:ap.error('only non-frozen multi-seat departments can be searched')
    if args.proposals<1 or args.max_seconds<=0 or not args.seeds:ap.error('positive budgets and seeds required')
    out=args.output.resolve()
    if out.exists():raise ValueError('use a new output directory')
    out.mkdir(parents=True);(out/'jobs').mkdir();(out/'plans').mkdir()
    config={'train':scope,'validation':[],'holdout':[]}
    protocol={'policy':policy.__dict__,'policy_id':policy.id,'policy_selection_reason':reason,
              'expected_departments':expected,'requested_departments':scope,
              'seeds':args.seeds,'proposal_budget':args.proposals,'wall_cap_seconds':args.max_seconds,
              'score':'production v1 fixed','allocation':'D53 unchanged','tree_attempt_cap':64,
              'pilot_result':str(args.pilot_result.resolve()),'publication':'no export or app changes'}
    write(out/'protocol.json',protocol)
    started=time.perf_counter();cases=real_cases(config,out);completed=[];partial=[]
    for d in scope:
        records=[]
        for seed in args.seeds:
            remaining=args.max_seconds-(time.perf_counter()-started)
            if remaining<=0:break
            result=run_policy(cases[d],policy,dept_seed(seed,d),args.proposals,64,min(60.,remaining))
            result.update(case=d,case_seed=seed)
            write(out/f'jobs/{d}_{seed}.json',result);records.append(result)
            print(d,seed,result['proposals_completed'],'gain vs incumbent',result['gain_vs_incumbent'],flush=True)
        if not records:break
        audit=audit_results({d:cases[d]},records)
        best=min(records,key=lambda r:r['best_metrics']['L_v1'])
        # Every trial includes the incumbent; this assertion is an explicit
        # non-regression gate, separate from the stochastic search logic.
        if best['best_metrics']['L_v1']>best['incumbent_L_v1']+1e-12:
            raise ValueError('incumbent non-regression check failed')
        write(out/f'plans/{d}.json',{'department':d,'assignment':best['best_assignment'],
               'metrics':best['best_metrics'],'incumbent_L_v1':best['incumbent_L_v1'],
               'strictly_improved':best['best_metrics']['L_v1']<best['incumbent_L_v1']-1e-12,
               'policy_id':policy.id,'audit':audit,'trial_count':len(records),
               'complete_department_budget':len(records)==len(args.seeds) and all(r['complete'] for r in records)})
        if len(records)==len(args.seeds) and all(r['complete'] for r in records):completed.append(d)
        else:partial.append(d)
        write(out/'progress.json',{'completed':completed,'partial':partial,
              'pending':[x for x in scope if x not in completed and x not in partial]})
    full=set(completed)==set(expected) and scope==expected
    write(out/'summary.json',{'status':'SEARCH_COMPLETED_NOT_NATIONAL_ACCEPTANCE' if full else 'PARTIAL_SEARCH',
          'completed':completed,'partial':partial,'uncompleted':[d for d in expected if d not in completed],
          'seconds':time.perf_counter()-started,'policy_id':policy.id,'published':False})
    if not full:raise SystemExit(5)


if __name__=='__main__':main()

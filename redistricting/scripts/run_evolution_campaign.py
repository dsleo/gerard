"""Benchmark, evolve bounded search policies, validate, then confirm on holdout.

Real data MUST run via run_blind.py. --prepare reads no project data and only
writes a protocol. --synthetic builds formula-defined toy graphs; it never
opens real population, geometry, archived plans or electoral files.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pickle
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from redistrict.optimize.evolve import Policy,initial_policies,evolve,run_policy,audit_results
from redistrict.optimize.experiment import ExperimentScorer
from redistrict.optimize.sa import Scorer,Weights,assignment_fingerprint
from redistrict.parallel import dept_seed


def protocol(synthetic=False):
    return {
        'version':1,'mode':'SYNTHETIC_ONLY' if synthetic else 'REAL_DATA_REQUIRES_OS_ISOLATION',
        'fixed_evaluator':'production L_v1: .50 local maximum deviation + .30 mean(1-PP) + .20 normalized EPCI splits',
        'secondary_metrics':'L_v2, population RMS, minimum PP and EPCI population fragmentation; never used to evolve fitness',
        'hard_constraints':{'population_tolerance':.20,'partition':'exact','contiguity':'certified graph','seat_count':'fixed D53'},
        'train':['toy_train_a','toy_train_b'] if synthetic else ['01','03','50'],
        'validation':['toy_validation'] if synthetic else ['13','31','75'],
        'holdout':['toy_holdout'] if synthetic else ['06','33','69'],
        'train_seeds':[11,23], 'validation_seeds':[101,202], 'holdout_seeds':[1009,1013,1019],
        'benchmark_seeds':[101,202],
        'benchmark_proposals':64 if synthetic else 192,
        'train_proposals':48 if synthetic else 96,
        'validation_proposals':96 if synthetic else 192,
        'holdout_proposals':128 if synthetic else 256,
        'policy_evaluations_per_arm':8 if synthetic else 10,
        'tree_attempt_cap':64,'flip_attempt_cap':16,'evolution_seed':73,
        'benchmark_policies':[asdict(p) for p in initial_policies()],
        'selection':'top two policies per training arm, plus four baselines; choose on mean validation gain; holdout used only after selection',
        'fitness':'negative mean relative improvement over the common best starting pool, across training cases and seeds',
        'control':'random policy search with identical domains, common four seeds and equal nominal evaluation budget',
        'promotion_rule':'validation mean relative gain >= .001 and strictly positive case-mean gain on at least half the validation cases; otherwise retain best validation baseline',
        'budgets':'equal proposal calls; all geometry setup and validation time included; timings reported, not matched',
        'wall_limits':{'campaign_seconds':1800,'trial_seconds':60},
        'incomplete_rule':'abort experiment if any job fails to complete its proposal budget; never rank partial jobs',
        'candidate_language':'bounded JSON policies; no arbitrary code, paid model call, evolved score or electoral features',
        'baseline_note':'production ReCom/cooling family, common 64-tree cap and no plateau stop; not an exact replay of the previous 800-proposal run',
        'starting_pool':'archived incumbent first, plus distinct valid archived starts, same for every policy',
        'allocation':'unchanged; this campaign tests search only',
        'evolution_note':'bounded heuristic evolution inspired by AlphaEvolve; no autonomous LLM program rewriting',
        'source':'https://arxiv.org/abs/2506.13131',
    }


def write(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def toy_cases():
    """Four predetermined connected grids, with different populations/EPCI layouts.

    Starts are row strips and column strips. Each is independently checked by
    run_policy. No initialization search or real project input is used.
    """
    from shapely.geometry import box
    from shapely import wkb
    cases={}
    for name,n,variant in [('toy_train_a',4,0),('toy_train_b',6,1),('toy_validation',6,2),('toy_holdout',6,3)]:
        units=[f'{i}:{j}' for i in range(n) for j in range(n)]
        pops={f'{i}:{j}':100+((i*7+j*11+variant*5)%21)-10 for i in range(n) for j in range(n)}
        adj={u:frozenset(f'{x}:{y}' for x,y in [(i-1,j),(i+1,j),(i,j-1),(i,j+1)] if 0<=x<n and 0<=y<n)
             for i in range(n) for j in range(n) for u in [f'{i}:{j}']}
        epci={f'{i}:{j}':f'E{(i//2)*3+j//2}' if variant%2==0 else f'E{(i+j)//2}' for i in range(n) for j in range(n)}
        geometry={f'{i}:{j}':wkb.dumps(box(j,i,j+1,i+1)) for i in range(n) for j in range(n)}
        starts=[{f'{i}:{j}':i for i in range(n) for j in range(n)},
                {f'{i}:{j}':j for i in range(n) for j in range(n)}]
        target=sum(pops.values())/n
        def maker(geo=geometry,p=pops,t=target,e=epci):
            return ExperimentScorer(Scorer(geo,p,t,e,Weights()),p,e,t,t)
        cases[name]={'name':name,'pops':pops,'adjacency':adj,'epci':epci,'starts':starts,'seats':n,'make_scorer':maker}
    return cases


def real_cases(config,out):
    # Install before reading any project data. Unsupported isolation fails here.
    from redistrict.ingest.generation import install_generation_guard
    install_generation_guard(ROOT,'run_evolution_campaign.py')
    state_path=ROOT/'data/processed/gate1/sampler_state.pkl'
    geometry_path=ROOT/'data/processed/gate1/unit_geometry_wkb.pkl'
    st=pickle.loads(state_path.read_bytes());geoms=pickle.loads(geometry_path.read_bytes())
    source=ROOT/'data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts'
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [state_path,geometry_path]}
    cases={}; national_target=sum(st['dept_pop'].values())/558
    for d in config['train']+config['validation']+config['holdout']:
        units={u for u in st['units'] if st['unit_dept'][u]==d}
        pops={u:st['pops'][u] for u in sorted(units)}
        adj={u:frozenset(v for v in st['certification_edges'].get(u,[]) if v in units) for u in sorted(units)}
        epci={u:st['epci_of'].get(u) for u in sorted(units)};geo={u:geoms[u] for u in sorted(units)}
        sp=source/f'starting_plans/{d}.json';ip=source/f'optimized_plans/{d}.json'
        hashes.update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [sp,ip]})
        incumbent=json.loads(ip.read_text())['assignment'];seen=set();starts=[]
        for p in [incumbent]+[p['assignment'] for p in json.loads(sp.read_text())['plans'] if p['valid']]:
            h=assignment_fingerprint(p)
            if h not in seen:seen.add(h);starts.append(p)
        target=sum(pops.values())/st['seats'][d]
        def maker(g=geo,p=pops,t=target,e=epci,nt=national_target):
            return ExperimentScorer(Scorer(g,p,t,e,Weights()),p,e,t,nt)
        cases[d]={'name':d,'pops':pops,'adjacency':adj,'epci':epci,'starts':starts,'seats':st['seats'][d],'make_scorer':maker}
    write(out/'inputs.json',hashes)
    return cases


def run(config,cases,out,started):
    jobs=out/'jobs';jobs.mkdir()
    records=[]
    def evaluate(policy,split,stage):
        group=config[split];seeds=config[split+'_seeds'];budget=config[split+'_proposals']
        rows=[]
        for name in group:
            for seed in seeds:
                if time.perf_counter()-started>config['wall_limits']['campaign_seconds']:
                    raise TimeoutError('campaign wall budget reached; experiment incomplete')
                path=jobs/f'{stage}_{policy.id}_{name}_{seed}.json'
                r=run_policy(cases[name],policy,dept_seed(seed,name),budget,config['tree_attempt_cap'],config['wall_limits']['trial_seconds'])
                r.update(stage=stage,case=name,case_seed=seed,split=split)
                write(path,r);records.append(r)
                if not r['complete']:raise TimeoutError('partial trial cannot be ranked')
                rows.append(r)
        print(stage,policy.id,'mean gain',f'{100*statistics.mean(r["relative_gain"] for r in rows):.3f}%',flush=True)
        return rows
    # The benchmark uses only the training cases. Validation is not touched
    # until every evolutionary/random candidate and shortlist is frozen.
    benchmark=[]
    for p in initial_policies():
        benchmark.extend(evaluate(p,'benchmark','benchmark'))
    def train_evaluator(p):
        return -statistics.mean(r['relative_gain'] for r in evaluate(p,'train','train'))
    evolution=evolve(train_evaluator,config['evolution_seed'],config['policy_evaluations_per_arm'])
    write(out/'evolution.json',evolution)
    shortlist={p.id:p for p in initial_policies()}
    for arm in ['evolution','random_control']:
        for row in evolution[arm][:2]:
            p=Policy(**row['policy']);shortlist[p.id]=p
    write(out/'frozen_validation_shortlist.json',[asdict(p) for p in shortlist.values()])
    validation={}
    for p in shortlist.values():
        validation[p.id]=evaluate(p,'validation','validation')
    mean_gain=lambda pid:statistics.mean(r['relative_gain'] for r in validation[pid])
    baseline_ids={p.id for p in initial_policies()}
    baseline_id=max(baseline_ids,key=lambda pid:(mean_gain(pid),pid))
    selected_id=max(sorted(shortlist),key=mean_gain)
    rows=validation[selected_id]
    positive=sum(statistics.mean(r['relative_gain'] for r in rows if r['case']==name)>1e-12 for name in config['validation'])
    qualifies=mean_gain(selected_id)>=.001 and positive>=math.ceil(len(config['validation'])/2)
    if not qualifies:selected_id=baseline_id
    selection={'policy_id':selected_id,'policy':asdict(shortlist[selected_id]),
               'best_validation_baseline_id':baseline_id,'validation_mean_gain':mean_gain(selected_id),
               'selected_is_seed_baseline':selected_id in baseline_ids,
               'promotion_criterion_passed':qualifies,'holdout_seen_for_selection':False}
    write(out/'frozen_selection_before_holdout.json',selection)
    holdout={}
    # All four baselines plus the SINGLE selected candidate, chosen beforehand.
    # Holdout never changes selection or generates another child policy.
    for pid in sorted(baseline_ids|{selected_id}):
        holdout[pid]=evaluate(shortlist[pid],'holdout','holdout')
    audit=audit_results(cases,records)
    write(out/'retained_map_audit.json',audit)
    with (out/'metrics.csv').open('w') as f:
        fields=['stage','case','case_seed','policy_id','proposal_budget','proposals_completed','seconds','unique_states','relative_gain','gain_vs_incumbent','best_L_v1']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in records:
            writer.writerow({**{k:r[k] for k in fields if k!='best_L_v1'},'best_L_v1':r['best_metrics']['L_v1']})
    pairs=[]
    for r in holdout[selected_id]:
        b=next(x for x in holdout[baseline_id] if x['case']==r['case'] and x['case_seed']==r['case_seed'])
        pairs.append({'case':r['case'],'seed':r['case_seed'],
                      'gain_selected':r['relative_gain'],'gain_baseline':b['relative_gain'],
                      'extra_gain_percentage_points':100*(r['relative_gain']-b['relative_gain'])})
    summary={'status':'COMPLETED_SYNTHETIC_ONLY' if config['mode']=='SYNTHETIC_ONLY' else 'COMPLETED_REAL_SEARCH_NOT_NATIONAL_CERTIFICATION',
             'trials':len(records),'proposal_calls':sum(r['proposals_completed'] for r in records),
             'seconds':time.perf_counter()-started,'selection':selection,
             'train_best_evolution_gain':-evolution['evolution'][0]['fitness'],
             'train_best_random_control_gain':-evolution['random_control'][0]['fitness'],
             'holdout_selected_mean_gain':statistics.mean(r['relative_gain'] for r in holdout[selected_id]),
             'holdout_baseline_mean_gain':statistics.mean(r['relative_gain'] for r in holdout[baseline_id]),
             'holdout_pairs':pairs,
             'retained_map_audit':audit,
             'warning':'toy-grid results cannot rank real-map methods' if config['mode']=='SYNTHETIC_ONLY' else 'small pilot; no global optimality or electoral fairness claim'}
    write(out/'summary.json',summary)
    return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--prepare',action='store_true')
    ap.add_argument('--synthetic',action='store_true')
    args=ap.parse_args()
    if args.prepare and args.synthetic:ap.error('prepare records the prospective real-data protocol')
    config=protocol(args.synthetic)
    # Benchmark train split is explicit; no validation/holdout leakage.
    config['benchmark']=list(config['train'])
    if not args.prepare and not args.synthetic:
        from redistrict.ingest.generation import install_generation_guard
        install_generation_guard(ROOT,'run_evolution_campaign.py')
    out=args.output.resolve()
    if out.exists():raise ValueError('use a new output directory; previous outputs are immutable')
    out.mkdir(parents=True)
    write(out/'protocol.json',config)
    sources=[Path(__file__).resolve(),ROOT/'src/redistrict/optimize/evolve.py',ROOT/'src/redistrict/optimize/experiment.py',ROOT/'src/redistrict/optimize/sa.py',ROOT/'src/redistrict/sample/recom.py',ROOT/'src/redistrict/metrics/population.py',ROOT/'src/redistrict/validate/constraints.py']
    write(out/'source_hashes.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    if args.prepare:
        write(out/'status.json',{'status':'PREPARED_NOT_RUN','reason':'OS isolation smoke check denied in current execution environment'})
        write(out/'next_optimization_series.json',{
            'status':'PREPARED_PENDING_REAL_PILOT_AND_AUDIT',
            'allocation':'existing D53 unchanged','score':'fixed production v1; v2 audit only',
            'scope':'all non-frozen departments with more than one constituency; resolve from hashed Gate 1 state',
            'unchanged_scope':'D53 frozen departments and one-constituency departments',
            'starting_pool':'audited incumbent plus distinct valid archived starts',
            'policy':'frozen winner of the completed real pilot; otherwise best validation baseline, never the synthetic winner',
            'seeds':[509,1009,2029],'proposals_per_department_seed':800,
            'wall_cap_seconds':3600,'incomplete_behavior':'checkpoint and report unfinished departments, never silently label national completion',
            'selection':'retain incumbent and only promote a strictly lower v1 score; archive alternative non-dominated valid maps',
            'promotion':'real pilot plus retained-map geometry/constraint audit; national export needs the existing national acceptance workflow',
            'execution':'plan only; not automatically launched by this pilot command',
        })
        print('Prepared protocol; no real-data search executed:',out);return
    started=time.perf_counter()
    try:
        result=run(config,toy_cases() if args.synthetic else real_cases(config,out),out,started)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as error:
        write(out/'status.json',{'status':'INCOMPLETE','error':type(error).__name__,'detail':str(error)})
        raise


if __name__=='__main__':main()

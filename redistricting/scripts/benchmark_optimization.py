"""Prospective equal-proposal-budget benchmark. MUST run via run_blind.py.

Does not overwrite production plans or the published map. Example:
  .venv/bin/python scripts/run_blind.py benchmark_optimization.py --output data/processed/pipeline_runs/optimization_benchmark
No wall-clock superiority claim follows from an equal-proposal-budget trial.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from redistrict.ingest.generation import install_generation_guard
from redistrict.optimize.sa import Scorer,Weights
from redistrict.optimize.experiment import ExperimentScorer,search
from redistrict.parallel import dept_seed
from redistrict.validate.constraints import validate_plan

install_generation_guard(ROOT,'benchmark_optimization.py')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--departments',nargs='+',default=['01','03','13','31','50','75'])
    ap.add_argument('--seeds',nargs='+',type=int,default=[101,202,303])
    ap.add_argument('--proposals',type=int,default=800)
    args=ap.parse_args()
    out=args.output.resolve()
    if out.exists():
        raise ValueError('use a new output directory to preserve previous results')
    out.mkdir(parents=True)
    state_path=ROOT/'data/processed/gate1/sampler_state.pkl'
    geom_path=ROOT/'data/processed/gate1/unit_geometry_wkb.pkl'
    st=pickle.loads(state_path.read_bytes());geometry=pickle.loads(geom_path.read_bytes())
    config={'departments':args.departments,'seeds':args.seeds,'proposals':args.proposals,
            'objectives':['L_v1','L_v2'],'methods':['sa_single','sa_multistart','pareto_bursts'],
            'budget':'proposal count; wall time measured, not matched','tolerance':.2,
            'production_cooling':{'t0':.02,'t1':.0005,'plateau_stopping':False},
            'input_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [state_path,geom_path]}}
    (out/'protocol.json').write_text(json.dumps(config,indent=2))
    nt=sum(st['dept_pop'].values())/558
    source=ROOT/'data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts/starting_plans'
    for d in args.departments:
        units={u for u in st['units'] if st['unit_dept'][u]==d}
        target=st['dept_pop'][d]/st['seats'][d]
        adj={u:frozenset(v for v in st['certification_edges'].get(u,[]) if v in units) for u in units}
        start_path=source/f'{d}.json'
        starts=[p['assignment'] for p in json.loads(start_path.read_text())['plans'] if p['valid']]
        for p in starts:
            if not validate_plan(p,units,st['pops'],adj,target,.2).ok or len(set(p.values()))!=st['seats'][d]:
                raise ValueError(f'invalid start: {d}')
        for seed in args.seeds:
            for objective in config['objectives']:
                for method in config['methods']:
                    # Fresh cache for each arm so elapsed times include equivalent
                    # scoring setup rather than inheriting another arm's warm cache.
                    base=Scorer({u:geometry[u] for u in sorted(units)},st['pops'],target,st['epci_of'],Weights())
                    scorer=ExperimentScorer(base,st['pops'],st['epci_of'],target,nt)
                    result=search(starts,adj,st['pops'],scorer,target,dept_seed(seed,d),method,objective,args.proposals)
                    for p in [result['best_assignment']]+[x['assignment'] for x in result['front']]:
                        if not validate_plan(p,units,st['pops'],adj,target,.2).ok or len(set(p.values()))!=st['seats'][d]:
                            raise ValueError('search returned invalid map')
                    result['starting_file_sha256']=hashlib.sha256(start_path.read_bytes()).hexdigest()
                    (out/f'{d}_{seed}_{objective}_{method}.json').write_text(json.dumps(result))
                    print(d,seed,objective,method,result['best_metrics'][objective],flush=True)


if __name__=='__main__':
    main()

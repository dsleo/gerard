"""Search valid departmental maps for projected runoff seats, with LFI split."""
import argparse,collections,concurrent.futures,json,multiprocessing,pickle,random,tarfile,time
from pathlib import Path
import experiment_partisan_campaign as c
import experiment_partisan_search as e
import runoff_model_split as split
from partisan_split_votes import allocate_split_votes

TARGETS=split.BLOCKS[:-1]
DEPS=['01','03','14','16','19','26','27','37','40','43','45','50','60','63','64','68','73','79','81','87','89']
STATE=VOTES=SCORER=OFFICIAL=REPORTS=COVERAGE=None

def search_department(dep,budget,seeds):
    state=STATE; units={u for u in state['units'] if state['unit_dept'][u]==dep}; votes=VOTES
    official=OFFICIAL[dep]; seats=len(official)
    if not units or not seats:return {'status':'excluded_missing_inputs'}
    adj={u:frozenset(v for v in state['certification_edges'].get(u,()) if v in units) for u in units}
    target_pop=state['dept_pop'][dep]/seats
    for u in units:
        if u not in votes and state['pops'][u]:return {'status':'excluded_missing_votes'}
        votes.setdefault(u,{})
    parents={u[:5] for u in units if len(u)>=9}|{u for u in units if u in COVERAGE}
    if parents and min(COVERAGE.get(p,0) for p in parents)<.99:return {'status':'excluded_incomplete_allocation'}
    starts=[]
    for report in REPORTS:
        result=report['results'].get(dep,{})
        if result.get('status')!='tested':continue
        starts.extend([result['start_assignment']]+[r['assignment'] for r in result['runs']])
    unique={json.dumps(p,sort_keys=True):p for p in starts}
    starts=[p for p in unique.values() if len(set(p.values()))==seats and c.validate_plan(p,units,state['pops'],adj,target_pop,.2).ok]
    if not starts:return {'status':'excluded_no_valid_start'}
    original={b:0 for b in TARGETS}
    for row in official:
        v=collections.defaultdict(float)
        for n,count in row['votes_by_nuance'].items():v[SCORER.mapping.get(n,'other')]+=count
        win=SCORER.winner(v)
        if win in original:original[win]+=1
    results={}
    for target in TARGETS:
        e.metrics=lambda plan,vs,bloc:SCORER.score(plan,vs,bloc)
        start=max(starts,key=lambda p:e.rank(e.metrics(p,votes,target)))
        best=start; metrics=e.metrics(start,votes,target); tried=[]
        for seed in seeds:
            for method in ('anneal_recom','greedy_flip'):
                candidate,info=e.search(start,adj,state['pops'],target_pop,.2,votes,target,method,budget,seed)
                if e.rank(info['metrics'])>e.rank(metrics):best,metrics=candidate,info['metrics']
                tried.append({'seed':seed,'method':method,'seats':info['metrics']['pluralities']})
        checked=c.validate_plan(best,units,state['pops'],adj,target_pop,.2)
        if not checked.ok:raise ValueError('invalid result '+dep)
        results[target]={'assignment':best,'projected_seats':metrics['pluralities'],'official_projected_seats':original[target],
                         'gain':metrics['pluralities']-original[target],'districts':seats,'runs':tried,'max_population_deviation':checked.max_deviation}
    return {'status':'tested','targets':results,'starts':len(starts),'split_coverage_by_commune':{p:COVERAGE[p] for p in sorted(parents)}}

def main():
    global STATE,VOTES,SCORER,OFFICIAL,REPORTS,COVERAGE
    p=argparse.ArgumentParser();p.add_argument('--budget',type=int,default=120);p.add_argument('--seeds',nargs='+',type=int,default=[3101,3102]);p.add_argument('--workers',type=int,default=4);p.add_argument('--departments',nargs='+',default=DEPS);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('output already exists')
    builder,defs,mapping,aff,first,second=split.inputs();SCORER=split.Scorer(builder,mapping,first,second)
    STATE=pickle.loads(e.STATE.read_bytes()); deps=set(args.departments)
    votes=e.load_votes(e.VOTES,deps,defs,None,aff)
    votes,COVERAGE,missing,details=allocate_split_votes(STATE,deps,votes,defs,None,c.CROSSWALK,c.BUREAUX,aff)
    VOTES={unit:split.merge_lfi_votes(counts) for unit,counts in votes['coarse'].items()}
    OFFICIAL=collections.defaultdict(list)
    for row in first:OFFICIAL[row['department']].append(row)
    archives=[Path(__file__).resolve().parents[2]/'docs/redistricting'/name for name in ('18_remaining_bloc_runs.tar.gz','15_left_campaign_runs.tar.gz','14_national_campaign_runs.tar.gz')]
    REPORTS=[]
    for archive in archives:
        with tarfile.open(archive) as tar:
            REPORTS.extend(json.load(tar.extractfile(item)) for item in tar.getmembers() if item.name.endswith('.json'))
    print('loaded',len(first),'districts;',len(REPORTS),'campaign reports',flush=True)
    results={}
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('fork')) as pool:
        futures={pool.submit(search_department,dep,args.budget,args.seeds):dep for dep in args.departments}
        for future in concurrent.futures.as_completed(futures):
            dep=futures[future];results[dep]=future.result();print(dep,results[dep]['status'],{b:r['gain'] for b,r in results[dep].get('targets',{}).items()},flush=True)
    baseline=builder.round_two_mapping_model(first,second,first,mapping,split.BLOCKS,2024)
    report={'method':'2024 candidate financial attachment split; calibrated nearest-duel central prediction; optimized projected second-round seats','baseline':{b:baseline['seat_projection'][b]['seats'] for b in split.BLOCKS},'budget_per_method':args.budget,'seeds':args.seeds,'departments':results}
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()

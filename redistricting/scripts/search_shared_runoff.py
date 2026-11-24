"""Share every valid proposed map among target-specific runoff searches."""
import argparse,collections,concurrent.futures,json,math,multiprocessing,pickle,random,tarfile
from pathlib import Path
import experiment_partisan_campaign as campaign
import experiment_partisan_search as exp
import runoff_model_split as split
from partisan_split_votes import allocate_split_votes
from redistrict.sample.recom import recom_step

TARGETS=split.BLOCKS[:-1]
STATE=VOTES=SCORER=PRIOR=COVERAGE=None

def rank(score):
    return score['pluralities'],score['smooth_score']

def preferred_pair(plan, adjacency, votes, target, scorer, rng, focus_probability=.7):
    """Favor districts close to qualifying or to the modeled runoff threshold.

    A uniform move remains possible with probability 1-focus_probability.
    Scores describe the *current candidate*, not fixed official districts.
    """
    if rng.random() >= focus_probability: return None
    groups=collections.defaultdict(lambda:collections.defaultdict(float))
    for unit,district in plan.items():
        for bloc,count in votes.get(unit,{}).items(): groups[district][bloc]+=count
    sensitivity={}
    for district,counts in groups.items():
        total=sum(counts.values())
        if not total: sensitivity[district]=0; continue
        shares={b:counts.get(b,0)/total for b in split.BLOCKS}
        finalists=sorted(split.BLOCKS,key=lambda b:shares[b],reverse=True)[:2]
        if target in finalists:
            a,b,p=scorer.prediction(counts)
            distance=abs(p-.5)
        else:
            distance=max(0,shares[finalists[1]]-shares[target])
        sensitivity[district]=math.exp(-distance/.08)
    pairs=sorted({tuple(sorted((plan[u],plan[v]))) for u in plan for v in adjacency.get(u,()) if v in plan and plan[u]!=plan[v]})
    if not pairs:return None
    weights=[.05+max(sensitivity.get(a,0),sensitivity.get(b,0)) for a,b in pairs]
    return rng.choices(pairs,weights=weights,k=1)[0]

class SharedArchive:
    def __init__(self,scorer,votes):
        self.scorer,self.votes=scorer,votes
        self.best={};self.cross_updates=collections.Counter();self.count=0
    def observe(self,plan,origin):
        scores=self.scorer.all_scores(plan,self.votes);self.count+=1
        for target in TARGETS:
            had_best = target in self.best
            if not had_best or rank(scores[target])>rank(self.best[target]['score']):
                self.best[target]={'assignment':dict(plan),'score':scores[target],'origin':dict(origin)}
                if had_best and origin.get('target') not in (None,target): self.cross_updates[target]+=1
        return scores

def search_department(dep,budget,seeds,rounds,focus):
    prior=PRIOR[dep]
    if prior['status']!='tested':return {'status':prior['status']}
    units={u for u in STATE['units'] if STATE['unit_dept'][u]==dep}
    adj={u:frozenset(v for v in STATE['certification_edges'].get(u,()) if v in units) for u in units}
    seats=prior['targets']['lfi']['districts']; pop=STATE['pops'];target_pop=STATE['dept_pop'][dep]/seats
    for unit in units:
        if unit not in VOTES and pop[unit]:raise ValueError(f'missing votes {dep} {unit}')
        VOTES.setdefault(unit,{})
    archive=SharedArchive(SCORER,VOTES)
    seen=set()
    for target in TARGETS:
        plan=prior['targets'][target]['assignment']; key=tuple(sorted(plan.items()))
        if key in seen:continue
        seen.add(key)
        checked=campaign.validate_plan(plan,units,pop,adj,target_pop,.2)
        if not checked.ok or len(set(plan.values()))!=seats:raise ValueError(f'invalid prior map {dep}')
        archive.observe(plan,{'target':target,'method':'previous_run'})
    seed_baseline={b:archive.best[b]['score']['pluralities'] for b in TARGETS}
    for turn in range(rounds):
        for target in TARGETS:
            for seed in seeds:
                for method in ('anneal_recom','greedy_flip'):
                    rng=random.Random(f'{dep}:{turn}:{target}:{seed}:{method}')
                    current=dict(archive.best[target]['assignment'])
                    current_score=SCORER.all_scores(current,VOTES)[target]
                    for step in range(budget):
                        if method=='anneal_recom':
                            pair=preferred_pair(current,adj,VOTES,target,SCORER,rng,focus)
                            candidate=recom_step(current,adj,pop,target_pop,.2,rng,preferred_pair=pair)
                        else:
                            candidate=exp.flip(current,adj,pop,target_pop,.2,rng)
                        if candidate==current:continue
                        checked=campaign.validate_plan(candidate,units,pop,adj,target_pop,.2)
                        if not checked.ok or len(set(candidate.values()))!=seats:raise ValueError(f'invalid proposal {dep}')
                        scores=archive.observe(candidate,{'target':target,'method':method,'round':turn,'seed':seed,'step':step})
                        new=scores[target]
                        if method=='greedy_flip': accept=rank(new)>=rank(current_score)
                        else:
                            old_j=current_score['pluralities']+current_score['smooth_score']/(seats+1)
                            new_j=new['pluralities']+new['smooth_score']/(seats+1)
                            temp=.3*(.01/.3)**(step/max(1,budget-1))
                            accept=new_j>=old_j or rng.random()<math.exp((new_j-old_j)/temp)
                        if accept:current,current_score=candidate,new
    results={}
    for target in TARGETS:
        best=archive.best[target];previous=prior['targets'][target]
        checked=campaign.validate_plan(best['assignment'],units,pop,adj,target_pop,.2)
        count=best['score']['pluralities'];official=previous['official_projected_seats']
        if count<previous['projected_seats']:raise ValueError(f'regression {dep} {target}')
        results[target]={'assignment':best['assignment'],'projected_seats':count,'official_projected_seats':official,
                         'previous_projected_seats':previous['projected_seats'],'gain':count-official,'districts':seats,
                         'origin':best['origin'],'cross_updates':archive.cross_updates[target],
                         'max_population_deviation':checked.max_deviation}
    return {'status':'tested','targets':results,'initial_shared_best':seed_baseline,'scored_candidates':archive.count,
            'split_coverage_by_commune':prior['split_coverage_by_commune']}

def main():
    global STATE,VOTES,SCORER,PRIOR,COVERAGE
    p=argparse.ArgumentParser();p.add_argument('--budget',type=int,default=100);p.add_argument('--seeds',nargs='+',type=int,default=[5101,5102]);p.add_argument('--rounds',type=int,default=2);p.add_argument('--focus',type=float,default=.7);p.add_argument('--workers',type=int,default=4);p.add_argument('--departments',nargs='+');p.add_argument('--output',type=Path,required=True);p.add_argument('--checkpoint-dir',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('output already exists')
    if args.budget<1 or args.rounds<1 or not 0<=args.focus<=1:p.error('invalid search parameters')
    builder,defs,mapping,aff,first,second=split.inputs();SCORER=split.Scorer(builder,mapping,first,second)
    STATE=pickle.loads(exp.STATE.read_bytes());PRIOR={};baselines=[]
    archive=Path(__file__).resolve().parents[2]/'docs/redistricting/19_runoff_search_runs.tar.gz'
    with tarfile.open(archive) as tar:
        for item in tar.getmembers():
            if not item.name.endswith('.json'):continue
            data=json.load(tar.extractfile(item));baselines.append(data['baseline']);PRIOR.update(data['departments'])
    if any(b!=baselines[0] for b in baselines):raise ValueError('inconsistent prior baselines')
    deps=args.departments or sorted(PRIOR);unknown=set(deps)-set(PRIOR)
    if unknown:p.error(f'departments absent from previous campaign: {sorted(unknown)}')
    votes=exp.load_votes(exp.VOTES,set(deps),defs,None,aff)
    votes,COVERAGE,_,_=allocate_split_votes(STATE,set(deps),votes,defs,None,campaign.CROSSWALK,campaign.BUREAUX,aff)
    VOTES={u:split.merge_lfi_votes(counts) for u,counts in votes['coarse'].items()}
    args.checkpoint_dir.mkdir(parents=True,exist_ok=True);results={}
    print('loaded',len(deps),'departments; prior baseline',baselines[0],flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('fork')) as pool:
        futures={pool.submit(search_department,dep,args.budget,args.seeds,args.rounds,args.focus):dep for dep in deps}
        for future in concurrent.futures.as_completed(futures):
            dep=futures[future];row=future.result();results[dep]=row
            (args.checkpoint_dir/f'{dep}.json').write_text(json.dumps(row,sort_keys=True)+'\n')
            print(dep,row['status'],{b:r['projected_seats']-r['previous_projected_seats'] for b,r in row.get('targets',{}).items()},flush=True)
    report={'method':'shared candidate archive, target-specific annealed recom and greedy flips','baseline':baselines[0],
            'budget_per_method_per_round':args.budget,'rounds':args.rounds,'seeds':args.seeds,
            'focus_probability':args.focus,'departments':results}
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()

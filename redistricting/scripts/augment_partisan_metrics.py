"""Add comparable vote-distribution, population and EPCI metrics to saved scenarios."""
import argparse,base64,collections,gzip,hashlib,json,pickle,re,sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'src'))
import experiment_partisan_campaign as c
import experiment_partisan_search as e
import runoff_model_split as split
from partisan_split_votes import allocate_split_votes
from redistrict.metrics.population import epci_split_count,epci_split_lower_bound,epci_split_max_possible

def main():
 p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--compactness',type=Path);args=p.parse_args(); local=args.data_root
 compactness=json.loads(args.compactness.read_text()) if args.compactness else None
 e.VOTES=local/'data/quarantine/electoral/legislatives_2024_t1_communes.csv';c.CROSSWALK=local/'data/quarantine/electoral/liaison_iris_bureaux_de_vote_2024.csv';c.BUREAUX=local/'data/quarantine/electoral/legislatives_2024_t1_bureaux.csv';c.SECOND=local/'data/quarantine/electoral/legislatives_2024_t2_circonscriptions.csv'
 state=pickle.loads((local/'data/processed/gate1/sampler_state.pkl').read_bytes()); builder,_=c.second_round_inputs();snap=c.snapshot();defs=yaml.safe_load(e.BLOCS.read_text())['mappings'];mapping={n:b for b,ns in defs['coarse']['blocs'].items() for n in ns};keys=split.BLOCKS
 sources={'lfi':'22_lfi_expected.json','left':'22_left_expected.json','centre':'22_centre_expected.json','right':'22_right_expected.json','far_right':'22_far_right_expected.json','other':'18_other_scenario.json'};plans={k:json.loads((ROOT.parent/'docs/redistricting'/v).read_text())['selected'] for k,v in sources.items()}; deps={r['department'] for v in plans.values() for r in v}
 builder,defs,mapping,aff,first,second=split.inputs(); snap['official_first_round']=first
 votes=e.load_votes(e.VOTES,deps,defs,None,aff);votes,_,_,_=allocate_split_votes(state,deps,votes,defs,None,c.CROSSWALK,c.BUREAUX,aff)
 votes['coarse']={unit:split.merge_lfi_votes(counts) for unit,counts in votes['coarse'].items()}
 metricfile=local/'data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts/national_draft/heuristic_national_comparison.json'; original=json.loads(metricfile.read_text())['official_metrics']; national=original['national_target_population_per_district']
 out=ROOT/'export/browser/partisan-scenarios.js';m=re.search(r'atob\("([A-Za-z0-9+/=]+)"\)',out.read_text());payload=json.loads(gzip.decompress(base64.b64decode(m.group(1))))
 base_votes={f"{r['department']}-{r['district_number']}":{b:sum(float(v) for n,v in r['votes_by_nuance'].items() if mapping.get(n,'other')==b) for b in keys} for r in snap['official_first_round'] if builder.is_metropolitan_department(r['department'])}
 baseline=builder.metric_summary(base_votes)
 for name,selected in plans.items():
  payload['scenarios'][name]['source_sha256']=hashlib.sha256((ROOT.parent/'docs/redistricting'/sources[name]).read_bytes()).hexdigest()
  replacements={r['department']:r['assignment'] for r in selected}; bloc_votes={k:v for k,v in base_votes.items() if k.split('-')[0] not in replacements};districts=[r for r in original['district_details'] if r['department'] not in replacements]; depts=[r for r in original['department_details'] if r['department'] not in replacements]
  for dep,plan in replacements.items():
   grouped=collections.defaultdict(lambda:collections.defaultdict(float));pops=collections.Counter()
   for unit,district in plan.items():
    pops[district]+=state['pops'][unit]
    for bloc,count in votes['coarse'].get(unit,{}).items():grouped[district][bloc]+=count
   for district,pop in pops.items():
    districts.append({'department':dep,'population':pop,'national_deviation':abs(pop-national)/national})
    if builder.is_metropolitan_department(dep): bloc_votes[f'{dep}-{district}']=dict(grouped[district])
   excess,_=epci_split_count(plan,state['epci_of']);depts.append({'epci_excess':excess,'epci_lower_bound':epci_split_lower_bound(plan,state['epci_of']),'epci_max_possible':epci_split_max_possible(plan,state['epci_of'])})
  if len(districts)!=len(original['district_details']):raise ValueError('district totals changed')
  excess=sum(d['epci_excess'] for d in depts);lower=sum(d['epci_lower_bound'] for d in depts);maximum=sum(d['epci_max_possible'] for d in depts)
  value={'population_max_abs_deviation_from_national_target':max(d['national_deviation'] for d in districts),'epci_pooled_avoidable_ratio':max(0,excess-lower)/max(1,maximum-lower)}
  if compactness:
   if abs(compactness['official']-original['compactness_loss_mean_1_minus_polsby_popper'])>1e-8:raise ValueError('compactness baseline mismatch')
   value['compactness_loss_mean_1_minus_polsby_popper']=compactness['scenarios'][name]
  result=builder.metric_summary(bloc_votes);payload['scenarios'][name]['territorial_metrics']=value;payload['scenarios'][name]['mmd_delta']={b:result['blocks'][b]['mmd']-baseline['blocks'][b]['mmd'] for b in keys};print(name,value,payload['scenarios'][name]['mmd_delta'],flush=True)
 raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode(); encoded=base64.b64encode(gzip.compress(raw,compresslevel=9,mtime=0)).decode();out.write_text("window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};window.REDISTRICTING_DATA['partisan-scenarios']=(async()=>{const b=Uint8Array.from(atob(\""+encoded+"\"),c=>c.charCodeAt(0));const d=new DecompressionStream('gzip');return JSON.parse(await new Response(new Blob([b]).stream().pipeThrough(d)).text())})();\n")
if __name__=='__main__':main()

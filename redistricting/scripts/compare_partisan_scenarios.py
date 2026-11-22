import sys,json,csv,pickle,collections,yaml,argparse
from pathlib import Path
root=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(root/'redistricting/scripts'))
import experiment_partisan_campaign as c, experiment_partisan_search as e
from partisan_split_votes import allocate_split_votes
from partisan_affiliations import load_affiliations,affiliation_for,PARTY_LFI
parser=argparse.ArgumentParser(); parser.add_argument('--data-root',type=Path,default=root/'redistricting'); args=parser.parse_args(); old=args.data_root; e.STATE=old/'data/processed/gate1/sampler_state.pkl'; e.VOTES=old/'data/quarantine/electoral/legislatives_2024_t1_communes.csv'; c.FIRST=old/'data/quarantine/electoral/legislatives_2024_t1_circonscriptions.csv'; c.AFFILIATION=old/'data/quarantine/electoral/rattachement-candidats-leg-2024.xlsx'; c.CROSSWALK=old/'data/quarantine/electoral/liaison_iris_bureaux_de_vote_2024.csv'; c.BUREAUX=old/'data/quarantine/electoral/legislatives_2024_t1_bureaux.csv'
state=pickle.loads(e.STATE.read_bytes()); defs=yaml.safe_load(e.BLOCS.read_text())['mappings']; mapping={n:b for b,ns in defs['coarse']['blocs'].items() for n in ns}
files={'RN':'14_national_partisan_scenario.json','Gauche':'15_broad_left_scenario.json','LFI':'15_lfi_attachment_scenario.json'}; plans={k:json.loads((root/'docs/redistricting'/v).read_text())['selected'] for k,v in files.items()}; deps={r['department'] for rows in plans.values() for r in rows}; aff=load_affiliations(c.AFFILIATION,c.FIRST)
registered=collections.Counter()
with e.VOTES.open(encoding='utf-8-sig') as f:
 for row in csv.DictReader(f,delimiter=';'):
  if row['Code département'].strip().upper().zfill(2) in deps:registered[row['Code commune'].strip().upper().zfill(5)]+=int((row['Inscrits'] or '0').replace(' ',''))
allresults={}
for target,nuance,attachment in [('RN','RN',None),('Gauche',None,None),('LFI',None,aff)]:
 key={'RN':'party:RN','Gauche':'left','LFI':'party:LFI'}[target]; official=collections.Counter()
 with c.FIRST.open(encoding='utf-8-sig') as f:
  for row in csv.DictReader(f,delimiter=';'):
   dep=row['Code département'].strip().upper().zfill(2); b=collections.Counter()
   for col,n in row.items():
    if not col.startswith('Nuance candidat ') or not n.strip():continue
    slot=col.rsplit(' ',1)[1];count=int((row['Voix '+slot] or '0').replace(' ',''));label=('party:RN' if nuance and n==nuance else mapping.get(n,'other'))
    if attachment and affiliation_for(attachment,row,slot)==PARTY_LFI:label='party:LFI'
    b[label]+=count
   if min(b,key=lambda v:(-b[v],v))==key:official[dep]+=1
 base=sum(official.values());votes=e.load_votes(e.VOTES,deps,defs,nuance,attachment);votes,coverage,missing,detail=allocate_split_votes(state,deps,votes,defs,nuance,c.CROSSWALK,c.BUREAUX,attachment); result={'officiel':base}
 for scenario,items in plans.items():
  total=base
  for item in items:
   dep=item['department'];units={u for u in state['units'] if state['unit_dept'][u]==dep}; vv=votes['coarse']
   for u in units:
    if u not in vv:
     if state['pops'][u]:raise ValueError((dep,u))
     vv[u]={}
   extra={u for u in vv if u.startswith(dep)}-units; extra_reg=sum(registered[u] for u in extra); split={u[:5] for u in units if len(u)>=9}|{u for u in units if u in coverage};unknown=extra_reg+(missing.get(dep,0) if split else 0)
   total+=c.robust_pluralities(item['assignment'],vv,key,unknown,detail if split else None,extra_reg)-official[dep]
  result[scenario]=total
 allresults[target]=result; print(target,result,flush=True)
print(json.dumps(allresults))

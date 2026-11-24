"""Assemble departmental maps by gains in expected simulated runoff seats."""
import argparse,hashlib,json
from pathlib import Path
import runoff_model_split as split

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path);parser.add_argument('--output-dir',required=True,type=Path);args=parser.parse_args()
    report=json.loads(args.report.read_text());tested={d:r for d,r in report['departments'].items() if r['status']=='tested'}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for bloc in split.BLOCKS[:-1]:
        selected=[{'department':dep,**row['targets'][bloc]} for dep,row in tested.items() if row['targets'][bloc]['gain']>1e-9]
        selected.sort(key=lambda r:(-r['gain'],r['department']))
        base=report['baseline'][bloc]; total=base+sum(r['gain'] for r in selected)
        data={'objective':'expected seats under empirical runoff residual simulation','target_key':bloc,
              'official_districts':559,'baseline_expected_seats':base,'total_expected_seats':total,
              'tested_departments':len(tested),'screened_departments':len(report['departments']),
              'selected_departments':len(selected),'selected':selected,
              'other_tested_departments':sorted(set(tested)-{r['department'] for r in selected}),
              'excluded_departments':{d:r['status'] for d,r in report['departments'].items() if r['status']!='tested'},
              'search_scope':'best found in eligible screened departments; not a national optimum',
              'report':{'file':args.report.name,'sha256':hashlib.sha256(args.report.read_bytes()).hexdigest()}}
        path=args.output_dir/f'22_{bloc}_expected.json'
        if path.exists():raise FileExistsError(path)
        path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
        print(bloc,round(base,2),round(total,2),len(selected))
if __name__=='__main__':main()

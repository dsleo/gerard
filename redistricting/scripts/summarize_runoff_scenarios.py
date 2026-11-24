"""Combine independent runoff search batches into reproducible hybrid maps."""
import argparse
import hashlib
import json
from pathlib import Path
import runoff_model_split as split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    reports = [json.loads(p.read_text()) for p in args.reports]
    baseline = reports[0]['baseline']
    if any(report['baseline'] != baseline for report in reports):
        raise ValueError('campaigns have different model baselines')
    results = {}
    for report in reports:
        for dep, row in report['departments'].items():
            if dep in results:
                raise ValueError(f'duplicate department: {dep}')
            results[dep] = row
    tested = {dep: row for dep, row in results.items() if row['status'] == 'tested'}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for target in split.BLOCKS[:-1]:
        selected = [{'department':dep, **row['targets'][target]} for dep,row in tested.items()
                    if row['targets'][target]['gain'] > 0]
        selected.sort(key=lambda row:(-row['gain'],row['department']))
        data = {'objective':'estimated second-round seats', 'target_key':target,
                'official_districts':559, 'baseline_projected_seats':baseline[target],
                'total_projected_seats':baseline[target]+sum(row['gain'] for row in selected),
                'tested_departments':len(tested), 'selected_departments':len(selected),
                'selected':selected,
                'other_tested_departments':sorted(set(tested)-{row['department'] for row in selected}),
                'search_scope':'best found in screened departments; not a national optimum',
                'reports':[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in args.reports]}
        path = args.output_dir / f'19_{target}_runoff.json'
        if path.exists(): raise FileExistsError(path)
        path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
        print(target, baseline[target], data['total_projected_seats'], len(selected))

if __name__ == '__main__': main()

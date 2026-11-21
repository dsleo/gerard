"""Independent geometry check of archived candidates, without any new search."""
import argparse
import gzip
import hashlib
import json
import pickle
from pathlib import Path

from shapely import STRtree, wkb

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);args=ap.parse_args();out=args.directory
    path=ROOT/'data/processed/gate1/unit_geometry_wkb.pkl'
    # Only the named, previously-hashed geometry input is opened. No raw or
    # electoral data is used. Reuse pair intersections across all assignments.
    expected=json.loads((out/'inputs.json').read_text())[str(path.relative_to(ROOT))]
    blob=path.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=expected:raise ValueError('geometry input changed')
    geometries=pickle.loads(blob);result={}
    for dept in ['01','03','13','31','50','75']:
        with gzip.open(out/f'{dept}_archive.json.gz','rt') as f:archive=json.load(f)
        units=sorted(archive[0]['assignment']);shapes=[wkb.loads(geometries[u]) for u in units]
        tree=STRtree(shapes);positive=[];conflicts=[];max_area=0.
        for i,g in enumerate(shapes):
            for j in tree.query(g,predicate='intersects'):
                j=int(j)
                if j<=i:continue
                area=g.intersection(shapes[j]).area
                if area>0:
                    max_area=max(max_area,area);positive.append((i,j,area))
                if area>1.:conflicts.append((units[i],units[j],area))
        invalid=[];max_cross=0.
        for row in archive:
            p=row['assignment']
            for i,j,area in positive:
                if p[units[i]]!=p[units[j]]:max_cross=max(max_cross,area)
            if any(p[a]!=p[b] for a,b,_ in conflicts):invalid.append(row['metrics']['fingerprint'])
        result[dept]={'plans_checked':len(archive),'valid_nonempty_atoms':all(g.is_valid and not g.is_empty for g in shapes),
                      'unit_pairs_with_positive_area_overlap':len(positive),'unit_pairs_above_one_m2':len(conflicts),
                      'max_unit_pair_overlap_m2':max_area,'max_cross_district_unit_overlap_m2_over_all_plans':max_cross,
                      'invalid_cross_district_overlap_fingerprints':invalid}
        print(dept,'checked',len(archive),'maps; max cross-district overlap m2',max_cross,'failures',len(invalid),flush=True)
    (out/'geometry_audit.json').write_text(json.dumps(result,indent=2))
    if any(r['invalid_cross_district_overlap_fingerprints'] or not r['valid_nonempty_atoms'] for r in result.values()):
        raise ValueError('geometry audit failed')


if __name__=='__main__':main()

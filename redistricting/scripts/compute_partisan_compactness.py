"""Reconstruct the official territorial audit and score hybrid scenarios, vote-blind."""
from __future__ import annotations
import argparse,collections,csv,json,math,pickle,sys
from pathlib import Path
from shapely import coverage_is_valid,coverage_union_all,wkb
from shapely.ops import unary_union

ROOT=Path(__file__).resolve().parents[1]

def loss(pieces):
    if coverage_is_valid(pieces): shape=coverage_union_all(pieces)
    else: shape=unary_union(pieces).buffer(0)
    return 1-4*math.pi*shape.area/(shape.length*shape.length) if shape.length>0 else 1.0

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data-root',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);args=ap.parse_args()
    local=args.data_root.resolve();sys.path.insert(0,str(local/'scripts'));sys.path.insert(0,str(local/'src'))
    from redistrict.graph.iris import iris_geometry, split_units
    import geopandas as gpd
    import pandas as pd
    state=pickle.loads((local/'data/processed/gate1/sampler_state.pkl').read_bytes())
    geometry={u:wkb.loads(b) for u,b in pickle.loads((local/'data/processed/gate1/unit_geometry_wkb.pkl').read_bytes()).items()}
    path=local/'data/processed/pipeline_runs/20261120T001804Z-6d568ab9/artifacts/national_draft/official_unit_assignment_heuristic.csv'
    bydept=collections.defaultdict(lambda:collections.defaultdict(list))
    with path.open() as f:
        for row in csv.DictReader(f): bydept[row['department']][row['official_constituency']].append(row['unit'])
    original_units={u for districts in bydept.values() for units in districts.values() for u in units}
    missing=original_units-set(geometry)
    virtual_parents={u[:5] for u in missing}
    iris_paths=list((local/'data/processed/iris').rglob('CONTOURS-IRIS.shp'))+list((local/'data/processed/iris_reu').rglob('CONTOURS-IRIS.shp'))
    iris=gpd.GeoDataFrame(pd.concat([iris_geometry(str(p)).to_crs('EPSG:2154') for p in iris_paths]),geometry='geometry',crs='EPSG:2154')
    frame=pd.read_csv(local/'data/processed/iris_population_2022.csv',dtype={'iris':str})
    iris_pop={str(row.iris):float(row.pop22) for row in frame.itertuples(index=False)}
    expanded_geom=dict(geometry);virtual={}
    for parent in sorted(virtual_parents):
        members=[u for u in state['units'] if (u[:5] if len(u)>=9 else u)==parent]
        parent_row=gpd.GeoDataFrame({'unit':[parent],'geometry':[unary_union([geometry[u] for u in members])]},geometry='geometry',crs='EPSG:2154').set_index('unit')
        population=sum(state['pops'][u] for u in members)
        split_frame,_,pieces=split_units(parent_row,{parent:population},[parent],iris,iris_pop)
        for piece in pieces: expanded_geom[piece.code]=split_frame.loc[piece.code,'geometry']
        virtual[parent]=[piece.code for piece in pieces]
    if original_units-set(expanded_geom):raise ValueError('missing reconstructed official geometries')
    print('expanded',len(original_units),'virtual parents',len(virtual),flush=True)
    official={}
    for dep,districts in sorted(bydept.items()):
        official[dep]=[loss([expanded_geom[u] for u in units]) for units in districts.values()]
    count=sum(len(v) for v in official.values());baseline=sum(map(sum,official.values()))/count
    reference=json.loads((path.parent/'heuristic_national_comparison.json').read_text())['official_metrics']['compactness_loss_mean_1_minus_polsby_popper']
    if abs(baseline-reference)>1e-8:raise ValueError(f'official compactness mismatch {baseline} vs {reference}')
    print('verified baseline',baseline,'districts',count,flush=True)
    docs=ROOT.parent/'docs/redistricting'
    sources={'rn':'14_national_partisan_scenario.json','left':'15_broad_left_scenario.json','lfi':'15_lfi_attachment_scenario.json'}
    result={'official':baseline,'districts':count,'method':'same expanded official units and Lambert-93 Polsby-Popper audit; changed districts use original model units','scenarios':{}}
    for name,filename in sources.items():
        scenarios=json.loads((docs/filename).read_text())['selected'];changed={x['department'] for x in scenarios};vals=[v for dep,scores in official.items() if dep not in changed for v in scores]
        for row in scenarios:
            groups=collections.defaultdict(list)
            for unit,district in row['assignment'].items():groups[district].append(unit)
            vals.extend(loss([geometry[u] for u in units]) for units in groups.values())
        if len(vals)!=count:raise ValueError('district count changed')
        result['scenarios'][name]=sum(vals)/len(vals);print(name,result['scenarios'][name],flush=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()

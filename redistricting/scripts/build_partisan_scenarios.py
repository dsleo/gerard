"""Build a browser-only hybrid map and bloc-runoff snapshot from saved research maps.

Reads local quarantined election inputs, never changes search results or publishes
raw votes. 2024 official districts outside changed departments are retained.
"""
from __future__ import annotations
import base64
import collections
import gzip
import hashlib
import json
import pickle
import sys
from pathlib import Path
import pyproj
import yaml
from shapely import wkb, make_valid
from shapely.geometry import mapping
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import experiment_partisan_campaign as campaign
import experiment_partisan_search as exp
from partisan_affiliations import load_affiliations
from partisan_split_votes import allocate_split_votes

SPECS = [
    ('rn', '14_national_partisan_scenario.json', 'RN', 'far_right'),
    ('left', '15_broad_left_scenario.json', None, 'left'),
    ('lfi', '15_lfi_attachment_scenario.json', 'LFI', 'left'),
]
OUT = ROOT / 'export/browser/partisan-scenarios.js'
BLOCKS = campaign.BLOCKS


def write_payload(path, data):
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf8')
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode()
    path.write_text("window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};window.REDISTRICTING_DATA['partisan-scenarios']=(async()=>{const b=Uint8Array.from(atob(\""+encoded+"\"),c=>c.charCodeAt(0));const d=new DecompressionStream('gzip');return JSON.parse(await new Response(new Blob([b]).stream().pipeThrough(d)).text())})();\n", encoding='utf8')


def main():
    snap = campaign.snapshot()
    state = pickle.loads(exp.STATE.read_bytes())
    geometry = pickle.loads((ROOT / 'data/processed/gate1/unit_geometry_wkb.pkl').read_bytes())
    definitions = yaml.safe_load(exp.BLOCS.read_text())['mappings']
    mapping_bloc = {n:b for b, ns in definitions['coarse']['blocs'].items() for n in ns}
    runoff_builder, second = campaign.second_round_inputs()
    augmented = dict(mapping_bloc); augmented.update({'model:'+b:b for b in BLOCKS})
    transform_xy = pyproj.Transformer.from_crs(2154, 4326, always_xy=True).transform
    scenarios = {}
    for key, file, party, bloc in SPECS:
        data = json.loads((REPO / 'docs/redistricting' / file).read_text())
        selected = data['selected']
        departments = {r['department'] for r in selected}
        affiliations = load_affiliations(campaign.AFFILIATION, campaign.FIRST) if party == 'LFI' else None
        nuance = 'RN' if party == 'RN' else None
        votes = exp.load_votes(exp.VOTES, departments, definitions, nuance, affiliations)
        votes, coverage, _, _ = allocate_split_votes(state, departments, votes, definitions, nuance,
                                                      campaign.CROSSWALK, campaign.BUREAUX, affiliations)
        changed_rows = []
        features = []
        for item in selected:
            dep = item['department']; plan = item['assignment']
            if any(len(k) != 2 for k in [dep]):
                raise ValueError('only metropolitan selected geometries are currently supported')
            units = set(plan)
            for unit in units:
                if unit not in votes['coarse']:
                    if state['pops'][unit]: raise ValueError(f'missing votes: {dep} {unit}')
                    votes['coarse'][unit] = {}
            groups = collections.defaultdict(lambda: collections.defaultdict(float))
            members = collections.defaultdict(list)
            for unit, district in plan.items():
                members[district].append(unit)
                for label, count in votes['coarse'][unit].items():
                    # Recombine the target with its coarse bloc for the atlas model.
                    if label in ('party:RN', 'party:LFI'):
                        label = bloc
                    groups[district][label] += count
            for district in sorted(members):
                number = int(district) + 1
                tallies = groups[district]; total = sum(tallies.values())
                if not total: raise ValueError(f'no votes: {dep}-{number}')
                winner = min(BLOCKS, key=lambda b: (-tallies.get(b, 0), b))
                name = dep + '-' + str(number).zfill(2)
                changed_rows.append({'department': dep, 'district_number': number, 'estimated': True,
                                     'votes_by_nuance': {'model:'+b:v for b,v in tallies.items()},
                                     'first_bloc': winner, 'first_share': tallies.get(winner,0)/total,
                                     'map_id': name})
                shapes = [wkb.loads(geometry[u]) for u in members[district]]
                shapes = [g if g.is_valid else make_valid(g) for g in shapes]
                district_geom = transform(transform_xy, unary_union(shapes)).simplify(.0007, preserve_topology=True)
                features.append({'type':'Feature', 'properties':{'department':dep, 'district_number':number, 'map_id':name},
                                 'geometry':mapping(district_geom)})
        rows = []
        for row in snap['official_first_round']:
            if row['department'] not in departments:
                shares = runoff_builder.block_shares(row['votes_by_nuance'], mapping_bloc, BLOCKS)
                winner = min(BLOCKS, key=lambda b:(-shares[b],b))
                rows.append({'department':row['department'], 'district_number':row['district_number'],
                             'estimated':True, 'votes_by_nuance':row['votes_by_nuance'],
                             'first_bloc':winner, 'first_share':shares[winner],
                             'map_id': row['department']+'-'+str(row['district_number']).zfill(2)})
        rows.extend(changed_rows)
        counts = collections.Counter((r['department'], r['district_number']) for r in rows)
        if any(v != 1 for v in counts.values()): raise ValueError('duplicate district identifier')
        model = runoff_builder.round_two_mapping_model(snap['official_first_round'], second, rows, augmented, BLOCKS, 2024)
        result_by_key = {(r['department'],r['district_number']):r for r in model['districts']}
        output_rows = {}
        for row in rows:
            res=result_by_key[(row['department'],row['district_number'])]
            output_rows[row['map_id']] = {'first_bloc':row['first_bloc'], 'first_share':row['first_share'],
                                          'runoff_bloc':res.get('winner_bloc'), 'estimated':res['estimated'],
                                          'runoff_share':res.get('bloc_a_share'), 'bloc_a':res.get('bloc_a'),
                                          'interval_low':res.get('bloc_a_interval_low'), 'interval_high':res.get('bloc_a_interval_high')}
        if len(rows) > 577: raise ValueError('more modeled districts than the Assembly')
        scenarios[key] = {'changed_departments':sorted(departments), 'districts':output_rows,
                          'features':{'type':'FeatureCollection','features':features},
                          'seat_projection':model['seat_projection'], 'estimated':sum(r['estimated'] for r in model['districts']),
                          'unestimated':577-sum(r['estimated'] for r in model['districts']),
                          'first_target_leads':data.get('total_bounded_rn_leads',data.get('total_bounded_target_leads')),
                          'baseline_target_leads':data.get('official_rn_leads',data.get('official_target_leads')),
                          'source_sha256':hashlib.sha256((REPO / 'docs/redistricting' / file).read_bytes()).hexdigest()}
        print(key,'changed',len(departments),'rows',len(rows),'estimated',scenarios[key]['estimated'],
              'seats',{b:model['seat_projection'][b]['seats'] for b in BLOCKS},flush=True)
    payload={'scenarios':scenarios, 'method':'coarse_bloc_nearest_2024_duel_analogs',
             'note':'2024 votes; selected departments optimized; projections are hypothetical bloc-level duels.'}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_payload(OUT, payload)
    print('wrote',OUT,OUT.stat().st_size,flush=True)

if __name__ == '__main__': main()

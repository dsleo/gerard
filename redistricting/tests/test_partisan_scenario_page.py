"""The shipped scenario snapshot must match its audited map selections."""
import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def payload():
    path = ROOT / 'redistricting/export/browser/partisan-scenarios.js'
    match = re.search(r'atob\("([A-Za-z0-9+/=]+)"\)', path.read_text())
    assert match
    return json.loads(gzip.decompress(base64.b64decode(match.group(1))))


def test_saved_scenarios_match_their_selected_maps_and_assembly_totals():
    data = payload()['scenarios']
    expected = {'rn': ('14_national_partisan_scenario.json', 289, 30),
                'left': ('15_broad_left_scenario.json', 230, 33),
                'lfi': ('15_lfi_attachment_scenario.json', 69, 7)}
    assert set(data) == set(expected)
    for key, (filename, target, departments) in expected.items():
        scenario = data[key]
        source = ROOT / 'docs/redistricting' / filename
        plan = json.loads(source.read_text())
        assert scenario['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert scenario['first_target_leads'] == target
        assert len(scenario['changed_departments']) == departments
        assert set(scenario['changed_departments']) == {r['department'] for r in plan['selected']}
        assert len(scenario['features']['features']) == sum(r['districts'] for r in plan['selected'])
        assert len(scenario['districts']) == 559
        assert scenario['estimated'] + scenario['unestimated'] == 577
        assert sum(row['seats'] for row in scenario['seat_projection'].values()) == scenario['estimated']
        assert all(row['first_bloc'] in {'left','centre','right','far_right','other'} for row in scenario['districts'].values())

"""The shipped scenario snapshot must match its audited map selections."""
import base64
from collections import Counter
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
    expected = {key: f'22_{key}_expected.json' for key in ('lfi','left','centre','right','far_right')}
    expected['other'] = '18_other_scenario.json'
    assert set(data) == set(expected)
    for key, filename in expected.items():
        scenario = data[key]
        source = ROOT / 'docs/redistricting' / filename
        # Detailed research inputs can be retained locally without being published.
        if source.exists():
            plan = json.loads(source.read_text())
            assert scenario['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
            if key != 'other':
                assert abs(scenario['seat_projection'][key]['expected'] - plan['total_expected_seats']) < 1e-7
                assert plan['total_expected_seats'] >= plan['baseline_expected_seats']
            assert len(scenario['changed_departments']) == plan['selected_departments']
            assert set(scenario['changed_departments']) == {r['department'] for r in plan['selected']}
            assert len(scenario['features']['features']) == sum(r['districts'] for r in plan['selected'])
        assert len(scenario['districts']) == 559
        assert scenario['estimated'] + scenario['unestimated'] == 577
        assert sum(row['seats'] for row in scenario['seat_projection'].values()) == scenario['estimated']
        assert sum(row['representative'] for row in scenario['seat_projection'].values()) == scenario['estimated']
        sampled = Counter(row['runoff_bloc'] for row in scenario['districts'].values() if row['estimated'])
        assert all(sampled[bloc] == row['representative'] for bloc,row in scenario['seat_projection'].items())
        assert all(row['first_bloc'] in {'lfi','left','centre','right','far_right','other'} for row in scenario['districts'].values())


def test_partisan_metrics_have_population_epci_and_mmd():
    for scenario in payload()['scenarios'].values():
        metrics = scenario['territorial_metrics']
        assert metrics['population_max_abs_deviation_from_national_target'] >= 0
        assert 0 <= metrics['epci_pooled_avoidable_ratio'] <= 1
        assert 0 <= metrics['compactness_loss_mean_1_minus_polsby_popper'] <= 1
        assert set(scenario['mmd_delta']) == {'lfi','left','centre','right','far_right','other'}


def test_official_first_round_uses_the_same_split_as_partisan_reference():
    text = (ROOT / 'redistricting/export/browser/projection-2026.js').read_text()
    match = re.search(r'atob\("([A-Za-z0-9+/=]+)"\)', text)
    projection = json.loads(gzip.decompress(base64.b64decode(match.group(1))))
    reference = payload()['scenarios']['other']['districts']
    matched = 0
    for row in projection['official_first_round']:
        district_id = f"{row['department']}-{row['district_number']:02d}"
        nuance = row['votes_by_nuance']
        expected = nuance.get('EXG', 0) + nuance.get('LFI_ATTACHMENT', 0)
        assert abs(row['votes_by_bloc'].get('lfi', 0) - expected) < 1e-6
        if district_id in reference:
            assert reference[district_id]['first_bloc'] == row['bloc']
            matched += 1
    assert matched == 559
    assert set(projection['round_two']['seat_projection']) == {'lfi','left','centre','right','far_right','other'}
    neutral = projection['round_two']
    winners = Counter(row['representative_winner_bloc'] for row in neutral['districts'] if row['estimated'])
    assert all(winners[bloc] == row['representative'] for bloc,row in neutral['seat_projection'].items())


def test_2024_winner_map_keeps_extreme_left_distinct():
    text = (ROOT / 'redistricting/export/browser/election-2024.js').read_text()
    marker = "window.REDISTRICTING_DATA['election-2024']="
    election = json.loads(text.split(marker, 1)[1].rstrip(';\n'))
    groups = {f['properties']['group'] for f in election['features']}
    assert {'extreme_gauche','gauche','centre','droite','rn','autres'} <= groups
    assert all(f['properties']['group'] == 'extreme_gauche'
               for f in election['features'] if f['properties']['nuance'] == 'EXG')

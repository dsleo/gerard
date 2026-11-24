"""The search objective must reproduce the displayed central runoff model."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_results_view_data as builder
import runoff_model_split as split

def test_exg_and_lfi_attachment_votes_are_added():
    assert split.merge_lfi_votes({'lfi': 45, 'party:LFI': 80, 'left': 30}) == {'lfi': 125, 'left': 30}


def test_cached_search_scorer_matches_full_model_for_split_left():
    mapping = {'L': 'lfi', 'G': 'left', 'R': 'far_right'}
    first, second = [], []
    for i in range(12):
        dep = f'{i+1:02d}'
        votes = {'L': 300+i*4, 'G': 160+i, 'R': 250-i}
        first.append({'department':dep, 'district_number':1, 'votes_by_nuance':votes, 'estimated':True})
        second.append({'department':dep, 'district_number':1, 'candidate_count':2, 'expressed':500,
                       'votes_by_nuance':{'L':270+i, 'R':230-i}})
    fast = split.Scorer(builder, mapping, first, second)
    full = builder.round_two_mapping_model(first, second, first, mapping, split.BLOCKS, 2024)
    for row, prediction in zip(first, full['districts']):
        grouped = {bloc:sum(v for n,v in row['votes_by_nuance'].items() if mapping[n] == bloc)
                   for bloc in split.BLOCKS}
        assert fast.winner(grouped) == prediction['winner_bloc']
    plan={str(i):i for i in range(len(first))}
    unit_votes={str(i):{mapping[n]:value for n,value in row['votes_by_nuance'].items()}
                for i,row in enumerate(first)}
    scores=fast.all_scores(plan,unit_votes)
    for bloc in split.BLOCKS:
        assert scores[bloc]['pluralities'] == full['seat_projection'][bloc]['seats']
    expected=fast.expected_scores(plan,unit_votes)
    for bloc in split.BLOCKS:
        assert abs(expected[bloc]['expected']-full['seat_projection'][bloc]['expected']) < 1e-9
        assert sum(row.get('representative_winner_bloc')==bloc for row in full['districts']) == full['seat_projection'][bloc]['representative']
    assert sum(row['representative'] for row in full['seat_projection'].values()) == len(first)

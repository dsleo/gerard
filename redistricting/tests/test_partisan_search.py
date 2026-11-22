"""Checks for the standalone electoral experiment, not the vote-blind pipeline."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('partisan_experiment', Path(__file__).parents[1] / 'scripts/experiment_partisan_search.py')
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


def test_vote_aggregation_and_target_nuance(tmp_path):
    source = tmp_path / 'votes.csv'
    source.write_text('Code département;Code commune;Nuance candidat 1;Voix 1;Nuance candidat 2;Voix 2\n'
                      '1;1001;RN;10;UXD;5\n1;1001;RN;3;UG;4\n', encoding='utf8')
    maps = {'coarse': {'blocs': {'far_right': ['RN', 'UXD'], 'left': ['UG']}}}
    result = experiment.load_votes(source, {'01'}, maps, 'RN')['coarse']['01001']
    assert dict(result) == {'party:RN': 13, 'far_right': 5, 'left': 4}


def test_methods_preserve_validity_and_never_return_worse_start():
    plan = {'a': 0, 'b': 0, 'c': 1, 'd': 1}
    adjacency = {'a': frozenset('b'), 'b': frozenset('ac'),
                 'c': frozenset('bd'), 'd': frozenset('c')}
    pop = {u: 1 for u in plan}
    votes = {'a': {'party:RN': 8, 'left': 1}, 'b': {'party:RN': 1, 'left': 8},
             'c': {'party:RN': 8, 'left': 1}, 'd': {'party:RN': 1, 'left': 8}}
    for method in experiment.METHODS:
        best, details = experiment.search(plan, adjacency, pop, 2, .5, votes, 'party:RN', method, 40, 5)
        assert experiment.validate_plan(best, set(plan), pop, adjacency, 2, .5).ok
        assert len(set(best.values())) == 2
        assert experiment.rank(details['metrics']) >= experiment.rank(experiment.metrics(plan, votes, 'party:RN'))
        assert (best, details) == experiment.search(plan, adjacency, pop, 2, .5, votes, 'party:RN', method, 40, 5)


def test_minimum_department_selection_uses_observed_worst_run_gains():
    spec = importlib.util.spec_from_file_location('partisan_campaign', Path(__file__).parents[1] / 'scripts/experiment_partisan_campaign.py')
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    campaign = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(campaign)
    results = {'01': {'status': 'tested', 'minimum_observed_gain': 3},
               '02': {'status': 'tested', 'minimum_observed_gain': 2},
               '03': {'status': 'tested', 'minimum_observed_gain': -1},
               '04': {'status': 'excluded_split_units'}}
    selection = campaign.minimum_departments(results, 10, 14)
    assert selection['reached']
    assert [item['department'] for item in selection['selected']] == ['01', '02']
    assert selection['result_lower_bound'] == 15
    assert not campaign.minimum_departments(results, 10, 16)['reached']


def test_party_and_bloc_remain_distinct_in_runoff_inputs():
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    import experiment_partisan_campaign as campaign
    campaign.TARGET_NUANCE = 'RN'
    campaign.TARGET_BLOC = 'far_right'
    campaign.TARGET_KEY = 'party:RN'
    votes = {'a': {'party:RN': 40, 'far_right': 5, 'left': 55}}
    projected = campaign.projected_rows('01', {'a': 0}, votes)
    assert projected[0]['votes_by_nuance'] == {'model:far_right': 45, 'model:left': 55}
    assert campaign.map_official_votes({'RN': 40, 'UXD': 5, 'UG': 55},
        {'RN': 'far_right', 'UXD': 'far_right', 'UG': 'left'}, 'RN') == {
            'party:RN': 40, 'far_right': 5, 'left': 55}


def test_split_vote_allocation_preserves_coverage_and_whole_communes(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    from partisan_split_votes import allocate_split_votes
    crosswalk = tmp_path / 'crosswalk.csv'
    crosswalk.write_text('iris,bureau,poids_dans_bureau\n010010001,010010001,0.4\n010010002,010010001,0.6\n')
    bureaux = tmp_path / 'bureaux.csv'
    bureaux.write_text('Code commune;Code BV;Inscrits;Nuance candidat 1;Voix 1\n1001;1;100;RN;80\n1001;2;20;RN;10\n')
    state = {'units': ['010010001', '010010002', '01002'],
             'unit_dept': {'010010001': '01', '010010002': '01', '01002': '01'}}
    votes = {'coarse': {'01001': {'party:RN': 90}, '01002': {'left': 7}}}
    maps = {'coarse': {'blocs': {'far_right': ['RN'], 'left': ['UG']}}}
    allocated, coverage, missing, details = allocate_split_votes(state, {'01'}, votes, maps, 'RN', crosswalk, bureaux)
    assert coverage['01001'] == 100 / 120
    assert missing['01'] == 20
    assert allocated['coarse']['010010001']['party:RN'] == 32
    assert allocated['coarse']['010010002']['party:RN'] == 48
    assert allocated['coarse']['01002'] == {'left': 7}
    assert '01001' not in allocated['coarse']


def test_missing_voters_are_allowed_to_strengthen_any_opponent():
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    import experiment_partisan_campaign as campaign
    plan = {'a': 0, 'b': 1}
    votes = {'a': {'party:RN': 70, 'left': 40}, 'b': {'party:RN': 60, 'left': 45}}
    assert campaign.robust_pluralities(plan, votes, 'party:RN', 0) == 2
    assert campaign.robust_pluralities(plan, votes, 'party:RN', 20) == 1
    assert campaign.robust_pluralities(plan, votes, 'party:RN', 30) == 0


def test_citywide_bureau_votes_allocate_to_arrondissement_units(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    from partisan_split_votes import allocate_split_votes
    crosswalk = tmp_path / 'crosswalk.csv'
    crosswalk.write_text('iris,bureau,poids_dans_bureau\n132010001,130550001,0.4\n132020001,130550001,0.6\n')
    bureaux = tmp_path / 'bureaux.csv'
    bureaux.write_text('Code commune;Code BV;Inscrits;Nuance candidat 1;Voix 1\n13055;1;100;RN;80\n')
    state = {'units': ['13201', '13202'], 'unit_dept': {'13201': '13', '13202': '13'}}
    votes = {'coarse': {'13055': {'party:RN': 80}}}
    maps = {'coarse': {'blocs': {'far_right': ['RN']}}}
    allocated, coverage, missing, details = allocate_split_votes(state, {'13'}, votes, maps, 'RN', crosswalk, bureaux)
    assert allocated['coarse']['13201']['party:RN'] == 32
    assert allocated['coarse']['13202']['party:RN'] == 48
    assert '13055' not in allocated['coarse']
    assert coverage == {'13201': 1, '13202': 1}
    assert missing['13'] == 0


def test_missing_votes_are_limited_to_districts_in_source_commune():
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    import experiment_partisan_campaign as campaign
    plan = {'010010001': 0, '01002': 1}
    votes = {'010010001': {'party:RN': 70, 'left': 40}, '01002': {'party:RN': 60, 'left': 45}}
    detail = {'parent_sources': {'01001': ['01001']}, 'source_missing_registered': {'01001': 31}}
    assert campaign.robust_pluralities(plan, votes, 'party:RN', 31, detail, 0) == 1
    assert campaign.robust_pluralities(plan, votes, 'party:RN', 36, detail, 16) == 0


def test_financial_attachment_separates_lfi_from_union_de_gauche(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    from partisan_affiliations import candidate_key, PARTY_LFI
    source = tmp_path / 'votes.csv'
    source.write_text('Code département;Code commune;Nuance candidat 1;Voix 1;Nom candidat 1;Prénom candidat 1;Nuance candidat 2;Voix 2;Nom candidat 2;Prénom candidat 2\n'
                      '1;1001;UG;30;DUPONT;Élise;UG;20;DURAND;Alix\n', encoding='utf8')
    affiliation = {candidate_key('1', 'Dupont', 'Elise'): PARTY_LFI,
                   candidate_key('1', 'Durand', 'Alix'): 'Parti Socialiste'}
    maps = {'coarse': {'blocs': {'left': ['UG']}}}
    result = experiment.load_votes(source, {'01'}, maps, candidate_affiliations=affiliation)
    assert result['coarse']['01001'] == {'party:LFI': 30, 'left': 20}

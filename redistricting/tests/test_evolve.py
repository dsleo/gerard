"""Validity, frozen evaluator, reproducibility and controlled evolution checks."""
import importlib.util
import random
from dataclasses import asdict,replace
from pathlib import Path

import pytest

from redistrict.optimize.evolve import Policy,DOMAINS,initial_policies,mutate,propose,run_policy,evolve,audit_results
from redistrict.validate.constraints import validate_plan


def campaign_module():
    path=Path(__file__).resolve().parents[1]/'scripts/run_evolution_campaign.py'
    spec=importlib.util.spec_from_file_location('campaign_for_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_policy_cannot_mutate_score_or_constraints():
    with pytest.raises(TypeError):Policy(score_weights=[1,0,0])
    with pytest.raises(TypeError):Policy(tolerance=.5)
    with pytest.raises(ValueError):Policy(controller='exec_python')
    rng=random.Random(8);p=Policy()
    for _ in range(50):
        p=mutate(p,rng)
        assert set(asdict(p))==set(DOMAINS)
        assert all(value in DOMAINS[key] for key,value in asdict(p).items())


def test_inactive_policy_fields_do_not_create_fake_new_programs():
    assert Policy(burst_length=5).id==Policy().id
    assert Policy(controller='bursts',temperature=.08,multistart=True).id==Policy(controller='bursts').id


@pytest.mark.parametrize('policy',initial_policies()+[
    Policy(controller='pareto',epci_tree_bias=2.,population_pair_bias=4.,flip_probability=.3)])
def test_real_proposals_are_valid_on_nonuniform_synthetic_graph(policy):
    case=campaign_module().toy_cases()['toy_train_b']
    target=sum(case['pops'].values())/case['seats'];p=case['starts'][0];rng=random.Random(33)
    for _ in range(30):
        p=propose(p,case['adjacency'],case['pops'],case['epci'],target,.2,policy,rng,8)
        assert validate_plan(p,set(case['pops']),case['pops'],case['adjacency'],target,.2).ok
        assert len(set(p.values()))==case['seats']


def test_search_is_reproducible_and_retains_incumbent():
    case=campaign_module().toy_cases()['toy_train_a']
    p=Policy(controller='pareto',epci_tree_bias=.5,flip_probability=.3)
    a=run_policy(case,p,99,32,8);b=run_policy(case,p,99,32,8)
    assert a['proposals_completed']==32 and a['complete']
    assert a['best_assignment']==b['best_assignment']
    assert a['best_metrics']==b['best_metrics']
    assert a['best_metrics']['L_v1']<=a['initial_best_L_v1']+1e-12
    assert a['best_metrics']['L_v1']==pytest.approx(.5*a['best_metrics']['l_pop']+.3*a['best_metrics']['l_comp']+.2*a['best_metrics']['l_epci'])


def test_final_audit_detects_score_tampering():
    case=campaign_module().toy_cases()['toy_train_a']
    result=run_policy(case,Policy(),123,10,8)
    result['case']='toy_train_a'
    assert audit_results({'toy_train_a':case},[result])['status']=='PASS_RETAINED_MAP_CHECKS'
    result['best_metrics']=dict(result['best_metrics'],L_v1=-999)
    with pytest.raises(ValueError,match='recomputation'):
        audit_results({'toy_train_a':case},[result])


def test_national_series_rejects_synthetic_winner(tmp_path,monkeypatch):
    import json
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    import run_next_optimization_series as series
    (tmp_path/'summary.json').write_text(json.dumps({'status':'COMPLETED_SYNTHETIC_ONLY'}))
    with pytest.raises(ValueError,match='REAL pilot'):
        series.frozen_policy(tmp_path)


def test_national_promotion_needs_real_holdout_confirmation(tmp_path,monkeypatch):
    import json
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    import run_next_optimization_series as series
    baseline=initial_policies()[1];child=Policy(population_pair_bias=4.)
    data={'status':'COMPLETED_REAL_SEARCH_NOT_NATIONAL_CERTIFICATION',
          'retained_map_audit':{'status':'PASS_RETAINED_MAP_CHECKS'},
          'selection':{'holdout_seen_for_selection':False,'policy':asdict(child),'best_validation_baseline_id':baseline.id},
          'holdout_selected_mean_gain':.03,'holdout_baseline_mean_gain':.04,
          'holdout_pairs':[{'case':d,'extra_gain_percentage_points':-1.} for d in ['06','33','69']]}
    (tmp_path/'summary.json').write_text(json.dumps(data));(tmp_path/'source_hashes.json').write_text('{}')
    policy,reason=series.frozen_policy(tmp_path)
    assert policy==baseline
    data['holdout_selected_mean_gain']=.05
    data['holdout_pairs']=[{'case':d,'extra_gain_percentage_points':1.} for d in ['06','33','69']]
    (tmp_path/'summary.json').write_text(json.dumps(data))
    policy,reason=series.frozen_policy(tmp_path)
    assert policy==child


def test_incomplete_trial_explicit_not_silently_ranked():
    case=campaign_module().toy_cases()['toy_train_a']
    result=run_policy(case,Policy(),42,32,8,max_seconds=0)
    assert not result['complete'] and result['proposals_completed']==0


def test_evolution_budget_control_and_reproducibility():
    seen=[]
    def evaluate(p):
        seen.append(p.id)
        return float(p.flip_probability+p.epci_tree_bias/10)
    a=evolve(evaluate,seed=73,evaluations=8)
    b=evolve(evaluate,seed=73,evaluations=8)
    assert a==b
    assert len(a['evolution'])==len(a['random_control'])==8
    assert len({r['policy_id'] for r in a['evolution']})==8
    assert len({r['policy_id'] for r in a['random_control']})==8
    assert len(set(seen))==a['unique_evaluations']
    assert all(r['parent'] in {x['policy_id'] for x in a['records'][:r['index']]}
               for r in a['records'] if r['parent'])


def test_protocol_splits_are_disjoint_and_locked_score():
    p=campaign_module().protocol()
    assert not set(p['train'])&set(p['validation'])
    assert not set(p['train'])&set(p['holdout'])
    assert not set(p['validation'])&set(p['holdout'])
    assert set(p['holdout'])=={'06','33','69'}
    assert p['hard_constraints']['population_tolerance']==.2


def test_selection_is_frozen_before_holdout_is_evaluated(tmp_path):
    """Integration: a tiny fake evaluator makes split access order observable."""
    import time
    module=campaign_module();config=module.protocol(True)
    config['benchmark']=list(config['train'])
    config['policy_evaluations_per_arm']=4
    called=[]
    original=module.run_policy
    original_audit=module.audit_results
    def fake(case,policy,seed,proposals,*args):
        name=case['name'];called.append(name)
        if name=='toy_holdout':assert (tmp_path/'frozen_selection_before_holdout.json').is_file()
        if name=='toy_validation':assert (tmp_path/'frozen_validation_shortlist.json').is_file()
        return {'policy_id':policy.id,'policy':asdict(policy),'complete':True,'proposals_completed':proposals,
                'proposal_budget':proposals,'seconds':0.,'unique_states':1,'relative_gain':0.,'gain_vs_incumbent':0.,
                'best_metrics':{'L_v1':1.},'best_assignment':{}}
    module.run_policy=fake
    module.audit_results=lambda cases,records:{'status':'MOCKED_IN_SPLIT_ORDER_TEST'}
    cases={n:{'name':n} for s in ['train','validation','holdout'] for n in config[s]}
    try:result=module.run(config,cases,tmp_path,time.perf_counter())
    finally:
        module.run_policy=original
        module.audit_results=original_audit
    assert not result['selection']['holdout_seen_for_selection']
    assert result['selection']['policy_id']==result['selection']['best_validation_baseline_id']
    first_holdout=called.index('toy_holdout')
    assert all(n=='toy_holdout' for n in called[first_holdout:])

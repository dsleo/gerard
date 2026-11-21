"""Independent arithmetic and search invariants for the experimental harness."""
import math

import pytest
from shapely.geometry import box
from shapely import wkb

from redistrict.optimize.sa import Scorer, Weights
from redistrict.optimize.experiment import ExperimentScorer, dominates, pareto_indices, search
from redistrict.validate.constraints import validate_plan


def fixture():
    units=['a','b','c','d']
    pops={u:100 for u in units}
    adj={'a':frozenset(['b','c']),'b':frozenset(['a','d']),
         'c':frozenset(['a','d']),'d':frozenset(['b','c'])}
    geoms={u:wkb.dumps(box(i%2,i//2,i%2+1,i//2+1)) for i,u in enumerate(units)}
    epci={u:'one_large_epci' for u in units}
    base=Scorer(geoms,pops,200,epci,Weights())
    return units,pops,adj,ExperimentScorer(base,pops,epci,200,150)


def test_population_rms_and_epci_cap_bound_by_hand():
    _,_,_,scorer=fixture()
    m=scorer.components({'a':0,'b':0,'c':1,'d':1})
    assert m['pop_national_rms']==pytest.approx(1/3)
    assert m['pop_national_mse']==pytest.approx(1/9)
    assert m['epci_outside_largest_population']==200
    assert m['epci_population_cap_lower_bound']==160
    assert m['epci_avoidable_population_fraction']==pytest.approx(.1)
    assert m['L_v2']==pytest.approx(.5/3+.3*m['l_comp']+.2*.1)


def test_metrics_ignore_district_labels_and_rms_decomposes():
    _,_,_,scorer=fixture()
    a=scorer.components({'a':0,'b':0,'c':1,'d':1})
    b=scorer.components({'a':19,'b':19,'c':7,'d':7})
    assert a==b
    # E[(P/T-1)^2] = Var(P)/T^2 + (mean(P)/T-1)^2.
    dp=[170,230];t=150
    assert sum((p/t-1)**2 for p in dp)/2==pytest.approx(30**2/t**2+(200/t-1)**2)


def test_pareto_removes_dominated_but_keeps_tradeoffs():
    rows=[{'pop_national_mse':a,'l_comp':b,'epci_avoidable_population_fraction':c}
          for a,b,c in [(1,1,1),(2,2,2),(.5,2,1)]]
    assert pareto_indices(rows)==[0,2]
    assert not dominates((1,1,1),(1,1,1))


@pytest.mark.parametrize('method',['sa_single','sa_multistart','pareto_bursts'])
def test_search_budget_validity_reproducibility_and_elitism(method):
    units,pops,adj,scorer=fixture()
    starts=[{'a':0,'b':0,'c':1,'d':1},{'a':0,'c':0,'b':1,'d':1}]
    x=search(starts,adj,pops,scorer,200,123,method,proposals=20)
    y=search(starts,adj,pops,scorer,200,123,method,proposals=20)
    assert x['proposals']==20
    assert x['best_assignment']==y['best_assignment']
    assert x['best_metrics']==y['best_metrics']
    assert x['best_metrics']['L_v1']<=min(scorer.components(p)['L_v1'] for p in starts)
    for p in [x['best_assignment']]+[row['assignment'] for row in x['front']]:
        assert validate_plan(p,set(units),pops,adj,200,.2).ok
        assert len(set(p.values()))==2


def test_invalid_epci_bound_is_not_silently_clipped():
    _,_,_,scorer=fixture()
    with pytest.raises(ValueError,match='bound violated'):
        scorer.components({'a':0,'b':0,'c':0,'d':0})

"""ReCom on the 4x4 toy grid: every move keeps districts contiguous and balanced; the initial plan is valid."""

from __future__ import annotations

import random

from conftest import make_grid
from redistrict.sample.recom import component_seats, grow_initial, max_deviation, recom_step
from redistrict.validate.constraints import check_contiguity


def test_initial_plan_covers_all_units_with_k_districts():
    units, pop, adj = make_grid(4)
    plan = grow_initial(adj, sorted(units), pop, k=2, target=800, tol=0.2, rng=random.Random(1), first_label=0)
    assert set(plan) == units
    assert len(set(plan.values())) == 2


def test_recom_keeps_contiguity_and_balance_over_many_seeds():
    units, pop, adj = make_grid(4)
    target = 800.0
    tol = 0.20
    for seed in range(20):
        rng = random.Random(seed)
        plan = grow_initial(adj, sorted(units), pop, k=2, target=target, tol=tol, rng=rng, first_label=0)
        for _ in range(30):
            plan = recom_step(plan, adj, pop, target, tol, rng)
            assert not check_contiguity(plan, adj), f"seed {seed}: contiguity broken"
            assert max_deviation(plan, pop, target) <= tol + 1e-9, f"seed {seed}: balance broken"


def test_component_seats_sum_and_ranges():
    ks = component_seats([800, 1600], target=800, tol=0.2, seats=3)
    assert sum(ks) == 3
    assert ks == [1, 2]


def test_component_seats_rejects_impossible_component():
    try:
        component_seats([10, 800], target=800, tol=0.2, seats=2)
    except ValueError:
        return
    raise AssertionError("expected ValueError")

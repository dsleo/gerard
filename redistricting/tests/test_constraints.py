"""Hard constraints on the 4x4 toy grid. These are the tests that prove the validator works."""

from __future__ import annotations

from redistrict.metrics.population import epci_split_count, max_population_deviation
from redistrict.validate.constraints import validate_plan


def _two_halves():
    """Left two columns = district 0, right two columns = district 1. Both 8 units."""
    return {f"r{i}c{j}": (0 if j < 2 else 1) for i in range(4) for j in range(4)}


def test_valid_plan_passes(grid4):
    units, pop, adj = grid4
    res = validate_plan(_two_halves(), units, pop, adj, target=800, hard_tolerance=0.20)
    assert res.ok
    assert res.district_population == {0: 800, 1: 800}
    assert res.max_deviation == 0.0


def test_unassigned_unit_is_rejected(grid4):
    units, pop, adj = grid4
    plan = _two_halves()
    del plan["r0c0"]
    res = validate_plan(plan, units, pop, adj, target=800, hard_tolerance=0.20)
    assert not res.ok
    assert res.violations[0].rule == "partition"


def test_disconnected_district_is_rejected(grid4):
    units, pop, adj = grid4
    plan = _two_halves()
    # swap two far-apart corners: district 0 becomes disconnected
    plan["r0c0"], plan["r3c0"] = 1, 0
    res = validate_plan(plan, units, pop, adj, target=800, hard_tolerance=0.20)
    rules = {v.rule for v in res.violations}
    assert "contiguity" in rules


def test_population_deviation_over_tolerance_is_rejected(grid4):
    units, pop, adj = grid4
    # district 0 gets 9 units (900), district 1 gets 7 (700): deviation 12.5% -> passes at 20%
    plan = _two_halves()
    plan["r0c2"] = 0  # 9 vs 7
    res = validate_plan(plan, units, pop, adj, target=800, hard_tolerance=0.20)
    assert res.ok
    assert res.max_deviation == 0.125
    # tighten the tolerance to 10%: same plan must now fail
    res = validate_plan(plan, units, pop, adj, target=800, hard_tolerance=0.10)
    assert {v.rule for v in res.violations} == {"population"}


def test_max_population_deviation_helper():
    assert max_population_deviation({0: 900, 1: 700}, 800) == 0.125


def test_epci_split_counts_excess_districts():
    # EPCI "A" touches districts 0 and 1 (1 excess split); EPCI "B" only district 1
    plan = {"u1": 0, "u2": 1, "u3": 1}
    epci = {"u1": "A", "u2": "A", "u3": "B"}
    assert epci_split_count(plan, epci) == (1, 2)

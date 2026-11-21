"""Optimizer pieces on real polygons: Polsby-Popper values and that annealing never returns an invalid plan."""

from __future__ import annotations

import math
import random

from shapely.geometry import box
from shapely import wkb as shapely_wkb

from conftest import make_grid
from redistrict.optimize.sa import Scorer, Weights, anneal, polsby_popper
from redistrict.sample.recom import grow_initial
from redistrict.validate.constraints import check_contiguity


def test_polsby_popper_of_a_square_and_a_long_strip():
    assert math.isclose(polsby_popper([box(0, 0, 1, 1)]), math.pi / 4, rel_tol=1e-6)
    strip = polsby_popper([box(0, 0, 10, 0.1)])
    assert strip < 0.1


def test_anneal_returns_a_valid_plan_on_the_toy_grid():
    units, pop, adj = make_grid(4)
    # toy geometry: unit (i, j) is the square [i, i+1] x [j, j+1] of the grid, with its code
    codes = sorted(units)
    geoms = {c: shapely_wkb.dumps(box(int(c[1]), int(c[3]), int(c[1]) + 1, int(c[3]) + 1)) for c in codes}
    target = 800.0
    rng = random.Random(3)
    plan = grow_initial(adj, codes, pop, 2, target, 0.2, rng, first_label=0)
    scorer = Scorer(geoms, pop, target, epci_of={c: "E" for c in codes}, weights=Weights())
    best, comps, accepted, diagnostics = anneal(plan, adj, scorer, pop, target, 0.2, steps=200, rng=rng)
    assert not check_contiguity(best, adj)
    assert comps["l_pop"] <= 0.2 + 1e-9
    assert set(best) == set(codes)
    assert diagnostics["proposals_completed"] <= 200

"""IRIS split: scaling to the legal population, exact sums, and unit replacement."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from redistrict.graph.iris import pieces_for_unit, split_units


def test_pieces_sum_exactly_to_legal_population():
    pieces = pieces_for_unit("31555", 1000, ["315550101", "315550102", "315550103"],
                             {"315550101": 100, "315550102": 200, "315550103": 300})
    assert sum(p.pop for p in pieces) == 1000
    scales = {round(p.scale, 6) for p in pieces}
    assert scales == {round(1000 / 600, 6)}


def test_zero_population_is_refused():
    with pytest.raises(ValueError):
        pieces_for_unit("31555", 1000, ["315550101"], {"315550101": 0})


def test_no_iris_is_refused():
    with pytest.raises(ValueError):
        pieces_for_unit("31555", 1000, [], {})


def test_split_replaces_parent_with_its_iris():
    units = gpd.GeoDataFrame(
        {"geometry": [box(0, 0, 2, 1), box(2, 0, 3, 1)]}, index=["31555", "31556"], geometry="geometry", crs="EPSG:2154"
    )
    iris = gpd.GeoDataFrame(
        {"INSEE_COM": ["31555", "31555"], "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)]},
        index=["315550101", "315550102"], geometry="geometry", crs="EPSG:2154",
    )
    pops = {"31555": 300, "31556": 50}
    new_units, new_pop, pieces = split_units(units, pops, ["31555"], iris, {"315550101": 1, "315550102": 3})
    assert "31555" not in new_units.index
    assert set(new_units.index) == {"315550101", "315550102", "31556"}
    assert new_pop["315550101"] + new_pop["315550102"] == 300
    assert new_pop["31556"] == 50

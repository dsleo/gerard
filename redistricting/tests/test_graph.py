"""Dual graph on real polygons: rook adjacency, ferry edges, components per department."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from redistrict.graph.build import Graph, add_manual_edges, department_components, rook_edges


def code(i: int, j: int) -> str:
    """Five-character INSEE-like code for grid cell (i, j), department '01'."""
    return f"01{i}{j}0"


def grid_units(n: int) -> gpd.GeoDataFrame:
    rows = [{"code": code(i, j), "geometry": box(i, j, i + 1, j + 1)} for i in range(n) for j in range(n)]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:2154").set_index("code")


def test_centre_cell_has_four_rook_neighbours():
    edges = rook_edges(grid_units(3))
    assert edges[code(1, 1)] == {code(0, 1), code(2, 1), code(1, 0), code(1, 2)}


def test_corner_cell_has_two_neighbours():
    edges = rook_edges(grid_units(3))
    assert edges[code(0, 0)] == {code(1, 0), code(0, 1)}


def test_diagonal_is_not_an_edge():
    edges = rook_edges(grid_units(2))
    assert code(1, 1) not in edges[code(0, 0)]


def test_forced_edge_joins_an_isolated_unit():
    # two-unit island 'a'-'b' with no border to the rest of the department
    edges = {"a": frozenset({"b"}), "b": frozenset({"a"}), "c": frozenset()}
    graph = Graph(units={"a": "01", "b": "01", "c": "01"}, edges=edges)
    assert len(department_components(graph, "01")) == 2  # {a,b} and {c}

    joined = add_manual_edges(edges, [("b", "c")], known={"a", "b", "c"})
    graph = Graph(units={"a": "01", "b": "01", "c": "01"}, edges=joined)
    assert len(department_components(graph, "01")) == 1


def test_components_only_use_same_department_edges():
    edges = {"a": frozenset({"b"}), "b": frozenset({"a", "d"}), "d": frozenset({"b"})}
    graph = Graph(units={"a": "01", "b": "01", "d": "02"}, edges=edges)
    # b-d crosses departments: department 01 is just {a, b}
    assert [sorted(c) for c in department_components(graph, "01")] == [["a", "b"]]
    assert department_components(graph, "02") == [frozenset({"d"})]


def test_forced_edge_refers_to_unknown_unit_is_rejected():
    with pytest.raises(KeyError):
        add_manual_edges({}, [("x", "y")], known={"x"})

"""Island links (D14) and enclave attachment (D13) on a small hand-made map."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import box

from redistrict.graph.build import Graph, rook_edges
from redistrict.graph.links import apply_links, attach_small_pieces, nearest_link_edges


def _units():
    # mainland: two touching squares; island: one square 2 km east (gap 1.0 km), another 40 km away
    rows = {
        "01001": box(0, 0, 1000, 1000),
        "01002": box(1000, 0, 2000, 1000),
        "01003": box(3000, 0, 4000, 1000),   # island, gap 1000 m from 01002
        "01004": box(40000, 0, 41000, 1000), # far away island, gap 36 km
    }
    return gpd.GeoDataFrame({"geometry": list(rows.values())}, index=list(rows.keys()), geometry="geometry", crs="EPSG:2154")


def _graph(units):
    edges = rook_edges(units)
    return Graph(units={c: "01" for c in units.index}, edges=edges)


def test_island_within_gap_is_linked_far_island_is_not():
    units = _units()
    graph = _graph(units)
    links = nearest_link_edges(units, graph, "01", max_gap_m=5000)
    pairs = {(l.a, l.b) for l in links}
    assert ("01003", "01002") in pairs or ("01002", "01003") in pairs
    assert all("01004" not in p for p in pairs)


def test_applying_links_joins_the_island():
    units = _units()
    graph = _graph(units)
    links = nearest_link_edges(units, graph, "01", max_gap_m=5000)
    # The candidate link is unapproved: only opt into it for this exploratory graph.
    linked = apply_links(graph, links, set(units.index), include_unapproved=True)
    from redistrict.graph.build import department_components
    assert len(department_components(linked, "01")) == 2  # mainland+island, and the far island


def test_unapproved_link_is_not_part_of_the_certification_graph_by_default():
    units = _units()
    graph = _graph(units)
    links = nearest_link_edges(units, graph, "01", max_gap_m=5000)
    linked = apply_links(graph, links, set(units.index))
    from redistrict.graph.build import department_components
    assert len(department_components(linked, "01")) == 3


def test_small_far_piece_is_attached_to_nearest_piece():
    units = _units()
    graph = _graph(units)
    # piece 01004 has 50 people; target 100 with 20% tolerance -> too small to be a district
    pops = {"01001": 100, "01002": 100, "01003": 100, "01004": 50}
    links = attach_small_pieces(graph, units, "01", pops, target=100, hard_tol=0.20)
    assert [l.kind for l in links] == ["enclave_attach"]
    assert links[0].a == "01004"

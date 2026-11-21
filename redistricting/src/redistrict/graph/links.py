"""Candidate links for islands and estuaries (D14) and enclave pieces (D13).

Distance-derived links are assumptions, not evidence of physical or legal continuity.
They are unapproved by default. They may be applied to a separate exploratory graph, but
must not be used for Gate 1 certification without source-backed approval.

D14 proposes one nearest-unit candidate per disconnected component within `max_gap_m`.
D13 proposes a nearest-centroid attachment for a component too small to hold a district.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
from shapely.geometry import Point

from redistrict.graph.build import Graph, add_manual_edges, department_components


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    gap_m: float
    dept: str
    kind: str  # adjacency_fix | generated_link | enclave_attach | manual_override
    basis: str = "distance_only"
    approval_status: str = "unapproved"


def nearest_link_edges(units: gpd.GeoDataFrame, graph: Graph, dept: str, max_gap_m: float) -> list[Link]:
    """One link per non-main component of `dept` that has a unit within `max_gap_m` of another component."""
    comps = department_components(graph, dept)
    if len(comps) <= 1:
        return []
    main = comps[0]
    others = comps[1:]
    dept_units = units.loc[sorted(set().union(*comps))]
    links: list[Link] = []
    for comp in others:
        best: tuple[float, str, str] | None = None
        comp_geoms = units.loc[sorted(comp)].geometry
        candidates = dept_units.drop(index=list(comp), errors="ignore")
        if candidates.empty:
            continue
        sindex = candidates.sindex
        for code, geom in comp_geoms.items():
            window = geom.buffer(max_gap_m)
            for pos in sindex.query(window, predicate="intersects"):
                other = candidates.index[pos]
                gap = geom.distance(candidates.geometry.iloc[pos])
                if gap <= max_gap_m and (best is None or gap < best[0]):
                    best = (gap, code, other)
        if best is not None:
            kind = "adjacency_fix" if best[0] < 1.0 else "generated_link"  # touching pieces vs. water gap
            links.append(Link(best[1], best[2], round(best[0], 1), dept, kind,
                              basis="nearest_polygon_distance", approval_status="unapproved"))
    return links


def apply_links(
    graph: Graph,
    links: list[Link],
    known: set[str],
    *,
    include_unapproved: bool = False,
) -> Graph:
    """Apply explicitly approved links, or all candidates for exploratory planning.

    The default deliberately excludes distance-derived candidates. Callers that use
    assumptions to explore plans must opt in and keep that graph separate from legal
    contiguity checks.
    """
    eligible = [l for l in links if l.approval_status == "approved" or include_unapproved]
    edges = add_manual_edges(graph.edges, [(l.a, l.b) for l in eligible], known)
    return Graph(units=graph.units, edges=edges)


def attach_small_pieces(
    graph: Graph,
    units: gpd.GeoDataFrame,
    dept: str,
    piece_population: dict[str, int],
    target: float,
    hard_tol: float,
) -> list[Link]:
    """D13: pieces too small to be a district are attached to the nearest other piece of their department.

    Only the pieces that are still separate after D14 links are considered. A piece is 'small' when it
    cannot hold one whole district within the hard tolerance: population < (1 - hard_tol) * target.
    """
    comps = department_components(graph, dept)
    if len(comps) <= 1:
        return []
    centroids = units.geometry.centroid
    out: list[Link] = []
    main_pieces = [c for c in comps if sum(piece_population.get(u, 0) for u in c) >= (1 - hard_tol) * target]
    if not main_pieces:
        return out  # nothing big enough: the department is infeasible, reported elsewhere
    for comp in comps:
        pop = sum(piece_population.get(u, 0) for u in comp)
        if pop >= (1 - hard_tol) * target:
            continue
        members = centroids.loc[sorted(comp)]
        c_xy = Point(members.x.mean(), members.y.mean())
        best_code, best_d = None, float("inf")
        for big in main_pieces:
            for u in big:
                d = c_xy.distance(centroids.loc[u])
                if d < best_d:
                    best_code, best_d = u, d
        anchor = min(comp)
        out.append(Link(anchor, best_code, round(best_d, 1), dept, "enclave_attach",
                        basis="nearest_centroid_attachment", approval_status="unapproved"))
    return out

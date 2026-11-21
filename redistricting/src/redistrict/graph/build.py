"""Dual graph of units (Module 2 input, Gate 1).

Nodes are units with a population: communes, plus the municipal arrondissements of Paris,
Lyon and Marseille (which replace their parent city). Edges are rook contiguity: units
sharing a border of positive length (at least `min_shared_border_m`). Manual ferry/bridge
edges from config are added on top.

The graph is built once on the whole country and then split by department. A department's
graph never uses an edge to another department (D6: districts are per department).
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from redistrict.allocate.departments import department_of

LAMBERT_93 = "EPSG:2154"  # metric CRS, so shared-border lengths are in metres


@dataclass(frozen=True)
class Graph:
    units: dict[str, str]  # unit code -> department
    edges: dict[str, frozenset[str]]  # unit -> neighbours (undirected)

    def neighbours(self, unit: str) -> frozenset[str]:
        return self.edges.get(unit, frozenset())


def build_units(
    communes: gpd.GeoDataFrame,
    arrondissements: gpd.GeoDataFrame,
    unit_codes: list[str],
) -> gpd.GeoDataFrame:
    """Geometry for each unit code. Arrondissements come from the municipal layer; communes from the commune layer.

    `communes` must have INSEE_COM; `arrondissements` must have INSEE_ARM. Both in the same CRS.
    Returns a GeoDataFrame indexed by unit code, in Lambert-93.
    """
    arr = arrondissements.rename(columns={"INSEE_ARM": "code"})[["code", "geometry"]]
    com = communes.rename(columns={"INSEE_COM": "code"})[["code", "geometry"]]
    both = gpd.GeoDataFrame(pd.concat([arr, com], ignore_index=True), geometry="geometry", crs=communes.crs)
    both = both.drop_duplicates("code", keep="first").set_index("code")
    missing = [c for c in unit_codes if c not in both.index]
    if missing:
        raise KeyError(f"no geometry for {len(missing)} units, e.g. {missing[:5]}")
    return both.loc[unit_codes].to_crs(LAMBERT_93)


def rook_edges(units: gpd.GeoDataFrame, min_shared_border_m: float = 0.5) -> dict[str, frozenset[str]]:
    """Undirected rook adjacency: pairs of units sharing a border longer than the minimum."""
    sindex = units.sindex
    neighbours: dict[str, set[str]] = {code: set() for code in units.index}
    geoms = units.geometry
    for code, geom in geoms.items():
        for pos in sindex.query(geom, predicate="intersects"):
            other = units.index[pos]
            if other == code or other in neighbours[code]:
                continue
            shared = geom.boundary.intersection(geoms.loc[other].boundary).length
            if shared >= min_shared_border_m:
                neighbours[code].add(other)
                neighbours[other].add(code)
    return {k: frozenset(v) for k, v in neighbours.items()}


def add_manual_edges(
    edges: dict[str, frozenset[str]], forced: list[tuple[str, str]], known: set[str]
) -> dict[str, frozenset[str]]:
    """Add ferry/bridge edges from config. Both ends must be known units."""
    out = {k: set(v) for k, v in edges.items()}
    for a, b in forced:
        if a not in known or b not in known:
            raise KeyError(f"forced edge refers to unknown unit: {a}, {b}")
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in out.items()}


def build_graph(units: gpd.GeoDataFrame, forced: list[tuple[str, str]], min_shared_border_m: float = 0.5) -> Graph:
    edges = add_manual_edges(rook_edges(units, min_shared_border_m), forced, set(units.index))
    dept = {code: department_of(code) for code in units.index}
    return Graph(units=dept, edges=edges)


def department_components(graph: Graph, dept: str) -> list[frozenset[str]]:
    """Connected components of one department's graph, using only same-department edges. Sorted largest first."""
    members = {u for u, d in graph.units.items() if d == dept}
    seen: set[str] = set()
    comps: list[frozenset[str]] = []
    for start in sorted(members):
        if start in seen:
            continue
        comp = {start}
        stack = [start]
        seen.add(start)
        while stack:
            u = stack.pop()
            for v in graph.neighbours(u):
                if v in members and v not in seen:
                    seen.add(v)
                    comp.add(v)
                    stack.append(v)
        comps.append(frozenset(comp))
    return sorted(comps, key=lambda c: (-len(c), min(c)))

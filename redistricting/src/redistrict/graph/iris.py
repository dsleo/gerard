"""IRIS split for units above the ceiling (D4-r case 2, decision O13: allowed).

Each flagged unit (a commune or a Paris arrondissement) is replaced by its IRIS pieces.
A piece's weight is its census population (INSEE, Recensement 2022, `P22_POP`)
on the IRIS geography in force 2024-01-01. It is scaled so that the pieces sum
to the selected 2021 legal population for the parent (D1-r). The scale is
recorded so it can be audited. These 2022 values are disaggregation weights,
not the legal populations used for seat allocation.

Geography note: both the population table and the IRIS contours use the
geography in force on 1 January 2024. Any geometry IRIS lacking a source
population row is an error; a missing source value must never become zero.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union


@dataclass(frozen=True)
class IrisPiece:
    code: str          # 9-character IRIS code
    parent: str        # unit being split (commune or arrondissement code)
    raw_pop: float     # census population weight (Recensement 2022, P22_POP)
    pop: int           # scaled population (sums to the parent's legal population)
    scale: float


def iris_geometry(path: str) -> gpd.GeoDataFrame:
    """IRIS contours with the parent commune code, indexed by IRIS code."""
    g = gpd.read_file(path)
    return g.set_index(g["CODE_IRIS"].astype(str))[["INSEE_COM", "geometry"]]


def pieces_for_unit(
    parent: str,
    legal_pop: int,
    iris_codes: list[str],
    iris_pop: dict[str, float],
) -> list[IrisPiece]:
    """Scale the census population of one parent's IRIS so the pieces sum to `legal_pop`."""
    if not iris_codes:
        raise ValueError(f"no IRIS found for {parent}")
    missing = sorted(set(iris_codes) - iris_pop.keys())
    if missing:
        raise ValueError(f"IRIS population weights missing for {parent}: {missing}")
    raw = {c: float(iris_pop[c]) for c in iris_codes}
    total = sum(raw.values())
    if total <= 0:
        raise ValueError(f"IRIS population is zero for {parent}")
    scale = legal_pop / total
    pieces = []
    running = 0
    for c in sorted(iris_codes):
        pop = round(raw[c] * scale)
        running += pop
        pieces.append(IrisPiece(c, parent, raw[c], pop, scale))
    # put any rounding difference on the largest piece, so the sum is exact
    diff = legal_pop - running
    largest = max(pieces, key=lambda p: p.pop)
    idx = pieces.index(largest)
    pieces[idx] = IrisPiece(largest.code, parent, largest.raw_pop, largest.pop + diff, scale)
    return pieces


def split_units(
    units: gpd.GeoDataFrame,
    unit_pop: dict[str, int | None],
    to_split: list[str],
    iris: gpd.GeoDataFrame,
    iris_pop: dict[str, float],
) -> tuple[gpd.GeoDataFrame, dict[str, int | None], list[IrisPiece]]:
    """Replace each unit in `to_split` by its IRIS pieces. Returns new units, populations, and the pieces."""
    new_units = units.drop(index=[u for u in to_split if u in units.index]).copy()
    new_pop = {u: p for u, p in unit_pop.items() if u not in set(to_split)}
    all_pieces: list[IrisPiece] = []
    rows = []
    for parent in to_split:
        legal = unit_pop.get(parent)
        if legal is None:
            raise ValueError(f"cannot split {parent}: no legal population")
        parent_geometry = units.loc[parent, "geometry"]
        codes = sorted(iris.index[iris["INSEE_COM"].astype(str) == parent])
        if not codes:  # arrondissements: IRIS INSEE_COM is the arrondissement code in the same file
            codes = sorted(c for c in iris.index if c.startswith(parent))
        pieces = pieces_for_unit(parent, legal, codes, iris_pop)

        # IRIS contours and the 2024 commune/arrondissement layer are independently
        # generalized and can differ by small slivers. Keep atoms inside the legal
        # parent geometry before building adjacency: e.g. Aix IRIS 130010404 overlaps
        # Meyreuil by 84.5 m² as published, hiding their 269 m shared boundary. Assign
        # only the small parent-area remainder back to touching IRIS atoms so the
        # repaired pieces still exactly cover the parent without overlap.
        piece_geometries = {
            piece.code: iris.loc[piece.code, "geometry"].intersection(parent_geometry)
            for piece in pieces
        }
        empty = [code for code, geometry in piece_geometries.items() if geometry.is_empty]
        if empty:
            raise ValueError(f"IRIS pieces fall completely outside parent {parent}: {empty[:5]}")
        irises = gpd.GeoSeries(piece_geometries, crs=units.crs)
        parent_remainder = parent_geometry.difference(unary_union(list(piece_geometries.values())))
        if parent_remainder.area > parent_geometry.area * 0.005:
            raise ValueError(
                f"clipped IRIS cover for {parent} leaves {parent_remainder.area:,.1f} m² "
                f"({parent_remainder.area / parent_geometry.area:.2%}) uncovered; refusing geometry repair"
            )
        remainder_parts = list(parent_remainder.geoms) if hasattr(parent_remainder, "geoms") else [parent_remainder]
        remainder_parts = [part for part in remainder_parts if not part.is_empty and part.area > 1e-7]
        if remainder_parts:
            spatial_index = irises.sindex
            for remainder in remainder_parts:
                candidates = spatial_index.query(remainder, predicate="intersects")
                shared = []
                for pos in candidates:
                    code = irises.index[pos]
                    length = remainder.boundary.intersection(irises.iloc[pos].boundary).length
                    if length > 0:
                        shared.append((length, code))
                if shared:
                    recipient = max(shared)[1]
                else:
                    # Independently generalized layers can leave a remainder
                    # whose closest IRIS is point-touching at floating precision.
                    # Permit only a <=1 cm tie and treat it as a sliver repair;
                    # a farther remainder is ambiguous and must be repaired at
                    # source rather than connected by a nearest-distance edge.
                    nearest_distance, recipient = min(
                        (float(irises.loc[code].distance(remainder)), code)
                        for code in irises.index
                    )
                    if nearest_distance > 0.01:
                        raise ValueError(
                            f"uncovered area for {parent} is {nearest_distance:.3f} m from every IRIS piece; "
                            "refusing nonlocal assignment"
                        )
                piece_geometries[recipient] = unary_union([piece_geometries[recipient], remainder])
                irises.loc[recipient] = piece_geometries[recipient]

        repaired_union = unary_union(list(piece_geometries.values()))
        uncovered = parent_geometry.difference(repaired_union).area
        outside = repaired_union.difference(parent_geometry).area
        overlap = sum(geometry.area for geometry in piece_geometries.values()) - repaired_union.area
        # Allow sub-square-metre floating-point residue; the national validator
        # already uses 1 m² as its geometry-overlap tolerance.
        if uncovered > 1.0 or outside > 1.0 or overlap > 1.0:
            raise ValueError(
                f"repaired IRIS cover for {parent} is not a partition "
                f"(uncovered={uncovered:.3f} m², outside={outside:.3f} m², overlap={overlap:.3f} m²)"
            )

        for p in pieces:
            rows.append({"code": p.code, "geometry": piece_geometries[p.code]})
            new_pop[p.code] = p.pop
        all_pieces += pieces
    if rows:
        add = gpd.GeoDataFrame(rows, geometry="geometry", crs=units.crs).set_index("code")
        new_units = pd.concat([new_units, add]).pipe(gpd.GeoDataFrame, geometry="geometry", crs=units.crs)
    return new_units, new_pop, all_pieces

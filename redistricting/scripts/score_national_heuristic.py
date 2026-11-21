"""Compare the official and mixed D53 maps with an explicit unit-assignment heuristic.

Official whole-commune correspondences stay exact. Model units in split or
unmapped communes are assigned to the official constituency with the largest
intersection area, using IRIS pieces where the model has them. Whole-commune
fallbacks use the same dominant-area rule. This is an estimate, not an official
crosswalk or a legal validation.
"""

from __future__ import annotations

import json
import math
import pickle
import sys
import csv
from collections import Counter, defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import coverage_is_valid, coverage_union_all, wkb
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.metrics.population import (  # noqa: E402
    epci_split_count,
    epci_split_lower_bound,
    epci_split_max_possible,
)
from redistrict.sample.official import (  # noqa: E402
    _official_rows_by_department,
    _parent_code,
    _source_to_current,
)
from redistrict.graph.iris import iris_geometry, split_units  # noqa: E402

install_generation_guard(ROOT, "score_national_heuristic.py")

PIPELINE_ID = "20261120T001804Z-6d568ab9"
MONITOR_ID = "20261120T001804Z-3bed7d8e"
STATE_PATH = ROOT / "data/processed/gate1/sampler_state.pkl"
GEOMETRY_PATH = ROOT / "data/processed/gate1/unit_geometry_wkb.pkl"
CORRESPONDENCE = ROOT / "data/raw/constituencies/insee_commune_circonscription_2026.xlsx"
COG_COMMUNES = ROOT / "data/raw/insee_cog2024/v_commune_2024.csv"
COG_MOVEMENTS = ROOT / "data/raw/insee_cog2024/v_mvt_commune_2024.csv"
IRIS_POPULATION = ROOT / "data/processed/iris_population_2022.csv"
IRIS_FXX = ROOT / "data/processed/iris/CONTOURS-IRIS_3-0__SHP_LAMB93_FXX_2024-01-01/CONTOURS-IRIS/1_DONNEES_LIVRAISON_2024-12-00164/CONTOURS-IRIS_3-0_SHP_LAMB93_FXX-ED2024-01-01/CONTOURS-IRIS.shp"
IRIS_REU = ROOT / "data/processed/iris_reu/CONTOURS-IRIS_3-0__SHP_RGR92UTM40S_REU_2024-01-01/CONTOURS-IRIS/1_DONNEES_LIVRAISON_2024-12-00164/CONTOURS-IRIS_3-0_SHP_RGR92UTM40S_REU-ED2024-01-01/CONTOURS-IRIS.shp"
OFFICIAL_SHAPE = ROOT / "data/raw/constituencies/insee_circonscriptions_2022_simplified.zip"
PIPELINE = ROOT / "data/processed/pipeline_runs" / PIPELINE_ID
OUT = PIPELINE / "artifacts/national_draft"


def normalize_contour_id(dept: str, raw: object) -> str:
    value = str(raw).strip()
    if dept.isdigit() and len(dept) == 2 and value.startswith(dept):
        return dept + value[len(dept):].zfill(3)
    if value.startswith(dept):
        return value
    if dept.isdigit() and len(dept) == 3:
        return dept + value[-2:].zfill(2)
    return dept + value[-2:].zfill(2)


def official_unit_assignment(state: dict, geometry_objects: dict[str, object], official: gpd.GeoDataFrame):
    rows_by_dept = _official_rows_by_department(str(CORRESPONDENCE.resolve()))
    source_to_current = _source_to_current(str(COG_COMMUNES.resolve()), str(COG_MOVEMENTS.resolve()))
    assignment: dict[str, str] = {}
    method: dict[str, str] = {}
    overlap_share: dict[str, float] = {}
    candidate_count: dict[str, int] = {}
    official_ids = set(official["id_circo"].astype(str))
    exact_by_parent: dict[str, set[str]] = defaultdict(set)
    partial_parents: set[str] = set()
    for dept, rows in rows_by_dept.items():
        if dept not in state["dept_pop"]:
            continue
        for row in rows.itertuples(index=False):
            source_code, circle, kind = str(row.COMMUNE_RESID), str(row.circo), str(row.type_com)
            for parent in source_to_current.get(source_code, set()):
                if kind == "entière":
                    exact_by_parent[parent].add(circle)
                elif kind == "partiel":
                    partial_parents.add(parent)

    exact_parent_to_circle = {
        parent: next(iter(circles))
        for parent, circles in exact_by_parent.items()
        if len(circles) == 1 and parent not in partial_parents
    }
    for unit in state["units"]:
        circle = exact_parent_to_circle.get(_parent_code(str(unit)))
        if circle and circle in official_ids:
            assignment[str(unit)] = circle
            method[str(unit)] = "exact_insee_whole_commune"
            overlap_share[str(unit)] = 1.0
            candidate_count[str(unit)] = 1

    # Spatial fallback is only used for units not mapped by an exact whole-
    # commune row. IRIS units are preferred naturally because the parent code
    # lookup above operates on each model atom; a whole-commune atom is used
    # only when no IRIS atom exists in that commune in the model inventory.
    by_dept: dict[str, list[str]] = defaultdict(list)
    for unit in state["units"]:
        if str(unit) not in assignment:
            by_dept[str(state["unit_dept"][unit])].append(str(unit))
    for dept, units in by_dept.items():
        polygons = official[official["dep"] == dept].reset_index(drop=True)
        if polygons.empty:
            raise ValueError(f"no official constituency polygons for department {dept}")
        spatial_index = polygons.sindex
        polygon_geoms = list(polygons.geometry)
        polygon_ids = list(polygons["id_circo"].astype(str))
        for unit in units:
            geom = geometry_objects[unit]
            candidate_ix = list(spatial_index.query(geom, predicate="intersects"))
            scored = []
            for ix in candidate_ix:
                area = geom.intersection(polygon_geoms[ix]).area
                if area > 0:
                    scored.append((area / geom.area if geom.area else 0.0, polygon_ids[ix]))
            if scored:
                scored.sort(key=lambda item: (-item[0], item[1]))
                share, circle = scored[0]
                method[unit] = "iris_max_overlap" if len(unit) >= 9 else "whole_unit_max_overlap"
                overlap_share[unit] = float(share)
                candidate_count[unit] = len(scored)
            else:
                # Edge case for a tiny geometry gap in the simplified source:
                # use the nearest official contour, and flag it distinctly.
                distances = [(geom.distance(poly), code) for poly, code in zip(polygon_geoms, polygon_ids)]
                distance, circle = min(distances, key=lambda item: (item[0], item[1]))
                method[unit] = "nearest_official_contour_fallback"
                overlap_share[unit] = 0.0
                candidate_count[unit] = 0
            if circle not in official_ids:
                raise ValueError(f"{unit}: heuristic produced unknown official constituency {circle}")
            assignment[unit] = circle

    if set(assignment) != set(state["units"]):
        raise ValueError(f"official heuristic did not assign every unit: {len(set(state['units'])-set(assignment))} missing")
    return assignment, method, overlap_share, candidate_count, geometry_objects


def expand_partial_communes_to_iris(state: dict, geometry_objects: dict[str, object]):
    """Use virtual IRIS pieces for partial official communes, even if the new
    plan correctly keeps that commune whole. This is only for the official
    map's population/geometry attribution and comparison.
    """
    rows_by_dept = _official_rows_by_department(str(CORRESPONDENCE.resolve()))
    source_to_current = _source_to_current(str(COG_COMMUNES.resolve()), str(COG_MOVEMENTS.resolve()))
    partial_parents: set[str] = set()
    for dept, rows in rows_by_dept.items():
        if dept not in state["dept_pop"]:
            continue
        for row in rows.itertuples(index=False):
            if str(row.type_com) == "partiel":
                partial_parents.update(source_to_current.get(str(row.COMMUNE_RESID), set()))

    units_by_parent: dict[str, list[str]] = defaultdict(list)
    for unit in state["units"]:
        units_by_parent[_parent_code(str(unit))].append(str(unit))
    split_candidates = []
    skipped_reasons = Counter()
    for parent in sorted(partial_parents):
        members = units_by_parent.get(parent, [])
        if len(parent) != 5 or not members:
            continue
        if any(len(u) >= 9 for u in members):
            continue  # already represented by model IRIS atoms
        split_candidates.append((parent, members))

    iris_parts = []
    for path in (IRIS_FXX, IRIS_REU):
        if path.exists():
            iris_parts.append(iris_geometry(str(path)).to_crs("EPSG:2154"))
    if not iris_parts:
        return state, geometry_objects, {}, {"virtual_iris_parents": 0, "skipped": len(split_candidates),
                                              "skip_reasons": {"no_iris_geometry": len(split_candidates)}}
    iris = pd.concat(iris_parts)
    iris = gpd.GeoDataFrame(iris, geometry="geometry", crs="EPSG:2154")
    iris_pop_frame = pd.read_csv(IRIS_POPULATION, dtype={"iris": str})
    iris_pop = {str(row.iris): float(row.pop22) for row in iris_pop_frame.itertuples(index=False)}

    ready = []
    skipped_parent_reasons: dict[str, str] = {}
    for parent, members in split_candidates:
        codes = sorted(iris.index[iris["INSEE_COM"].astype(str) == parent])
        if not codes:
            skipped_reasons["no_iris_codes"] += 1
            skipped_parent_reasons[parent] = "no_iris_codes"
            continue
        if set(codes) - iris_pop.keys():
            skipped_reasons["missing_iris_population_weights"] += 1
            skipped_parent_reasons[parent] = "missing_iris_population_weights"
            continue
        if sum(iris_pop[c] for c in codes) <= 0:
            skipped_reasons["zero_iris_population_weights"] += 1
            skipped_parent_reasons[parent] = "zero_iris_population_weights"
            continue
        ready.append((parent, members, codes))
    if not ready:
        return state, geometry_objects, {}, {"virtual_iris_parents": 0, "skipped": len(split_candidates),
                                              "skip_reasons": dict(skipped_reasons)}

    successful = []
    pieces = []
    split_geometries = {}
    split_pop = {}
    parent_pop = {}
    for parent, members, codes in ready:
        parent_row = gpd.GeoDataFrame(
            {"unit": [parent],
             "geometry": [unary_union([geometry_objects[u] for u in members])]},
            geometry="geometry", crs="EPSG:2154",
        ).set_index("unit")
        legal_pop = sum(int(state["pops"][u]) for u in members)
        try:
            split_frame, split_parent_pop, parent_pieces = split_units(
                parent_row, {parent: legal_pop}, [parent], iris, iris_pop
            )
        except ValueError:
            skipped_reasons["iris_geometry_does_not_cover_parent"] += 1
            skipped_parent_reasons[parent] = "iris_geometry_does_not_cover_parent"
            continue
        if {piece.code for piece in parent_pieces} != set(codes):
            skipped_reasons["iris_piece_inventory_mismatch"] += 1
            skipped_parent_reasons[parent] = "iris_piece_inventory_mismatch"
            continue
        successful.append((parent, members, codes))
        parent_pop[parent] = legal_pop
        pieces.extend(parent_pieces)
        split_pop.update(split_parent_pop)
        for code in codes:
            split_geometries[code] = split_frame.loc[code, "geometry"]

    parents = [parent for parent, _, _ in successful]

    expanded_state = dict(state)
    expanded_state["units"] = [u for u in state["units"] if u not in set(parents)]
    expanded_state["unit_dept"] = dict(state["unit_dept"])
    expanded_state["pops"] = dict(state["pops"])
    expanded_state["epci_of"] = dict(state["epci_of"])
    expanded_geometry = dict(geometry_objects)
    parent_to_pieces: dict[str, list[str]] = defaultdict(list)
    for parent in parents:
        for u in units_by_parent[parent]:
            expanded_state["unit_dept"].pop(u, None)
            expanded_state["pops"].pop(u, None)
            expanded_state["epci_of"].pop(u, None)
            expanded_geometry.pop(u, None)
    for piece in pieces:
        code = piece.code
        expanded_state["units"].append(code)
        expanded_state["unit_dept"][code] = state["unit_dept"][piece.parent]
        expanded_state["pops"][code] = int(split_pop[code])
        expanded_state["epci_of"][code] = state["epci_of"].get(piece.parent)
        expanded_geometry[code] = split_geometries[code]
        parent_to_pieces[piece.parent].append(code)
    expanded_state["units"] = sorted(expanded_state["units"])
    for parent, _, codes in successful:
        if set(parent_to_pieces[parent]) != set(codes):
            raise ValueError(f"{parent}: virtual IRIS split does not cover source IRIS codes")
        if sum(expanded_state["pops"][c] for c in parent_to_pieces[parent]) != parent_pop[parent]:
            raise ValueError(f"{parent}: virtual IRIS populations do not conserve parent total")
    return expanded_state, expanded_geometry, parent_to_pieces, {
        "virtual_iris_parents": len(parents),
        "virtual_iris_pieces": len(pieces),
        "skipped": len(split_candidates) - len(parents),
        "skip_reasons": dict(skipped_reasons),
        "skipped_parents": skipped_parent_reasons,
        "parents": parents,
    }


def metrics(label: str, assignments: dict[str, str], state: dict,
            geometry_objects: dict[str, object], seat_target: float) -> dict:
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for unit, district in assignments.items():
        dept = str(state["unit_dept"][unit])
        grouped[dept][str(district)].append(unit)
    all_district_pops = []
    local_abs_deviations = []
    all_geometries = []
    epci_excess = epci_lower = epci_max = 0
    district_count = 0
    dep_rows = []
    district_rows = []
    for dept in sorted(grouped):
        districts = grouped[dept]
        target = float(state["dept_pop"][dept]) / len(districts)
        local_assignment = {u: d for d, units in districts.items() for u in units}
        excess, _ = epci_split_count(local_assignment, state["epci_of"])
        lower = epci_split_lower_bound(local_assignment, state["epci_of"])
        maximum = epci_split_max_possible(local_assignment, state["epci_of"])
        epci_excess += excess
        epci_lower += lower
        epci_max += maximum
        local_deviations = []
        for district, units in districts.items():
            pop = sum(int(state["pops"][u]) for u in units)
            dev_nat = abs(pop - seat_target) / seat_target
            dev_local = abs(pop - target) / target
            all_district_pops.append({"department": dept, "district": str(district),
                                      "population": pop, "deviation": dev_nat})
            district_rows.append({"department": dept, "district": str(district),
                                  "population": pop, "national_deviation": dev_nat,
                                  "department_deviation": dev_local, "units": len(units)})
            local_abs_deviations.append(dev_local)
            local_deviations.append(dev_local)
            pieces = [geometry_objects[u] for u in units]
            if coverage_is_valid(pieces):
                shape = coverage_union_all(pieces)
            else:
                shape = unary_union(pieces).buffer(0)
            perimeter = shape.length
            pp = 4.0 * math.pi * shape.area / (perimeter * perimeter) if perimeter > 0 else 0.0
            all_geometries.append((1.0 - pp, dept, district))
            district_count += 1
        dep_rows.append({"department": dept, "districts": len(districts),
                         "max_local_population_deviation": max(local_deviations),
                         "epci_excess": excess, "epci_lower_bound": lower,
                         "epci_max_possible": maximum})
    pop_dev = [row["deviation"] for row in all_district_pops]
    comp = sum(x for x, _, _ in all_geometries) / len(all_geometries)
    epci_ratio = max(0, epci_excess - epci_lower) / max(1, epci_max - epci_lower)
    l_pop = max(pop_dev)
    score = 0.5 * l_pop + 0.3 * comp + 0.2 * epci_ratio
    return {
        "label": label,
        "districts": district_count,
        "population_total": sum(row["population"] for row in all_district_pops),
        "national_target_population_per_district": seat_target,
        "population_max_abs_deviation_from_national_target": l_pop,
        "population_worst_district_by_national_target": max(all_district_pops, key=lambda row: row["deviation"]),
        "population_mean_abs_deviation_from_national_target": sum(row["deviation"] for row in all_district_pops) / len(all_district_pops),
        "population_max_department_local_deviation": max(r["max_local_population_deviation"] for r in dep_rows),
        "compactness_loss_mean_1_minus_polsby_popper": comp,
        "epci_excess_splits": epci_excess,
        "epci_unavoidable_lower_bound": epci_lower,
        "epci_max_possible_excess": epci_max,
        "epci_pooled_avoidable_ratio": epci_ratio,
        "national_composite_L_0_5_pop_0_3_comp_0_2_epci": score,
        "department_details": dep_rows,
        "district_details": district_rows,
    }


def main() -> int:
    state = pickle.loads(STATE_PATH.read_bytes())
    geometry_wkb = pickle.loads(GEOMETRY_PATH.read_bytes())
    geometry_objects = {u: wkb.loads(raw) for u, raw in geometry_wkb.items()}
    official = gpd.read_file(f"zip://{OFFICIAL_SHAPE}").to_crs("EPSG:2154")
    official["geometry"] = official.geometry.make_valid()
    official["dep"] = official["dep"].astype(str).str.zfill(2)
    official["id_circo"] = [normalize_contour_id(str(dep), raw)
                             for dep, raw in zip(official["dep"], official["id_circo"])]
    if len(official) != 558:
        raise ValueError(f"expected 558 official constituency contours, found {len(official)}")

    score_state, score_geometry, virtual_parent_to_pieces, virtual_iris = expand_partial_communes_to_iris(
        state, geometry_objects
    )
    official_assignment, method, shares, candidate_counts, score_geometry = official_unit_assignment(
        score_state, score_geometry, official
    )
    proposed_assignment = dict(official_assignment)
    search_depts = sorted(set(state["dept_pop"]) - set(D53_FIXED_SEATS))
    for dept in search_depts:
        doc = json.loads((PIPELINE / "artifacts/optimized_plans" / f"{dept}.json").read_text(encoding="utf-8"))
        assignment = {str(u): int(d) for u, d in doc["assignment"].items()}
        expected = {u for u in state["units"] if state["unit_dept"][u] == dept}
        if set(assignment) != expected or len(set(assignment.values())) != int(state["seats"][dept]):
            raise ValueError(f"{dept}: generated assignment fails coverage/seat-count check")
        for unit, district in assignment.items():
            district_id = f"{dept}-{district + 1:02d}"
            virtual = virtual_parent_to_pieces.get(unit)
            if virtual:
                proposed_assignment.update({piece: district_id for piece in virtual})
            elif unit in score_state["units"]:
                proposed_assignment[unit] = district_id
    if len(search_depts) != 89 or set(proposed_assignment) != set(score_state["units"]):
        raise ValueError("proposed national plan must cover all 101 departments exactly")
    official_districts = len(set(official_assignment.values()))
    proposed_districts = len(set(proposed_assignment.values()))
    if official_districts != 558 or proposed_districts != 558:
        raise ValueError(f"fixed national seat-count mismatch: official={official_districts}, proposed={proposed_districts}")

    national_target = sum(int(v) for v in score_state["pops"].values()) / 558
    official_metrics = metrics("current_official_2024_heuristic", official_assignment, score_state,
                               score_geometry, national_target)
    proposed_metrics = metrics("mixed_new_map_89_search_12_carry_forward", proposed_assignment,
                               score_state, score_geometry, national_target)

    fallback_counts = Counter(method.values())
    low_share = sum(1 for unit, share in shares.items() if method[unit] != "exact_insee_whole_commune" and share < 0.5)
    ambiguous = sum(1 for unit, n in candidate_counts.items() if method[unit] != "exact_insee_whole_commune" and n > 1)
    report = {
        "status": "HEURISTIC_NATIONAL_COMPARISON_ESTIMATE",
        "pipeline_run_id": PIPELINE_ID,
        "departmental_districts": {"official": official_districts, "proposed": proposed_districts},
        "national_seat_total_including_19_overseas_abroad": 577,
        "population_reference": "INSEE legal population 2021, except Mayotte 2017 as decided in D1/D31",
        "assignment_heuristic": {
            "priority_1": "Apply INSEE June 2026 correspondence exactly for whole communes, translated from COG 2021 to 2024 geography.",
            "priority_2": "For a split commune represented as one model unit, replace it only in the official-map scoring view with virtual IRIS pieces where 2024 IRIS geometry and 2022 population weights are available; scale those weights to the parent's selected legal population. Assign each IRIS to the official contour with the largest intersection area. Existing model IRIS atoms are used directly.",
            "fallback": "If the model has only a whole-commune unit, assign the commune to the constituency with the largest area overlap. If simplified contours have no positive overlap, assign to the nearest contour.",
            "remainder": "Where virtual IRIS are not available, use the whole model unit and largest-area overlap. Each parent population is assigned exactly once; total national population is conserved.",
            "limitations": "Largest-overlap attribution is an estimate, because official contours are simplified. It can misallocate residents near split boundaries and does not establish official membership or legal validity.",
        },
        "assignment_coverage": {
            "total_units_in_scoring_view": len(score_state["units"]),
            "original_model_units": len(state["units"]),
            "virtual_iris": virtual_iris,
            "exact_whole_commune_units": fallback_counts.get("exact_insee_whole_commune", 0),
            "iris_majority_overlap_units": fallback_counts.get("iris_max_overlap", 0),
            "whole_unit_overlap_fallback_units": fallback_counts.get("whole_unit_max_overlap", 0),
            "nearest_contour_fallback_units": fallback_counts.get("nearest_official_contour_fallback", 0),
            "fallback_units_with_less_than_half_area_in_assigned_contour": low_share,
            "fallback_units_intersecting_multiple_contours": ambiguous,
            "total_population_sum_exactly_preserved": sum(int(v) for v in score_state["pops"].values()),
            "national_target_population_per_district": national_target,
        },
        "metrics_method": "Both plans scored on the same 2024 model units and geometries. Population parity uses the common national mean (total legal population / 558). Compactness uses unions of the same model-unit polygons. EPCI score pools avoidable excess splits over the pooled maximum. L = 0.50 population + 0.30 compactness + 0.20 EPCI.",
        "official_metrics": official_metrics,
        "proposed_metrics": proposed_metrics,
        "difference_proposed_minus_official": {
            key: proposed_metrics[key] - official_metrics[key]
            for key in (
                "population_max_abs_deviation_from_national_target",
                "population_mean_abs_deviation_from_national_target",
                "population_max_department_local_deviation",
                "compactness_loss_mean_1_minus_polsby_popper",
                "epci_pooled_avoidable_ratio",
                "national_composite_L_0_5_pop_0_3_comp_0_2_epci",
            )
        },
        "disclaimer": "Exploratory comparison, not an authoritative official crosswalk, legal opinion, neutrality analysis, or acceptance certificate. Read the assignment fallback counts before interpreting small metric differences.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "heuristic_national_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT / "official_unit_assignment_heuristic.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["unit", "department", "official_constituency", "method", "largest_overlap_share", "intersecting_contours"])
        writer.writeheader()
        for unit in sorted(official_assignment):
            writer.writerow({"unit": unit, "department": score_state["unit_dept"][unit],
                             "official_constituency": official_assignment[unit], "method": method[unit],
                             "largest_overlap_share": f"{shares[unit]:.9f}",
                             "intersecting_contours": candidate_counts[unit]})
    with (OUT / "national_plan_assignments_heuristic.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["unit", "department", "official_constituency_heuristic", "proposed_constituency", "official_assignment_method", "official_overlap_share"])
        writer.writeheader()
        for unit in sorted(proposed_assignment):
            writer.writerow({"unit": unit, "department": score_state["unit_dept"][unit],
                             "official_constituency_heuristic": official_assignment[unit],
                             "proposed_constituency": proposed_assignment[unit],
                             "official_assignment_method": method[unit],
                             "official_overlap_share": f"{shares[unit]:.9f}"})
    print(json.dumps({k: v for k, v in report.items() if k not in {"official_metrics", "proposed_metrics"}}, ensure_ascii=False, indent=2))
    print("OFFICIAL", json.dumps({k: v for k, v in official_metrics.items() if k != "department_details"}, ensure_ascii=False))
    print("PROPOSED", json.dumps({k: v for k, v in proposed_metrics.items() if k != "department_details"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

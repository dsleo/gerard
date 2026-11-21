"""Assemble a run-scoped, non-certified mixed national map draft.

Generated departments use the audited run's unit assignments. The 12 D53
carry-forward departments use the available simplified official polygons; they
are for national visual context only and must not be used to claim exact
population, contiguity, or objective metrics for the complete map.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
from shapely import wkb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402

install_generation_guard(ROOT, "assemble_mixed_national_draft.py")

PIPELINE_ID = "20261120T001804Z-6d568ab9"
MONITOR_ID = "20261120T001804Z-3bed7d8e"
PIPELINE = ROOT / "data/processed/pipeline_runs" / PIPELINE_ID
STATE_PATH = ROOT / "data/processed/gate1/sampler_state.pkl"
GEOMETRY_PATH = ROOT / "data/processed/gate1/unit_geometry_wkb.pkl"
OFFICIAL_SHAPE = ROOT / "data/raw/constituencies/insee_circonscriptions_2022_simplified.zip"
OUT = PIPELINE / "artifacts/national_draft"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_contour_id(dept: str, raw: object) -> str:
    value = str(raw).strip()
    if dept.isdigit() and len(dept) == 2 and value.startswith(dept):
        return dept + value[len(dept):].zfill(3)
    if value.startswith(dept):
        return value
    if dept.isdigit() and len(dept) == 3:
        return dept + value[-2:].zfill(2)
    return dept + value[-2:].zfill(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pipeline-run-id", default=PIPELINE_ID)
    args = ap.parse_args()
    pipeline = ROOT / "data/processed/pipeline_runs" / args.pipeline_run_id
    if args.pipeline_run_id != PIPELINE_ID:
        ap.error("this draft assembler is pinned to the audited 2026-11-20 run")

    state = pickle.loads(STATE_PATH.read_bytes())
    geometry_wkb = pickle.loads(GEOMETRY_PATH.read_bytes())
    optimized_dir = pipeline / "artifacts/optimized_plans"
    generated_depts = sorted(set(state["dept_pop"]) - set(D53_FIXED_SEATS))
    generated_rows: list[dict] = []
    district_count = 0
    search_population = 0
    exact_lpop_by_dept = []
    exact_lcomp_by_dept = []
    exact_lepci_by_dept = []
    exact_epci_counts_by_dept = []
    exact_L_by_dept = []
    generated_units = set()

    for dept in generated_depts:
        plan_path = optimized_dir / f"{dept}.json"
        plan_doc = json.loads(plan_path.read_text(encoding="utf-8"))
        assignment = {str(u): int(d) for u, d in plan_doc["assignment"].items()}
        if set(assignment) != {u for u in state["units"] if state["unit_dept"][u] == dept}:
            raise ValueError(f"{dept}: run assignment does not exactly cover model units")
        if len(set(assignment.values())) != int(state["seats"][dept]):
            raise ValueError(f"{dept}: district count differs from D53 seat allocation")
        generated_units.update(assignment)
        by_district: dict[int, list[str]] = defaultdict(list)
        for unit, district in assignment.items():
            by_district[district].append(unit)
        district_count += len(by_district)
        search_population += sum(int(state["pops"][u]) for u in assignment)
        target = float(state["dept_pop"][dept]) / int(state["seats"][dept])
        # Keep the source atoms as separate map features. This preserves the
        # audited assignment exactly and avoids introducing a geometry dissolve
        # step in this visualization-only assembly.
        for unit, district in sorted(assignment.items()):
            generated_rows.append({
                "district_id": f"{dept}-{district + 1:02d}",
                "department": dept,
                "district_number": district + 1,
                "unit_id": unit,
                "population_legal_residents": int(state["pops"][unit]),
                "population_reference_year": 2017 if dept == "976" else 2021,
                "population_deviation_local_target": None,
                "map_source": "audited_optimized_unit_assignment",
                "validity": "independently_audited_pass",
                "geometry": wkb.loads(geometry_wkb[unit]).simplify(30.0, preserve_topology=True),
            })

        # These are the exact same department-local metrics used by the v1
        # optimizer. The national report deliberately does not invent a new
        # aggregation across departments or include unscored carry-forwards.
        metrics_path = ROOT / "data/processed/optimizer_monitor/runs" / MONITOR_ID / "departments" / f"{dept}.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))["best"]
        exact_lpop_by_dept.append(metrics["l_pop"])
        exact_lcomp_by_dept.append((metrics["l_comp"], int(state["seats"][dept])))
        exact_lepci_by_dept.append((metrics["epci_excess_splits"], metrics["epci_max_possible_excess_splits"]))
        exact_epci_counts_by_dept.append((metrics["epci_excess_splits"],
                                          metrics["epci_unavoidable_excess_splits"],
                                          metrics["epci_max_possible_excess_splits"]))
        exact_L_by_dept.append((metrics["L"], int(state["seats"][dept])))

    if len(generated_depts) != 89 or district_count != 484:
        raise ValueError(f"unexpected search scope: {len(generated_depts)} departments / {district_count} districts")

    # The published INSEE layer is explicitly simplified; use only the 74
    # unchanged records to draw the carried-forward part of this draft.
    official = gpd.read_file(f"zip://{OFFICIAL_SHAPE}").to_crs("EPSG:2154")
    official["dep"] = official["dep"].astype(str).str.zfill(2)
    official["id_circo"] = [normalize_contour_id(str(dep), raw)
                             for dep, raw in zip(official["dep"], official["id_circo"])]
    carried = official[official["dep"].isin(D53_FIXED_SEATS)].copy()
    expected = sum(D53_FIXED_SEATS.values())
    if len(carried) != expected:
        raise ValueError(f"simplified official layer has {len(carried)} carry-forward features; expected {expected}")
    carried_rows = []
    for row in carried.itertuples(index=False):
        carried_rows.append({
            "district_id": str(row.id_circo),
            "department": str(row.dep),
            "district_number": int(str(row.id_circo)[-2:]),
            "population_legal_residents": None,
            "population_reference_year": 2017 if str(row.dep) == "976" else 2021,
            "population_deviation_local_target": None,
            "map_source": "unchanged_official_constituency_simplified_polygon",
            "validity": "official_boundary_carried_forward; atom crosswalk and project validator pending",
            "geometry": row.geometry,
        })

    result = gpd.GeoDataFrame(generated_rows + carried_rows, geometry="geometry", crs="EPSG:2154")
    result = result.to_crs("EPSG:4326")
    if result["district_id"].nunique() != 558 or len(result) != len(generated_units) + expected:
        raise ValueError("assembled draft must cover 558 unique departmental districts and all mapped features")
    OUT.mkdir(parents=True, exist_ok=True)
    geojson_path = OUT / "national_mixed_assignment_draft.geojson.gz"
    temp_json = OUT / "national_mixed_assignment_draft.geojson"
    result.to_file(temp_json, driver="GeoJSON")
    with temp_json.open("rb") as source, gzip.open(geojson_path, "wb", compresslevel=8) as target:
        target.write(source.read())
    temp_json.unlink()

    total_seats = 558
    weighted_compactness_loss = sum(v * n for v, n in exact_lcomp_by_dept) / sum(n for _, n in exact_lcomp_by_dept)
    pooled_epci_denominator = sum(maximum - lower for _, lower, maximum in exact_epci_counts_by_dept)
    pooled_epci = (sum(excess - lower for excess, lower, _ in exact_epci_counts_by_dept)
                   / pooled_epci_denominator if pooled_epci_denominator else 0.0)
    summary = {
        "status": "ASSEMBLED_DRAFT_NOT_CERTIFIED",
        "pipeline_run_id": args.pipeline_run_id,
        "map_features": len(result),
        "departmental_districts": 558,
        "generated_departments": len(generated_depts),
        "generated_districts": district_count,
        "carry_forward_departments": len(D53_FIXED_SEATS),
        "carry_forward_districts": expected,
        "departmental_seats": total_seats,
        "total_seats_including_19_overseas_and_abroad": 577,
        "population_covered_exactly_in_generated_scope": search_population,
        "population_reference": "INSEE legal population 2021; Mayotte 2017 exception",
        "exact_generated_scope_metrics": {
            "scope": "89 generated departments only; same department-local definitions as the optimizer",
            "max_l_pop_across_generated_departments": max(exact_lpop_by_dept),
            "mean_department_l_pop_unweighted": sum(exact_lpop_by_dept) / len(exact_lpop_by_dept),
            "l_comp_weighted_by_district_count": weighted_compactness_loss,
            "l_epci_pooled_avoidable_excess_ratio": pooled_epci,
            "district_count_weighted_mean_of_department_objectives_not_a_national_L": sum(v * n for v, n in exact_L_by_dept) / sum(n for _, n in exact_L_by_dept),
        },
        "exact_full_national_metrics": None,
        "heuristic_full_national_metrics_file": "heuristic_national_comparison.json",
        "exact_metrics_limitation": "Exact unit membership is unavailable for some official partial communes. A separately reported, IRIS-informed heuristic comparison estimates national metrics; it is not an exact official crosswalk or project certification.",
        "geometry_caveat": "Generated atom outlines are simplified by 30 m for visualization. The 74 carry-forward polygons come from a simplified official reference layer; do not treat their edges as exact or certify the mixed map from this file.",
        "official_comparison_caveat": "The run has 13 exact same-seat department-level comparisons. A whole-national comparison is available only as the IRIS-informed heuristic estimate in heuristic_national_comparison.json; it is not an exact official score.",
        "map_file": geojson_path.name,
        "input_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in (STATE_PATH, GEOMETRY_PATH, OFFICIAL_SHAPE,
                      pipeline / "artifacts/optimized_plans/manifest.json",
                      ROOT / "data/processed/optimizer_monitor/runs" / MONITOR_ID / "analysis/report.md",
                      OUT / "heuristic_national_comparison.json")
        },
    }
    (OUT / "assembly_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

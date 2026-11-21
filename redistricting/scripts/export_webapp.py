"""Export compact data for the webapp into export/ (outside webapp/).

The webapp never contains the generated maps. It reads export/ at runtime:
  export/summary.json            one row per department (seats, population, validity, optimized L)
  export/gate1.json              Gate 1 result and flags
  export/links.json              island links (D14) and enclave exceptions (D13)
  export/departments.geojson.gz France: department outlines with code and name (INSEE, ADMIN EXPRESS)
  export/maps/<dept>.geojson.gz one polygon per district of the optimized plan of the department
  export/cells/<dept>.geojson.gz the atomic cells used by the engine (communes, municipal
                                 arrondissements, IRIS pieces), with population and district

Coordinates are rounded to about 1 m. Run from redistricting/:
    .venv/bin/python scripts/run_blind.py export_webapp.py
"""

from __future__ import annotations

import csv
import hashlib
import gzip
import json
import pickle
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely.wkb as shapely_wkb
from shapely import set_precision
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.metrics.population import (
    epci_split_count,
    epci_split_lower_bound,
    epci_split_max_possible,
    epci_split_term,
    epci_missing_membership_count,
)
from redistrict.optimize.sa import Weights
from redistrict.ingest.generation import install_generation_guard

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "export_webapp.py")
EXPORT = ROOT / "export"
ACCEPTANCE = ROOT / "data/processed/acceptance/current.json"
GATE1_PATH = ROOT / "data/processed/gate1/step1_graph_audit.json"
GATE2_PATH = ROOT / "data/processed/gate2/seat_allocation_comparison.csv"
STATE_PATH = ROOT / "data/processed/gate1/sampler_state.pkl"
GEOMETRY_PATH = ROOT / "data/processed/gate1/unit_geometry_wkb.pkl"
HEMICYCLE_LAYOUT_SOURCE = ROOT / "data/raw/assembly/hemicycle_layout.json"
ADMIN = ROOT / "data/processed/admin_express_fra/ADMIN-EXPRESS-COG_3-2__SHP_WGS84G_FRA_2024-02-22/ADMIN-EXPRESS-COG/1_DONNEES_LIVRAISON_2024-03-00168/ADECOG_3-2_SHP_WGS84G_FRA-ED2024-02-22"
PRECISION = 1e-5        # about 1 m
SIMPLIFY_MAP = 0.0005   # about 50 m, for district maps
SIMPLIFY_CELL = 0.0001  # about 10 m, for atomic cells
SIMPLIFY_DEPT = 0.003   # for department outlines


def to_wgs84(geoms_l93: list) -> list:
    """Lambert-93 shapely geometries to WGS84 (EPSG:4326)."""
    return list(gpd.GeoSeries(geoms_l93, crs="EPSG:2154").to_crs("EPSG:4326").values)


def write_geojson_gzip(frame: gpd.GeoDataFrame, path: Path) -> None:
    """Write the complete GeoJSON feature collection losslessly, gzip-compressed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = frame.to_json(na="null", drop_id=True, to_wgs84=True).encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as compressed:
            compressed.write(payload)


def verify_acceptance_certificate() -> dict:
    if not ACCEPTANCE.is_file():
        raise RuntimeError("refusing to export: no national acceptance report exists")
    report = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    if report.get("status") != "ACCEPTED_MACHINE_CHECKS":
        raise RuntimeError(f"refusing to export map with status {report.get('status', 'UNKNOWN')}")
    for path in (STATE_PATH, GEOMETRY_PATH, GATE1_PATH, GATE2_PATH):
        key = str(path.relative_to(ROOT))
        if report.get("artifact_sha256", {}).get(key) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise RuntimeError(f"refusing to export: validation inputs changed since acceptance ({key})")
    optimized = {p.stem: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (ROOT / "data/processed/optimized").glob("*.json") if p.stem != "summary"}
    if optimized != report.get("plan_sha256"):
        raise RuntimeError("refusing to export: optimized plans changed since national validation")
    return report


def validate_exported_districts(frame: gpd.GeoDataFrame, dept: str) -> None:
    if frame.empty or frame.geometry.is_empty.any() or not frame.geometry.is_valid.all():
        raise RuntimeError(f"department {dept}: exported district geometry is empty or invalid")
    metric = frame.to_crs("EPSG:2154")
    index = metric.sindex
    overlaps = []
    for i, row in enumerate(metric.itertuples()):
        for j in index.query(row.geometry, predicate="intersects"):
            if j <= i:
                continue
            area = row.geometry.intersection(metric.geometry.iloc[j]).area
            if area > 1.0:
                overlaps.append((int(row.district), int(metric.iloc[j]["district"]), area))
    if overlaps:
        raise RuntimeError(f"department {dept}: exported district polygons overlap by more than 1 m²; e.g. {overlaps[:3]}")


def main() -> None:
    acceptance = verify_acceptance_certificate()
    EXPORT.mkdir(exist_ok=True)
    layout_path = HEMICYCLE_LAYOUT_SOURCE
    if not layout_path.is_file():
        raise RuntimeError("refusing to export: the pinned official Assembly seat layout is missing")
    hemicycle_layout = json.loads(layout_path.read_text(encoding="utf-8"))
    if len(hemicycle_layout.get("seats", [])) < 570 or not hemicycle_layout.get("viewBox"):
        raise RuntimeError("refusing to export: the pinned official Assembly seat layout is incomplete")
    browser_dir = EXPORT / "browser"
    browser_dir.mkdir(parents=True, exist_ok=True)
    (browser_dir / "hemicycle-layout.js").write_text(
        "window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};"
        + "window.REDISTRICTING_DATA['hemicycle-layout']="
        + json.dumps(hemicycle_layout, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + ";\n",
        encoding="utf-8",
    )
    (EXPORT / "acceptance.json").write_text(
        json.dumps({"status": "PENDING", "reason": "The certified map is being exported."}, ensure_ascii=False),
        encoding="utf-8",
    )
    for sub in ("maps", "cells"):
        (EXPORT / sub).mkdir(exist_ok=True)
        for old in (EXPORT / sub).glob("*.geojson*"):
            old.unlink()  # remove files from earlier exports
    for old in EXPORT.glob("departments.geojson*"):
        old.unlink()
    st = pickle.load(open(ROOT / "data/processed/gate1/sampler_state.pkl", "rb"))
    geometry_path = ROOT / "data/processed/gate1" / st.get("geometry_file", "unit_geometry_wkb.pkl")
    st["geometry"] = pickle.load(open(geometry_path, "rb"))
    epci_of = st.get("epci_of", {})
    # Repair older checkpoints that looked up EPCI membership directly from
    # u[:5]. IRIS units inherit from that base code; municipal arrondissements
    # and their IRIS inherit from the parent commune in the official ARM layer.
    cdf = gpd.read_file(ADMIN / "COMMUNE.shp", ignore_geometry=True)
    epci_by_commune = {
        str(r.INSEE_COM): (str(r.SIREN_EPCI) if pd.notna(r.SIREN_EPCI) and str(r.SIREN_EPCI).strip() else None)
        for r in cdf[["INSEE_COM", "SIREN_EPCI"]].itertuples(index=False)
    }
    arm_df = gpd.read_file(ADMIN / "ARRONDISSEMENT_MUNICIPAL.shp", ignore_geometry=True)
    arm_to_commune = dict(zip(arm_df["INSEE_ARM"].astype(str), arm_df["INSEE_COM"].astype(str)))
    epci_of = {
        u: epci_by_commune.get(arm_to_commune.get(u[:5] if len(u) >= 9 else u, u[:5] if len(u) >= 9 else u))
        for u in st["units"]
    }
    gate = json.load(open(ROOT / "data/processed/gate1/step1_graph_audit.json"))
    arr_codes = set(gpd.read_file(ADMIN / "ARRONDISSEMENT_MUNICIPAL.shp")["INSEE_ARM"].astype(str))
    names = gpd.read_file(ADMIN / "DEPARTEMENT.shp")[["INSEE_DEP", "NOM_M"]]
    dept_name = {str(r.INSEE_DEP): r.NOM_M for r in names.itertuples()}

    # rebuild the summary from every department file (summary.csv is overwritten by partial runs)
    rows_all = []
    for path in sorted((ROOT / "data/processed/plans").glob("*.json")):
        res = json.load(open(path))
        valid = [p_ for p_ in res["plans"] if p_["valid"]]
        scored = [(p_, epci_split_term(p_["assignment"], epci_of)) for p_ in valid]
        raw_counts = [epci_split_count(p_["assignment"], epci_of)[0] for p_ in valid]
        represented_counts = [epci_split_count(p_["assignment"], epci_of)[1] for p_ in valid]
        lower_counts = [epci_split_lower_bound(p_["assignment"], epci_of) for p_ in valid]
        max_counts = [epci_split_max_possible(p_["assignment"], epci_of) for p_ in valid]
        missing_counts = [epci_missing_membership_count(p_["assignment"], epci_of) for p_ in valid]
        rows_all.append({
            "dept": res["dept"], "name": dept_name.get(res["dept"], ""),
            "seats": res["seats"], "units": res["units"],
            "population": res["population"], "target": round(res["target"]),
            "population_reference_year": 2017 if res["dept"] == "976" else 2021,
            "feasible": res["feasible"], "plans": len(res["plans"]), "valid_plans": len(valid),
            "sampled_max_deviation": max((p_["max_deviation"] for p_ in valid), default=None),
            "mean_l_epci": round(sum(value for _, value in scored) / len(scored), 4) if scored else None,
            "mean_epci_excess_splits": round(sum(raw_counts) / len(raw_counts), 3) if raw_counts else None,
            "mean_epci_unavoidable_excess_splits": round(sum(lower_counts) / len(lower_counts), 3) if lower_counts else None,
            "mean_epci_max_possible_excess_splits": round(sum(max_counts) / len(max_counts), 3) if max_counts else None,
            "represented_epci_count": max(represented_counts, default=None),
            "epci_missing_membership_units": max(missing_counts, default=None),
        })
    summary = pd.DataFrame(rows_all).sort_values("dept")
    # optimized plan per department (optimize_departments.py); the map shows it when it exists
    opt_rows = {}
    for path in sorted((ROOT / "data/processed/optimized").glob("*.json")):
        res = json.load(open(path))
        opt_rows[res["dept"]] = res
    weights = Weights()
    for dept, res in opt_rows.items():
        plan_path = ROOT / "data/processed/plans" / f"{dept}.json"
        plans = json.load(open(plan_path))["plans"]
        start_assignment = next((p_["assignment"] for p_ in plans if p_["valid"]), {})
        for score_key, assignment in (("start", start_assignment), ("optimized", res["assignment"])):
            score = res[score_key]
            score["l_epci"] = epci_split_term(assignment, epci_of)
            score["epci_excess_splits"], score["epci_count"] = epci_split_count(assignment, epci_of)
            score["epci_unavoidable_excess_splits"] = epci_split_lower_bound(assignment, epci_of)
            score["epci_max_possible_excess_splits"] = epci_split_max_possible(assignment, epci_of)
            score["epci_missing_membership_units"] = epci_missing_membership_count(assignment, epci_of)
            score["L"] = (weights.pop * score["l_pop"] + weights.comp * score["l_comp"]
                           + weights.epci * score["l_epci"])
        # Keep every displayed sampled score on the corrected definition too.
        res["sampled"] = []
        for p_ in plans:
            if not p_["valid"]:
                continue
            l_epci = epci_split_term(p_["assignment"], epci_of)
            res["sampled"].append({
                "l_epci": l_epci,
                "epci_excess_splits": epci_split_count(p_["assignment"], epci_of)[0],
                "epci_unavoidable_excess_splits": epci_split_lower_bound(p_["assignment"], epci_of),
                "epci_max_possible_excess_splits": epci_split_max_possible(p_["assignment"], epci_of),
                "epci_missing_membership_units": epci_missing_membership_count(p_["assignment"], epci_of),
            })
    summary["opt_L_start"] = summary["dept"].map(lambda d: round(opt_rows[d]["start"]["L"], 4) if d in opt_rows else None)
    summary["opt_L"] = summary["dept"].map(lambda d: round(opt_rows[d]["optimized"]["L"], 4) if d in opt_rows else None)
    # This is the maximum deviation of the optimized plan actually displayed
    # by the webapp. Keep it distinct from sampled_max_deviation, which
    # summarizes exploratory samples and is not a district-plan value.
    summary["optimized_max_deviation"] = summary["dept"].map(
        lambda d: round(opt_rows[d]["optimized"]["l_pop"], 4) if d in opt_rows else None
    )
    summary["opt_l_comp"] = summary["dept"].map(lambda d: round(opt_rows[d]["optimized"]["l_comp"], 4) if d in opt_rows else None)
    summary["opt_l_epci"] = summary["dept"].map(lambda d: round(opt_rows[d]["optimized"]["l_epci"], 4) if d in opt_rows else None)
    summary.to_csv(ROOT / "data/processed/plans/summary.csv", index=False)  # replaces the stale file from partial runs

    gate_out = {k: gate.get(k) for k in [
        "passes", "contiguity_status", "unapproved_link_count", "link_candidates",
        "departments", "departments_excluded", "seats_sum", "population_sum", "flag_counts",
        "epci_covered_units", "epci_missing_membership_units",
        "infeasible_departments", "disconnected_departments", "iris_split_units", "d17_split_units",
        "d17_missing_iris_population", "iris_pieces", "island_links", "enclave_attachments"]}
    gate_out["flags"] = [{**f, "target": None if f["target"] != f["target"] else f["target"]} for f in gate["flags"]]
    (EXPORT / "gate1.json").write_text(json.dumps(gate_out, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    links = list(csv.DictReader(open(ROOT / "data/processed/gate1/ferry_bridge_edges.csv", encoding="utf-8")))
    enclaves = list(csv.DictReader(open(ROOT / "data/processed/gate1/enclave_exceptions.csv", encoding="utf-8")))
    (EXPORT / "links.json").write_text(json.dumps({"island_links": links, "enclave_exceptions": enclaves},
                                                  ensure_ascii=False), encoding="utf-8")
    rows = summary.astype(object).where(summary.notna(), None).to_dict(orient="records")
    (EXPORT / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    # atomic cells and district maps, per department, from the same geometry the engine used
    outlines = []
    for d in sorted(summary["dept"]):
        res = json.load(open(ROOT / "data/processed/plans" / f"{d}.json"))
        plans = res["plans"]
        if not plans:
            continue
        best = min((p for p in plans if p["valid"]), key=lambda p: p["max_deviation"], default=None)
        chosen = best or min(plans, key=lambda p: p["max_deviation"])
        assign = chosen["assignment"]
        is_opt = d in opt_rows
        if is_opt:  # optimized plan is valid by construction (anneal returns valid plans only)
            assign = opt_rows[d]["assignment"]
        target = res["target"]
        units = sorted(u for u in assign if u in st["geometry"])
        geoms = to_wgs84([shapely_wkb.loads(st["geometry"][u]) for u in units])

        cells = gpd.GeoDataFrame({
            "code": units,
            "kind": ["iris" if len(u) == 9 else "arrondissement" if u in arr_codes else "commune" for u in units],
            "pop": [st["pops"][u] for u in units],
            "district": [assign[u] for u in units],
            "dept": d,
        }, geometry=geoms, crs="EPSG:4326")
        cells["geometry"] = cells.geometry.simplify(SIMPLIFY_CELL, preserve_topology=True)
        cells["geometry"] = set_precision(cells.geometry.values, PRECISION)
        write_geojson_gzip(cells, EXPORT / "cells" / f"{d}.geojson.gz")

        dissolved = []
        for district, part in cells.groupby("district"):
            pop = int(part["pop"].sum())
            geom = unary_union(part.geometry.values).buffer(0)
            dissolved.append({"district": int(district), "pop": pop,
                              "deviation": round((pop - target) / target, 4), "geometry": geom})
        out = gpd.GeoDataFrame(dissolved, geometry="geometry", crs="EPSG:4326")
        out["geometry"] = out.geometry.simplify(SIMPLIFY_MAP, preserve_topology=True)
        out["geometry"] = set_precision(out.geometry.values, PRECISION)
        validate_exported_districts(out, d)
        out["valid"] = True  # certificate verifies every displayed optimized assignment
        out["validity_status"] = acceptance["status"]
        out["kind"] = "optimized" if is_opt else "sampled"
        out["dept"] = d
        write_geojson_gzip(out, EXPORT / "maps" / f"{d}.geojson.gz")
        outlines.append({"dept": d, "name": dept_name.get(d, ""), "geometry": unary_union(list(out.geometry)).buffer(0)})

    # France outline: department polygons from ADMIN EXPRESS (all departments, incl. overseas), with names
    dep_all = gpd.read_file(ADMIN / "DEPARTEMENT.shp")[["INSEE_DEP", "NOM_M", "geometry"]]
    dep_all = dep_all.rename(columns={"INSEE_DEP": "dept", "NOM_M": "name"}).to_crs("EPSG:4326")
    dep_all["geometry"] = dep_all.geometry.simplify(SIMPLIFY_DEPT, preserve_topology=True)
    dep_all["geometry"] = set_precision(dep_all.geometry.values, PRECISION)
    write_geojson_gzip(dep_all, EXPORT / "departments.geojson.gz")
    (EXPORT / "acceptance.json").write_text(json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_browser_data import main as build_browser_data
    build_browser_data()
    size = sum(f.stat().st_size for f in EXPORT.rglob("*") if f.is_file()) / 1e6
    print(f"exported {len(outlines)} departments to {EXPORT} ({size:.1f} MB)")


if __name__ == "__main__":
    main()

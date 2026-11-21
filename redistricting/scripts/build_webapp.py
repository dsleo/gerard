"""Build the static webapp data: department outlines, one map per department, and summaries.

Run from redistricting/ after Gate 1 and the sampler:
    .venv/bin/python scripts/run_blind.py build_webapp.py
Writes webapp/data/ (JSON and GeoJSON). Open webapp/index.html in a browser (no server needed).
"""

from __future__ import annotations

import csv
import glob
import json
import pickle
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redistrict.ingest.generation import install_generation_guard

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "build_webapp.py")
WEB = ROOT / "webapp" / "data"
ADMIN = ROOT / "data/processed/admin_express_fra/ADMIN-EXPRESS-COG_3-2__SHP_WGS84G_FRA_2024-02-22/ADMIN-EXPRESS-COG/1_DONNEES_LIVRAISON_2024-03-00168/ADECOG_3-2_SHP_WGS84G_FRA-ED2024-02-22"
IRIS_FXX = glob.glob(str(ROOT / "data/processed/iris/CONTOURS-IRIS_3-0__SHP_LAMB93_FXX_2024-01-01/**/CONTOURS-IRIS.shp"), recursive=True)[0]
IRIS_REU = glob.glob(str(ROOT / "data/processed/iris_reu/**/CONTOURS-IRIS.shp"), recursive=True)[0]
SIMPLIFY = 0.0005  # degrees, roughly 50 m


def load_geometry(codes: set[str]) -> gpd.GeoDataFrame:
    communes = gpd.read_file(ADMIN / "COMMUNE.shp")[["INSEE_COM", "geometry"]].rename(columns={"INSEE_COM": "code"})
    arr = gpd.read_file(ADMIN / "ARRONDISSEMENT_MUNICIPAL.shp")[["INSEE_ARM", "geometry"]].rename(columns={"INSEE_ARM": "code"})
    iris_fxx = gpd.read_file(IRIS_FXX)[["CODE_IRIS", "geometry"]].rename(columns={"CODE_IRIS": "code"}).to_crs("EPSG:4326")
    iris_reu = gpd.read_file(IRIS_REU)[["CODE_IRIS", "geometry"]].rename(columns={"CODE_IRIS": "code"}).to_crs("EPSG:4326")
    both = pd.concat([iris_fxx, iris_reu, arr, communes], ignore_index=True)
    both["code"] = both["code"].astype(str)
    both = both[both["code"].isin(codes)].drop_duplicates("code", keep="first")
    return gpd.GeoDataFrame(both, geometry="geometry", crs="EPSG:4326").set_index("code")


def main() -> None:
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "dept").mkdir(exist_ok=True)
    st = pickle.load(open(ROOT / "data/processed/gate1/sampler_state.pkl", "rb"))
    gate = json.load(open(ROOT / "data/processed/gate1/step1_graph_audit.json"))
    summary = pd.read_csv(ROOT / "data/processed/plans/summary.csv", dtype={"dept": str})

    # Gate 1 for the page
    gate_out = {
        "passes": gate["passes"],
        "contiguity_status": gate.get("contiguity_status", "UNRESOLVED"),
        "unapproved_link_count": gate.get("unapproved_link_count", 0),
        "link_candidates": gate.get("link_candidates", []),
        "departments": gate["departments"],
        "excluded": gate["departments_excluded"],
        "seats_sum": gate["seats_sum"],
        "population_sum": gate["population_sum"],
        "flag_counts": gate["flag_counts"],
        "flags": gate["flags"],
        "infeasible_departments": gate["infeasible_departments"],
        "disconnected_departments": gate["disconnected_departments"],
        "iris_split_units": gate.get("iris_split_units", []),
        "iris_pieces": gate.get("iris_pieces", 0),
        "island_links": gate.get("island_links", 0),
        "enclave_attachments": gate.get("enclave_attachments", 0),
    }
    for f in gate_out["flags"]:
        if isinstance(f.get("target"), float) and f["target"] != f["target"]:
            f["target"] = None  # NaN is not valid JSON
    (WEB / "gate1.json").write_text(json.dumps(gate_out, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    links = list(csv.DictReader(open(ROOT / "data/processed/gate1/ferry_bridge_edges.csv", encoding="utf-8")))
    enclaves = list(csv.DictReader(open(ROOT / "data/processed/gate1/enclave_exceptions.csv", encoding="utf-8")))
    (WEB / "links.json").write_text(json.dumps({"island_links": links, "enclave_exceptions": enclaves},
                                               ensure_ascii=False), encoding="utf-8")

    rows = summary.astype(object).where(summary.notna(), None).to_dict(orient="records")
    (WEB / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, default=str, allow_nan=False), encoding="utf-8")

    # One map per department: the first valid sampled plan, units coloured by district
    all_codes = set(st["units"])
    geo = load_geometry(all_codes)
    depts = sorted({r["dept"] for r in rows})
    outlines = []
    for d in depts:
        path = ROOT / "data/processed/plans" / f"{d}.json"
        if not path.exists():
            continue
        res = json.load(open(path))
        valid = [p for p in res["plans"] if p["valid"]]
        units_d = [u for u in st["units"] if st["unit_dept"][u] == d]
        g = geo.loc[[u for u in units_d if u in geo.index]].copy()
        if valid:
            assign = valid[0]["assignment"]
            g["district"] = [int(assign.get(u, -1)) for u in g.index]
        else:
            g["district"] = -1
        g["pop"] = [st["pops"][u] for u in g.index]
        g = g.reset_index().rename(columns={"code": "unit"})
        g["geometry"] = g.geometry.simplify(SIMPLIFY, preserve_topology=True)
        g.to_file(WEB / "dept" / f"{d}.geojson", driver="GeoJSON")
        outlines.append({"dept": d, "geometry": g.union_all().buffer(0)})

    out = gpd.GeoDataFrame(outlines, geometry="geometry", crs="EPSG:4326")
    out["geometry"] = out.geometry.simplify(0.002, preserve_topology=True)
    out.to_file(WEB / "departments.geojson", driver="GeoJSON")
    print(f"wrote {WEB}: {len(depts)} departments")


if __name__ == "__main__":
    main()

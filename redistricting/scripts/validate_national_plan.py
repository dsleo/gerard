"""Fail-closed acceptance check for the optimized national map.

This validates the exact assignments that would be exported. It uses only
physical shared-border edges plus reviewed, source-backed links from Gate 1.
"""

from __future__ import annotations

import csv
import hashlib
import json
import pickle
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.validate.constraints import validate_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "validate_national_plan.py")
STATE_PATH = ROOT / "data/processed/gate1/sampler_state.pkl"
GEOMETRY_PATH = ROOT / "data/processed/gate1/unit_geometry_wkb.pkl"
GATE1_PATH = ROOT / "data/processed/gate1/step1_graph_audit.json"
GATE2_PATH = ROOT / "data/processed/gate2/seat_allocation_comparison.csv"
OPTIMIZED_DIR = ROOT / "data/processed/optimized"
OUT = ROOT / "data/processed/acceptance"
TOL = 0.20
OVERLAP_AREA_TOL_M2 = 1.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    failures: list[str] = []
    departments: list[dict] = []
    plan_hashes: dict[str, str] = {}
    if not all(p.exists() for p in (STATE_PATH, GEOMETRY_PATH, GATE1_PATH, GATE2_PATH)):
        missing = [str(p.relative_to(ROOT)) for p in (STATE_PATH, GEOMETRY_PATH, GATE1_PATH, GATE2_PATH) if not p.exists()]
        failures.append(f"required pipeline inputs missing: {missing}")
        return write_report(failures, departments, plan_hashes, {})

    state = pickle.loads(STATE_PATH.read_bytes())
    if "certification_edges" not in state:
        failures.append("Gate 1 state lacks certification_edges; rebuild Gate 1 before validating")
        return write_report(failures, departments, plan_hashes, {})
    if state.get("seat_allocation_policy") != "D53_FIXED_12":
        failures.append("Gate 1 state does not use the approved D53 fixed-seat allocation; rebuild Gate 1")

    gate1 = json.loads(GATE1_PATH.read_text(encoding="utf-8"))
    populations = {str(k): int(v) for k, v in state["pops"].items()}
    unit_dept = {str(k): str(v) for k, v in state["unit_dept"].items()}
    dept_pop = {str(k): int(v) for k, v in state["dept_pop"].items()}
    seats = {str(k): int(v) for k, v in state["seats"].items()}
    depts = sorted(dept_pop)
    if set(populations) != set(unit_dept):
        failures.append("unit population and department inventories do not match")
    if set(depts) != set(seats) or set(depts) != set(unit_dept.values()):
        failures.append("department inventory differs across population, seat allocation, and units")
    if len(depts) != 101 or sum(seats.values()) != 558:
        failures.append(f"unexpected modeled scope: {len(depts)} departments / {sum(seats.values())} departmental seats; expected 101 / 558")
    for dept in depts:
        unit_total = sum(populations[u] for u in populations if unit_dept[u] == dept)
        if unit_total != dept_pop[dept]:
            failures.append(f"{dept}: unit population sum {unit_total} != department population {dept_pop[dept]}")

    # Confirm the selected D24 allocation exactly matches Gate 2's 577-seat,
    # fixed-overseas, D'Hondt scenario.
    allocation = pd.read_csv(GATE2_PATH, dtype={"department": str})
    selected = allocation[(allocation["national_seats"] == 577)
                          & (allocation["overseas_mode"] == "fixed")]
    selected = selected.drop_duplicates("department").set_index("department")
    if set(selected.index.astype(str)) != set(depts):
        failures.append("Gate 2 selected scenario does not cover the same 101 departments")
    else:
        if set(selected["dhondt_policy"].astype(str)) != {"D53_FIXED_12"}:
            failures.append("Gate 2 selected scenario does not use the D53 fixed-seat carry-forward policy")
        for dept in depts:
            if int(selected.loc[dept, "dhondt_seats"]) != seats[dept]:
                failures.append(f"{dept}: Gate 1 seat count differs from selected Gate 2 allocation")
    if gate1.get("flag_counts"):
        failures.append(f"Gate 1 has unresolved population/unit flags: {gate1['flag_counts']}")

    optimized_files = {p.stem: p for p in OPTIMIZED_DIR.glob("*.json") if p.stem not in {"summary"}}
    if set(optimized_files) != set(depts):
        failures.append(f"optimized plan files cover {len(optimized_files)} departments; expected exactly {len(depts)}")

    geometry = pickle.loads(GEOMETRY_PATH.read_bytes())
    # Every assigned unit must have a non-empty, valid source geometry.
    invalid_geometry = []
    for unit in populations:
        geom = wkb.loads(geometry[unit]) if unit in geometry else None
        if geom is None or geom.is_empty or not geom.is_valid:
            invalid_geometry.append(unit)
    if invalid_geometry:
        failures.append(f"{len(invalid_geometry)} assigned units lack valid non-empty geometry; e.g. {invalid_geometry[:10]}")

    for dept in depts:
        path = optimized_files.get(dept)
        if path is None:
            continue
        plan_hashes[dept] = sha256(path)
        result = json.loads(path.read_text(encoding="utf-8"))
        assignment = {str(u): int(d) for u, d in result.get("assignment", {}).items()}
        units = {u for u, d in unit_dept.items() if d == dept}
        missing, extra = sorted(units - assignment.keys()), sorted(assignment.keys() - units)
        dept_failures = []
        if missing or extra:
            dept_failures.append(f"partition mismatch: {len(missing)} missing, {len(extra)} extra")
        expected_districts = set(range(seats[dept]))
        actual_districts = set(assignment.values())
        if actual_districts != expected_districts:
            dept_failures.append(f"district labels {sorted(actual_districts)} do not equal 0..{seats[dept]-1}")
        if not missing and not extra:
            adjacency = {
                u: set(v for v in state["certification_edges"].get(u, ()) if v in units)
                for u in units
            }
            checked = validate_plan(assignment, units, populations, adjacency,
                                    dept_pop[dept] / seats[dept], TOL)
            dept_failures.extend(f"{v.rule}: {v.detail}" for v in checked.violations)

            # Unit interiors assigned to different districts must not overlap by
            # more than the documented sliver tolerance.
            unit_list = sorted(units)
            geoms = [wkb.loads(geometry[u]) for u in unit_list]
            frame = gpd.GeoDataFrame({"unit": unit_list, "district": [assignment[u] for u in unit_list]},
                                     geometry=geoms, crs="EPSG:2154")
            sindex = frame.sindex
            overlaps = []
            for i, row in enumerate(frame.itertuples()):
                for j in sindex.query(row.geometry, predicate="intersects"):
                    if j <= i or frame.iloc[j]["district"] == row.district:
                        continue
                    area = row.geometry.intersection(frame.geometry.iloc[j]).area
                    if area > OVERLAP_AREA_TOL_M2:
                        overlaps.append((row.unit, frame.iloc[j]["unit"], area))
            if overlaps:
                dept_failures.append(f"{len(overlaps)} cross-district unit overlaps exceed {OVERLAP_AREA_TOL_M2:g} m²; e.g. {overlaps[:3]}")

        departments.append({"department": dept, "seats": seats[dept], "units": len(units),
                            "districts_present": len(actual_districts), "status": "PASS" if not dept_failures else "FAIL",
                            "failures": dept_failures})
        failures.extend(f"{dept}: {item}" for item in dept_failures)

    context = {
        "departments": len(depts), "departmental_seats": sum(seats.values()),
        "population": sum(dept_pop.values()), "tolerance": TOL,
        "edge_basis": state.get("contiguity_basis"),
        "unapproved_link_candidates": int(gate1.get("unapproved_link_count", 0)),
        "note": "Unapproved candidates are never included in certification_edges; unused candidates do not invalidate a map.",
    }
    return write_report(failures, departments, plan_hashes, context)


def write_report(failures: list[str], departments: list[dict], plan_hashes: dict[str, str], context: dict) -> int:
    status = "ACCEPTED_MACHINE_CHECKS" if not failures and len(departments) == 101 else "REJECTED"
    report = {
        "status": status,
        "scope": "encoded hard constraints only; legal review is a separate release gate",
        "validation_role": "Recheck of the persisted optimized assignments against the current Gate 1 certification graph; the optimizer is not run by this command.",
        "completed_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "failures": failures,
        "departments": departments,
        "context": context,
        "plan_sha256": plan_hashes,
        "artifact_sha256": {
            str(p.relative_to(ROOT)): sha256(p)
            for p in (STATE_PATH, GEOMETRY_PATH, GATE1_PATH, GATE2_PATH) if p.exists()
        },
        "legal_review_status": "OPEN_ITEMS_REMAIN; this report is not legal certification",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "current.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# National map acceptance check", "", f"**Status: {status}.**", "",
             f"Scope: {context.get('departments', 0)} departments, {context.get('departmental_seats', 0)} departmental seats.",
             "Machine checks cover exact unit partition, seat allocation, population tolerance, certified-graph contiguity, valid geometry, and cross-district overlap.",
             "This command rechecks persisted assignments; it does not rerun the optimizer.",
             "Legal review remains a separate release gate.", "", "## Failures", ""]
    lines.extend([f"- {item}" for item in failures] or ["- none"])
    lines += ["", "## Department results", "", "| Department | Seats | Units | Status | Failures |", "|---|---:|---:|---|---:|"]
    for row in departments:
        lines.append(f"| {row['department']} | {row['seats']} | {row['units']} | {row['status']} | {len(row['failures'])} |")
    lines += ["", f"Certified edge basis: `{context.get('edge_basis', 'unavailable')}`.",
              "No output may be exported unless this file says `ACCEPTED_MACHINE_CHECKS` and its recorded plan/input hashes still match.", ""]
    (OUT / "current.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"national map validation: {status}; failures={len(failures)}; report={OUT / 'current.md'}")
    # A rejected map is a successful validation run. The status field, not the
    # process exit code, carries the accept/reject result for the orchestrator.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

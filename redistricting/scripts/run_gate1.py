"""Run Gate 1: build the national unit graph, add island links (D14), attach enclave pieces (D13),
check each department's pieces for feasibility, and write the audit.

Run from redistricting/:  .venv/bin/python scripts/run_blind.py run_gate1.py
Outputs (data/processed/gate1/):
    step1_graph_audit.json / .md     the gate report
    ferry_bridge_edges.csv           generated island links (review these, D14)
    enclave_exceptions.csv           enclave pieces attached to a district (D13)
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.allocate.policy import project_dhondt_allocation  # noqa: E402
from redistrict.allocate.departments import department_of, population_by_department  # noqa: E402
from redistrict.graph.build import build_graph, build_units, department_components  # noqa: E402
from redistrict.graph.feasibility import department_feasible  # noqa: E402
from redistrict.graph.iris import iris_geometry, split_units  # noqa: E402
from redistrict.graph.links import Link, apply_links, attach_small_pieces, nearest_link_edges  # noqa: E402
from redistrict.graph.subdivision import classify_units  # noqa: E402
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.report.gate1 import gate1_summary, write_gate1  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "run_gate1.py")
ADMIN = ROOT / "data/processed/admin_express_fra/ADMIN-EXPRESS-COG_3-2__SHP_WGS84G_FRA_2024-02-22/ADMIN-EXPRESS-COG/1_DONNEES_LIVRAISON_2024-03-00168/ADECOG_3-2_SHP_WGS84G_FRA-ED2024-02-22"
OUT = ROOT / "data/processed/gate1"
K_TOTAL_DEPARTMENTAL = 558   # 577 - 19 (D3, fixed)
SUBDIVISION_FACTOR = 1.20    # 1 + hard tolerance (D4-r)
HARD_TOL = 0.20              # D5
LINK_MAX_GAP_M = 5000        # D14
IRIS_SHP = ROOT / "data/processed/iris/CONTOURS-IRIS_3-0__SHP_LAMB93_FXX_2024-01-01/CONTOURS-IRIS/1_DONNEES_LIVRAISON_2024-12-00164/CONTOURS-IRIS_3-0_SHP_LAMB93_FXX-ED2024-01-01/CONTOURS-IRIS.shp"
IRIS_REU_SHP = ROOT / "data/processed/iris_reu/CONTOURS-IRIS_3-0__SHP_RGR92UTM40S_REU_2024-01-01/CONTOURS-IRIS/1_DONNEES_LIVRAISON_2024-12-00164/CONTOURS-IRIS_3-0_SHP_RGR92UTM40S_REU-ED2024-01-01/CONTOURS-IRIS.shp"
IRIS_POP_CSV = ROOT / "data/processed/iris_population_2022.csv"
IRIS_GRANULARITY_DEPTS = ["59", "69", "92", "93", "94", "95"]  # D17
IRIS_GRANULARITY_FACTOR = 0.25                                  # D17
FORCED = [("17019", "17369")]     # config example; verify codes against the geometry
APPROVED_LINKS = ROOT / "config/approved_contiguity_links.csv"


def main() -> None:
    t0 = time.time()
    pop = pd.read_csv(ROOT / "data/processed/cog2024_population.csv", dtype={"unit_2024": str})
    unit_pop = {r.unit_2024: (None if pd.isna(r.pop_2024) else int(r.pop_2024)) for r in pop.itertuples()}
    UNRESOLVED = {u for u, p in unit_pop.items() if p is None}
    known_pop = {u: p for u, p in unit_pop.items() if p is not None}

    communes = gpd.read_file(ADMIN / "COMMUNE.shp")
    arrondissements = gpd.read_file(ADMIN / "ARRONDISSEMENT_MUNICIPAL.shp")
    units = build_units(communes, arrondissements, sorted(unit_pop))
    arr_codes = set(arrondissements["INSEE_ARM"])
    print(f"geometry: {len(units)} units ({time.time() - t0:.0f}s)")

    # D4-r case 2 (O13 decided: IRIS split allowed): split units above the ceiling into IRIS pieces
    dept_pop0 = population_by_department(known_pop)
    seats0 = project_dhondt_allocation(dept_pop0, K_TOTAL_DEPARTMENTAL)
    to_split = [f.unit for f in classify_units(unit_pop, arr_codes, dept_pop0, seats0,
                                               SUBDIVISION_FACTOR, UNRESOLVED)
                if f.status == "INFEASIBLE_UNDER_RULE"]
    # D17: in departments whose sampling failed at commune level, split every commune above 0.25 x target
    d17_depts = set(IRIS_GRANULARITY_DEPTS)
    d17 = [u for u, p_ in unit_pop.items()
           if p_ is not None and u not in arr_codes and department_of(u) in d17_depts
           and p_ > IRIS_GRANULARITY_FACTOR * dept_pop0[department_of(u)] / seats0[department_of(u)]
           and u not in to_split]
    # D17 candidates must have complete IRIS 2022 weights on the same 2024 geography.
    iris_pop_codes = {str(c)[:5] for c in pd.read_csv(IRIS_POP_CSV, dtype={"iris": str})["iris"]}
    d17_missing = [u for u in d17 if u not in iris_pop_codes]
    if d17_missing:
        raise ValueError(f"D17 split candidates lack 2022 IRIS population weights: {d17_missing}")
    to_split = to_split + d17
    iris = pd.concat([iris_geometry(str(IRIS_SHP)), iris_geometry(str(IRIS_REU_SHP)).to_crs(units.crs)])
    iris = iris[~iris.index.duplicated()]
    iris_pop_df = pd.read_csv(IRIS_POP_CSV, dtype={"iris": str})
    iris_pop = dict(zip(iris_pop_df["iris"], iris_pop_df["pop22"]))
    split_parent_population = {u: unit_pop[u] for u in to_split}
    units, unit_pop, iris_pieces = split_units(units, unit_pop, to_split, iris, iris_pop)
    known_pop = {u: p for u, p in unit_pop.items() if p is not None}
    arr_codes = {c for c in arr_codes if c not in set(to_split)}
    print(f"IRIS split: {len(to_split)} units into {len(iris_pieces)} pieces ({time.time() - t0:.0f}s)")

    # Gate 1's physical graph contains only actual rook adjacency. Even an edge listed in
    # FORCED is a candidate until it has source/provenance review; do not let a config
    # override silently certify physical contiguity.
    physical_graph = build_graph(units, [])
    print(f"physical graph: {sum(len(v) for v in physical_graph.edges.values()) // 2} edges ({time.time() - t0:.0f}s)")

    known_units = set(units.index)
    manual_candidates = [
        Link(a, b, round(float(units.loc[a, "geometry"].distance(units.loc[b, "geometry"])), 1),
             department_of(a), "manual_override", basis="configured_edge_without_source",
             approval_status="unapproved")
        for a, b in FORCED
    ]
    # Only source-documented rows from the review file may enter the certified graph.
    approved_links = []
    if APPROVED_LINKS.exists():
        with APPROVED_LINKS.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                a, b = row["unit_a"].strip(), row["unit_b"].strip()
                source, rationale, reviewer = (row[k].strip() for k in ("source_url", "rationale", "reviewer"))
                dept = row["department"].strip()
                if not all((a, b, source, rationale, reviewer, dept)):
                    raise ValueError("approved link rows require endpoints, department, source_url, rationale, and reviewer")
                if a not in known_units or b not in known_units or a == b:
                    raise ValueError(f"approved link has unknown or repeated endpoint: {a}, {b}")
                if department_of(a) != dept or department_of(b) != dept:
                    raise ValueError(f"approved link crosses a department or has a wrong department: {a}, {b}, {dept}")
                gap = float(units.loc[a, "geometry"].distance(units.loc[b, "geometry"]))
                approved_links.append(Link(a, b, round(gap, 1), dept, "approved_transport",
                                           basis=f"{source} — {rationale} (reviewed by {reviewer})",
                                           approval_status="approved"))
    certification_graph = apply_links(physical_graph, approved_links, known_units)
    # Exploratory candidates remain in a separate graph and never feed the
    # standard sampler, optimizer, or acceptance validator.
    assumption_graph = apply_links(certification_graph, manual_candidates, known_units, include_unapproved=True)

    dept_pop = population_by_department(known_pop)
    seats = project_dhondt_allocation(dept_pop, K_TOTAL_DEPARTMENTAL)
    depts = sorted(dept_pop)

    # D14: island and estuary links, per department, on the graph as it grows
    # Repeat until no piece is left within the gap: a piece can link to another isolated piece first,
    # and the merged piece then needs its own link to the main component.
    link_list = []
    for d in depts:
        while True:
            found = nearest_link_edges(units, assumption_graph, d, LINK_MAX_GAP_M)
            if not found:
                break
            link_list += found
            assumption_graph = apply_links(assumption_graph, found, known_units, include_unapproved=True)
    print(f"island links: {len(link_list)} ({time.time() - t0:.0f}s)")

    # D13: pieces that cannot form a district are attached to their nearest piece
    enclave_list = []
    for d in depts:
        target = dept_pop[d] / seats[d]
        enclave_list += attach_small_pieces(assumption_graph, units, d, known_pop, target, HARD_TOL)

    # Per department: pieces after attaching enclaves are the pools the feasibility check uses
    components = {}
    feasibility = {}
    for d in depts:
        # Report and assess the graph that actually has physical adjacency. Candidate
        # island/enclave links do not collapse components for this legal gate.
        comps = [set(c) for c in department_components(certification_graph, d)]
        components[d] = [frozenset(p) for p in comps]
        target = dept_pop[d] / seats[d]
        comp_pops = [sum(known_pop.get(u, 0) for u in p) for p in comps]
        feasibility[d] = department_feasible(comp_pops, target, HARD_TOL, seats[d])

    flags = classify_units(unit_pop, arr_codes, dept_pop, seats, SUBDIVISION_FACTOR, UNRESOLVED)
    all_candidates = approved_links + manual_candidates + link_list + enclave_list
    summary = gate1_summary(components, flags, dept_pop, seats, excluded_depts=[],
                            forced_edges=[], feasibility=feasibility,
                            link_candidates=[l.__dict__ for l in all_candidates])
    summary["seat_allocation_policy"] = "D53_FIXED_12"
    summary["iris_split_units"] = to_split
    summary["d17_split_units"] = d17
    summary["d17_missing_iris_population"] = d17_missing
    summary["iris_pieces"] = len(iris_pieces)
    summary["island_links"] = len(link_list)
    summary["enclave_attachments"] = len(enclave_list)

    # The sampler may use the assumption graph for exploratory maps, but this must never
    # be reused as evidence that a district is physically or legally contiguous.
    import pickle
    exploratory_graph = apply_links(assumption_graph, link_list + enclave_list, known_units, include_unapproved=True)
    epci_of: dict[str, str | None] = {}
    cdf = gpd.read_file(ADMIN / "COMMUNE.shp", ignore_geometry=True)
    epci_by_commune = {
        str(r.INSEE_COM): (str(r.SIREN_EPCI) if pd.notna(r.SIREN_EPCI) and str(r.SIREN_EPCI).strip() else None)
        for r in cdf[["INSEE_COM", "SIREN_EPCI"]].itertuples(index=False)
    }
    arm_df = gpd.read_file(ADMIN / "ARRONDISSEMENT_MUNICIPAL.shp", ignore_geometry=True)
    arm_to_commune = dict(zip(arm_df["INSEE_ARM"].astype(str), arm_df["INSEE_COM"].astype(str)))
    for u in units.index:
        # IRIS units inherit through their 5-character base code. Municipal
        # arrondissement units (and IRIS inside them) inherit the parent
        # commune's EPCI. Missing official membership remains None.
        base = u[:5] if len(u) >= 9 else u
        commune = arm_to_commune.get(base, base)
        epci_of[u] = epci_by_commune.get(commune)
    summary["epci_covered_units"] = sum(value is not None for value in epci_of.values())
    summary["epci_missing_membership_units"] = sum(value is None for value in epci_of.values())
    OUT.mkdir(parents=True, exist_ok=True)
    write_gate1(summary, OUT)
    geometry_wkb = {u: units.loc[u, "geometry"].wkb for u in known_pop if u in units.index}
    with open(OUT / "unit_geometry_wkb.pkl", "wb") as fh:
        pickle.dump(geometry_wkb, fh, protocol=pickle.HIGHEST_PROTOCOL)
    with open(OUT / "graph_splits.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["parent_unit", "parent_legal_population", "iris", "pop22_weight", "weight_share", "scaled_piece_population", "scale_factor"])
        for piece in iris_pieces:
            parent_pop = split_parent_population[piece.parent]
            total_weight = parent_pop / piece.scale
            w.writerow([
                piece.parent, parent_pop, piece.code, format(piece.raw_pop, ".15g"),
                format(piece.raw_pop / total_weight, ".12g"), piece.pop, format(piece.scale, ".15g"),
            ])
    state = {
        "units": sorted(known_pop),
        "unit_dept": {u: department_of(u) for u in known_pop},
        # `edges` remains a compatibility alias for the certified graph. All
        # production generation must use certification_edges explicitly.
        "edges": {u: sorted(v for v in certification_graph.edges.get(u, ()) if v in known_pop) for u in known_pop},
        "physical_edges": {u: sorted(v for v in physical_graph.edges.get(u, ()) if v in known_pop) for u in known_pop},
        "certification_edges": {u: sorted(v for v in certification_graph.edges.get(u, ()) if v in known_pop) for u in known_pop},
        "exploratory_edges": {u: sorted(v for v in exploratory_graph.edges.get(u, ()) if v in known_pop) for u in known_pop},
        "pops": known_pop,
        "dept_pop": dept_pop,
        "seats": seats,
        "seat_allocation_policy": "D53_FIXED_12",
        "epci_of": {u: epci_of.get(u) for u in known_pop},
        "exceptions": [{"unit_a": l.a, "unit_b": l.b, "gap_m": l.gap_m, "dept": l.dept, "kind": l.kind} for l in enclave_list],
        "contiguity_basis": "physical_rook_edges_plus_source_documented_approved_links",
        "exploratory_contiguity_basis": "candidate_links_may_include_unapproved_assumptions",
        "link_candidates": [l.__dict__ for l in all_candidates],
        "approved_links": [l.__dict__ for l in approved_links],
        "unresolved": sorted(UNRESOLVED),
        # Geometry is stored separately so samplers and data consumers do not
        # deserialize hundreds of MB they never use.
        "geometry_file": "unit_geometry_wkb.pkl",
    }
    with open(OUT / "sampler_state.pkl", "wb") as fh:
        pickle.dump(state, fh)
    for name, rows in [("ferry_bridge_edges.csv", manual_candidates + link_list), ("enclave_exceptions.csv", enclave_list)]:
        with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["unit_a", "unit_b", "gap_m", "department", "kind", "basis", "approval_status"])
            for l in rows:
                w.writerow([l.a, l.b, l.gap_m, l.dept, l.kind, l.basis, l.approval_status])

    print(f"passes={summary['passes']}")
    print(f"flags: {summary['flag_counts']}")
    print(f"infeasible departments: {list(summary['infeasible_departments'])}")
    print(f"wrote {OUT} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

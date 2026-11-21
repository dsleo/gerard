"""Sample plans for every non-frozen search department, in parallel.

Run from redistricting/:
    .venv/bin/python scripts/run_blind.py sample_departments.py --replicates 3 --steps 300 --workers 4
    Outputs: exploratory candidate plans in data/processed/plans/<dept>.json and summary.csv.
    These outputs are not a validated neutral ensemble and must not support percentile or PASS/FAIL claims.
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
import sys
from functools import lru_cache, partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.parallel import run_per_department  # noqa: E402
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.sample.department import sample_department  # noqa: E402
from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402
from redistrict.sample.official import build_official_seed  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "sample_departments.py")
STATE = ROOT / "data/processed/gate1/sampler_state.pkl"
OUT = ROOT / "data/processed/plans"
OFFICIAL_CORRESPONDENCE = ROOT / "data/raw/constituencies/insee_commune_circonscription_2026.xlsx"
COG_COMMUNES = ROOT / "data/raw/insee_cog2024/v_commune_2024.csv"
COG_MOVEMENTS = ROOT / "data/raw/insee_cog2024/v_mvt_commune_2024.csv"
TOL = 0.20

@lru_cache(maxsize=1)
def _state() -> dict:
    with open(STATE, "rb") as fh:
        return pickle.load(fh)


def job(dept: str, seed: int, replicates: int, steps: int) -> dict:
    """One department. Runs in a worker process; the state is loaded once per process."""
    st = _state()
    if "certification_edges" not in st:
        raise RuntimeError("Gate 1 state predates certified-edge separation; rerun run_gate1.py before sampling")
    units = [u for u in st["units"] if st["unit_dept"][u] == dept]
    unit_set = set(units)
    adjacency = {u: frozenset(v for v in st["certification_edges"].get(u, []) if v in unit_set) for u in units}
    result = sample_department(
        units=units,
        pops=st["pops"],
        adjacency=adjacency,
        epci_of=st["epci_of"],
        seats=st["seats"][dept],
        tol=TOL,
        replicates=replicates,
        steps=steps,
        seed=seed,
    )
    result["dept"] = dept
    result["seats"] = st["seats"][dept]
    result["units"] = len(units)
    result["population"] = st["dept_pop"][dept]
    official = build_official_seed(
        dept, st, OFFICIAL_CORRESPONDENCE, COG_COMMUNES, COG_MOVEMENTS, tolerance=TOL
    )
    result["official_seed_status"] = {key: value for key, value in official.items() if key != "candidate"}
    if official.get("candidate") is not None:
        result["plans"].insert(0, {
            "replicate": -1,
            "chain_seed": None,
            "attempts_run": 0,
            "steps_requested": 0,
            "changed_steps": 0,
            "unique_states_visited": 1,
            "tolerance_schedule": "official plan unchanged",
            "assignment": official["candidate"],
            "max_deviation": round(float(official["max_population_deviation"]), 6),
            "l_epci": round(float(official["l_epci"]), 6),
            "valid": True,
            "notes": ["Official current plan from exact INSEE whole-commune correspondence; validated by project hard checks."],
            "source": "official_current",
            "official_id_to_label": official["official_id_to_label"],
        })
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replicates", type=int, default=3)
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--departments", nargs="*", help="limit to these department codes (for tests)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    st = _state()
    # D53 freezes the current official plans in these departments. Never ask
    # ReCom to regenerate them; their separate carry-forward validator remains
    # a national acceptance requirement.
    search_depts = sorted(set(st["dept_pop"]) - set(D53_FIXED_SEATS))
    depts = search_depts if not args.departments else args.departments
    unexpected = sorted(set(depts) - set(search_depts))
    if unexpected:
        ap.error(f"frozen D53 departments cannot be sampled: {unexpected}")
    worker = partial(job, replicates=args.replicates, steps=args.steps)
    results = run_per_department(worker, depts, global_seed=args.seed, workers=args.workers)

    OUT.mkdir(parents=True, exist_ok=True)
    for dept, res in results.items():
        with open(OUT / f"{dept}.json", "w", encoding="utf-8") as fh:
            json.dump(res, fh)

    # A partial department run refreshes only those plan files, but the summary
    # remains a national index over the latest file for every department.
    rows = []
    for plan_path in sorted(OUT.glob("*.json")):
        if plan_path.name == "summary.json":
            continue
        dept = plan_path.stem
        if dept in D53_FIXED_SEATS:
            continue  # Old candidate files are not part of the current search scope.
        res = json.load(open(plan_path, encoding="utf-8"))
        valid = [p for p in res["plans"] if p["valid"]]
        rows.append({
            "dept": dept, "seats": res["seats"], "units": res["units"],
            "population": res["population"], "target": round(res["target"]),
            "feasible": res["feasible"], "plans": len(res["plans"]), "valid_plans": len(valid),
            "official_seed_status": res.get("official_seed_status", {}).get("status", "NOT_CHECKED"),
            "official_seed_included": any(p.get("source") == "official_current" for p in res["plans"]),
            "sampling_status": res.get("sampling_status", "UNKNOWN"),
            "convergence_status": res.get("convergence_status", "NOT_ASSESSED"),
            "reference_use_allowed": res.get("reference_use_allowed", False),
            "sampled_max_deviation": max((p["max_deviation"] for p in res["plans"]), default=""),
            "mean_l_epci": round(sum(p["l_epci"] for p in valid) / len(valid), 4) if valid else "",
        })
    with open(OUT / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    bad = [r["dept"] for r in rows if not r["feasible"] or r["valid_plans"] < r["plans"]]
    print(f"departments: {len(rows)}; candidate plans failing constraints: {bad or 'none'}")
    print("sampling status: exploratory candidates only; convergence not assessed; reference use disabled")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

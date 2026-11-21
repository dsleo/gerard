"""Optimize non-frozen departments in parallel (weighted-sum annealing over ReCom).

Run from redistricting/:
    .venv/bin/python scripts/run_blind.py optimize_departments.py --steps 800 --workers 3
Outputs: data/processed/optimized/<dept>.json and data/processed/optimized/benchmark.csv
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import pickle
import random
import shutil
import sys
import time
import uuid
from functools import lru_cache, partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.optimize.sa import Scorer, Weights, anneal, assignment_fingerprint  # noqa: E402
from redistrict.parallel import run_per_department  # noqa: E402
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.optimizer_monitor import atomic_json, monitor_directory, write_department_progress  # noqa: E402
from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "optimize_departments.py")
STATE = ROOT / "data/processed/gate1/sampler_state.pkl"
PLANS = ROOT / "data/processed/plans"
OUT = ROOT / "data/processed/optimized"
TRACE_OUT = OUT / "traces"
TOL = 0.20
WEIGHTS = Weights(pop=0.50, comp=0.30, epci=0.20)  # config: fitness_weights


@lru_cache(maxsize=1)
def _state() -> dict:
    with open(STATE, "rb") as fh:
        state = pickle.load(fh)
    geometry_path = STATE.parent / state.get("geometry_file", "unit_geometry_wkb.pkl")
    with open(geometry_path, "rb") as fh:
        state["geometry"] = pickle.load(fh)
    return state


def job(dept: str, seed: int, steps: int, steps_per_round: int, patience_rounds: int,
        min_rounds: int, min_improvement: float) -> dict:
    st = _state()
    if "certification_edges" not in st:
        raise RuntimeError("Gate 1 state predates certified-edge separation; rerun run_gate1.py before optimization")
    units = [u for u in st["units"] if st["unit_dept"][u] == dept]
    unit_set = set(units)
    adjacency = {u: frozenset(v for v in st["certification_edges"].get(u, []) if v in unit_set) for u in units}
    target = st["dept_pop"][dept] / st["seats"][dept]
    sampled = json.load(open(PLANS / f"{dept}.json"))
    valid = [p for p in sampled["plans"] if p["valid"]]
    if not valid:
        raise ValueError(f"department {dept} has no valid sampled starting plan")
    for plan in valid:
        if set(plan["assignment"]) != unit_set:
            raise ValueError(
                f"department {dept} sampled plan does not cover the current unit set; regenerate candidates"
            )
    start = valid[0]["assignment"]
    start_source = valid[0].get("source", "sampled_recom")

    scorer = Scorer({u: st["geometry"][u] for u in units if u in st["geometry"]}, st["pops"], target,
                    st["epci_of"], WEIGHTS)
    sampled_scores = [scorer.components(p["assignment"]) for p in valid]
    start_scores = scorer.components(start)

    rng = random.Random(seed)
    monitor_root = monitor_directory()
    trace_directory = monitor_root / "traces" if monitor_root is not None else TRACE_OUT
    trace_directory.mkdir(parents=True, exist_ok=True)
    trace_path = trace_directory / f"{dept}.jsonl.gz"
    trace_work_path = trace_directory / f"{dept}.jsonl.partial"
    configuration = {
        "objective_weights": {"population": WEIGHTS.pop, "compactness": WEIGHTS.comp, "epci_splits": WEIGHTS.epci},
        "population_tolerance": TOL,
        "max_proposals": steps,
        "steps_per_round": steps_per_round,
        "patience_rounds": patience_rounds,
        "min_rounds": min_rounds,
        "min_improvement": min_improvement,
        "seed": seed,
    }
    progress_started = time.monotonic()
    with trace_work_path.open("w", encoding="utf-8") as trace_fh:
        plan_input_sha256 = hashlib.sha256((PLANS / f"{dept}.json").read_bytes()).hexdigest()
        trace_fh.write(json.dumps({
            "event": "run_metadata",
            "trace_schema_version": 2,
            "trace_run_id": monitor_root.name if monitor_root is not None else TRACE_OUT.name,
            "dept": dept,
            "seed": seed,
            "start_source": start_source,
            "configuration": configuration,
            "sampled_plan_file": str((PLANS / f"{dept}.json").relative_to(ROOT)),
            "sampled_plan_file_sha256": plan_input_sha256,
            "start_assignment": dict(sorted(start.items())),
            "start_assignment_hash": assignment_fingerprint(start),
            "start_metrics": start_scores,
            "sampled_candidate_metrics": sampled_scores,
        }, separators=(",", ":")) + "\n")
        trace_fh.flush()

        def write_trace(record: dict) -> None:
            trace_fh.write(json.dumps(record, separators=(",", ":")) + "\n")
            # Keep an append-only recovery trace if the process stops abruptly.
            trace_fh.flush()
            progress = {
                "dept": dept,
                "status": "RUNNING",
                "configuration": configuration,
                "elapsed_seconds": round(time.monotonic() - progress_started, 2),
                "event": record.get("event"),
                "step": record.get("step", record.get("last_step", 0)),
                "round": record.get("round"),
                "temperature": record.get("temperature"),
                "proposal_status": record.get("proposal_status", "round checkpoint"),
                "current": record.get("current"),
                "best": record.get("best"),
                "current_hash": record.get("current_hash"),
                "best_hash": record.get("best_hash"),
                "trace_file": str(trace_work_path.relative_to(ROOT)),
            }
            write_department_progress(progress)

        best, best_c, accepted, run_diagnostics = anneal(
            start, adjacency, scorer, st["pops"], target, TOL, steps=steps, rng=rng,
            steps_per_round=steps_per_round, patience_rounds=patience_rounds,
            min_rounds=min_rounds, min_improvement=min_improvement, trace_callback=write_trace,
        )
    with trace_work_path.open("rb") as source, gzip.open(trace_path, "wb") as compressed:
        shutil.copyfileobj(source, compressed)
    trace_work_path.unlink()
    trace_sha256 = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    write_department_progress({
        "dept": dept,
        "status": "COMPLETED",
        "configuration": configuration,
        "elapsed_seconds": round(time.monotonic() - progress_started, 2),
        "proposals_completed": run_diagnostics["proposals_completed"],
        "accepted_moves": accepted,
        "start": start_scores,
        "start_source": start_source,
        "best": best_c,
        "run_diagnostics": run_diagnostics,
        "trace_schema_version": 2,
        "trace_file": str(trace_path.relative_to(ROOT)),
        "trace_sha256": trace_sha256,
    })
    return {
        "dept": dept,
        "seats": st["seats"][dept],
        "target": target,
        "steps": steps,
        "seed": seed,
        "accepted": accepted,
        "run_diagnostics": run_diagnostics,
        "trace_file": str(trace_path.relative_to(ROOT)),
        "trace_sha256": trace_sha256,
        "start": start_scores,
        "start_source": start_source,
        "optimized": best_c,
        "sampled": sampled_scores,
        "assignment": dict(sorted(best.items())),
    }


def main() -> None:
    global TRACE_OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=800)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--steps-per-round", type=int, default=100)
    ap.add_argument("--patience-rounds", type=int, default=3,
                    help="stop after this many stale rounds; 0 disables early stopping")
    ap.add_argument("--min-rounds", type=int, default=4)
    ap.add_argument("--min-improvement", type=float, default=1e-4,
                    help="minimum best-score improvement per round to reset patience")
    ap.add_argument("--departments", nargs="*")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    st = _state()
    # D53 freezes the current official plans in these departments. Never ask
    # ReCom to regenerate them; their separate carry-forward validator remains
    # a national acceptance requirement.
    search_depts = sorted(set(st["dept_pop"]) - set(D53_FIXED_SEATS))
    depts = search_depts if not args.departments else args.departments
    unexpected = sorted(set(depts) - set(search_depts))
    if unexpected:
        ap.error(f"frozen D53 departments cannot be optimized: {unexpected}")
    if args.steps <= 0 or args.steps_per_round <= 0 or args.min_rounds <= 0 \
            or args.patience_rounds < 0 or args.min_improvement < 0:
        ap.error("steps, steps-per-round, and min-rounds must be positive; patience and min-improvement non-negative")
    root_monitor = monitor_directory()
    if root_monitor is not None:
        (root_monitor / "traces").mkdir(parents=True, exist_ok=True)
        (root_monitor / "departments").mkdir(parents=True, exist_ok=True)
        atomic_json(root_monitor / "optimizer_configuration.json", {
            "trace_schema_version": 2,
            "weights": {"population": WEIGHTS.pop, "compactness": WEIGHTS.comp, "epci_splits": WEIGHTS.epci},
            "population_tolerance": TOL,
            "max_proposals": args.steps,
            "steps_per_round": args.steps_per_round,
            "patience_rounds": args.patience_rounds,
            "min_rounds": args.min_rounds,
            "min_improvement": args.min_improvement,
            "workers": args.workers,
            "seed": args.seed,
            "departments": depts,
        })
    else:
        TRACE_OUT = TRACE_OUT / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8])
        TRACE_OUT.mkdir(parents=True, exist_ok=True)
        atomic_json(TRACE_OUT / "optimizer_configuration.json", {
            "trace_schema_version": 2,
            "weights": {"population": WEIGHTS.pop, "compactness": WEIGHTS.comp, "epci_splits": WEIGHTS.epci},
            "population_tolerance": TOL,
            "max_proposals": args.steps,
            "steps_per_round": args.steps_per_round,
            "patience_rounds": args.patience_rounds,
            "min_rounds": args.min_rounds,
            "min_improvement": args.min_improvement,
            "workers": args.workers,
            "seed": args.seed,
            "departments": depts,
        })
    worker = partial(job, steps=args.steps, steps_per_round=args.steps_per_round,
                     patience_rounds=args.patience_rounds, min_rounds=args.min_rounds,
                     min_improvement=args.min_improvement)
    results = run_per_department(worker, depts, global_seed=args.seed, workers=args.workers)

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for d, res in results.items():
        with open(OUT / f"{d}.json", "w", encoding="utf-8") as fh:
            json.dump(res, fh)
        sampled = res["sampled"]
        rows.append({
            "dept": d, "seats": res["seats"],
            "L_start": round(res["start"]["L"], 4),
            "L_optimized": round(res["optimized"]["L"], 4),
            "L_sampled_mean": round(sum(s["L"] for s in sampled) / len(sampled), 4) if sampled else "",
            "L_sampled_best": round(min(s["L"] for s in sampled), 4) if sampled else "",
            "start_source": res.get("start_source", "sampled_recom"),
            "comp_optimized": round(res["optimized"]["l_comp"], 4),
            "epci_optimized": round(res["optimized"]["l_epci"], 4),
            "pop_dev_optimized": round(res["optimized"]["l_pop"], 4),
            "accepted_moves": res["accepted"],
            "proposals_completed": res["run_diagnostics"]["proposals_completed"],
            "rounds_completed": res["run_diagnostics"]["rounds_completed"],
            "early_stopped": res["run_diagnostics"]["early_stopped"],
        })
    with open(OUT / "benchmark.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    better = sum(1 for r in rows if r["L_optimized"] <= r["L_sampled_best"])
    print(f"departments: {len(rows)}; optimized plan at least as good as the best sampled plan in {better}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

"""Run the vote-blind search for 89 departments; do not accept/export a national map.

Usage: .venv/bin/python scripts/run_national_pipeline.py
Each generation stage runs through run_blind.py. The orchestration process only
reads/writes processed artifacts and never reads electoral quarantine data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402

BLIND = ROOT / "scripts/run_blind.py"
PIPELINE_DIR = ROOT / "data/processed/pipeline_runs"
ACCEPTANCE_DIR = ROOT / "data/processed/acceptance"
EXPORT = ROOT / "export"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replicates", type=int, default=3)
    ap.add_argument("--sample-steps", type=int, default=300)
    ap.add_argument("--optimizer-steps", type=int, default=800)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--optimizer-steps-per-round", type=int, default=100)
    ap.add_argument("--optimizer-patience-rounds", type=int, default=3)
    ap.add_argument("--optimizer-min-rounds", type=int, default=4)
    ap.add_argument("--optimizer-min-improvement", type=float, default=1e-4)
    args = ap.parse_args()
    if min(args.replicates, args.sample_steps, args.optimizer_steps, args.workers) <= 0:
        ap.error("replicates, steps, and workers must be positive")
    if args.optimizer_steps_per_round <= 0 or args.optimizer_min_rounds <= 0 \
            or args.optimizer_patience_rounds < 0 or args.optimizer_min_improvement < 0:
        ap.error("optimizer round size/minimum rounds must be positive; patience and improvement non-negative")

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = PIPELINE_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    report = {"run_id": run_id, "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "status": "RUNNING", "stages": [], "arguments": vars(args),
              "search_scope": "D53 non-frozen departments only; the 12 official carry-forward departments are excluded from ReCom search.",
              "validity_rule": "Generated search plans require exact partition + 0.5m shared-border/source-approved graph contiguity + +/-20% population + selected Gate 2 seats + valid geometry/no cross-district overlap. This run does not validate frozen carry-forward assignments.",
              "legal_scope": "Machine checks do not close the project's open legal-review items."}
    monitor_dir_value = os.environ.get("REDISTRICT_MONITOR_DIR")
    monitor_run_path = Path(monitor_dir_value) / "run.json" if monitor_dir_value else None

    def update_monitor(**updates) -> None:
        if monitor_run_path is None or not monitor_run_path.exists():
            return
        monitor_state = json.loads(monitor_run_path.read_text(encoding="utf-8"))
        monitor_state.update(updates)
        atomic_json(monitor_run_path, monitor_state)

    update_monitor(pipeline_run_id=run_id, pipeline_status="RUNNING")
    # This run explores only the 89 D53 search departments. It must not change
    # the acceptance state of any previously certified national map.

    def stage(name: str, script: str, *script_args: str) -> bool:
        log = run_dir / f"{name}.log"
        cmd = [sys.executable, str(BLIND), script, *script_args]
        update_monitor(current_stage=name, stage_started_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
                                  env=os.environ.copy(), check=False)
        report["stages"].append({"name": name, "script": script, "arguments": list(script_args),
                                 "exit_code": proc.returncode, "log": str(log.relative_to(ROOT))})
        atomic_json(run_dir / "run.json", report)
        update_monitor(current_stage=name, last_stage_exit_code=proc.returncode,
                       stages=report["stages"])
        return proc.returncode == 0

    def preserve_artifacts(name: str, sources: list[Path]) -> None:
        """Keep run-scoped copies of candidate/final outputs before shared files refresh."""
        destination = run_dir / "artifacts" / name
        destination.mkdir(parents=True, exist_ok=True)
        manifest = []
        for source in sources:
            if not source.is_file():
                continue
            target = destination / source.name
            shutil.copy2(source, target)
            manifest.append({
                "file": target.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "bytes": target.stat().st_size,
            })
        atomic_json(destination / "manifest.json", {"artifacts": manifest})
        report.setdefault("preserved_artifacts", {})[name] = str(destination.relative_to(ROOT))
        atomic_json(run_dir / "run.json", report)
        update_monitor(preserved_artifacts=report["preserved_artifacts"])

    def reject(status: str, reasons: list[str], *, preserve_acceptance_report: bool = False) -> int:
        report["status"] = status
        report["failures"] = reasons
        report["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        acceptance = {"status": "REJECTED", "run_id": run_id, "reasons": reasons,
                      "scope": "No map was accepted or exported by this run."}
        if not preserve_acceptance_report:
            atomic_json(ACCEPTANCE_DIR / "current.json", acceptance)
        atomic_json(EXPORT / "acceptance.json", acceptance)
        atomic_json(run_dir / "run.json", report)
        atomic_json(PIPELINE_DIR / "latest.json", report)
        update_monitor(status=status, completed_utc=report["completed_utc"], failures=reasons,
                       pipeline_status=status, current_stage="complete", stages=report["stages"])
        print(f"National map pipeline: {status}; see {run_dir / 'run.json'}")
        return 1

    def complete_search_only(search_departments: list[str]) -> int:
        report["status"] = "SEARCH_COMPLETED_NOT_CERTIFIED"
        report["search_departments"] = search_departments
        report["carry_forward_departments"] = sorted(D53_FIXED_SEATS)
        report["limitations"] = [
            "The 89 non-frozen departments were sampled and optimized.",
            "The 12 D53 departments were left unchanged and excluded from search.",
            "This run reports the 89-department search; it does not publish a combined national map.",
        ]
        report["completion_note"] = (
            "Recherche sur les 89 départements non gelés. Les 12 départements officiels sont conservés tels quels."
        )
        report["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        atomic_json(run_dir / "run.json", report)
        atomic_json(PIPELINE_DIR / "latest.json", report)
        update_monitor(status=report["status"], pipeline_status=report["status"],
                       current_stage="search_complete_carry_forward_validation_pending",
                       completed_utc=report["completed_utc"], stages=report["stages"],
                       preserved_artifacts=report.get("preserved_artifacts", {}),
                       search_departments=search_departments,
                       carry_forward_departments=report["carry_forward_departments"],
                       limitations=report["limitations"])
        print(f"Search completed for {len(search_departments)} departments; national map not certified.")
        return 0

    for name, script, stage_args in [
        ("population_map", "map_to_cog2024.py", []),
        ("gate1", "run_gate1.py", []),
        ("gate2", "run_gate2.py", []),
    ]:
        if not stage(name, script, *stage_args):
            return reject(f"REJECTED_AT_{name.upper()}", [f"Stage {name} failed; inspect its log and blindness report."])

    gate = json.loads((ROOT / "data/processed/gate1/step1_graph_audit.json").read_text(encoding="utf-8"))
    state = pickle.loads((ROOT / "data/processed/gate1/sampler_state.pkl").read_bytes())
    search_departments = sorted(set(state["dept_pop"]) - set(D53_FIXED_SEATS))
    blockers = []
    infeasible_search = {d: reason for d, reason in gate.get("infeasible_departments", {}).items()
                         if d not in D53_FIXED_SEATS}
    disconnected_search = {d: parts for d, parts in gate.get("disconnected_departments", {}).items()
                           if d not in D53_FIXED_SEATS}
    if infeasible_search:
        blockers.extend(f"Gate 1 {dept}: {reason}" for dept, reason in infeasible_search.items())
    if disconnected_search:
        blockers.extend(f"Gate 1 {dept}: physical graph has disconnected components" for dept in disconnected_search)
    if gate.get("flag_counts"):
        blockers.append(f"Gate 1 has unresolved unit/population flags: {gate['flag_counts']}")
    if gate.get("departments") != 101 or gate.get("seats_sum") != 558:
        blockers.append(f"Gate 1 scope mismatch: departments={gate.get('departments')}, seats={gate.get('seats_sum')}")
    if blockers:
        return reject("REJECTED_AT_GATE1", blockers)

    sample_args = ["--replicates", str(args.replicates), "--steps", str(args.sample_steps),
                   "--workers", str(args.workers), "--seed", str(args.seed)]
    if not stage("sampling", "sample_departments.py", *sample_args):
        return reject("REJECTED_AT_SAMPLING", ["Certified-graph sampling stage failed."])
    sample_dir = ROOT / "data/processed/plans"
    sample_blockers = []
    for dept in search_departments:
        p = sample_dir / f"{dept}.json"
        if not p.exists():
            sample_blockers.append(f"{dept}: no sample output")
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        if not r.get("feasible") or not any(pl.get("valid") for pl in r.get("plans", [])):
            sample_blockers.append(f"{dept}: no valid certified-graph starting plan ({r.get('reason', 'no valid sample')})")
    if sample_blockers:
        return reject("REJECTED_AT_SAMPLING", sample_blockers)
    preserve_artifacts("starting_plans", [sample_dir / f"{dept}.json" for dept in search_departments])

    optimizer_args = ["--steps", str(args.optimizer_steps), "--workers", str(args.workers), "--seed", str(args.seed),
                      "--steps-per-round", str(args.optimizer_steps_per_round),
                      "--patience-rounds", str(args.optimizer_patience_rounds),
                      "--min-rounds", str(args.optimizer_min_rounds),
                      "--min-improvement", str(args.optimizer_min_improvement)]
    if not stage("optimization", "optimize_departments.py", *optimizer_args):
        return reject("REJECTED_AT_OPTIMIZATION", ["Certified-graph optimizer stage failed."])
    optimized_dir = ROOT / "data/processed/optimized"
    preserve_artifacts("optimized_plans", [
        *[optimized_dir / f"{dept}.json" for dept in search_departments],
        optimized_dir / "benchmark.csv",
    ])
    return complete_search_only(search_departments)


if __name__ == "__main__":
    raise SystemExit(main())

"""Independently validate one search run and its full proposal-trace integrity.

Run through run_blind.py with a pipeline run id and optimizer-monitor run id.
The report is deliberately scoped to the 89 generated departments; it is not
the separate national acceptance/carry-forward certification.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import pickle
import sys
from pathlib import Path

import geopandas as gpd
from shapely import wkb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.optimize.sa import Scorer, Weights, assignment_fingerprint  # noqa: E402
from redistrict.validate.constraints import validate_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "audit_search_run_results.py")
STATE_PATH = ROOT / "data/processed/gate1/sampler_state.pkl"
GEOMETRY_PATH = ROOT / "data/processed/gate1/unit_geometry_wkb.pkl"
OFFICIAL_AUDIT = ROOT / "data/processed/official_seed_audit/departments.csv"
TOLERANCE = 0.20
OVERLAP_AREA_TOL_M2 = 1.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_assignment(value: dict) -> dict[str, int]:
    return {str(unit): int(district) for unit, district in value.items()}


def verify_manifest(folder: Path) -> list[str]:
    manifest_path = folder / "manifest.json"
    failures: list[str] = []
    if not manifest_path.is_file():
        return [f"missing artifact manifest: {manifest_path.relative_to(ROOT)}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest.get("artifacts", []):
        path = ROOT / item["file"]
        if not path.is_file():
            failures.append(f"missing preserved artifact: {item['file']}")
        elif path.stat().st_size != int(item["bytes"]) or sha256(path) != item["sha256"]:
            failures.append(f"preserved artifact hash/size mismatch: {item['file']}")
    return failures


def replay_trace(path: Path, monitor_run_id: str, expected: dict, sampled_hash: str) -> list[str]:
    failures: list[str] = []
    metadata = None
    current: dict[str, int] | None = None
    best: dict[str, int] | None = None
    proposals = 0
    checkpoints = 0
    run_starts = 0
    run_ends = 0
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                row = json.loads(line)
                event = row.get("event")
                if event == "run_metadata":
                    if metadata is not None:
                        failures.append("trace contains duplicate run_metadata")
                    metadata = row
                    if row.get("trace_schema_version") != 2:
                        failures.append("unexpected trace schema version")
                    if row.get("trace_run_id") != monitor_run_id:
                        failures.append("trace run id does not match the monitor run")
                    if row.get("sampled_plan_file_sha256") != sampled_hash:
                        failures.append("trace sampled-plan hash does not match preserved start artifact")
                elif event == "run_start":
                    run_starts += 1
                    current = as_assignment(row["assignment"])
                    best = dict(current)
                    if assignment_fingerprint(current) != row.get("assignment_hash"):
                        failures.append(f"line {line_number}: run-start fingerprint mismatch")
                elif event == "proposal":
                    proposals += 1
                    if current is None or best is None:
                        failures.append(f"line {line_number}: proposal precedes run_start")
                        continue
                    before_hash = assignment_fingerprint(current)
                    if before_hash != row.get("current_before_hash"):
                        failures.append(f"line {line_number}: current-before fingerprint mismatch")
                    candidate = dict(current)
                    candidate.update({str(unit): int(district)
                                      for unit, district in row.get("candidate_delta", {}).items()})
                    if assignment_fingerprint(candidate) != row.get("candidate_hash"):
                        failures.append(f"line {line_number}: candidate fingerprint mismatch")
                    if row.get("proposal_status") == "accepted":
                        current = candidate
                    if assignment_fingerprint(current) != row.get("current_hash"):
                        failures.append(f"line {line_number}: current fingerprint mismatch")
                    best_hash = assignment_fingerprint(best)
                    if row.get("best_hash") != best_hash:
                        # A newly improved best state is always the accepted current state.
                        if row.get("best_hash") != assignment_fingerprint(current):
                            failures.append(f"line {line_number}: best fingerprint is not replayable")
                        else:
                            best = dict(current)
                elif event == "round_checkpoint":
                    checkpoints += 1
                    if current is None or best is None:
                        failures.append(f"line {line_number}: checkpoint precedes run_start")
                        continue
                    if as_assignment(row.get("current_assignment", {})) != current:
                        failures.append(f"line {line_number}: current checkpoint assignment mismatch")
                    if as_assignment(row.get("best_assignment", {})) != best:
                        failures.append(f"line {line_number}: best checkpoint assignment mismatch")
                    if assignment_fingerprint(current) != row.get("current_hash"):
                        failures.append(f"line {line_number}: current checkpoint fingerprint mismatch")
                    if assignment_fingerprint(best) != row.get("best_hash"):
                        failures.append(f"line {line_number}: best checkpoint fingerprint mismatch")
                elif event == "run_end":
                    run_ends += 1
                    final = as_assignment(row.get("best_assignment", {}))
                    if best is not None and final != best:
                        failures.append(f"line {line_number}: final best assignment differs from replay")
                    if assignment_fingerprint(final) != row.get("best_hash"):
                        failures.append(f"line {line_number}: final best fingerprint mismatch")
                    diagnostic = row.get("diagnostics", {})
                    if int(diagnostic.get("proposals_completed", -1)) != proposals:
                        failures.append("trace proposal count differs from run-end diagnostics")
                    if int(diagnostic.get("rounds_completed", -1)) != checkpoints:
                        failures.append("trace checkpoint count differs from run-end diagnostics")
    except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        failures.append(f"trace cannot be fully read: {type(exc).__name__}: {exc}")

    if metadata is None:
        failures.append("trace lacks run_metadata")
    if run_starts != 1:
        failures.append(f"trace has {run_starts} run_start records; expected one")
    if run_ends != 1:
        failures.append(f"trace has {run_ends} run_end records; expected one")
    if proposals != int(expected.get("run_diagnostics", {}).get("proposals_completed", -1)):
        failures.append("trace proposal count differs from optimized result")
    if checkpoints != int(expected.get("run_diagnostics", {}).get("rounds_completed", -1)):
        failures.append("trace round count differs from optimized result")
    if best is not None and best != as_assignment(expected.get("assignment", {})):
        failures.append("replayed best assignment differs from preserved optimized plan")
    return failures


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: audit_search_run_results.py <pipeline_run_id> <monitor_run_id>")
        return 2
    pipeline_run_id, monitor_run_id = sys.argv[1:]
    pipeline_dir = ROOT / "data/processed/pipeline_runs" / pipeline_run_id
    monitor_dir = ROOT / "data/processed/optimizer_monitor/runs" / monitor_run_id
    report = json.loads((pipeline_dir / "run.json").read_text(encoding="utf-8"))
    monitor = json.loads((monitor_dir / "run.json").read_text(encoding="utf-8"))
    if report.get("status") != "SEARCH_COMPLETED_NOT_CERTIFIED":
        raise ValueError(f"pipeline did not complete search successfully: {report.get('status')}")
    if monitor.get("pipeline_run_id") != pipeline_run_id:
        raise ValueError("pipeline and monitor run IDs do not point to one another")

    state = pickle.loads(STATE_PATH.read_bytes())
    geometry_bytes: dict[str, bytes] = pickle.loads(GEOMETRY_PATH.read_bytes())
    populations = {str(unit): int(value) for unit, value in state["pops"].items()}
    unit_department = {str(unit): str(value) for unit, value in state["unit_dept"].items()}
    departments = sorted(set(state["dept_pop"]) - set(D53_FIXED_SEATS))
    if departments != sorted(report.get("search_departments", [])):
        raise ValueError("pipeline department scope differs from the current D53 search scope")

    official_status = {}
    with OFFICIAL_AUDIT.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            official_status[row["department"]] = row["status"]

    starting_dir = pipeline_dir / "artifacts/starting_plans"
    optimized_dir = pipeline_dir / "artifacts/optimized_plans"
    failures = verify_manifest(starting_dir) + verify_manifest(optimized_dir)
    plan_hashes: dict[str, str] = {}
    rows: list[dict] = []
    all_units = {unit for unit, dep in unit_department.items() if dep in departments}
    invalid_geometry = []
    for unit in all_units:
        geom = wkb.loads(geometry_bytes[unit]) if unit in geometry_bytes else None
        if geom is None or geom.is_empty or not geom.is_valid:
            invalid_geometry.append(unit)
    if invalid_geometry:
        failures.append(f"{len(invalid_geometry)} search units lack valid non-empty geometry")

    trace_ids: set[str] = set()
    for dept in departments:
        path = optimized_dir / f"{dept}.json"
        sample_path = starting_dir / f"{dept}.json"
        if not path.is_file() or not sample_path.is_file():
            failures.append(f"{dept}: missing preserved plan artifact")
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        samples = json.loads(sample_path.read_text(encoding="utf-8"))
        assignment = as_assignment(result.get("assignment", {}))
        units = {unit for unit, unit_dept in unit_department.items() if unit_dept == dept}
        dept_failures: list[str] = []
        if set(assignment) != units:
            dept_failures.append("assignment does not exactly cover the department units")
        expected_labels = set(range(int(state["seats"][dept])))
        if set(assignment.values()) != expected_labels:
            dept_failures.append("district labels do not match the D53 seat count")
        if set(assignment) == units:
            adjacency = {unit: {n for n in state["certification_edges"].get(unit, ()) if n in units}
                         for unit in units}
            checked = validate_plan(assignment, units, populations, adjacency,
                                    float(state["dept_pop"][dept]) / int(state["seats"][dept]), TOLERANCE)
            dept_failures.extend(f"{item.rule}: {item.detail}" for item in checked.violations)
            unit_list = sorted(units)
            geoms = [wkb.loads(geometry_bytes[unit]) for unit in unit_list]
            frame = gpd.GeoDataFrame({"unit": unit_list, "district": [assignment[unit] for unit in unit_list]},
                                     geometry=geoms, crs="EPSG:2154")
            sindex = frame.sindex
            overlaps = []
            for i, item in enumerate(frame.itertuples()):
                for j in sindex.query(item.geometry, predicate="intersects"):
                    j = int(j)
                    if j <= i or frame.iloc[j]["district"] == item.district:
                        continue
                    area = item.geometry.intersection(frame.geometry.iloc[j]).area
                    if area > OVERLAP_AREA_TOL_M2:
                        overlaps.append((item.unit, frame.iloc[j]["unit"], area))
            if overlaps:
                dept_failures.append(f"{len(overlaps)} cross-district unit overlaps exceed 1 m²")

            scorer = Scorer({unit: geometry_bytes[unit] for unit in units}, populations,
                             float(state["dept_pop"][dept]) / int(state["seats"][dept]),
                             state["epci_of"], Weights())
            recomputed = scorer.components(assignment)
            recorded = result.get("optimized", {})
            for metric in ("L", "l_pop", "l_comp", "l_epci"):
                if abs(float(recomputed[metric]) - float(recorded.get(metric, float("nan")))) > 1e-9:
                    dept_failures.append(f"stored optimized metric {metric} does not match recomputation")

        start_source = result.get("start_source", "sampled_recom")
        source_candidates = [candidate for candidate in samples.get("plans", []) if candidate.get("valid")]
        if not source_candidates:
            dept_failures.append("no valid sampled/official start was preserved")

        trace_file = result.get("trace_file")
        trace_path = ROOT / str(trace_file or "")
        expected_trace_hash = result.get("trace_sha256")
        sampled_hash = sha256(sample_path)
        if not trace_path.is_file():
            dept_failures.append("optimizer proposal trace is missing")
        elif sha256(trace_path) != expected_trace_hash:
            dept_failures.append("optimizer trace hash does not match its result record")
        else:
            trace_failures = replay_trace(trace_path, monitor_run_id, result, sampled_hash)
            dept_failures.extend(trace_failures)
            try:
                with gzip.open(trace_path, "rt", encoding="utf-8") as trace:
                    first = json.loads(trace.readline())
                trace_ids.add(str(first.get("trace_run_id", "")))
                if first.get("start_source") != start_source:
                    dept_failures.append("trace start source differs from optimized result")
                if assignment_fingerprint(as_assignment(first.get("start_assignment", {}))) != assignment_fingerprint(
                        as_assignment(source_candidates[0]["assignment"])):
                    dept_failures.append("trace start assignment differs from first valid preserved start")
            except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError, IndexError):
                dept_failures.append("trace metadata cannot be checked against the preserved start")

        official = official_status.get(dept, "UNKNOWN")
        comparable = official == "VALID_PROJECT_START" and start_source == "official_current"
        start_score = float(result.get("start", {}).get("L", float("nan")))
        best_score = float(result.get("optimized", {}).get("L", float("nan")))
        rows.append({
            "department": dept,
            "seats": int(state["seats"][dept]),
            "valid": not dept_failures,
            "official_start_status": official,
            "start_source": start_source,
            "official_objective_comparable": comparable,
            "official_or_start_L": start_score if comparable else "",
            "optimized_L": best_score,
            "objective_improvement": start_score - best_score if comparable else "",
            "strictly_better_than_official_objective": comparable and best_score < start_score - 1e-9,
            "proposals": int(result.get("run_diagnostics", {}).get("proposals_completed", 0)),
            "stop_reason": result.get("run_diagnostics", {}).get("stop_reason", ""),
            "failures": " | ".join(dept_failures),
        })
        plan_hashes[dept] = sha256(path)

    if trace_ids != {monitor_run_id}:
        failures.append(f"trace run IDs differ from expected monitor run: {sorted(trace_ids)}")
    invalid = [row["department"] for row in rows if not row["valid"]]
    if invalid:
        failures.append(f"{len(invalid)} department plans failed independent search validation: {invalid}")

    output_dir = monitor_dir / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "departments.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    comparable_rows = [row for row in rows if row["official_objective_comparable"]]
    improved = [row for row in comparable_rows if row["strictly_better_than_official_objective"]]
    summary = {
        "pipeline_run_id": pipeline_run_id,
        "monitor_run_id": monitor_run_id,
        "search_departments": len(rows),
        "valid_search_plans": sum(row["valid"] for row in rows),
        "direct_official_comparisons": len(comparable_rows),
        "strictly_better_than_official_objective": len(improved),
        "comparable_departments_improved": [row["department"] for row in improved],
        "official_comparison_limit": "Direct objective comparison is limited to exact official starts with matching D53 seats. For other departments, official geometry/seat count is not an equivalent comparator.",
        "objective_limit": "L is the configured population/compactness/EPCI search objective; it is not an electoral-neutrality or legal-validity score.",
        "failures": failures,
        "status": "ALL_SEARCH_PLANS_VALID" if not failures and len(rows) == 89 else "AUDIT_FAILURE",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Search run validation and official-objective comparison",
        "",
        f"Status: **{summary['status']}**",
        "",
        f"- Search plans independently validated: {summary['valid_search_plans']} / {summary['search_departments']}",
        f"- Direct official comparisons: {summary['direct_official_comparisons']}",
        f"- Strictly lower v1 objective than official start: {summary['strictly_better_than_official_objective']}",
        f"- Improved departments: {', '.join(summary['comparable_departments_improved']) or 'none'}",
        "",
        "The objective compares population balance, compactness, and EPCI splits. It does not certify electoral fairness or legal superiority. Departments with different official seat counts or incomplete official crosswalks are not described as better/worse than the official map.",
        "",
        "Every proposal trace was replayed from the recorded start assignment using its assignment deltas; fingerprints, checkpoints, final assignments, metrics, and hashes were checked.",
        "",
        "## Audit failures",
        "",
        *(tuple(f"- {item}" for item in failures) if failures else ("- none",)),
        "",
        "Per-department details: `departments.csv`.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    monitor["analysis_summary"] = {
        "status": summary["status"],
        "valid_search_plans": summary["valid_search_plans"],
        "search_departments": summary["search_departments"],
        "direct_official_comparisons": summary["direct_official_comparisons"],
        "strictly_better_than_official_objective": summary["strictly_better_than_official_objective"],
        "comparable_departments_improved": summary["comparable_departments_improved"],
        "report": str((output_dir / "report.md").relative_to(ROOT)),
    }
    monitor_path = monitor_dir / "run.json"
    temporary_monitor = monitor_path.with_suffix(".json.tmp")
    temporary_monitor.write_text(json.dumps(monitor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_monitor.replace(monitor_path)
    print(f"search result audit: {summary['status']}; valid={summary['valid_search_plans']}/89; direct official improvements={len(improved)}/{len(comparable_rows)}; report={output_dir / 'report.md'}")
    return 0 if summary["status"] == "ALL_SEARCH_PLANS_VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())

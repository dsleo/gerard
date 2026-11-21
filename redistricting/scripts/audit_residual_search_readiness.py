"""Verify every non-frozen department has a valid D53 search start.

This revalidates saved sampled candidates against the live Gate 1 state and the
shared hard-constraint checker. It does not certify an official-map crosswalk
or claim that exploratory samples are a converged ensemble.

Run from redistricting/:
  .venv/bin/python scripts/run_blind.py audit_residual_search_readiness.py
"""

from __future__ import annotations

import csv
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.validate.constraints import validate_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "audit_residual_search_readiness.py")
STATE_PATH = ROOT / "data/processed/gate1/sampler_state.pkl"
OFFICIAL_AUDIT_PATH = ROOT / "data/processed/official_seed_audit/departments.csv"
PLAN_DIR = ROOT / "data/processed/plans"
OUT = ROOT / "data/processed/residual_search_readiness_audit"
TOLERANCE = 0.20


def main() -> int:
    state = pickle.loads(STATE_PATH.read_bytes())
    with OFFICIAL_AUDIT_PATH.open(newline="", encoding="utf-8") as stream:
        official_rows = list(csv.DictReader(stream))

    output: list[dict] = []
    for row in official_rows:
        department = row["department"]
        plan_path = PLAN_DIR / f"{department}.json"
        if not plan_path.is_file():
            output.append({
                "department": department,
                "official_seed_status": row["status"],
                "project_seats": int(state["seats"][department]),
                "saved_valid_candidates": 0,
                "revalidated_candidates": 0,
                "search_start_status": "NO_SAVED_PLAN_FILE",
                "detail": str(plan_path),
            })
            continue
        saved = json.loads(plan_path.read_text(encoding="utf-8"))
        units = {u for u in state["units"] if state["unit_dept"][u] == department}
        adjacency = {
            u: {v for v in state["certification_edges"].get(u, ()) if v in units}
            for u in units
        }
        target = float(state["dept_pop"][department]) / int(state["seats"][department])
        candidates = [p for p in saved.get("plans", []) if p.get("valid")]
        passed = 0
        failures: list[str] = []
        for index, candidate in enumerate(candidates):
            assignment = {str(u): int(district) for u, district in candidate["assignment"].items()}
            district_count = len(set(assignment.values()))
            if district_count != int(state["seats"][department]):
                failures.append(f"candidate {index}: {district_count} districts != {state['seats'][department]} D53 seats")
                continue
            checked = validate_plan(
                assignment, units, state["pops"], adjacency, target, TOLERANCE
            )
            if checked.violations:
                failures.append(f"candidate {index}: " + "; ".join(v.detail for v in checked.violations))
                continue
            passed += 1
        output.append({
            "department": department,
            "official_seed_status": row["status"],
            "project_seats": int(state["seats"][department]),
            "saved_valid_candidates": len(candidates),
            "revalidated_candidates": passed,
            "search_start_status": "SEARCH_READY_WITH_VALID_RECOM_START" if passed else "NO_VALID_RECOM_START",
            "detail": " | ".join(failures),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    fields = list(output[0]) if output else []
    with (OUT / "departments.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)
    counts: dict[str, int] = {}
    for item in output:
        counts[item["search_start_status"]] = counts.get(item["search_start_status"], 0) + 1
    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "All non-frozen departments checked by the official-seed audit",
        "departments_checked": len(output),
        "status_counts": counts,
        "meaning": "Each PASS revalidates at least one saved ReCom candidate against current D53 seat count, exact unit partition, certified contiguity, and current ±20% population. These are exploratory starting candidates, not a converged ensemble or proof that the official-plan crosswalk is complete.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Search-start readiness for all non-frozen departments",
        "",
        "This audit separates the optional current-official-plan seed from the valid ReCom starts needed by the D53 search.",
        "",
        "| Official-seed issue | Departments checked |",
        "|---|---:|",
        f"| Official plans with a different D53 seat count | {sum(x['official_seed_status'] == 'VALID_OFFICIAL_SEAT_COUNT_MISMATCH' for x in output)} |",
        f"| Official crosswalk incomplete | {sum(x['official_seed_status'] == 'INCOMPLETE_CROSSWALK' for x in output)} |",
        f"| Official plan fails current project check | {sum(x['official_seed_status'] == 'FAILS_PROJECT_CURRENT_RULES' for x in output)} |",
        "",
        "| Search-start result | Departments |",
        "|---|---:|",
    ]
    lines.extend(f"| {status} | {count} |" for status, count in sorted(counts.items()))
    lines.extend([
        "",
        "The recheck uses the shared validator plus an explicit D53 district-count check. A PASS means the department has at least one valid exploratory ReCom start. It does not turn an official map with a different seat count into an official seed, certify an incomplete official crosswalk, or imply that the search has converged.",
        "",
        "See `departments.csv` for each department and candidate count.",
        "",
    ])
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"residual search-start audit: {counts}; report={OUT / 'report.md'}")
    if any(x["search_start_status"] != "SEARCH_READY_WITH_VALID_RECOM_START" for x in output):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

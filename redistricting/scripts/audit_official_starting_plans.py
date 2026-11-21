"""Audit whether the current official plan can seed the 89-department search.

Run from redistricting/:
  .venv/bin/python scripts/run_blind.py audit_official_starting_plans.py

Uses the official INSEE commune/circonscription correspondence. Split communes
are reported as unresolved because this table does not locate their internal
boundaries; the simplified INSEE contour is never used to guess those assignments.
"""

from __future__ import annotations

import csv
import json
import pickle
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.sample.official import build_official_seed  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "audit_official_starting_plans.py")
STATE_PATH = ROOT / "data/processed/gate1/sampler_state.pkl"
CORRESPONDENCE_PATH = ROOT / "data/raw/constituencies/insee_commune_circonscription_2026.xlsx"
COG_COMMUNES_PATH = ROOT / "data/raw/insee_cog2024/v_commune_2024.csv"
COG_MOVEMENTS_PATH = ROOT / "data/raw/insee_cog2024/v_mvt_commune_2024.csv"
OUT = ROOT / "data/processed/official_seed_audit"


def main() -> int:
    for path in (STATE_PATH, CORRESPONDENCE_PATH, COG_COMMUNES_PATH, COG_MOVEMENTS_PATH):
        if not path.exists():
            raise FileNotFoundError(path)
    state = pickle.loads(STATE_PATH.read_bytes())
    departments = sorted(set(state["dept_pop"]) - set(D53_FIXED_SEATS))
    units_by_department: dict[str, list[str]] = {}
    for unit, unit_department in state["unit_dept"].items():
        units_by_department.setdefault(str(unit_department), []).append(str(unit))
    detail_rows = []
    for department in departments:
        audit = build_official_seed(
            department, state, CORRESPONDENCE_PATH, COG_COMMUNES_PATH, COG_MOVEMENTS_PATH,
            model_units=units_by_department.get(department, []),
        )
        row = {key: value for key, value in audit.items() if key != "candidate"}
        row["examples"] = json.dumps(row.get("examples", {}), ensure_ascii=False, sort_keys=True)
        row["violations"] = json.dumps(row.get("violations", []), ensure_ascii=False)
        detail_rows.append(row)

    status_counts = dict(Counter(row["status"] for row in detail_rows))
    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "D53 non-frozen search departments only",
        "departments_checked": len(detail_rows),
        "status_counts": status_counts,
        "interpretation": (
            "The INSEE table uses COG 2021 commune codes; the COG 2024 inventory and movement history "
            "translate those codes to current model units. A unit formed by merging communes is "
            "assigned only if every component has an exact whole-commune membership in the same "
            "constituency. Split communes, conflicting memberships, and missing constituency values "
            "remain unresolved; no membership is guessed from simplified polygon overlay. "
            "Project-rule failures are reported separately from crosswalk gaps."
        ),
        "sources": [
            "INSEE June 2026 commune-to-constituency table",
            "INSEE COG 2024 commune inventory and commune-movement history",
            "Gate 1 certified adjacency and legal population state",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fieldnames = sorted({key for row in detail_rows for key in row})
    with (OUT / "departments.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(detail_rows)
    lines = [
        "# Official starting-plan audit",
        "",
        f"Departments checked: {len(detail_rows)} (the 12 D53 frozen departments are excluded).",
        "",
        "| Status | Departments |",
        "|---|---:|",
    ]
    lines.extend(f"| {status} | {count} |" for status, count in sorted(status_counts.items()))
    lines += [
        "",
        "A `VALID_PROJECT_START` row means the official whole-commune correspondence covers every current model unit, official and project seat counts match, and the shared machine validator passes the project's certified-graph contiguity and 2021-population ±20% checks. It is a project-start result, not a legal certification of the official map.",
        "A `VALID_OFFICIAL_SEAT_COUNT_MISMATCH` row means the plan passes those current project checks using its official seat count, but D53 assigns a different number of seats, so the unchanged plan cannot seed the project plan.",
        "A `FAILS_PROJECT_CURRENT_RULES` row means an exact official assignment does not pass at least one current project check. This does not by itself establish that the adopted official map was unlawful; see the separate historical population-basis audit.",
        "The audit uses current 2021 population values for project-start eligibility; it does not decide whether an official 2009 boundary was legal under the 2006 reference population. See the historical audit and D69 for that separate question.",
        "Crosswalk gaps and current project-rule failures are reported separately. See `departments.csv` for affected units and per-rule violations.",
        "",
    ]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"official starting-plan audit: {status_counts}; report={OUT / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

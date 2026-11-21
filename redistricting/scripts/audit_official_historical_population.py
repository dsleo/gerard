"""Compare current official constituency membership with INSEE's 2006 population.

This is a historical population-basis audit of the map adopted in 2009, not a
validator for newly generated plans. It only calculates an exact result when
every commune has a whole-commune assignment in the current INSEE table and a
matching 2006 commune code. Partial communes and code changes are reported as
unresolved rather than guessed.

Run from redistricting/:
  .venv/bin/python scripts/run_blind.py audit_official_historical_population.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.ingest.generation import install_generation_guard  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "audit_official_historical_population.py")
POPULATION_PATH = ROOT / "data/raw/population/insee_populations_legales_2006_ensemble.xls"
CORRESPONDENCE_PATH = ROOT / "data/raw/constituencies/insee_commune_circonscription_2026.xlsx"
OUT = ROOT / "data/processed/official_historical_population_audit"


def _department(value: object) -> str:
    value = str(value).strip()
    return value.zfill(2) if value.isdigit() and len(value) < 2 else value


def _constituency(department: str, value: object) -> str:
    value = str(value).strip()
    if value.startswith(department):
        return value
    if department.isdigit():
        return value.zfill(5)
    return department + value[-2:].zfill(2)


def main() -> int:
    for path in (POPULATION_PATH, CORRESPONDENCE_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)

    population = pd.read_excel(POPULATION_PATH, sheet_name="Communes", header=7, dtype=str)
    population["code"] = population["Code département"].map(_department) + population["Code commune"].astype(str).str.strip().str.zfill(3)
    population["population_municipale_2006"] = pd.to_numeric(population["Population municipale"], errors="coerce")
    population["population_totale_2006"] = pd.to_numeric(population["Population totale"], errors="coerce")
    if population["code"].duplicated().any():
        raise ValueError("INSEE 2006 commune population table has duplicate department/commune codes")

    correspondence = pd.read_excel(
        CORRESPONDENCE_PATH,
        sheet_name="table",
        dtype={"DEP": str, "COMMUNE_RESID": str, "circo": str, "type_com": str},
    )
    correspondence["DEP"] = correspondence["DEP"].map(_department)
    correspondence["COMMUNE_RESID"] = correspondence["COMMUNE_RESID"].astype(str).str.strip().str.zfill(5)
    correspondence["circo"] = correspondence.apply(
        lambda row: _constituency(row["DEP"], row["circo"]), axis=1
    )
    correspondence["type_com"] = correspondence["type_com"].astype(str).str.strip().str.casefold()

    rows: list[dict] = []
    for department, group in correspondence.groupby("DEP", sort=True):
        merged = group.merge(population, left_on="COMMUNE_RESID", right_on="code", how="left", indicator=True)
        partial = sorted(merged.loc[merged["type_com"] != "entière", "COMMUNE_RESID"].unique())
        missing_codes = sorted(merged.loc[merged["_merge"] != "both", "COMMUNE_RESID"].unique())
        whole_rows = merged.loc[merged["type_com"] == "entière", ["COMMUNE_RESID"]]
        duplicate_codes = sorted(whole_rows.loc[whole_rows["COMMUNE_RESID"].duplicated(keep=False), "COMMUNE_RESID"].unique())
        row = {
            "department": department,
            "official_constituencies": int(group["circo"].nunique()),
            "correspondence_rows": int(len(group)),
            "whole_commune_rows": int((merged["type_com"] == "entière").sum()),
            "partial_communes": len(partial),
            "missing_2006_codes": len(missing_codes),
            "duplicate_whole_communes": len(duplicate_codes),
            "status": "INCOMPLETE_HISTORICAL_CROSSWALK",
            "municipal_max_abs_deviation": "",
            "total_max_abs_deviation": "",
            "municipal_worst_constituency": "",
            "municipal_worst_population": "",
            "municipal_mean_population": "",
            "total_worst_constituency": "",
            "total_worst_population": "",
            "total_mean_population": "",
            "examples": json.dumps({
                "partial_communes": partial[:10],
                "missing_2006_codes": missing_codes[:10],
                "duplicate_whole_communes": duplicate_codes[:10],
            }, ensure_ascii=False, sort_keys=True),
        }
        if not partial and not missing_codes and not duplicate_codes:
            counts = merged.groupby("circo", sort=True).agg(
                population_municipale_2006=("population_municipale_2006", "sum"),
                population_totale_2006=("population_totale_2006", "sum"),
            )
            for label, column, maximum_key, worst_key, pop_key, mean_key in (
                ("municipal", "population_municipale_2006", "municipal_max_abs_deviation", "municipal_worst_constituency", "municipal_worst_population", "municipal_mean_population"),
                ("total", "population_totale_2006", "total_max_abs_deviation", "total_worst_constituency", "total_worst_population", "total_mean_population"),
            ):
                mean = float(counts[column].sum()) / len(counts)
                deviations = (counts[column] / mean - 1.0).abs()
                worst = str(deviations.idxmax())
                row[maximum_key] = float(deviations.max())
                row[worst_key] = worst
                row[pop_key] = int(counts.loc[worst, column])
                row[mean_key] = mean
            row["status"] = "PASS_2006_BOTH_POPULATION_BASES" if max(
                row["municipal_max_abs_deviation"], row["total_max_abs_deviation"]
            ) <= 0.20 else "EXCEEDS_20_PERCENT_ON_2006_DATA"
        rows.append(row)

    counts = Counter(row["status"] for row in rows)
    OUT.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with (OUT / "departments.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    by_dept = {row["department"]: row for row in rows}
    essonne = by_dept.get("91")
    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Official current commune/constituency correspondence joined to INSEE 2006 commune population, where exact whole-commune matching is possible.",
        "status_counts": dict(counts),
        "legal_caveat": "This checks historical population deviation only. It does not certify every legal boundary, contiguity exception, or the project’s current 2021-population generation criteria. A current correspondence table is used only where its commune code directly matches the 2006 INSEE code.",
        "sources": [
            "INSEE Populations légales 2006, reference date 1 Jan 2006, commune geography in force 1 Jan 2008",
            "INSEE June 2026 commune-to-constituency correspondence",
            "Law 2009-39, Article 2 II (population basis and ±20% rule for the 2009 redistricting operation)",
        ],
        "department_91": essonne,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Official map: historical population-basis audit",
        "",
        "This audit compares the INSEE commune-to-constituency correspondence with INSEE's 2006 legal population figures, the historical reference used for the 2009 redistricting. It only calculates a department when every current table row is whole-commune and every commune code matches the 2006 table exactly.",
        "",
        "| Status | Departments |",
        "|---|---:|",
    ]
    lines.extend(f"| {status} | {count} |" for status, count in sorted(counts.items()))
    lines.extend([
        "",
        "The reported deviation is the maximum absolute difference from the department's mean constituency population, computed separately for INSEE municipal and total population. A partial commune or unmatched historical code is unresolved, not assigned by estimate.",
        "",
        "This historical population check is distinct from the project’s 2021 snapshot constraints and from a full legal certification of exact boundaries and justified exceptions.",
        "",
    ])
    if essonne and essonne["status"] == "PASS_2006_BOTH_POPULATION_BASES":
        lines.extend([
            "## Essonne (91)",
            "",
            f"The 10 official constituencies pass ±20% under both 2006 municipal and total population. Worst municipal deviation: {essonne['municipal_max_abs_deviation']:.2%} in {essonne['municipal_worst_constituency']}; worst total-population deviation: {essonne['total_max_abs_deviation']:.2%} in {essonne['total_worst_constituency']}.",
            "",
        ])
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"historical official population audit: {dict(counts)}; Essonne={essonne['status'] if essonne else 'NOT_FOUND'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Prepare the minimal IRIS 2022 population-share table used by Gate 1.

This is a deterministic source-preparation step, not a plan-generation entry
point. It keeps only the 2024-geography IRIS code and INSEE P22_POP field.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/insee_iris_pop/base_ic_population_2022_iris_cog2024_csv.zip"
OUTPUT = ROOT / "data/processed/iris_population_2022.csv"
MEMBER = "base-ic-evol-struct-pop-2022.CSV"


def main() -> None:
    rows: list[tuple[str, int]] = []
    with zipfile.ZipFile(SOURCE) as archive:
        with archive.open(MEMBER) as binary:
            reader = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline=""), delimiter=";")
            for row in reader:
                iris = row["IRIS"].strip()
                if len(iris) != 9 or not iris.isdigit():
                    continue
                value = float(row["P22_POP"].replace(",", "."))
                rows.append((iris, value))

    if not rows or len({code for code, _ in rows}) != len(rows):
        raise ValueError("IRIS source is empty or contains duplicate IRIS codes")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["iris", "pop22"])
        writer.writerows((code, format(pop, ".15g")) for code, pop in sorted(rows))
    print(f"Wrote {len(rows):,} IRIS rows to {OUTPUT}")


if __name__ == "__main__":
    main()
